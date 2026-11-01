"""Фоновые задачи внутри процесса: asyncio-воркер над таблицей `job`.

Не больше двух задач ffmpeg одновременно; незавершённые подхватываются после перезапуска.
Долгие операции идут вне транзакции БД: SQLite пишет по одному, и ffmpeg на минуту не должен
держать блокировку записи.
"""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable, Collection

from sqlalchemy.orm import Session

from app import db as database
from app import linkpreview, media, models
from app.config import Settings, get_settings
from app.constants import FileKind, JobType
from app.services import files as file_service
from app.services import jobs

log = logging.getLogger(__name__)

MAX_PARALLEL = 2
IDLE_POLL_SEC = 2.0


def _file(db: Session, job: models.Job) -> models.File | None:
    file = db.get(models.File, job.payload.get("file_id"))
    return None if file is None or file.deleted_at is not None or not file.path else file


def _link_preview(db: Session, file: models.File, settings: Settings) -> None:
    """Карточка ссылки: заголовок и картинка Open Graph. Ходит в чужую сеть — см. linkpreview."""
    url, file_id = file.url, file.id
    db.rollback()  # не держим транзакцию на время сетевых запросов
    if not url:
        return
    card = linkpreview.fetch_card(url)
    fields: dict[str, object] = {"link_title": card.title}
    if card.image:
        out_dir = settings.cache_dir / str(file_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        raw = out_dir / "og-source"
        raw.write_bytes(card.image)
        try:
            media.image_variants(raw, out_dir)  # перекодирует: чужие байты на диске не остаются
            fields["thumb_path"] = f"{file_id}/thumb.jpg"
        except media.MediaError:
            pass  # картинка битая — остаётся карточка с заголовком
        finally:
            raw.unlink(missing_ok=True)
    file_service.apply_media_info(db, file_id, **fields)


def _preview(db: Session, job: models.Job, settings: Settings) -> None:
    link = db.get(models.File, job.payload.get("file_id"))
    if link is not None and link.deleted_at is None and link.kind == FileKind.LINK:
        _link_preview(db, link, settings)
        return
    file = _file(db, job)
    if file is None:
        return
    source = settings.files_dir / file.path  # type: ignore[operator]
    out_dir = settings.cache_dir / str(file.id)
    thumb = f"{file.id}/thumb.jpg"
    file_id, kind = file.id, file.kind
    db.rollback()  # не держим транзакцию на время обработки

    if kind == FileKind.VIDEO:
        info = media.probe(source)
        media.video_poster(source, out_dir, info.duration)
        playable = media.browser_playable(info)
        fields = dict(
            duration_sec=info.duration, width=info.width, height=info.height, fps=info.fps
        )
    elif kind == FileKind.IMAGE:
        width, height = media.image_variants(source, out_dir)
        playable = True
        fields = dict(width=width, height=height)
    else:  # PDF
        width, height = media.pdf_first_page(source, out_dir)
        playable = True
        fields = dict(width=width, height=height)

    file_service.apply_media_info(db, file_id, thumb_path=thumb, **fields)
    if kind == FileKind.VIDEO and not playable:
        file_service.queue_proxy(db, file_id)


def _waveform(db: Session, job: models.Job, settings: Settings) -> None:
    file = _file(db, job)
    if file is None:
        return
    source = settings.files_dir / file.path  # type: ignore[operator]
    file_id = file.id
    db.rollback()
    info = media.probe(source)
    peaks = media.waveform(source, info.duration)
    file_service.apply_media_info(db, file_id, duration_sec=info.duration, waveform_json=peaks)


def _proxy(db: Session, job: models.Job, settings: Settings) -> None:
    file = _file(db, job)
    if file is None:
        return
    source = settings.files_dir / file.path  # type: ignore[operator]
    file_id, job_id = file.id, job.id
    db.rollback()
    info = media.probe(source)
    destination = settings.cache_dir / str(file_id) / "proxy.mp4"

    def progress(value: float) -> None:
        with database.session_factory()() as short:
            jobs.set_progress(short, job_id, value)
            short.commit()

    media.make_proxy(source, destination, info.duration, progress)
    file_service.apply_media_info(db, file_id, proxy_path=f"{file_id}/proxy.mp4")


def _tg_import(db: Session, job: models.Job, settings: Settings) -> None:
    from app.tg import importer

    payload, job_id, created_by = dict(job.payload), job.id, job.created_by
    db.rollback()  # скачивание долгое: транзакцию не держим
    if "preview" in payload:
        importer.run_preview(job_id, int(payload["preview"]), settings)
    else:
        importer.run_import(job_id, created_by, payload, settings)


def _export(db: Session, job: models.Job, settings: Settings) -> None:
    from app.services import exports

    export_id, job_id = int(job.payload["export_id"]), job.id
    db.rollback()  # сборка пакета долгая: транзакцию не держим
    exports.run(export_id, job_id, settings)


HANDLERS: dict[str, Callable[[Session, models.Job, Settings], None]] = {
    JobType.EXPORT.value: _export,
    JobType.TG_IMPORT.value: _tg_import,
    JobType.PREVIEW.value: _preview,
    JobType.WAVEFORM.value: _waveform,
    JobType.PROXY.value: _proxy,
}


def process_job(job_id: int) -> None:
    """Выполняет одну задачу; ошибка превращается в статус `failed`, а не в падение воркера."""
    global _tg_running
    settings = get_settings()
    with database.session_factory()() as db:
        job = db.get(models.Job, job_id)
        if job is None:
            return
        is_tg = job.type == JobType.TG_IMPORT.value
        try:
            handler = HANDLERS.get(job.type)
            if handler is None:
                raise media.MediaError(f"Тип задачи «{job.type}» пока не поддерживается")
            handler(db, job, settings)
            jobs.finish(db, job_id)
            db.commit()
        except Exception as exc:  # в том числе MediaError
            db.rollback()
            if not isinstance(exc, media.MediaError):
                log.exception("задача %s упала", job_id)
            jobs.fail(db, job_id, str(exc) or exc.__class__.__name__)
            db.commit()
        finally:
            if is_tg:
                with _tg_lock:
                    _tg_running = max(0, _tg_running - 1)


_tg_lock = threading.Lock()
_tg_running = 0  # задач tg_import, взятых и ещё не завершённых


def tg_busy() -> bool:
    return _tg_running > 0


def claim_next_id(skip: Collection[str] = ()) -> int | None:
    global _tg_running
    with database.session_factory()() as db:
        job = jobs.claim_next(db, skip)
        job_id = job.id if job else None
        if job is not None and job.type == JobType.TG_IMPORT.value:
            with _tg_lock:
                _tg_running += 1
        db.commit()
        return job_id


def drain() -> int:
    """Выполняет все задачи из очереди синхронно. Для тестов и ручного запуска."""
    done = 0
    while (job_id := claim_next_id()) is not None:
        process_job(job_id)
        done += 1
    return done


class JobRunner:
    def __init__(self, parallel: int = MAX_PARALLEL) -> None:
        self._slots = asyncio.Semaphore(parallel)
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running: set[asyncio.Task[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        requeued = await asyncio.to_thread(self._requeue)
        if requeued:
            log.info("возвращено в очередь после перезапуска: %s", requeued)
        self._task = asyncio.create_task(self._serve(), name="job-runner")

    @staticmethod
    def _requeue() -> int:
        with database.session_factory()() as db:
            count = jobs.requeue_interrupted(db)
            db.commit()
            return count

    def wake(self) -> None:
        """Сообщить, что в очереди появилась задача (можно вызывать из потока запроса)."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._wakeup.set)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        for task in list(self._running):
            task.cancel()
        await asyncio.gather(*self._running, return_exceptions=True)

    async def _serve(self) -> None:
        """Главный цикл. Разовая ошибка (например, база занята) не должна его убивать:
        иначе превью и прокси молча перестанут обрабатываться до перезапуска."""
        while True:
            await self._slots.acquire()
            try:
                # Загрузка из Telegram идёт по одной: вторая не должна занять слот ffmpeg впустую.
                skip = (JobType.TG_IMPORT.value,) if tg_busy() else ()
                job_id = await asyncio.to_thread(claim_next_id, *([skip] if skip else []))
            except Exception:
                self._slots.release()
                log.exception("не удалось взять задачу из очереди, повтор через секунду")
                await asyncio.sleep(1)
                continue
            if job_id is None:
                self._slots.release()
                self._wakeup.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wakeup.wait(), IDLE_POLL_SEC)
                continue
            task = asyncio.create_task(self._run(job_id))
            self._running.add(task)
            task.add_done_callback(self._running.discard)

    async def _run(self, job_id: int) -> None:
        try:
            await asyncio.to_thread(process_job, job_id)
        finally:
            self._slots.release()
            self._wakeup.set()

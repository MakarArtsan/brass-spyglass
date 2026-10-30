"""Фоновые задачи внутри процесса: asyncio-воркер над таблицей `job`.

Не больше двух задач ffmpeg одновременно; незавершённые подхватываются после перезапуска.
Долгие операции идут вне транзакции БД: SQLite пишет по одному, и ffmpeg на минуту не должен
держать блокировку записи.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app import db as database
from app import media, models
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


def _preview(db: Session, job: models.Job, settings: Settings) -> None:
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


HANDLERS: dict[str, Callable[[Session, models.Job, Settings], None]] = {
    JobType.PREVIEW.value: _preview,
    JobType.WAVEFORM.value: _waveform,
    JobType.PROXY.value: _proxy,
}


def process_job(job_id: int) -> None:
    """Выполняет одну задачу; ошибка превращается в статус `failed`, а не в падение воркера."""
    settings = get_settings()
    with database.session_factory()() as db:
        job = db.get(models.Job, job_id)
        if job is None:
            return
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


def claim_next_id() -> int | None:
    with database.session_factory()() as db:
        job = jobs.claim_next(db)
        job_id = job.id if job else None
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
        while True:
            await self._slots.acquire()
            job_id = await asyncio.to_thread(claim_next_id)
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

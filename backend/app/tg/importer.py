"""Задача `tg_import`: скачать выбранное из Telegram, сделать превью, привязать к карточке.

Выполняется в потоке воркера; клиент Telethon живёт в основном цикле, поэтому скачивание
заказывается у шлюза через `run_coroutine_threadsafe`. Каждый файл — в своей короткой транзакции:
сбой одного не отменяет уже принятые, а прогресс виден в углу экрана. Файлы качаются строго по
одному (защита аккаунта), для этого в самом шлюзе есть блокировка.
"""

import asyncio
import concurrent.futures
import hashlib
import logging
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from app import db as database
from app import models, storage
from app.config import Settings
from app.constants import Role
from app.media import MediaError
from app.permissions import Actor, PermissionDenied
from app.services import core, jobs, projects
from app.services import telegram as tg_service
from app.tg import previews, runtime
from app.tg.limiter import FloodTooLong
from app.tg.types import MediaInfo

log = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SEC = 3600
WAIT_SLICE_SEC = 1.0
PROGRESS_EVERY_SEC = 1.5
HASH_BLOCK = 1 << 20


def _await[T](coro: Coroutine[Any, Any, T], timeout: float = DOWNLOAD_TIMEOUT_SEC) -> T:
    loop = runtime.loop
    if loop is None:
        coro.close()
        raise MediaError("Telegram не подключён")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    deadline = time.monotonic() + timeout
    # Ждём короткими кусками: если главный цикл остановлен (перезапуск приложения), поток не должен
    # висеть до конца часового тайма-аута и задерживать выключение.
    while True:
        try:
            return future.result(WAIT_SLICE_SEC)
        except concurrent.futures.TimeoutError:
            if loop.is_closed() or not loop.is_running():
                future.cancel()
                raise MediaError("Приложение остановлено, загрузка из Telegram прервана") from None
            if time.monotonic() >= deadline:
                future.cancel()
                raise MediaError("Telegram не ответил вовремя") from None


def _gateway() -> Any:
    if runtime.gateway is None:
        raise MediaError("Юзербот Telegram не подключён: проверьте TG_SESSION и TG_CHAT_ID")
    return runtime.gateway


def _sha256(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        while block := handle.read(HASH_BLOCK):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def explain(exc: BaseException) -> str:
    """Причина сбоя человеческим языком; технические детали остаются в логе."""
    if isinstance(exc, FloodTooLong):
        return f"Telegram просит подождать {int(exc.seconds)} с, повторите позже"
    if isinstance(exc, TimeoutError):
        return "Скачивание заняло слишком много времени"
    if isinstance(
        exc, (storage.NoRoom, FileNotFoundError, MediaError, core.ServiceError, PermissionDenied)
    ):
        return str(exc)
    return f"Не удалось загрузить ({exc.__class__.__name__})"


def _actor(db: Any, user_id: int | None) -> Actor:
    user = db.get(models.User, user_id) if user_id is not None else None
    if user is None or user.access_revoked_at is not None:
        raise MediaError("Пользователь, запустивший импорт, больше не имеет доступа")
    return Actor(id=user.id, role=Role(user.role))


def _report(job_id: int, fraction: float) -> None:
    with database.session_factory()() as db:
        jobs.set_progress(db, job_id, fraction)
        db.commit()


def run_import(
    job_id: int, created_by: int | None, payload: dict[str, Any], settings: Settings
) -> None:
    """Импорт выбранного. Если часть не удалась, задача помечается ошибкой с итогом, а принятые
    файлы остаются в карточке."""
    gateway = _gateway()
    ids: list[int] = list(payload["media_ids"])
    with database.session_factory()() as db:
        actor = _actor(db, created_by)
    done, failures = 0, []
    for index, media_id in enumerate(ids):
        try:
            _import_one(job_id, index, len(ids), media_id, actor, payload, settings, gateway)
            done += 1
        except Exception as exc:
            if not isinstance(
                exc,
                (
                    storage.NoRoom,
                    FileNotFoundError,
                    MediaError,
                    core.ServiceError,
                    PermissionDenied,
                ),
            ):
                log.exception("импорт из Telegram: сообщение %s не загружено", media_id)
            failures.append(explain(exc))
        _report(job_id, (index + 1) / len(ids))
    if failures:
        reasons = "; ".join(dict.fromkeys(failures))[:300]
        raise MediaError(f"Загружено {done} из {len(ids)}. {reasons}")


def _import_one(
    job_id: int,
    index: int,
    total: int,
    media_id: int,
    actor: Actor,
    payload: dict[str, Any],
    settings: Settings,
    gateway: Any,
) -> None:
    sessions = database.session_factory()
    entity = (payload["entity_type"], payload["entity_id"], payload["purpose"])
    project_id = payload["project_id"]
    with sessions() as db:
        row = tg_service.get_media(db, media_id)
        # Повторный выбор того же сообщения не создаёт дубль: привязываем уже загруженный файл.
        if tg_service.attach_imported(db, actor, row, *entity) is not None:
            db.commit()
            return
        if row.kind == "link":
            tg_service.import_link(
                db, actor, row, project_id=project_id,
                entity_type=entity[0], entity_id=entity[1], purpose=entity[2],
            )  # fmt: skip
            db.commit()
            return
        message_id, expected = row.message_id, row.size_bytes or 0
        project = projects.get_project(db)
        limit_gb = project.storage_limit_gb if project else 5.0
    storage.ensure_room(settings, limit_gb, expected)

    tmp = settings.tg_tmp_dir / f"{job_id}-{media_id}.part"
    last = [0.0]

    def on_progress(received: int, size: int) -> None:
        now = time.monotonic()
        if size and now - last[0] >= PROGRESS_EVERY_SEC and runtime.loop is not None:
            last[0] = now
            runtime.loop.run_in_executor(None, _report, job_id, (index + received / size) / total)

    try:
        _await(gateway.download(message_id, tmp, on_progress))
        digest, size = _sha256(tmp)
        with sessions() as db:
            row = tg_service.get_media(db, media_id)
            if tg_service.attach_imported(db, actor, row, *entity) is not None:
                db.commit()  # пока качали, тот же файл успел принять другой импорт
                return
            tg_service.import_downloaded(
                db, actor, row, project_id=project_id, tmp_path=tmp, sha256=digest,
                size_bytes=size, files_dir=settings.files_dir,
                entity_type=entity[0], entity_id=entity[1], purpose=entity[2],
            )  # fmt: skip
            db.commit()
    finally:
        tmp.unlink(missing_ok=True)  # после успешного переноса файла уже нет


def run_preview(job_id: int, media_id: int, settings: Settings) -> None:
    """Скачивает файл во временный кэш просмотра (не в проект)."""
    gateway = _gateway()
    with database.session_factory()() as db:
        row = tg_service.get_media(db, media_id)
        info = MediaInfo(
            message_id=row.message_id, topic_id=row.topic_id, posted_at=row.posted_at,
            kind=row.kind, mime=row.mime, file_name=row.file_name,
        )  # fmt: skip
        expected = row.size_bytes or 0
        project = projects.get_project(db)
        limit_gb = project.storage_limit_gb if project else 5.0
    if previews.cached(settings, info.message_id, info.topic_id) is not None:
        return
    storage.ensure_room(settings, limit_gb, expected)
    dest = previews.target(settings, info)
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        _await(gateway.download(info.message_id, part, None))
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    previews.evict(settings, keep=dest)

"""Фоновое обслуживание: ночной бэкап базы и уборка старых пакетов экспорта.

Раз в несколько минут проверяет, не пора ли. Сами тяжёлые операции идут задачами очереди (`job`),
как и всё остальное: воркер уже не больше двух задач за раз и переживает перезапуск.
"""

import asyncio
import contextlib
import logging

from sqlalchemy import select

from app import backup, models
from app import db as database
from app.config import Settings
from app.constants import JobStatus, JobType
from app.services import exports, jobs

log = logging.getLogger(__name__)

TICK_SEC = 600
CLEANUP_EVERY_TICKS = 6  # раз в час


def queue_backup_if_due(settings: Settings) -> bool:
    """Ставит задачу бэкапа, если пора и такой ещё нет в очереди. Возвращает, поставлена ли."""
    if not backup.is_due(settings):
        return False
    with database.session_factory()() as db:
        pending = db.scalar(
            select(models.Job.id).where(
                models.Job.type == JobType.BACKUP.value,
                models.Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
            )
        )
        if pending is not None:
            return False
        jobs.enqueue(db, JobType.BACKUP, {})
        db.commit()
    return True


class Maintenance:
    def __init__(self, settings: Settings, wake: callable) -> None:  # type: ignore[valid-type]
        self.settings = settings
        self._wake = wake
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await asyncio.to_thread(exports.cleanup, self.settings)
        self._task = asyncio.create_task(self._run(), name="maintenance")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(TICK_SEC)  # первая проверка — спустя минуты после старта, не сразу
            try:
                if await asyncio.to_thread(queue_backup_if_due, self.settings):
                    self._wake()
                tick += 1
                if tick % CLEANUP_EVERY_TICKS == 0:
                    await asyncio.to_thread(exports.cleanup, self.settings)
            except Exception:
                log.exception("ошибка фонового обслуживания")

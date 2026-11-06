"""Пул индексаторов: по шлюзу и индексатору на чат каждого проекта.

Чат собирает либо юзербот (фильм и старые проекты: он читает и историю), либо бот (новые проекты:
только то, что прислали после его появления в чате); кто именно — `project.collector`. У каждого
клиента свой `RateLimiter` (≤ 1 запрос в секунду на аккаунт, а не на чат: иначе три проекта втроём
упрутся во FloodWait) и свой замок: файлы клиента качаются по одному, а большие загрузки фильма не
задерживают бота.
"""

import asyncio
import logging
import shutil
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.config import Settings
from app.constants import Collector
from app.tg import runtime
from app.tg.indexer import Indexer
from app.tg.limiter import RateLimiter
from app.tg.telethon_gateway import TelethonGateway

log = logging.getLogger(__name__)


class IndexerPool:
    def __init__(
        self, userbot: Any, sessions: sessionmaker[Session], settings: Settings, *, bot: Any = None
    ) -> None:
        self._clients: dict[Collector, Any] = {Collector.USERBOT: userbot, Collector.BOT: bot}
        self._limiters = {c: RateLimiter() for c in Collector}
        self._locks = {c: asyncio.Lock() for c in Collector}
        self._sessions = sessions
        self._settings = settings
        self._started: dict[int, Indexer] = {}

    async def start(self, chat_ids: list[int]) -> None:
        shutil.rmtree(
            self._settings.tg_tmp_dir, ignore_errors=True
        )  # недокачанное с прошлого запуска
        runtime.loop = asyncio.get_running_loop()
        for chat_id in chat_ids:
            try:
                await self.ensure(chat_id)
            except Exception:  # один чат без клиента не должен остановить остальные
                log.exception("индексатор чата %s не запущен", chat_id)

    def _collector_of(self, chat_id: int) -> Collector:
        with self._sessions() as db:
            value = db.scalar(
                select(models.Project.collector).where(models.Project.tg_chat_id == chat_id)
            )
        return Collector(value) if value else Collector.USERBOT

    async def ensure(self, chat_id: int, collector: Collector | None = None) -> Indexer:
        """Запускает индексатор чата, если ещё не запущен (проекту привязали чат). Кто собирает —
        из проекта, если не сказано."""
        indexer = self._started.get(chat_id)
        if indexer is not None:
            return indexer
        collector = collector or await asyncio.to_thread(self._collector_of, chat_id)
        client = self._clients[collector]
        if client is None:
            raise RuntimeError(
                "Бот не подключён" if collector is Collector.BOT else "Юзербот не подключён"
            )
        gateway = TelethonGateway(
            client,
            chat_id,
            self._limiters[collector],
            download_lock=self._locks[collector],
            live_only=collector is Collector.BOT,
        )
        indexer = Indexer(gateway, self._sessions, self._settings)
        runtime.register(gateway, indexer)
        self._started[chat_id] = indexer
        await indexer.start()
        log.info("индексатор Telegram запущен для чата %s (%s)", chat_id, collector.value)
        return indexer

    async def remove(self, chat_id: int) -> None:
        """Проект отклонён или чат отвязан: индексатор чата останавливается, шлюз забывается."""
        indexer = self._started.pop(chat_id, None)
        if indexer is not None:
            await indexer.stop()
        runtime.gateways.pop(chat_id, None)
        runtime.indexers.pop(chat_id, None)

    async def stop(self) -> None:
        for indexer in self._started.values():
            await indexer.stop()
        self._started.clear()

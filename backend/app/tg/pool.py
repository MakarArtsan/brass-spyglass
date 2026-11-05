"""Пул индексаторов: по шлюзу и индексатору на чат каждого проекта, поверх одного юзербота.

Запросы всех чатов идут через один `RateLimiter` (≤ 1 в секунду на аккаунт, а не на чат: иначе три
проекта втроём упрутся во FloodWait), а файлы качаются по одному на весь аккаунт.
"""

import asyncio
import logging
import shutil
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.tg import runtime
from app.tg.indexer import Indexer
from app.tg.limiter import RateLimiter
from app.tg.telethon_gateway import TelethonGateway

log = logging.getLogger(__name__)


class IndexerPool:
    def __init__(self, userbot: Any, sessions: sessionmaker[Session], settings: Settings) -> None:
        self._userbot = userbot
        self._sessions = sessions
        self._settings = settings
        self._limiter = RateLimiter()
        self._download_lock = asyncio.Lock()
        self._started: dict[int, Indexer] = {}

    async def start(self, chat_ids: list[int]) -> None:
        shutil.rmtree(
            self._settings.tg_tmp_dir, ignore_errors=True
        )  # недокачанное с прошлого запуска
        runtime.loop = asyncio.get_running_loop()
        for chat_id in chat_ids:
            await self.ensure(chat_id)

    async def ensure(self, chat_id: int) -> Indexer:
        """Запускает индексатор чата, если ещё не запущен (проекту привязали чат)."""
        indexer = self._started.get(chat_id)
        if indexer is not None:
            return indexer
        gateway = TelethonGateway(
            self._userbot, chat_id, self._limiter, download_lock=self._download_lock
        )
        indexer = Indexer(gateway, self._sessions, self._settings)
        runtime.register(gateway, indexer)
        self._started[chat_id] = indexer
        await indexer.start()
        log.info("индексатор Telegram запущен для чата %s", chat_id)
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

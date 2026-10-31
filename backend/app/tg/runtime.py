"""Что запущено в процессе: шлюз, индексатор и цикл событий. Воркер (он в потоке) берёт отсюда
шлюз и ходит в него через `run_coroutine_threadsafe`: клиент Telethon живёт в основном цикле."""

import asyncio
from typing import TYPE_CHECKING

from app.tg.types import Gateway

if TYPE_CHECKING:
    from app.tg.indexer import Indexer

gateway: Gateway | None = None
indexer: "Indexer | None" = None
loop: asyncio.AbstractEventLoop | None = None


def reset() -> None:
    global gateway, indexer, loop
    gateway, indexer, loop = None, None, None

"""Что запущено в процессе: шлюзы и индексаторы по чатам проектов и цикл событий.

Воркер (он в потоке) берёт отсюда шлюз нужного чата и ходит в него через `run_coroutine_threadsafe`:
клиент Telethon живёт в основном цикле. Один чат — один проект, поэтому ключ — id чата."""

import asyncio
from typing import TYPE_CHECKING

from app.tg.types import Gateway

if TYPE_CHECKING:
    from app.tg.indexer import Indexer

gateways: dict[int, Gateway] = {}
indexers: "dict[int, Indexer]" = {}
loop: asyncio.AbstractEventLoop | None = None


def register(gateway: Gateway, indexer: "Indexer | None" = None) -> None:
    gateways[gateway.chat_id] = gateway
    if indexer is not None:
        indexers[gateway.chat_id] = indexer


def gateway_for(chat_id: int | None) -> Gateway | None:
    """Шлюз чата проекта; None — юзербот не подключён или у проекта нет чата."""
    return gateways.get(chat_id) if chat_id is not None else None


def indexer_for(chat_id: int | None) -> "Indexer | None":
    return indexers.get(chat_id) if chat_id is not None else None


def reset() -> None:
    global loop
    gateways.clear()
    indexers.clear()
    loop = None

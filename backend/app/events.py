"""Живые обновления: шина событий внутри процесса и поток SSE.

Сервисы пишут журнал (`log_activity`) и двигают задачи (`jobs`) внутри транзакции запроса. Рассылать
событие до коммита нельзя: клиент получит его раньше данных и перечитает старое. Поэтому события
копятся в `session.info` и уходят подписчикам из `after_commit`; откат транзакции их отбрасывает.

В событии только тип, сущность и id: содержимое клиент перечитывает обычным запросом, поэтому через
SSE не утекает ничего, что не отдал бы и сам API.

Приложение работает в одном процессе, так что шина — обычный набор очередей asyncio.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

KEEPALIVE_SEC = 15
MAX_SUBSCRIBERS = 200
QUEUE_SIZE = 256
MAX_EVENTS_PER_COMMIT = 100  # больше — одно событие «перечитайте всё» (пакетный импорт, сид)
PENDING = "pending_events"

Payload = dict[str, Any]
RESYNC: Payload = {"type": "resync"}


class TooManySubscribers(Exception):
    pass


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Payload]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)

    def publish(self, payload: Payload) -> None:
        """Из любого потока: запросы идут в пуле потоков, а очереди живут в цикле событий."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):  # цикл закрылся между проверкой и вызовом
            loop.call_soon_threadsafe(self._deliver, payload)

    def _deliver(self, payload: Payload) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Медленный клиент не копит память: сбрасываем очередь и просим перечитать всё.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(RESYNC)

    @contextlib.contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Payload]]:
        if len(self._subscribers) >= MAX_SUBSCRIBERS:
            raise TooManySubscribers
        queue: asyncio.Queue[Payload] = asyncio.Queue(QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


bus = EventBus()


def queue_event(db: Session, payload: Payload) -> None:
    """Запоминает событие; оно уйдёт подписчикам, только если транзакция зафиксирована."""
    db.info.setdefault(PENDING, []).append(payload)


@event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    pending: list[Payload] | None = session.info.pop(PENDING, None)
    if not pending:
        return
    unique = list({json.dumps(p, sort_keys=True): p for p in pending}.values())
    if len(unique) > MAX_EVENTS_PER_COMMIT:
        unique = [RESYNC]
    for payload in unique:
        bus.publish(payload)


@event.listens_for(Session, "after_rollback")
def _drop_after_rollback(session: Session) -> None:
    session.info.pop(PENDING, None)


def encode(payload: Payload) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def sse_stream(source: EventBus, keepalive: float = KEEPALIVE_SEC) -> AsyncIterator[str]:
    """Тело SSE-ответа. Отключение клиента отменяет генератор, и подписка снимается в `finally`."""
    with source.subscribe() as queue:
        yield "retry: 3000\n\n"
        yield encode({"type": "hello"})
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), keepalive)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield encode(payload)

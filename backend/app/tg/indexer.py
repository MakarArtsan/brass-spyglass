"""Индексатор: при первом подключении проходит все темы и пишет метаданные и маленькие превью;
дальше слушает новые сообщения, чтобы свежий референс был виден на сайте почти сразу.

Историю темы читает от новых сообщений к старым и запоминает, докуда дочитал: после перезапуска
контейнера продолжает с того места, а не с начала. Всё, что идёт в БД, — через `services.telegram`.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app import media
from app.config import Settings
from app.services import telegram as tg_service
from app.tg.limiter import FloodTooLong, flood_seconds
from app.tg.types import Gateway, HistoryItem, MediaInfo

log = logging.getLogger(__name__)

BATCH = 100
RESYNC_SEC = 15 * 60
THUMB_BATCH = 40
TOPIC_RETRIES = 3


@dataclass
class IndexState:
    """Что показывает экран «Telegram»: идёт ли синхронизация и чем закончилась последняя."""

    running: bool = False
    phase: str = "idle"  # idle | topics | history | thumbs
    topic: str | None = None
    thumbs_left: int = 0
    last_error: str | None = None
    last_run_at: datetime | None = None
    history: dict[int, str] = field(default_factory=dict)


class Indexer:
    def __init__(
        self,
        gateway: Gateway,
        sessions: sessionmaker[Session],
        settings: Settings,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.gateway = gateway
        self._sessions = sessions
        self._settings = settings
        self._sleep = sleep
        self.state = IndexState()
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    # --- жизненный цикл ------------------------------------------------------------------------

    async def start(self) -> None:
        self.gateway.on_new(self._on_new)
        self._task = asyncio.create_task(self._serve(), name="telegram-indexer")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def request_sync(self) -> None:
        """Ручная синхронизация (экран «Telegram»): не ждать плановой."""
        self._wake.set()

    async def _serve(self) -> None:
        while True:
            await self.run_once()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), RESYNC_SEC)

    async def run_once(self) -> None:
        self.state.running = True
        try:
            await self.sync_all()
            await self.make_thumbs()
            self.state.last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # индекс не должен валить сайт; ошибку видно на экране «Telegram»
            log.exception("синхронизация Telegram не удалась")
            self.state.last_error = str(exc) or exc.__class__.__name__
        finally:
            self.state.running = False
            self.state.phase = "idle"
            self.state.topic = None
            self.state.last_run_at = datetime.now(UTC)

    # --- работа с БД в потоке ------------------------------------------------------------------

    async def _db(self, fn: Callable[[Session], object]) -> object:
        def run() -> object:
            with self._sessions() as db:
                result = fn(db)
                db.commit()
                return result

        return await asyncio.to_thread(run)

    # --- история ---------------------------------------------------------------------------------

    async def sync_all(self) -> None:
        self.state.phase = "topics"
        chat = self.gateway.chat_id
        topics = await self.gateway.topics()
        await self._db(lambda db: tg_service.upsert_topics(db, chat, topics))
        for topic in topics:
            self.state.phase, self.state.topic = "history", topic.title
            await self._sync_topic_with_retries(topic.topic_id)

    async def _sync_topic_with_retries(self, topic_id: int) -> None:
        for attempt in range(TOPIC_RETRIES + 1):
            try:
                await self.sync_topic(topic_id)
                return
            except FloodTooLong:
                raise
            except Exception as exc:
                seconds = flood_seconds(exc)
                if seconds is None or attempt == TOPIC_RETRIES:
                    raise
                # Telegram просит подождать: ждём и продолжаем с сохранённого места темы.
                log.warning("FloodWait в теме %s: ждём %s с", topic_id, seconds)
                await self._sleep(seconds + 1)

    async def sync_topic(self, topic_id: int) -> None:
        chat = self.gateway.chat_id

        def read(db: Session) -> tuple[int, int | None, bool]:
            topic = tg_service.get_topic(db, chat, topic_id)
            newest = tg_service.newest_message_id(db, chat, topic_id)
            return (
                newest,
                topic.oldest_message_id if topic else None,
                bool(topic and topic.history_complete),
            )

        newest, oldest, complete = await self._db(read)  # type: ignore[misc]
        if newest:  # что пришло, пока нас не было
            await self._read(topic_id, min_id=newest, reverse=True)
        if not complete:
            await self._read(topic_id, max_id=oldest or 0, backfill=True)

    async def _read(
        self,
        topic_id: int,
        *,
        min_id: int = 0,
        max_id: int = 0,
        reverse: bool = False,
        backfill: bool = False,
    ) -> None:
        chat = self.gateway.chat_id
        pending: list[MediaInfo] = []
        lowest = 0

        async def flush(final: bool = False) -> None:
            nonlocal pending
            batch, pending = pending, []

            def write(db: Session) -> None:
                tg_service.save_media(db, chat, batch)
                tg_service.mark_progress(
                    db,
                    chat,
                    topic_id,
                    oldest=lowest or None if backfill else None,
                    complete=True if backfill and final else None,
                )

            await self._db(write)

        async for item in self.gateway.history(
            topic_id, min_id=min_id, max_id=max_id, reverse=reverse
        ):
            lowest = item.message_id if not lowest else min(lowest, item.message_id)
            if item.media is not None:
                pending.append(item.media)
            if len(pending) >= BATCH:
                await flush()
        await flush(final=True)

    # --- миниатюры -----------------------------------------------------------------------------

    async def make_thumbs(self) -> None:
        """Маленькие превью (ТЗ): по одному запросу в секунду, сначала самые новые."""
        chat = self.gateway.chat_id
        self.state.phase = "thumbs"
        while True:
            todo = await self._db(lambda db: tg_service.without_thumbs(db, chat, THUMB_BATCH))
            self.state.thumbs_left = len(todo)  # type: ignore[arg-type]
            if not todo:
                return
            for media_id, message_id in todo:  # type: ignore[attr-defined]
                await self._thumb_one(media_id, message_id)

    async def _thumb_one(self, media_id: int, message_id: int) -> None:
        chat = self.gateway.chat_id
        path = self._settings.tg_thumbs_dir / str(chat) / f"{media_id}.jpg"
        stored = ""  # пусто — у этого файла миниатюры нет, повторять не нужно
        try:
            data = await self.gateway.thumb(message_id)
            if data:
                await asyncio.to_thread(media.thumb_from_bytes, data, path)
                stored = f"{chat}/{media_id}.jpg"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if flood_seconds(exc) is not None:
                raise  # FloodWait — не вина файла: повторим в следующий проход
            log.warning("миниатюра сообщения %s не получена: %s", message_id, exc)
        await self._db(lambda db: tg_service.set_thumb(db, media_id, stored))

    # --- новые сообщения -----------------------------------------------------------------------

    async def _on_new(self, item: HistoryItem, topic_id: int) -> None:
        """Новое сообщение чата: сразу в индекс, а миниатюра — следом."""
        if item.media is None:
            return
        chat = self.gateway.chat_id
        info = item.media

        def write(db: Session) -> int | None:
            tg_service.upsert_topics(db, chat, [])  # no-op: тема уже должна быть в индексе
            if tg_service.get_topic(db, chat, topic_id) is None:
                return None
            tg_service.save_media(db, chat, [info])
            tg_service.mark_progress(db, chat, topic_id)
            row = tg_service.find_media(db, chat, info.message_id)
            return row.id if row else None

        try:
            media_id = await self._db(write)
            if media_id is not None and info.kind in ("image", "video"):
                await self._thumb_one(media_id, info.message_id)  # type: ignore[arg-type]
            elif media_id is None:
                self.request_sync()  # тема новая — пусть полный проход заведёт её и дочитает
        except Exception:
            log.exception("не удалось проиндексировать новое сообщение %s", info.message_id)

"""Шлюз к Telegram на Telethon: единственное место, где видны типы Telethon.

Всё остальное (индексатор, сервисы, тесты) работает с `app.tg.types`. Защита аккаунта (ТЗ): запросы
идут через `RateLimiter` (не чаще раза в секунду, FloodWait пережидается), файлы качаются по одному.

Эта часть проверяется на подставном клиенте; с настоящим Telegram её нужно проверить на первом
подключении юзербота (см. DECISIONS.md).
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from app.tg.limiter import RateLimiter
from app.tg.parse import parse_message
from app.tg.types import GENERAL_TOPIC, HistoryItem, NewMessage, Progress, TopicInfo

log = logging.getLogger(__name__)

TOPICS_PAGE = 100
THUMB_TRIES = (1, -1, 0)  # индексы миниатюры от меньшей к большей; не у всех файлов их три
RECENT_MESSAGES = 500  # чтобы не спрашивать у Telegram то же сообщение второй раз ради миниатюры


class TelethonGateway:
    def __init__(self, client: Any, chat_id: int, limiter: RateLimiter | None = None) -> None:
        self.client = client
        self.chat_id = chat_id
        self.limiter = limiter or RateLimiter()
        self._input: Any = None
        self._forum: bool | None = None
        self._download_lock = asyncio.Lock()
        self._recent: OrderedDict[int, Any] = OrderedDict()

    # --- служебное -----------------------------------------------------------------------------

    async def _call(self, fn: Callable[[], Awaitable[Any]]) -> Any:
        return await self.limiter.call(fn)

    async def _chat(self) -> Any:
        if self._input is None:
            try:
                self._input = await self._call(lambda: self.client.get_input_entity(self.chat_id))
            except ValueError:
                await self._call(lambda: self.client.get_dialogs())  # прогрев кэша сущностей
                self._input = await self._call(lambda: self.client.get_input_entity(self.chat_id))
        return self._input

    def _remember(self, msg: Any) -> None:
        self._recent[msg.id] = msg
        self._recent.move_to_end(msg.id)
        while len(self._recent) > RECENT_MESSAGES:
            self._recent.popitem(last=False)

    async def _message(self, message_id: int) -> Any:
        known = self._recent.get(message_id)
        if known is not None:
            return known
        chat = await self._chat()
        msg = await self._call(lambda: self.client.get_messages(chat, ids=message_id))
        if msg is not None:
            self._remember(msg)
        return msg

    def _topic_of(self, msg: Any) -> int:
        """Тема сообщения: в форуме — id темы из reply_to, иначе «Общая»."""
        reply = getattr(msg, "reply_to", None)
        if self._forum and reply is not None and getattr(reply, "forum_topic", False):
            return int(getattr(reply, "reply_to_top_id", None) or reply.reply_to_msg_id)
        return GENERAL_TOPIC

    # --- Gateway -------------------------------------------------------------------------------

    async def topics(self) -> list[TopicInfo]:
        from telethon.tl.functions.channels import GetForumTopicsRequest

        chat = await self._chat()
        entity = await self._call(lambda: self.client.get_entity(chat))
        if not getattr(entity, "forum", False):
            # Чат без тем: весь чат — одна «тема», окно работает так же.
            self._forum = False
            return [TopicInfo(GENERAL_TOPIC, getattr(entity, "title", None) or "Чат")]
        self._forum = True
        out: list[TopicInfo] = []
        offset_date, offset_id, offset_topic = None, 0, 0
        while True:
            request = GetForumTopicsRequest(
                channel=chat,
                offset_date=offset_date,
                offset_id=offset_id,
                offset_topic=offset_topic,
                limit=TOPICS_PAGE,
            )
            page = await self._call(lambda r=request: self.client(r))
            topics = [t for t in page.topics if t.__class__.__name__ == "ForumTopic"]
            out += [TopicInfo(int(t.id), str(t.title)) for t in topics]
            if len(page.topics) < TOPICS_PAGE or not topics:
                return out
            last = topics[-1]
            offset_topic, offset_id = int(last.id), int(last.top_message)
            top = {m.id: m for m in page.messages}.get(last.top_message)
            offset_date = getattr(top, "date", None)

    async def history(
        self, topic_id: int, *, min_id: int = 0, max_id: int = 0, reverse: bool = False
    ) -> AsyncIterator[HistoryItem]:
        chat = await self._chat()
        options: dict[str, Any] = {
            "min_id": min_id,
            "max_id": max_id,
            "reverse": reverse,
            "wait_time": 1,
        }
        if self._forum and topic_id != GENERAL_TOPIC:
            options["reply_to"] = topic_id
        async for msg in self.client.iter_messages(chat, **options):
            if self._forum and topic_id == GENERAL_TOPIC and self._topic_of(msg) != GENERAL_TOPIC:
                continue  # у «Общей» темы нет своей ветки: отсеиваем сообщения других тем
            self._remember(msg)
            yield HistoryItem(int(msg.id), parse_message(msg, topic_id))

    async def thumb(self, message_id: int) -> bytes | None:
        msg = await self._message(message_id)
        if msg is None:
            return None
        for index in THUMB_TRIES:
            try:
                data = await self._call(
                    lambda i=index: self.client.download_media(msg, file=bytes, thumb=i)
                )
            except (IndexError, ValueError):
                continue  # у файла меньше миниатюр, чем мы просили
            if data:
                return bytes(data)
        return None

    async def download(
        self, message_id: int, dest: Path, on_progress: Progress | None = None
    ) -> None:
        async with self._download_lock:  # по одному файлу за раз (ТЗ)
            msg = await self._message(message_id)
            if msg is None or not getattr(msg, "media", None):
                raise FileNotFoundError("Сообщение удалено в Telegram или в нём нет файла")
            await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)

            def progress(received: int, total: int) -> None:
                if on_progress is not None:
                    on_progress(int(received), int(total or 0))

            result = await self._call(
                lambda: self.client.download_media(msg, file=str(dest), progress_callback=progress)
            )
            if not result:
                raise FileNotFoundError("Telegram не отдал файл")
            if Path(result) != dest:
                await asyncio.to_thread(Path(result).replace, dest)

    def on_new(self, callback: NewMessage) -> None:
        from telethon import events

        async def handler(event: Any) -> None:
            msg = event.message
            self._remember(msg)
            topic = self._topic_of(msg)
            await callback(HistoryItem(int(msg.id), parse_message(msg, topic)), topic)

        self.client.add_event_handler(handler, events.NewMessage(chats=self.chat_id))

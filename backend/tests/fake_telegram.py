"""Подставной Telegram для тестов: те же правила выдачи истории, что у настоящего (min_id/max_id
не включают границу, по умолчанию сначала новые), но без сети."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.tg.types import GENERAL_TOPIC, HistoryItem, MediaInfo, NewMessage, Progress, TopicInfo

CHAT = -1001234567890
T0 = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


def png_bytes(color=(90, 120, 160)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (800, 600), color).save(buffer, format="PNG")
    return buffer.getvalue()


def media(message_id: int, topic_id: int, kind: str = "image", **kw) -> MediaInfo:
    base = dict(
        message_id=message_id,
        topic_id=topic_id,
        posted_at=T0 + timedelta(minutes=message_id),
        kind=kind,
        mime={"image": "image/jpeg", "video": "video/mp4", "audio": "audio/ogg"}.get(kind),
        size_bytes=1000 + message_id,
        author_name="Лена",
        author_tg_id=7,
    )
    return MediaInfo(**{**base, **kw})


class FloodWaitError(Exception):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"flood {seconds}")
        self.seconds = seconds


class FakeGateway:
    def __init__(
        self, topics: list[TopicInfo], messages: dict[int, list[tuple[int, MediaInfo | None]]]
    ):
        self.chat_id = CHAT
        self._topics = topics
        self.messages = messages  # topic_id → [(message_id, media | None)]
        self.history_calls: list[dict] = []
        self.thumb_calls: list[int] = []
        self.no_thumb: set[int] = set()
        self.fail_history_after: int | None = None  # оборвать чтение после N сообщений
        self.flood_once: int | None = None
        self.callback: NewMessage | None = None
        self.files: dict[int, bytes] = {}
        self.download_calls: list[int] = []
        self.deleted: set[int] = set()

    async def topics(self) -> list[TopicInfo]:
        return list(self._topics)

    async def history(
        self, topic_id: int, *, min_id: int = 0, max_id: int = 0, reverse: bool = False
    ) -> AsyncIterator[HistoryItem]:
        self.history_calls.append(
            {"topic": topic_id, "min_id": min_id, "max_id": max_id, "reverse": reverse}
        )
        if self.flood_once is not None:
            seconds, self.flood_once = self.flood_once, None
            raise FloodWaitError(seconds)
        rows = [
            r
            for r in self.messages.get(topic_id, [])
            if r[0] > min_id and (not max_id or r[0] < max_id)
        ]
        rows.sort(key=lambda r: r[0], reverse=not reverse)
        for count, (message_id, info) in enumerate(rows):
            if self.fail_history_after is not None and count >= self.fail_history_after:
                raise ConnectionError("обрыв связи")
            yield HistoryItem(message_id, info)

    async def thumb(self, message_id: int) -> bytes | None:
        self.thumb_calls.append(message_id)
        return None if message_id in self.no_thumb else png_bytes()

    async def download(
        self, message_id: int, dest: Path, on_progress: Progress | None = None
    ) -> None:
        self.download_calls.append(message_id)
        if message_id in self.deleted or message_id not in self.files:
            raise FileNotFoundError("Сообщение удалено в Telegram или в нём нет файла")
        data = self.files[message_id]
        await asyncio.to_thread(self._write, dest, data)
        if on_progress:
            on_progress(len(data), len(data))

    @staticmethod
    def _write(dest: Path, data: bytes) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def on_new(self, callback: NewMessage) -> None:
        self.callback = callback

    async def emit(
        self, info: MediaInfo | None, topic_id: int, message_id: int | None = None
    ) -> None:
        assert self.callback is not None
        await self.callback(
            HistoryItem(message_id or (info.message_id if info else 0), info), topic_id
        )


def simple_chat(per_topic: int = 5) -> FakeGateway:
    topics = [TopicInfo(GENERAL_TOPIC, "Общая"), TopicInfo(5, "Персонажи"), TopicInfo(9, "Локации")]
    messages: dict[int, list[tuple[int, MediaInfo | None]]] = {}
    next_id = 100
    for topic in (5, 9):
        rows = []
        for _ in range(per_topic):
            next_id += 1
            rows.append((next_id, media(next_id, topic)))
        messages[topic] = rows
    return FakeGateway(topics, messages)

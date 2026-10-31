"""Что юзербот знает о чате. Типы Telethon дальше шлюза не проходят: индексатор, сервисы и тесты
работают с этими простыми структурами, поэтому проверяются без настоящего Telegram."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

GENERAL_TOPIC = 1  # «Общая» тема форума; в чате без тем весь чат считается ею


@dataclass(frozen=True, slots=True)
class TopicInfo:
    topic_id: int
    title: str
    icon_emoji: str | None = None


@dataclass(frozen=True, slots=True)
class MediaInfo:
    message_id: int
    topic_id: int
    posted_at: datetime
    kind: str  # image | video | audio | document | link
    grouped_id: int | None = None  # альбом
    mime: str | None = None
    size_bytes: int | None = None
    duration_sec: float | None = None
    caption: str | None = None
    file_name: str | None = None
    url: str | None = None  # у ссылок из текста
    author_name: str | None = None
    author_tg_id: int | None = None


@dataclass(frozen=True, slots=True)
class HistoryItem:
    """Сообщение истории. `media` пуст у текстовых: по ним индексатор всё равно двигает курсор."""

    message_id: int
    media: MediaInfo | None


Progress = Callable[[int, int], None]  # получено байт, всего байт
NewMessage = Callable[[HistoryItem, int], Awaitable[None]]  # (сообщение, id темы)


class Gateway(Protocol):
    """Единственное, что индексатору нужно от Telegram."""

    chat_id: int

    async def topics(self) -> list[TopicInfo]: ...

    def history(
        self, topic_id: int, *, min_id: int = 0, max_id: int = 0, reverse: bool = False
    ) -> AsyncIterator[HistoryItem]: ...

    async def thumb(self, message_id: int) -> bytes | None: ...

    async def download(
        self, message_id: int, dest: Path, on_progress: Progress | None = None
    ) -> None: ...

    def on_new(self, callback: NewMessage) -> None: ...

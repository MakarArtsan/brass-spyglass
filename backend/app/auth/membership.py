"""Кто состоит в закрытых чатах проектов. Списки читает юзербот (бот в чате может не быть)."""

import asyncio
import logging
import time
from collections.abc import Collection
from typing import Protocol

log = logging.getLogger(__name__)


class MembershipUnavailable(Exception):  # noqa: N818
    """Telegram не ответил или юзербот не настроен — решение «членство» принять нельзя."""


class MembershipChecker(Protocol):
    async def chats_of(self, tg_id: int, chat_ids: Collection[int]) -> dict[int, bool | None]:
        """Для каждого чата: состоит ли человек (True/False) или не удалось узнать (None).
        Если не удалось узнать ничего — `MembershipUnavailable`."""
        ...

    async def participants(self, chat_id: int) -> set[int]:
        """Свежий список участников чата (для синхронизации). Сбой — `MembershipUnavailable`."""
        ...

    def forget(self, chat_id: int) -> None:
        """Список чата устарел (кто-то вступил или вышел): следующая проверка читает его заново."""
        ...


class DisabledMembership:
    """Юзербот не подключён: проверить членство нельзя (суперадмин входит по OWNER_TG_ID)."""

    async def chats_of(self, tg_id: int, chat_ids: Collection[int]) -> dict[int, bool | None]:
        raise MembershipUnavailable("юзербот не подключён")

    async def participants(self, chat_id: int) -> set[int]:
        raise MembershipUnavailable("юзербот не подключён")

    def forget(self, chat_id: int) -> None:
        return None


class TelethonMembership:
    """Списки участников чатов читает юзербот. Участников немного, поэтому список чата хранится
    целиком; при проверке обновляется по требованию, не чаще раза в REFRESH_MIN_SEC (FloodWait)."""

    FRESH_SEC = 60
    REFRESH_MIN_SEC = 10

    def __init__(self, client: object) -> None:
        self._client = client
        self._members: dict[int, set[int]] = {}
        self._refreshed_at: dict[int, float] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def _read(self, chat_id: int) -> set[int]:
        client = self._client
        try:
            try:
                chat = await client.get_input_entity(chat_id)  # type: ignore[attr-defined]
            except ValueError:
                await client.get_dialogs()  # type: ignore[attr-defined]  # прогрев кэша сущностей
                chat = await client.get_input_entity(chat_id)  # type: ignore[attr-defined]
            ids: set[int] = set()
            async for member in client.iter_participants(chat):  # type: ignore[attr-defined]
                ids.add(member.id)
        except Exception as exc:
            log.warning("не удалось прочитать участников чата %s: %s", chat_id, exc)
            raise MembershipUnavailable(str(exc)) from exc
        return ids

    async def _refresh(self, chat_id: int) -> None:
        async with self._locks.setdefault(chat_id, asyncio.Lock()):
            self._members[chat_id] = await self._read(chat_id)
            self._refreshed_at[chat_id] = time.monotonic()

    async def participants(self, chat_id: int) -> set[int]:
        await self._refresh(chat_id)
        return set(self._members[chat_id])

    def forget(self, chat_id: int) -> None:
        self._refreshed_at.pop(chat_id, None)

    async def _is_member(self, chat_id: int, tg_id: int) -> bool:
        age = time.monotonic() - self._refreshed_at.get(chat_id, float("-inf"))
        if tg_id in self._members.get(chat_id, ()) and age < self.FRESH_SEC:
            return True
        if age >= self.REFRESH_MIN_SEC:
            await self._refresh(chat_id)
        return tg_id in self._members.get(chat_id, ())

    async def chats_of(self, tg_id: int, chat_ids: Collection[int]) -> dict[int, bool | None]:
        result: dict[int, bool | None] = {}
        for chat_id in chat_ids:
            try:
                result[chat_id] = await self._is_member(chat_id, tg_id)
            except MembershipUnavailable:
                result[chat_id] = None  # этот чат не прочитался; остальные могут быть известны
        if result and all(state is None for state in result.values()):
            raise MembershipUnavailable("не удалось прочитать ни один чат проекта")
        return result

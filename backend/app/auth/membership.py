"""Кто состоит в закрытых чатах проектов. Списки читает юзербот (бот в чате может не быть)."""

import asyncio
import logging
import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

MAX_DIALOGS = 150  # сколько последних диалогов юзербота просматривать при поиске чатов
MAX_CHAT_MEMBERS = 300  # чаты крупнее — не командные: не читаем и не предлагаем
CHATS_CACHE_SEC = 20.0


@dataclass(frozen=True, slots=True)
class ChatInfo:
    id: int
    title: str


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

    async def manageable_chats(self, tg_id: int, exclude: Collection[int]) -> list[ChatInfo]:
        """Группы, где состоят и юзербот, и этот человек, причём он администратор или создатель
        (чат нельзя «занять» простым участником). Занятые чаты (`exclude`) не предлагаются."""
        ...

    async def chat_for(
        self, tg_id: int, chat_id: int, *, require_admin: bool = True
    ) -> ChatInfo | None:
        """Тот же чат по id — проверка на сервере перед созданием проекта. None: юзербота в нём
        нет или человек не администратор (при `require_admin=False` хватает, что чат виден)."""
        ...


class DisabledMembership:
    """Юзербот не подключён: проверить членство нельзя (суперадмин входит по OWNER_TG_ID)."""

    async def chats_of(self, tg_id: int, chat_ids: Collection[int]) -> dict[int, bool | None]:
        raise MembershipUnavailable("юзербот не подключён")

    async def participants(self, chat_id: int) -> set[int]:
        raise MembershipUnavailable("юзербот не подключён")

    def forget(self, chat_id: int) -> None:
        return None

    async def manageable_chats(self, tg_id: int, exclude: Collection[int]) -> list[ChatInfo]:
        raise MembershipUnavailable("юзербот не подключён")

    async def chat_for(
        self, tg_id: int, chat_id: int, *, require_admin: bool = True
    ) -> ChatInfo | None:
        raise MembershipUnavailable("юзербот не подключён")


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
        self._chats_cache: dict[int, tuple[float, list[ChatInfo]]] = {}

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

    # --- чаты, которыми человек может распоряжаться ---------------------------------------------

    async def _is_admin(self, chat: object, tg_id: int) -> bool:
        """Состоит ли человек в чате и администратор ли он (создатель — тоже)."""
        client = self._client
        async for participant in client.iter_participants(chat):  # type: ignore[attr-defined]
            if participant.id == tg_id:
                rights = await client.get_permissions(chat, participant)  # type: ignore[attr-defined]
                return bool(rights.is_admin or rights.is_creator)
        return False

    async def manageable_chats(self, tg_id: int, exclude: Collection[int]) -> list[ChatInfo]:
        cached = self._chats_cache.get(tg_id)
        if cached is None or time.monotonic() - cached[0] >= CHATS_CACHE_SEC:
            cached = (time.monotonic(), await self._scan_chats(tg_id))
            self._chats_cache[tg_id] = cached
        return [chat for chat in cached[1] if chat.id not in set(exclude)]

    async def _scan_chats(self, tg_id: int) -> list[ChatInfo]:
        found: list[ChatInfo] = []
        try:
            async for dialog in self._client.iter_dialogs(limit=MAX_DIALOGS):  # type: ignore[attr-defined]
                if not dialog.is_group:
                    continue
                size = getattr(dialog.entity, "participants_count", None)
                if size is not None and size > MAX_CHAT_MEMBERS:
                    continue
                try:
                    if await self._is_admin(dialog.entity, tg_id):
                        found.append(ChatInfo(dialog.id, dialog.title or str(dialog.id)))
                except Exception as exc:  # один недоступный чат не должен скрыть остальные
                    log.warning("чат %s не проверен: %s", dialog.id, exc)
        except Exception as exc:
            log.warning("не удалось просмотреть чаты юзербота: %s", exc)
            raise MembershipUnavailable(str(exc)) from exc
        return found

    async def chat_for(
        self, tg_id: int, chat_id: int, *, require_admin: bool = True
    ) -> ChatInfo | None:
        client = self._client
        try:
            try:
                chat = await client.get_input_entity(chat_id)  # type: ignore[attr-defined]
            except ValueError:
                await client.get_dialogs()  # type: ignore[attr-defined]
                chat = await client.get_input_entity(chat_id)  # type: ignore[attr-defined]
            entity = await client.get_entity(chat)  # type: ignore[attr-defined]
            if require_admin and not await self._is_admin(chat, tg_id):
                return None
            return ChatInfo(chat_id, getattr(entity, "title", None) or str(chat_id))
        except ValueError:
            return None  # юзербота в этом чате нет
        except Exception as exc:
            log.warning("не удалось проверить чат %s: %s", chat_id, exc)
            raise MembershipUnavailable(str(exc)) from exc

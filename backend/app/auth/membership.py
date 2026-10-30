"""Проверка, что человек состоит в закрытом чате команды."""

import logging
import time
from typing import Protocol

log = logging.getLogger(__name__)


class MembershipUnavailable(Exception):  # noqa: N818
    """Telegram не ответил или юзербот не настроен — решение «членство» принять нельзя."""


class MembershipChecker(Protocol):
    async def is_member(self, tg_id: int) -> bool: ...


class DisabledMembership:
    """Юзербот не подключён: проверить членство нельзя (владелец входит по OWNER_TG_ID)."""

    async def is_member(self, tg_id: int) -> bool:
        raise MembershipUnavailable("юзербот не подключён")


class TelethonMembership:
    """Список участников чата читает юзербот: бот в чат может быть не добавлен.

    Участников немного, поэтому хранится целиком; обновляется по требованию,
    не чаще раза в REFRESH_MIN_SEC, чтобы не упереться во FloodWait.
    """

    FRESH_SEC = 60
    REFRESH_MIN_SEC = 10

    def __init__(self, client: object, chat_id: int) -> None:
        self._client = client
        self._chat_id = chat_id
        self._members: set[int] = set()
        self._refreshed_at = 0.0

    async def _refresh(self) -> None:
        client = self._client
        try:
            try:
                chat = await client.get_input_entity(self._chat_id)  # type: ignore[attr-defined]
            except ValueError:
                await client.get_dialogs()  # type: ignore[attr-defined]  # прогрев кэша сущностей
                chat = await client.get_input_entity(self._chat_id)  # type: ignore[attr-defined]
            ids: set[int] = set()
            async for member in client.iter_participants(chat):  # type: ignore[attr-defined]
                ids.add(member.id)
        except Exception as exc:
            log.warning("не удалось прочитать участников чата: %s", exc)
            raise MembershipUnavailable(str(exc)) from exc
        self._members = ids
        self._refreshed_at = time.monotonic()

    async def is_member(self, tg_id: int) -> bool:
        age = time.monotonic() - self._refreshed_at
        if tg_id in self._members and age < self.FRESH_SEC:
            return True
        if age >= self.REFRESH_MIN_SEC:
            await self._refresh()
        return tg_id in self._members

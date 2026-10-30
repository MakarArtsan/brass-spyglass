"""Одноразовые токены входа: сайт показывает t.me/<bot>?start=<токен> и ждёт подтверждения.

Живут в памяти процесса — приложение работает в одном экземпляре. Перезапуск сбрасывает
только ожидающие входы: человек нажимает кнопку ещё раз. Всё работает в одном event loop.
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field

MAX_PENDING = 500


@dataclass
class LoginToken:
    expires_at: float
    user_id: int | None = None
    claimed: bool = False
    confirmed: asyncio.Event = field(default_factory=asyncio.Event)


class LoginTokenStore:
    def __init__(self, ttl_sec: int = 300) -> None:
        self.ttl = ttl_sec
        self._items: dict[str, LoginToken] = {}

    def _purge(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._items.items() if v.expires_at <= now]:
            del self._items[key]

    def create(self) -> str | None:
        """Новый токен; `None`, если ожидающих входов подозрительно много."""
        self._purge()
        if len(self._items) >= MAX_PENDING:
            return None
        token = secrets.token_urlsafe(24)  # 32 символа — влезает в start-параметр Telegram
        self._items[token] = LoginToken(expires_at=time.monotonic() + self.ttl)
        return token

    def get(self, token: str) -> LoginToken | None:
        item = self._items.get(token)
        if item is None or item.expires_at <= time.monotonic():
            self._items.pop(token, None)
            return None
        return item

    def confirm(self, token: str, user_id: int) -> bool:
        item = self.get(token)
        if item is None or item.user_id is not None:
            return False
        item.user_id = user_id
        item.confirmed.set()
        return True

    async def wait(self, token: str, max_wait_sec: float) -> int | None:
        """Ждёт подтверждения; `None` — токен устарел или время вышло."""
        item = self.get(token)
        if item is None:
            return None
        try:
            await asyncio.wait_for(item.confirmed.wait(), max_wait_sec)
        except TimeoutError:
            return None
        return item.user_id

    def claim(self, token: str) -> int | None:
        """Забрать подтверждённый вход. Токен одноразовый."""
        item = self.get(token)
        if item is None or item.user_id is None or item.claimed:
            return None
        item.claimed = True
        user_id = item.user_id
        del self._items[token]
        return user_id

"""Защита аккаунта (ТЗ): не больше одного запроса в секунду к Telegram и обработка FloodWait."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")
MIN_INTERVAL_SEC = 1.0
MAX_FLOOD_SEC = 15 * 60  # дольше ждать не будем: пусть вызывающий решит, что делать
FLOOD_RETRIES = 3


def flood_seconds(exc: BaseException) -> float | None:
    """Сколько Telegram просит подождать при FloodWait (Telethon: `FloodWaitError.seconds`)."""
    if exc.__class__.__name__ in ("FloodWaitError", "SlowModeWaitError", "FloodPremiumWaitError"):
        seconds = getattr(exc, "seconds", None)
        return float(seconds) if isinstance(seconds, int | float) else None
    return None


class FloodTooLong(Exception):  # noqa: N818
    """Telegram просит ждать дольше `MAX_FLOOD_SEC`."""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"Telegram просит подождать {int(seconds)} с")
        self.seconds = seconds


class RateLimiter:
    def __init__(
        self,
        interval: float = MIN_INTERVAL_SEC,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Пропускает запросы не чаще одного за `interval`; ожидающие встают в очередь."""
        async with self._lock:
            now = self._clock()
            if now < self._next:
                await self._sleep(self._next - now)
                now = self._next
            self._next = now + self._interval

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Вызов с ограничением частоты; FloodWait пережидается и повторяется несколько раз."""
        for attempt in range(FLOOD_RETRIES + 1):
            await self.wait()
            try:
                return await fn()
            except Exception as exc:
                seconds = flood_seconds(exc)
                if seconds is None:
                    raise
                if seconds > MAX_FLOOD_SEC:
                    raise FloodTooLong(seconds) from exc
                if attempt == FLOOD_RETRIES:
                    raise
                log.warning("FloodWait: ждём %s с (попытка %s)", seconds, attempt + 1)
                await self._sleep(seconds + 1)
        raise AssertionError("недостижимо")  # pragma: no cover

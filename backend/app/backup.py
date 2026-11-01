"""Ночные бэкапы базы (ТЗ): `VACUUM INTO` в /data/backups, 14 копий, копию присылает бот владельцу.

Копия — целостный снимок базы без остановки приложения (SQLite в режиме WAL читается,
пока идёт запись). Файл сжимается gzip: база ужимается в несколько раз, а у бота есть лимит
на размер файла. Восстановление: остановить приложение, `gunzip` нужной копии и положить её
как /data/db/app.sqlite.
"""

import asyncio
import gzip
import json
import logging
import re
import shutil
import sqlite3
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import Settings
from app.metrics import TEAM_TZ

log = logging.getLogger(__name__)

KEEP = 14
NIGHT_HOUR = 3  # по Москве: команда в это время не работает
MIN_GAP = timedelta(hours=20)  # не чаще раза в сутки
CATCH_UP = timedelta(hours=30)  # старше — приложение стояло ночью, догоняем днём
SEND_LIMIT_MB = 50  # осторожный предел для файла от бота
SEND_TIMEOUT_SEC = 180
NAME = re.compile(r"^app-\d{8}-\d{6}\.sqlite\.gz$")
STATUS_FILE = "last_backup.json"

# Подставляются при запуске приложения: как бот отправляет файл владельцу и в каком цикле он живёт.
sender: Callable[[Path, str], Awaitable[None]] | None = None
loop: asyncio.AbstractEventLoop | None = None


class BackupError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Result:
    path: Path
    size_bytes: int
    sent: bool
    error: str | None = None


def _copies(settings: Settings) -> list[Path]:
    if not settings.backups_dir.is_dir():
        return []
    return sorted(p for p in settings.backups_dir.iterdir() if NAME.match(p.name))


def newest(settings: Settings) -> Path | None:
    copies = _copies(settings)
    return copies[-1] if copies else None


def is_due(settings: Settings, now: datetime | None = None) -> bool:
    """Пора ли делать копию: копий ещё нет; либо последней больше 20 часов и наступила ночь по
    Москве; либо последняя старше 30 часов (приложение стояло — догоняем днём)."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    last = newest(settings)
    if last is None:
        return True
    age = now - datetime.fromtimestamp(last.stat().st_mtime, UTC)
    if age < MIN_GAP:
        return False
    return now.astimezone(TEAM_TZ).hour >= NIGHT_HOUR or age >= CATCH_UP


_lock = threading.Lock()  # две копии в одну секунду не должны делить временные файлы


def snapshot(settings: Settings, now: datetime | None = None) -> Path:
    """Снимок базы через VACUUM INTO, проверка целостности, сжатие. Возвращает путь к .gz."""
    with _lock:
        return _snapshot(settings, now)


def _snapshot(settings: Settings, now: datetime | None) -> Path:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    raw = settings.backups_dir / f"app-{stamp}.sqlite"
    target = settings.backups_dir / f"app-{stamp}.sqlite.gz"
    part = target.with_suffix(".gz.part")
    try:
        source = sqlite3.connect(settings.db_path, timeout=60)
        try:
            source.execute("VACUUM INTO ?", (str(raw),))
        finally:
            source.close()
        check = sqlite3.connect(raw)
        try:
            verdict = check.execute("PRAGMA integrity_check").fetchone()
        finally:
            check.close()
        if not verdict or verdict[0] != "ok":
            raise BackupError(f"Копия базы повреждена: {verdict}")
        with raw.open("rb") as src, gzip.open(part, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        part.replace(target)
    except sqlite3.Error as exc:
        raise BackupError(f"Не удалось снять копию базы: {exc}") from exc
    finally:
        raw.unlink(missing_ok=True)
        part.unlink(missing_ok=True)
    return target


def prune(settings: Settings, keep: int = KEEP) -> int:
    """Оставляет `keep` последних копий. Возвращает, сколько удалено."""
    old = _copies(settings)[:-keep] if keep > 0 else _copies(settings)
    for path in old:
        path.unlink(missing_ok=True)
    return len(old)


def _caption(path: Path, size: int) -> str:
    when = datetime.now(TEAM_TZ).strftime("%d.%m.%Y %H:%M")
    return f"Копия базы The Brass Spyglass · {when} МСК · {size / 1_048_576:.1f} МБ · {path.name}"


def send(path: Path) -> str | None:
    """Отправляет копию владельцу. Возвращает текст ошибки или None, если всё ушло."""
    if sender is None or loop is None or loop.is_closed():
        return "Бот не подключён: копия осталась на диске"
    size = path.stat().st_size
    if size > SEND_LIMIT_MB * 1_048_576:
        return f"Копия {size / 1_048_576:.0f} МБ больше лимита отправки ({SEND_LIMIT_MB} МБ)"
    try:
        asyncio.run_coroutine_threadsafe(sender(path, _caption(path, size)), loop).result(
            SEND_TIMEOUT_SEC
        )
    except Exception as exc:  # бот мог быть заблокирован владельцем, сеть могла упасть
        return f"Не удалось отправить в Telegram: {exc or exc.__class__.__name__}"
    return None


def write_status(settings: Settings, result: Result) -> None:
    payload = {
        "at": datetime.now(UTC).isoformat(),
        "file": result.path.name,
        "size_bytes": result.size_bytes,
        "sent": result.sent,
        "error": result.error,
    }
    (settings.backups_dir / STATUS_FILE).write_text(json.dumps(payload), encoding="utf-8")


def read_status(settings: Settings) -> dict[str, object] | None:
    path = settings.backups_dir / STATUS_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run(settings: Settings, now: datetime | None = None) -> Result:
    """Снимок + удаление лишних + отправка владельцу. Ошибка отправки копию не отменяет."""
    path = snapshot(settings, now)
    removed = prune(settings)
    error = send(path)
    result = Result(path, path.stat().st_size, error is None, error)
    write_status(settings, result)
    if error:
        log.warning("бэкап %s: %s", path.name, error)
    log.info(
        "бэкап %s готов (%.1f МБ), удалено старых: %s", path.name, result.size_bytes / 1e6, removed
    )
    return result

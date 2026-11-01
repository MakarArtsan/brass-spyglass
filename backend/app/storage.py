"""Занятое место на диске /data и лимит проекта (ТЗ: дашборд показывает ГБ и предупреждает на 80%).

Считается по файлам на диске, а не по размерам в базе: превью, прокси, база и её WAL тоже занимают
место, и тарифный диск делят все. Обход каталогов недорог, но дашборд обновляется живьём, поэтому
результат кэшируется на несколько секунд.
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings

GIB = 1024**3
WARN_FRACTION = 0.8
CACHE_TTL_SEC = 15.0

_cache: dict[str, tuple[float, int]] = {}


def dir_size(path: Path) -> int:
    """Сумма размеров файлов каталога (без переходов по симлинкам); нет каталога — 0."""
    total = 0
    stack = [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue  # файл исчез между обходом и stat — не страшно
        except OSError:
            continue
    return total


def used_bytes(settings: Settings, *, fresh: bool = False) -> int:
    key = str(settings.data_dir)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and not fresh and now - cached[0] < CACHE_TTL_SEC:
        return cached[1]
    folders = (
        settings.files_dir,
        settings.cache_dir,
        settings.exports_dir,
        settings.backups_dir,
        settings.db_path.parent,
    )
    value = sum(dir_size(folder) for folder in folders)
    _cache[key] = (now, value)
    return value


def forget(settings: Settings) -> None:
    """Сбросить кэш (после загрузки или удаления файла считать заново)."""
    _cache.pop(str(settings.data_dir), None)


@dataclass(frozen=True, slots=True)
class Usage:
    used_bytes: int
    limit_bytes: int
    used_pct: float
    warn: bool  # заполнено на 80% и больше
    full: bool  # лимит исчерпан


def usage(settings: Settings, limit_gb: float, *, fresh: bool = False) -> Usage:
    used = used_bytes(settings, fresh=fresh)
    limit = int(limit_gb * GIB)
    fraction = used / limit if limit > 0 else 1.0
    return Usage(
        used_bytes=used,
        limit_bytes=limit,
        used_pct=round(100 * fraction, 1),
        warn=fraction >= WARN_FRACTION,
        full=fraction >= 1.0,
    )


class NoRoom(Exception):  # noqa: N818
    """Файл не помещается в лимит диска проекта. Текст показывается человеку."""


def ensure_room(settings: Settings, limit_gb: float, extra_bytes: int) -> None:
    """Отказывает, если после добавления `extra_bytes` диск переполнится.

    Диск делят файлы, превью, прокси и база, поэтому считаем занятое по факту, а не по размерам в
    таблице. База лежит на том же диске: заполненный диск остановил бы не только загрузки.
    """
    current = usage(settings, limit_gb, fresh=True)
    if current.used_bytes + max(0, extra_bytes) > current.limit_bytes:
        free = max(0, current.limit_bytes - current.used_bytes)
        raise NoRoom(
            f"На диске не хватает места: свободно {free / GIB:.1f} ГБ из "
            f"{current.limit_bytes / GIB:.1f} ГБ, а нужно {extra_bytes / GIB:.2f} ГБ. "
            "Удалите ненужные файлы или очистите корзину."
        )

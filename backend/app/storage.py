"""Занятое место: у проекта (его файлы) и на диске /data целиком (ТЗ: дашборд показывает ГБ и
предупреждает на 80%).

Считается по файлам на диске, а не по размерам в базе: превью, прокси и оригиналы до сжатия тоже
занимают место. Место проекта — это каталоги его файлов (`files/<id>`, `originals/<id>`); база,
бэкапы, кэш и экспорты общие и в долю проекта не входят, но входят в общий счёт диска: заполненный
диск остановил бы не только загрузки. Обход каталогов недорог, но дашборд обновляется живьём,
поэтому результат кэшируется на несколько секунд.
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import Settings

GIB = 1024**3
WARN_FRACTION = 0.8
CACHE_TTL_SEC = 15.0
PROJECT_CACHE_TTL_SEC = 3.0  # короче: сразу после загрузки человек ждёт увидеть новое число

_cache: dict[str, tuple[float, int]] = {}
_project_cache: dict[tuple[str, int], tuple[float, int]] = {}


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
        settings.originals_dir,
        settings.cache_dir,
        settings.exports_dir,
        settings.backups_dir,
        settings.db_path.parent,
    )
    value = sum(dir_size(folder) for folder in folders)
    _cache[key] = (now, value)
    return value


def project_used_bytes(
    settings: Settings, db: Session, project_id: int, *, fresh: bool = False
) -> int:
    """Место, которое занимают файлы проекта: оригиналы, превью, прокси и оригиналы до сжатия.
    Удалённые в корзину файлы лежат на диске, пока их не уберёт уборка, поэтому тоже считаются."""
    key = (str(settings.data_dir), project_id)
    now = time.monotonic()
    cached = _project_cache.get(key)
    if cached is not None and not fresh and now - cached[0] < PROJECT_CACHE_TTL_SEC:
        return cached[1]
    ids = list(db.scalars(select(models.File.id).where(models.File.project_id == project_id)))
    value = 0
    for file_id in ids:
        name = f"{file_id:06d}"
        value += dir_size(settings.files_dir / name) + dir_size(settings.originals_dir / name)
    _project_cache[key] = (now, value)
    return value


def forget_project(project_id: int) -> None:
    """У проекта появился или исчез файл: место считать заново."""
    for key in [k for k in _project_cache if k[1] == project_id]:
        _project_cache.pop(key, None)


def forget(settings: Settings) -> None:
    """Сбросить кэш (после загрузки или удаления файла считать заново)."""
    key = str(settings.data_dir)
    _cache.pop(key, None)
    for cached in [k for k in _project_cache if k[0] == key]:
        _project_cache.pop(cached, None)


@dataclass(frozen=True, slots=True)
class Usage:
    used_bytes: int
    limit_bytes: int
    used_pct: float
    warn: bool  # заполнено на 80% и больше
    full: bool  # лимит исчерпан


def usage(limit_gb: float, used: int) -> Usage:
    """Занятое `used` против лимита проекта `limit_gb`."""
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
    """Файл не помещается в лимит проекта или на диск. Текст показывается человеку."""


def ensure_room(
    settings: Settings, db: Session, project_id: int, limit_gb: float, extra_bytes: int
) -> None:
    """Отказывает, если после `extra_bytes` переполнится лимит проекта или диск целиком."""
    extra = max(0, extra_bytes)
    used = project_used_bytes(settings, db, project_id, fresh=True)
    limit = int(limit_gb * GIB)
    if used + extra > limit:
        free = max(0, limit - used)
        raise NoRoom(
            f"На диске не хватает места: свободно {free / GIB:.1f} ГБ из "
            f"{limit / GIB:.1f} ГБ, а нужно {extra / GIB:.2f} ГБ. "
            "Удалите ненужные файлы или очистите корзину."
        )
    ensure_disk(settings, extra)


def ensure_disk(settings: Settings, extra_bytes: int) -> None:
    """Диск тарифа делят все проекты: что его переполнит, не принимаем (база лежит там же)."""
    disk = int(settings.disk_total_gb * GIB)
    if used_bytes(settings, fresh=True) + max(0, extra_bytes) > disk:
        raise NoRoom(
            "На диске сайта не хватает места: его делят все проекты. "
            "Освободите место или напишите владельцу сайта."
        )

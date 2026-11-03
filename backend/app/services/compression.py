"""Сжатие картинок: подмена файла сжатым, оригинал на 7 дней, «Вернуть оригинал», уборка.

Само сжатие — `app/imagecompress.py` (чистые функции над файлами). Здесь всё, что трогает базу и
постоянный диск. Порядок такой, чтобы при сбое посередине файл оставался целым:
  1. оригинал получает вторую жёсткую ссылку в `/data/originals` (или копируется, если ссылки не
     поддерживаются);
  2. сжатый файл атомарно (`os.replace`) встаёт на место оригинала: файл доступен всё время;
  3. запись в базе обновляется, и только после коммита старый файл (если у сжатого другое
     расширение, например HEIC → JPG) удаляется.
`sha256` остаётся от оригинала: дубли ищутся по нему (ТЗ). В журнал подмена не пишется — это не
действие человека; «Вернуть оригинал» — действие, и оно записывается.
"""

import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db as database
from app import imagecompress, models, permissions, storage
from app.config import Settings
from app.constants import CompressState, EntityType, FileKind, JobType
from app.db import utcnow
from app.permissions import Actor
from app.services import core, files, jobs
from app.services.core import ValidationError, log_activity

log = logging.getLogger(__name__)

ORIGINAL_GONE = "Оригинал уже удалён: он хранится только {days} дн. после сжатия"


def _ext(path: str) -> str:
    return files.extension(path)


def _rename(name: str | None, ext: str) -> str | None:
    """Имя файла с другим расширением: `photo.heic` → `photo.jpg`."""
    if not name:
        return name
    base = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", name)
    return f"{base}.{ext}"


def eligible(file: models.File, settings: Settings) -> bool:
    """Нужно ли ставить файл на сжатие."""
    return bool(
        settings.compress_images
        and file.kind == FileKind.IMAGE.value
        and not file.no_compress
        and file.compress_state is None
        and file.deleted_at is None
        and file.path
        and imagecompress.can_compress(_ext(file.path))
    )


def queue_if_eligible(db: Session, file: models.File, settings: Settings) -> bool:
    if not eligible(file, settings):
        return False
    jobs.enqueue(db, JobType.COMPRESS, {"file_id": file.id})
    return True


@dataclass(frozen=True, slots=True)
class Replaced:
    """Что осталось сделать после коммита: убрать прежний файл, если у сжатого другое имя."""

    leftover: Path | None = None


def _keep_original(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    try:
        os.link(source, target)
    except OSError:  # файловая система без жёстких ссылок
        shutil.copy2(source, target)


def apply(
    db: Session,
    file_id: int,
    result: imagecompress.Result,
    expected_path: str,
    settings: Settings,
) -> Replaced:
    """Записывает итог сжатия. `expected_path` — путь, с которого сжимали: если файл за это время
    удалили или заменили, результат отбрасывается."""
    file = db.get(models.File, file_id)
    if file is None or file.deleted_at is not None or file.path != expected_path:
        if result.output is not None:
            result.output.unlink(missing_ok=True)
        return Replaced()
    if result.state == CompressState.SMALL_GAIN.value:
        file.compress_state = CompressState.SMALL_GAIN.value
        return Replaced()
    if result.state != CompressState.DONE.value or result.output is None or result.ext is None:
        return Replaced()  # «не подлежит сжатию»: состояние не ставим

    old_rel = file.path
    old_abs = settings.files_dir / old_rel
    before = old_abs.stat().st_size
    original_rel = f"{file.id:06d}/original.{_ext(old_rel)}"
    _keep_original(old_abs, settings.originals_dir / original_rel)

    new_rel = f"{file.id:06d}/original.{result.ext}"
    new_abs = settings.files_dir / new_rel
    os.replace(result.output, new_abs)  # атомарно: файл не пропадает ни на миг

    file.path = new_rel
    file.size_bytes = new_abs.stat().st_size
    file.mime = result.mime
    if result.ext != _ext(old_rel):
        file.original_name = _rename(file.original_name, result.ext)
    file.original_size_bytes = before
    file.original_path = original_rel
    file.compressed_at = utcnow()
    file.compress_state = CompressState.DONE.value
    db.flush()
    storage.forget(settings)
    return Replaced(leftover=old_abs if new_rel != old_rel else None)


def mark_failed(db: Session, file_id: int) -> None:
    file = db.get(models.File, file_id)
    if file is not None:
        file.compress_state = CompressState.FAILED.value


def original_until(file: models.File, settings: Settings) -> datetime | None:
    """До какого момента лежит оригинал (None — его нет)."""
    if not file.original_path or file.compressed_at is None:
        return None
    return file.compressed_at + timedelta(days=settings.originals_keep_days)


def can_restore(file: models.File, settings: Settings) -> bool:
    """Оригинал есть и в базе, и на диске: только тогда карточка предлагает его вернуть."""
    return bool(file.original_path) and (settings.originals_dir / file.original_path).is_file()


def restore_original(db: Session, actor: Actor, file_id: int, settings: Settings) -> models.File:
    """«Вернуть оригинал»: сжатый файл заменяется тем, что загрузили; второй раз его не жмём.
    Может автор файла, режиссёр и владелец (как удаление)."""
    file = core.get(db, EntityType.FILE, file_id)
    assert isinstance(file, models.File)
    permissions.require(permissions.can_delete(actor, file.uploaded_by))
    gone = ORIGINAL_GONE.format(days=settings.originals_keep_days)
    if not file.original_path or file.path is None:
        raise ValidationError(gone)
    kept = settings.originals_dir / file.original_path
    if not kept.is_file():
        raise ValidationError(gone)  # на диске его уже нет (кнопка в таком случае не показывается)

    old_rel = file.path
    ext = _ext(file.original_path)
    new_rel = f"{file.id:06d}/original.{ext}"
    new_abs = settings.files_dir / new_rel
    os.replace(kept, new_abs)  # оригинал возвращается на место, файл доступен всё время
    if new_rel != old_rel:
        (settings.files_dir / old_rel).unlink(missing_ok=True)

    compressed_size = file.size_bytes
    file.path = new_rel
    file.size_bytes = file.original_size_bytes or new_abs.stat().st_size
    file.mime = files.MIME_BY_EXT.get(ext, file.mime)
    if ext != _ext(old_rel):
        file.original_name = _rename(file.original_name, ext)
    file.original_size_bytes = None
    file.original_path = None
    file.compressed_at = None
    file.compress_state = None
    file.no_compress = True  # человек выбрал оригинал: второй раз не жмём
    db.flush()
    storage.forget(settings)
    log_activity(
        db,
        actor.id,
        "restore_original",
        EntityType.FILE,
        file.id,
        {"file": file.original_name, "from_bytes": compressed_size, "to_bytes": file.size_bytes},
        file.project_id,
    )
    return file


def cleanup_expired(settings: Settings, now: datetime | None = None) -> int:
    """Удаляет оригиналы старше срока хранения (ТЗ: 7 дней). Возвращает число удалённых."""
    now = now or utcnow()
    cutoff = now - timedelta(days=settings.originals_keep_days)
    removed = 0
    with database.session_factory()() as db:
        rows = db.scalars(
            select(models.File).where(
                models.File.original_path.is_not(None), models.File.compressed_at <= cutoff
            )
        )
        for file in rows:
            (settings.originals_dir / str(file.original_path)).unlink(missing_ok=True)
            file.original_path = None  # размер оригинала остаётся: экономия считается и дальше
            removed += 1
        db.commit()
    if removed:
        storage.forget(settings)
    return removed

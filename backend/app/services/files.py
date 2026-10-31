"""Файлы: запись о загруженном файле, дубли по sha256, результаты обработки."""

import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import linkpreview, models, permissions
from app.constants import EntityType, FileKind, FileSource, JobType, Purpose
from app.permissions import Actor
from app.services import core, jobs

# Что принимаем (ТЗ, «Загрузка с устройства и ссылки»).
KIND_BY_EXT: dict[str, FileKind] = {
    **dict.fromkeys(("mp4", "mov", "webm", "m4v"), FileKind.VIDEO),
    **dict.fromkeys(("png", "jpg", "jpeg", "webp", "heic", "heif", "gif"), FileKind.IMAGE),
    **dict.fromkeys(
        ("wav", "mp3", "aiff", "aif", "flac", "m4a", "ogg", "oga", "opus"), FileKind.AUDIO
    ),
    **dict.fromkeys(("pdf", "docx", "txt", "md", "xlsx"), FileKind.DOCUMENT),
}


def extension(name: str) -> str:
    match = re.search(r"\.([A-Za-z0-9]{1,8})$", name.strip())
    return match.group(1).lower() if match else ""


def kind_for(name: str) -> FileKind | None:
    return KIND_BY_EXT.get(extension(name))


def find_duplicates(db: Session, sha256: str, project_id: int) -> list[models.File]:
    return list(
        db.scalars(
            select(models.File)
            .where(
                models.File.project_id == project_id,
                models.File.sha256 == sha256,
                models.File.deleted_at.is_(None),
            )
            .order_by(models.File.id)
        )
    )


def store_upload(
    db: Session,
    actor: Actor,
    *,
    project_id: int,
    tmp_path: Path,
    original_name: str,
    mime: str | None,
    size_bytes: int,
    sha256: str,
    files_dir: Path,
) -> models.File:
    """Создаёт запись файла (автор и время — от сервера, из сессии), переносит загруженное на
    постоянный диск и ставит задачу на превью. Оригинал дальше не меняется."""
    kind = kind_for(original_name)
    if kind is None:
        raise core.ValidationError(f"Формат «{extension(original_name) or '?'}» не поддерживается")
    file = core.create(
        db,
        actor,
        EntityType.FILE,
        {
            "kind": kind.value,
            "source": FileSource.UPLOAD.value,
            "original_name": original_name,
            "mime": mime,
            "size_bytes": size_bytes,
            "sha256": sha256,
        },
        project_id=project_id,
    )
    ext = extension(original_name)
    relative = f"{file.id:06d}/original" + (f".{ext}" if ext else "")
    destination = files_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_path, destination)
    file.path = relative
    db.flush()

    if kind in (FileKind.VIDEO, FileKind.IMAGE) or ext == "pdf":
        jobs.enqueue(db, JobType.PREVIEW, {"file_id": file.id}, actor.id)
    elif kind is FileKind.AUDIO:
        jobs.enqueue(db, JobType.WAVEFORM, {"file_id": file.id}, actor.id)
    return file


MEDIA_FIELDS = {
    "link_title",
    "duration_sec",
    "width",
    "height",
    "fps",
    "thumb_path",
    "proxy_path",
    "waveform_json",
}


def apply_media_info(db: Session, file_id: int, **values: Any) -> None:
    """Результаты обработки (длительность, размеры, пути к превью). Не пишется в журнал:
    это не действие человека."""
    unknown = set(values) - MEDIA_FIELDS
    if unknown:
        raise core.ValidationError(f"Неизвестные поля: {sorted(unknown)}")
    file = db.get(models.File, file_id)
    if file is None:
        return
    for key, value in values.items():
        setattr(file, key, value)


def queue_proxy(db: Session, file_id: int) -> None:
    jobs.enqueue(db, JobType.PROXY, {"file_id": file_id})


def add_link(
    db: Session,
    actor: Actor,
    *,
    project_id: int,
    url: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    purpose: str = Purpose.REFERENCE.value,
) -> tuple[models.File, bool]:
    """Ссылка как файл (источник «ссылка»). Заголовок и картинку Open Graph подтянет фоновая задача.

    Та же ссылка второй раз не создаёт дубль: берётся существующая запись и привязывается к
    ещё одной карточке. Возвращает (файл, создан ли заново).
    """
    from app.services import links  # отложенный импорт: links сам использует этот модуль

    permissions.require(permissions.can_upload(actor))
    try:
        normalized = linkpreview.parse_url(url).geturl()
    except linkpreview.LinkError as exc:
        raise core.ValidationError(str(exc)) from exc
    file = db.scalar(
        select(models.File).where(
            models.File.project_id == project_id,
            models.File.kind == FileKind.LINK.value,
            models.File.url == normalized,
            models.File.deleted_at.is_(None),
        )
    )
    created = file is None
    if file is None:
        file = core.create(
            db,
            actor,
            EntityType.FILE,
            {"kind": FileKind.LINK.value, "source": FileSource.LINK.value, "url": normalized},
            project_id=project_id,
        )
        jobs.enqueue(db, JobType.PREVIEW, {"file_id": file.id}, actor.id)
    if entity_type is not None and entity_id is not None:
        links.attach(db, actor, file.id, entity_type, entity_id, purpose)
    return file, created

"""Версии файлов: v1, v2, v3… (ТЗ, «Авторство и версии»).

«Новая версия» ничего не затирает: прошлые версии лежат как были, у каждой свой автор и дата.
Версии одного файла — группа (`version_group_id` = id первой версии); текущая — одна, `is_current`.
Карточки показывают только текущие версии; все привязки старой версии копируются на новую, поэтому
откат — это просто смена текущей, привязки уже на месте. Откат пишется в журнал.
"""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, permissions
from app.constants import EntityType, FileKind, NotificationKind
from app.permissions import Actor
from app.services import core, files, links, notifications
from app.services.core import ConflictError, ValidationError, log_activity


def group_of(file: models.File) -> int:
    return file.version_group_id or file.id


def members(db: Session, file: models.File) -> list[models.File]:
    """Все версии файла (включая удалённые), от первой к последней."""
    if file.version_group_id is None:
        return [file]
    rows = db.scalars(
        select(models.File)
        .where(models.File.version_group_id == file.version_group_id)
        .order_by(models.File.version_no, models.File.id)
    )
    return list(rows)


def current_of(db: Session, file: models.File) -> models.File:
    """Текущая версия того же файла (или он сам, если версий нет)."""
    if file.version_group_id is None or file.is_current:
        return file
    current = db.scalar(
        select(models.File).where(
            models.File.version_group_id == file.version_group_id,
            models.File.is_current.is_(True),
        )
    )
    return current or file


def current_many(db: Session, ids: set[int]) -> dict[int, models.File]:
    """Для каждого id — текущая версия этого файла (удалённые не возвращаются)."""
    if not ids:
        return {}
    found = {f.id: f for f in db.scalars(select(models.File).where(models.File.id.in_(ids)))}
    groups = {f.version_group_id for f in found.values() if f.version_group_id and not f.is_current}
    current_by_group: dict[int, models.File] = {}
    if groups:
        for f in db.scalars(
            select(models.File).where(
                models.File.version_group_id.in_(groups), models.File.is_current.is_(True)
            )
        ):
            current_by_group[f.version_group_id] = f  # type: ignore[index]
    out: dict[int, models.File] = {}
    for file_id, f in found.items():
        target = current_by_group.get(f.version_group_id) if f.version_group_id else None  # type: ignore[arg-type]
        target = target or f
        if target.deleted_at is None:
            out[file_id] = target
    return out


def counts(db: Session, files_: list[models.File]) -> dict[int, int]:
    """Сколько живых версий у группы каждого файла (для значка «v3 из 3»)."""
    groups = {f.version_group_id for f in files_ if f.version_group_id}
    if not groups:
        return {}
    rows = db.execute(
        select(models.File.version_group_id, func.count())
        .where(models.File.version_group_id.in_(groups), models.File.deleted_at.is_(None))
        .group_by(models.File.version_group_id)
    )
    return dict(rows.all())  # type: ignore[arg-type]


def _targets(db: Session, file_id: int) -> list[models.Attachment]:
    return list(db.scalars(select(models.Attachment).where(models.Attachment.file_id == file_id)))


def new_version(
    db: Session,
    actor: Actor,
    *,
    base_file_id: int,
    project_id: int,
    tmp_path: Path,
    original_name: str,
    mime: str | None,
    size_bytes: int,
    sha256: str,
    files_dir: Path,
) -> models.File:
    """Сохраняет загруженное как следующую версию файла. Автор и время — от сервера."""
    permissions.require(permissions.can_upload(actor), "Гость не загружает файлы")
    base = core.get(db, EntityType.FILE, base_file_id)
    assert isinstance(base, models.File)
    if base.kind == FileKind.LINK.value:
        raise ValidationError("У ссылки версий нет")
    current = current_of(db, base)
    kind = files.kind_for(original_name)
    if kind is None or kind.value != current.kind:
        raise ValidationError("Новая версия должна быть файлом того же типа")
    group = members(db, current)
    if any(v.sha256 == sha256 and v.deleted_at is None for v in group):
        raise ConflictError("Такая версия уже есть: чтобы вернуться к ней, используйте откат")

    group_id = group_of(current)
    if current.version_group_id is None:
        current.version_group_id = group_id  # первый файл становится v1 своей группы
    number = max(v.version_no for v in group) + 1
    current.is_current = False
    db.flush()

    file = files.store_upload(
        db,
        actor,
        project_id=project_id,
        tmp_path=tmp_path,
        original_name=original_name,
        mime=mime,
        size_bytes=size_bytes,
        sha256=sha256,
        files_dir=files_dir,
        extra={"version_group_id": group_id, "version_no": number, "is_current": True},
    )
    for row in _targets(db, current.id):
        db.add(
            models.Attachment(
                file_id=file.id,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                purpose=row.purpose,
                created_by=actor.id,
            )
        )
    db.flush()
    _announce(db, actor, file, "version", {"version_no": number, "previous": current.id})
    return file


def rollback(db: Session, actor: Actor, file_id: int) -> models.File:
    """Делает выбранную версию текущей. Прошлая текущая остаётся в истории (откат обратим)."""
    permissions.require(permissions.can_upload(actor), "Гость не меняет версии")
    file = core.get(db, EntityType.FILE, file_id)
    assert isinstance(file, models.File)
    if file.version_group_id is None:
        raise ValidationError("У файла одна версия")
    if file.is_current:
        raise ValidationError("Эта версия уже текущая")
    current = current_of(db, file)
    current.is_current = False
    file.is_current = True
    db.flush()
    _announce(
        db,
        actor,
        file,
        "rollback",
        {"version_no": file.version_no, "from_version_no": current.version_no},
    )
    return file


def _announce(
    db: Session, actor: Actor, file: models.File, action: str, diff: dict[str, int]
) -> None:
    """Журнал: на самом файле и на каждой карточке, где он лежит (оттуда идут уведомления)."""
    payload = {**diff, "file_id": file.id, "file": file.original_name}
    log_activity(db, actor.id, action, EntityType.FILE, file.id, payload, file.project_id)
    for row in _targets(db, file.id):
        links.sync_takes(db, row.entity_type, row.entity_id)
        log_activity(db, actor.id, action, row.entity_type, row.entity_id, payload, file.project_id)
        if action == "version":  # откат — не новость для команды, новая версия — да
            notifications.notify(
                db,
                actor.id,
                NotificationKind.VERSION,
                row.entity_type,
                row.entity_id,
                f"{file.original_name} · v{file.version_no}",
            )

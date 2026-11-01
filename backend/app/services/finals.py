"""Финальный файл сцены и шота (`scene.final_file_id`, `shot.final_file_id`).

Хранится файл, который выбрали, а показывается и уходит в экспорт его *текущая* версия:
загрузили v3 — в аниматике и пакете уже v3. Выбрать можно только видео с этой же карточки.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, permissions
from app.constants import EntityType, FileKind
from app.permissions import Actor
from app.services import core, versions
from app.services.core import ValidationError, log_activity

LEVELS = (EntityType.SCENE, EntityType.SHOT)


def set_final(
    db: Session, actor: Actor, entity_type: str, entity_id: int, file_id: int | None
) -> models.Base:
    if entity_type not in LEVELS:
        raise ValidationError("Финальный файл есть только у сцены и шота")
    obj = core.get(db, entity_type, entity_id)
    spec = core.ENTITIES[entity_type]
    permissions.require(
        permissions.can_edit(actor, entity_type, core._owner_id(spec, obj), {"final_file_id"})
    )
    name = None
    if file_id is not None:
        chosen = core.get(db, EntityType.FILE, file_id)
        assert isinstance(chosen, models.File)
        if chosen.kind != FileKind.VIDEO.value:
            raise ValidationError("Финальным может быть только видеофайл")
        group = {f.id for f in versions.members(db, chosen)}
        attached = db.scalar(
            select(models.Attachment.id)
            .where(
                models.Attachment.entity_type == entity_type,
                models.Attachment.entity_id == entity_id,
                models.Attachment.file_id.in_(group),
            )
            .limit(1)
        )
        if attached is None:
            raise ValidationError("Сначала прикрепите файл к этой карточке")
        file_id = versions.group_of(
            chosen
        )  # храним начало группы: следующие версии подхватятся сами
        name = chosen.original_name
    old = obj.final_file_id  # type: ignore[attr-defined]
    if old == file_id:
        return obj
    obj.final_file_id = file_id  # type: ignore[attr-defined]
    if hasattr(obj, "updated_by"):
        obj.updated_by = actor.id
    db.flush()
    log_activity(
        db,
        actor.id,
        "update",
        entity_type,
        entity_id,
        {"final_file_id": [old, file_id], "final_file": name},
        getattr(obj, "project_id", None),
    )
    return obj


def resolve(db: Session, objs: list[models.Scene] | list[models.Shot]) -> dict[int, models.File]:
    """Текущие финальные файлы для списка сцен или шотов: {id сущности: файл}."""
    wanted = {o.final_file_id for o in objs if o.final_file_id}  # type: ignore[union-attr]
    current = versions.current_many(db, {i for i in wanted if i})
    return {
        o.id: current[o.final_file_id]  # type: ignore[union-attr,index]
        for o in objs
        if o.final_file_id in current  # type: ignore[union-attr]
    }

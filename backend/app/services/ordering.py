"""Порядок сцен и шотов — перетаскиванием; именно он идёт в экспорт (ТЗ)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, permissions
from app.constants import EntityType
from app.permissions import Actor
from app.services.core import NotFoundError, ValidationError, log_activity


def reorder(
    db: Session,
    actor: Actor,
    entity_type: str,
    ids: list[int],
    *,
    project_id: int,
    scene_id: int | None = None,
) -> int:
    """Выставляет `order` 1…N по списку id. Список должен содержать ровно все (неудалённые)
    сцены проекта либо все шоты сцены. Возвращает число реально сдвинутых записей.

    Это правка поля `order` каждой карточки, поэтому права проверяются как для редактирования:
    роль «Команда» может переставлять только свои карточки."""
    if entity_type == EntityType.SCENE:
        stmt = select(models.Scene).where(
            models.Scene.project_id == project_id, models.Scene.deleted_at.is_(None)
        )
    elif entity_type == EntityType.SHOT:
        if scene_id is None:
            raise ValidationError("Для шотов нужна сцена (scene_id)")
        stmt = select(models.Shot).where(
            models.Shot.scene_id == scene_id, models.Shot.deleted_at.is_(None)
        )
    else:
        raise ValidationError(f"{entity_type}: порядок менять нельзя")

    rows = {row.id: row for row in db.scalars(stmt)}
    if len(set(ids)) != len(ids):
        raise ValidationError("В списке есть повторы")
    if set(ids) != set(rows):
        missing = set(rows) - set(ids)
        unknown = set(ids) - set(rows)
        if unknown:
            raise NotFoundError(f"Нет таких записей: {sorted(unknown)}")
        raise ValidationError(f"В списке не хватает записей: {sorted(missing)}")

    moved = [(rows[i], pos) for pos, i in enumerate(ids, start=1) if rows[i].order != pos]
    for row, _ in moved:
        permissions.require(
            permissions.can_edit(actor, entity_type, row.created_by, {"order"}),
            "Переставлять чужие карточки может режиссёр или владелец",
        )
    if not moved:
        return 0
    for row, pos in moved:
        row.order = pos
        row.updated_by = actor.id
    db.flush()
    log_activity(
        db,
        actor.id,
        "reorder",
        entity_type,
        scene_id,
        {"ids": ids},
        project_id,
    )
    return len(moved)

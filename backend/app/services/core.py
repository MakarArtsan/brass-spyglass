"""Сервисный слой: все изменения данных идут через него, и каждое пишет строку в `activity`.

Функции работают в транзакции вызывающего: коммитит FastAPI-зависимость `get_db`
(или тест/фоновая задача). Права проверяются здесь, а не в роутерах, поэтому
прямой запрос к API не обходит их.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, permissions
from app.constants import EntityType
from app.db import utcnow
from app.permissions import Actor, PermissionDenied

__all__ = [
    "bulk_status",
    "Actor",
    "ConflictError",
    "NotFoundError",
    "PermissionDenied",
    "ServiceError",
    "ValidationError",
    "create",
    "delete",
    "get",
    "log_activity",
    "restore",
    "update",
]


class ServiceError(Exception):
    """Базовая ошибка сервисного слоя: API превращает её в 4xx."""


class NotFoundError(ServiceError):
    pass


class ValidationError(ServiceError):
    pass


class ConflictError(ServiceError):
    pass


# Поля, которые клиент может менять у любой рабочей сущности.
WORK_FIELDS = frozenset({"status", "priority", "assignee_id", "due_date", "comment"})


@dataclass(frozen=True, slots=True)
class EntitySpec:
    model: type[models.Base]
    fields: frozenset[str]  # меняются через update (и задаются при create)
    create_only: frozenset[str] = frozenset()  # задаются только при create
    owner_field: str | None = "created_by"  # кто автор: created_by / uploaded_by

    @property
    def has_project(self) -> bool:
        return hasattr(self.model, "project_id")

    @property
    def soft_delete(self) -> bool:
        return hasattr(self.model, "deleted_at")


ENTITIES: dict[str, EntitySpec] = {
    EntityType.SCENE: EntitySpec(
        models.Scene,
        WORK_FIELDS
        | {
            "number",
            "order",
            "title",
            "location",
            "time_of_day",
            "planned_sec",
            "drum_level",
            "meaning",
            "cut_notes",
            "characters",
            "key_assets",
            "lines_en",
            "side",
            "final_file_id",
        },
    ),
    EntityType.SHOT: EntitySpec(
        models.Shot,
        WORK_FIELDS
        | {
            "scene_id",
            "code",
            "order",
            "description",
            "size",
            "camera",
            "sound_note",
            "duration_sec",
            "tool",
            "stage",
            "takes_count",
            "side",
            "final_file_id",
        },
    ),
    EntityType.ASSET: EntitySpec(
        models.Asset,
        WORK_FIELDS | {"code", "type", "name", "description", "side"},
    ),
    EntityType.ASSET_STATE: EntitySpec(
        models.AssetState,
        frozenset({"name", "order", "description"}),
        create_only=frozenset({"asset_id"}),
        owner_field=None,
    ),
    EntityType.SETUP_PAYOFF: EntitySpec(
        models.SetupPayoff,
        WORK_FIELDS
        | {"number", "motif", "setup_shot_ids", "payoff_shot_ids", "reader_takeaway", "risk"},
    ),
    EntityType.SOUND_CUE: EntitySpec(
        models.SoundCue,
        WORK_FIELDS
        | {
            "code",
            "type",
            "who",
            "text_en",
            "text_ru",
            "rights",
            "start_offset_sec",
            "scene_id",
            "shot_id",
            "file_id",
        },
    ),
    EntityType.TASK: EntitySpec(
        models.Task,
        WORK_FIELDS | {"code", "block", "title"},
        create_only=frozenset({"entity_type", "entity_id"}),
    ),
    EntityType.COMMENT: EntitySpec(
        models.Comment,
        frozenset({"body", "mentions"}),
        create_only=frozenset({"entity_type", "entity_id", "file_id", "at_time_sec"}),
    ),
    EntityType.FILE: EntitySpec(
        models.File,
        frozenset({"original_name", "ai_tool", "ai_prompt", "ai_seed"}),
        # Метаданные файла проставляет серверный код загрузки/импорта, не клиент.
        create_only=frozenset(
            {
                "kind",
                "source",
                "path",
                "mime",
                "size_bytes",
                "sha256",
                "duration_sec",
                "width",
                "height",
                "fps",
                "thumb_path",
                "proxy_path",
                "url",
                "link_title",
                "version_group_id",
                "version_no",
                "is_current",
                "tg_chat_id",
                "tg_topic_id",
                "tg_message_id",
                "tg_author",
            }
        ),
        owner_field="uploaded_by",
    ),
    EntityType.USER: EntitySpec(models.User, frozenset({"role"}), owner_field=None),
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def log_activity(
    db: Session,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    diff: dict[str, Any] | None = None,
    project_id: int | None = None,
) -> models.Activity:
    row = models.Activity(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        diff=diff,
    )
    db.add(row)
    return row


def _spec_for(entity_type: str) -> EntitySpec:
    try:
        return ENTITIES[entity_type]
    except KeyError:
        raise ValidationError(f"Неизвестная сущность: {entity_type}") from None


def _owner_id(spec: EntitySpec, obj: models.Base) -> int | None:
    return getattr(obj, spec.owner_field) if spec.owner_field else None


def _check_fields(allowed: frozenset[str], data: dict[str, Any]) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValidationError(f"Поля нельзя менять: {', '.join(sorted(unknown))}")


def _explain(message: str) -> str:
    if "UNIQUE" in message:
        return "Такая запись уже есть: код или номер заняты"
    if "CHECK" in message:
        return "Недопустимое значение поля"
    if "FOREIGN KEY" in message:
        return "Ссылка на несуществующую запись"
    if "NOT NULL" in message:
        return "Не заполнено обязательное поле"
    return f"Данные нарушают ограничения: {message}"


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError(_explain(str(exc.orig))) from exc


def get(
    db: Session, entity_type: str, entity_id: int, *, include_deleted: bool = False
) -> models.Base:
    spec = _spec_for(entity_type)
    obj = db.get(spec.model, entity_id)
    if obj is None or (spec.soft_delete and obj.deleted_at is not None and not include_deleted):  # type: ignore[attr-defined]
        raise NotFoundError(f"{entity_type} #{entity_id} не найден")
    return obj


def create(
    db: Session,
    actor: Actor,
    entity_type: str,
    data: dict[str, Any],
    *,
    project_id: int | None = None,
) -> Any:
    spec = _spec_for(entity_type)
    permissions.require(permissions.can_create(actor, entity_type))
    if entity_type == EntityType.FILE:
        permissions.require(permissions.can_upload(actor))
    _check_fields(spec.fields | spec.create_only, data)

    obj = spec.model(**data)
    if spec.has_project:
        if project_id is None:
            raise ValidationError("Не указан проект")
        obj.project_id = project_id  # type: ignore[attr-defined]
    # Автора ставит сервер из сессии, подменить его нельзя.
    if spec.owner_field:
        setattr(obj, spec.owner_field, actor.id)
    if hasattr(obj, "updated_by"):
        obj.updated_by = actor.id
    db.add(obj)
    _flush(db)
    log_activity(
        db,
        actor.id,
        "create",
        entity_type,
        obj.id,  # type: ignore[attr-defined]
        {k: _jsonable(v) for k, v in data.items()},
        project_id,
    )
    return obj


def update(
    db: Session, actor: Actor, entity_type: str, entity_id: int, data: dict[str, Any]
) -> Any:
    spec = _spec_for(entity_type)
    _check_fields(spec.fields, data)
    obj = get(db, entity_type, entity_id)
    permissions.require(
        permissions.can_edit(actor, entity_type, _owner_id(spec, obj), set(data)),
    )

    diff: dict[str, Any] = {}
    for field, new in data.items():
        old = getattr(obj, field)
        if old != new:
            diff[field] = [_jsonable(old), _jsonable(new)]
            setattr(obj, field, new)
    if not diff:
        return obj
    if hasattr(obj, "updated_by"):
        obj.updated_by = actor.id
    _flush(db)
    action = "status" if set(diff) == {"status"} else "update"
    log_activity(
        db,
        actor.id,
        action,
        entity_type,
        entity_id,
        diff,
        getattr(obj, "project_id", None),
    )
    return obj


def delete(db: Session, actor: Actor, entity_type: str, entity_id: int) -> None:
    """Мягкое удаление: сущность уходит в корзину на 30 дней."""
    spec = _spec_for(entity_type)
    if not spec.soft_delete:
        raise ValidationError(f"{entity_type} нельзя удалить")
    obj = get(db, entity_type, entity_id)
    permissions.require(permissions.can_delete(actor, _owner_id(spec, obj)))
    obj.deleted_at = utcnow()  # type: ignore[attr-defined]
    _flush(db)
    log_activity(
        db, actor.id, "delete", entity_type, entity_id, None, getattr(obj, "project_id", None)
    )


def restore(db: Session, actor: Actor, entity_type: str, entity_id: int) -> Any:
    spec = _spec_for(entity_type)
    permissions.require(permissions.can_restore(actor))
    obj = get(db, entity_type, entity_id, include_deleted=True)
    if not spec.soft_delete or obj.deleted_at is None:  # type: ignore[attr-defined]
        raise ValidationError("Сущность не в корзине")
    obj.deleted_at = None  # type: ignore[attr-defined]
    _flush(db)
    log_activity(
        db, actor.id, "restore", entity_type, entity_id, None, getattr(obj, "project_id", None)
    )
    return obj


def bulk_status(
    db: Session, actor: Actor, entity_type: str, ids: list[int], status: str
) -> list[Any]:
    """Групповая смена статуса (шот-лист). Каждая карточка проходит обычное обновление:
    права проверяются по каждой, в журнал пишется строка на каждую. Всё или ничего."""
    if not ids:
        raise ValidationError("Не выбрано ни одной записи")
    return [update(db, actor, entity_type, entity_id, {"status": status}) for entity_id in ids]

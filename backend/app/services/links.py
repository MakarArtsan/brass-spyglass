"""Связи: ассеты в кадре шота (континьюити) и вложения файлов к карточкам."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, permissions
from app.constants import EntityType, Purpose
from app.permissions import Actor
from app.services import core
from app.services.core import ConflictError, NotFoundError, ValidationError, log_activity


def set_shot_asset(
    db: Session,
    actor: Actor,
    shot_id: int,
    asset_id: int,
    asset_state_id: int | None = None,
) -> models.ShotAsset:
    """Ассет в кадре шота и его состояние в этом шоте. Повторный вызов меняет состояние."""
    shot = core.get(db, EntityType.SHOT, shot_id)
    asset = core.get(db, EntityType.ASSET, asset_id)
    permissions.require(permissions.can_edit(actor, EntityType.SHOT, shot.created_by, {"assets"}))  # type: ignore[attr-defined]
    if asset_state_id is not None:
        state = db.get(models.AssetState, asset_state_id)
        if state is None or state.asset_id != asset_id or state.deleted_at is not None:
            raise ValidationError("Состояние не принадлежит этому ассету")

    link = db.scalar(
        select(models.ShotAsset).where(
            models.ShotAsset.shot_id == shot_id, models.ShotAsset.asset_id == asset_id
        )
    )
    created = link is None
    if link is None:
        link = models.ShotAsset(shot_id=shot_id, asset_id=asset_id, asset_state_id=asset_state_id)
        db.add(link)
        diff = {"asset": asset.code, "state_id": asset_state_id}  # type: ignore[attr-defined]
    elif link.asset_state_id == asset_state_id:
        return link
    else:
        diff = {"asset": asset.code, "state_id": [link.asset_state_id, asset_state_id]}  # type: ignore[attr-defined]
        link.asset_state_id = asset_state_id
    db.flush()
    log_activity(
        db,
        actor.id,
        "link" if created else "update",
        EntityType.SHOT,
        shot_id,
        diff,
        shot.project_id,  # type: ignore[attr-defined]
    )
    return link


def remove_shot_asset(db: Session, actor: Actor, shot_id: int, asset_id: int) -> None:
    shot = core.get(db, EntityType.SHOT, shot_id)
    permissions.require(permissions.can_edit(actor, EntityType.SHOT, shot.created_by, {"assets"}))  # type: ignore[attr-defined]
    link = db.scalar(
        select(models.ShotAsset).where(
            models.ShotAsset.shot_id == shot_id, models.ShotAsset.asset_id == asset_id
        )
    )
    if link is None:
        raise NotFoundError("Ассета нет в этом шоте")
    asset = db.get(models.Asset, asset_id)
    db.delete(link)
    db.flush()
    log_activity(
        db,
        actor.id,
        "unlink",
        EntityType.SHOT,
        shot_id,
        {"asset": asset.code if asset else asset_id},
        shot.project_id,  # type: ignore[attr-defined]
    )


# --- вложения ----------------------------------------------------------------------------------


def _sync_takes(db: Session, entity_type: str, entity_id: int) -> None:
    """`shot.takes_count` — число дублей-вложений; поддерживается при привязке и снятии."""
    if entity_type != EntityType.SHOT:
        return
    count = db.scalar(
        select(func.count())
        .select_from(models.Attachment)
        .join(models.File, models.File.id == models.Attachment.file_id)
        .where(
            models.Attachment.entity_type == EntityType.SHOT,
            models.Attachment.entity_id == entity_id,
            models.Attachment.purpose == Purpose.TAKE,
            models.File.deleted_at.is_(None),
        )
    )
    shot = db.get(models.Shot, entity_id)
    if shot is not None:
        shot.takes_count = count or 0


# К чему можно привязать файл. Один набор и для обычной привязки, и для импорта из Telegram.
ATTACH_TARGETS = frozenset(
    {
        EntityType.SCENE,
        EntityType.SHOT,
        EntityType.ASSET,
        EntityType.ASSET_STATE,
        EntityType.SETUP_PAYOFF,
        EntityType.SOUND_CUE,
        EntityType.TASK,
    }
)


def require_attach_target(entity_type: str) -> None:
    if entity_type not in ATTACH_TARGETS:
        raise ValidationError(f"К «{entity_type}» файлы не привязываются")


def attach(
    db: Session,
    actor: Actor,
    file_id: int,
    entity_type: str,
    entity_id: int,
    purpose: str = Purpose.REFERENCE.value,
) -> models.Attachment:
    """Привязка файла к шоту/сцене/ассету/состоянию. Файл из медиатеки можно привязать к
    ещё одной карточке без повторной загрузки; один и тот же файл — не дважды к одной."""
    permissions.require(permissions.can_upload(actor))
    if purpose not in {p.value for p in Purpose}:
        raise ValidationError(f"Неизвестное назначение: {purpose}")
    require_attach_target(entity_type)
    file = core.get(db, EntityType.FILE, file_id)
    target = core.get(db, entity_type, entity_id)

    existing = db.scalar(
        select(models.Attachment).where(
            models.Attachment.file_id == file_id,
            models.Attachment.entity_type == entity_type,
            models.Attachment.entity_id == entity_id,
            models.Attachment.purpose == purpose,
        )
    )
    if existing is not None:
        raise ConflictError("Этот файл уже привязан к карточке")

    row = models.Attachment(
        file_id=file_id,
        entity_type=entity_type,
        entity_id=entity_id,
        purpose=purpose,
        created_by=actor.id,
    )
    db.add(row)
    db.flush()
    _sync_takes(db, entity_type, entity_id)
    log_activity(
        db,
        actor.id,
        "attach",
        entity_type,
        entity_id,
        {"file_id": file_id, "file": file.original_name, "purpose": purpose},  # type: ignore[attr-defined]
        getattr(target, "project_id", None) or file.project_id,  # type: ignore[attr-defined]
    )
    return row


def detach(db: Session, actor: Actor, attachment_id: int) -> None:
    """Снять привязку (жёстко, в журнал). Свою снимает любой, чужую — режиссёр и владелец."""
    row = db.get(models.Attachment, attachment_id)
    if row is None:
        raise NotFoundError("Привязка не найдена")
    permissions.require(permissions.can_delete(actor, row.created_by))
    entity_type, entity_id, file_id = row.entity_type, row.entity_id, row.file_id
    file = db.get(models.File, file_id)
    db.delete(row)
    db.flush()
    _sync_takes(db, entity_type, entity_id)
    log_activity(
        db,
        actor.id,
        "detach",
        entity_type,
        entity_id,
        {"file_id": file_id, "file": file.original_name if file else None},
        file.project_id if file else None,
    )

"""Уведомления на сайте: комментарий или новый файл на карточке → уведомление остальным.

По решению заказчика — только на сайте (без Telegram и без согласований). Уведомление хранит
карточку, куда ведёт клик, и тот, кто его прочитал, снимает его у себя; у других оно остаётся.
Запись идёт в транзакции действия: откатили действие — уведомления тоже нет.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import models
from app.constants import EntityType, NotificationKind
from app.db import utcnow

COALESCE = timedelta(minutes=10)  # события одного автора на одной карточке склеиваются
KEEP_DAYS = 30
SNIPPET_LEN = 140


def _clip(text: str | None) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= SNIPPET_LEN else text[: SNIPPET_LEN - 1] + "…"


def card_of(db: Session, entity_type: str, entity_id: int) -> tuple[str, int]:
    """Куда вести клик: состояние ассета → его ассет, файл → первая карточка, где он лежит."""
    if entity_type == EntityType.ASSET_STATE.value:
        state = db.get(models.AssetState, entity_id)
        if state is not None:
            return EntityType.ASSET.value, state.asset_id
    if entity_type == EntityType.FILE.value:
        row = db.execute(
            select(models.Attachment.entity_type, models.Attachment.entity_id)
            .where(models.Attachment.file_id == entity_id)
            .order_by(models.Attachment.id)
            .limit(1)
        ).first()
        if row is not None:
            return row[0], row[1]
    return entity_type, entity_id


def _recipients(db: Session, actor_id: int | None) -> list[int]:
    stmt = select(models.User.id).where(models.User.access_revoked_at.is_(None))
    if actor_id is not None:
        stmt = stmt.where(models.User.id != actor_id)
    return list(db.scalars(stmt))


def notify(
    db: Session,
    actor_id: int | None,
    kind: NotificationKind,
    entity_type: str,
    entity_id: int,
    snippet: str | None = None,
) -> int:
    """Уведомляет всех, кроме автора действия. Возвращает число получателей."""
    entity_type, entity_id = card_of(db, entity_type, entity_id)
    people = _recipients(db, actor_id)
    if not people:
        return 0
    now = utcnow()
    fresh = {
        n.user_id: n
        for n in db.scalars(
            select(models.Notification).where(
                models.Notification.user_id.in_(people),
                models.Notification.actor_id == actor_id,
                models.Notification.kind == kind.value,
                models.Notification.entity_type == entity_type,
                models.Notification.entity_id == entity_id,
                models.Notification.read_at.is_(None),
                models.Notification.created_at > now - COALESCE,
            )
        )
    }
    text = _clip(snippet)
    for user_id in people:
        existing = fresh.get(user_id)
        if existing is not None:
            existing.count += 1
            existing.snippet = text or existing.snippet
            existing.created_at = now
        else:
            db.add(
                models.Notification(
                    user_id=user_id,
                    actor_id=actor_id,
                    kind=kind.value,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    snippet=text,
                    created_at=now,
                )
            )
    db.flush()
    return len(people)


# --- чтение и отметки ----------------------------------------------------------------------------


def unread_count(db: Session, user_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(models.Notification)
            .where(models.Notification.user_id == user_id, models.Notification.read_at.is_(None))
        )
        or 0
    )


def recent(db: Session, user_id: int, limit: int = 30) -> list[models.Notification]:
    return list(
        db.scalars(
            select(models.Notification)
            .where(models.Notification.user_id == user_id)
            .order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
            .limit(limit)
        )
    )


def mark_read(db: Session, user_id: int, notification_id: int) -> bool:
    """Своё уведомление помечается прочитанным; чужое не трогается. Возвращает, найдено ли своё."""
    row = db.get(models.Notification, notification_id)
    if row is None or row.user_id != user_id:
        return False
    if row.read_at is None:
        row.read_at = utcnow()
    return True


def mark_all_read(db: Session, user_id: int) -> int:
    result = db.execute(
        update(models.Notification)
        .where(models.Notification.user_id == user_id, models.Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    return result.rowcount or 0


def prune(db: Session, now: datetime | None = None) -> int:
    """Старше 30 дней уведомления не нужны ни прочитанные, ни нет."""
    cutoff = (now or utcnow()) - timedelta(days=KEEP_DAYS)
    result = db.execute(delete(models.Notification).where(models.Notification.created_at < cutoff))
    return result.rowcount or 0

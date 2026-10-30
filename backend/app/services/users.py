"""Пользователи: аккаунт на сайте = аккаунт в Telegram. Создаются только при входе."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.constants import USER_COLORS, Role
from app.db import utcnow
from app.services.core import log_activity

SEEN_THROTTLE = timedelta(minutes=1)


def pick_color(db: Session) -> str:
    """Самый редкий цвет палитры среди участников — соседи отличаются друг от друга."""
    rows = db.execute(select(models.User.color, func.count()).group_by(models.User.color)).all()
    used = dict(rows)
    return min(USER_COLORS, key=lambda c: (used.get(c, 0), USER_COLORS.index(c)))


def upsert_from_telegram(
    db: Session,
    *,
    tg_id: int,
    username: str | None,
    name: str,
    avatar_path: str | None,
    owner_tg_id: int | None,
) -> models.User:
    """Вход подтверждён: создаёт участника или обновляет имя, @username и аватар из Telegram."""
    user = db.scalar(select(models.User).where(models.User.tg_id == tg_id))
    created = user is None
    if user is None:
        user = models.User(tg_id=tg_id, color=pick_color(db), role=Role.TEAM.value, name=name)
        db.add(user)
    user.tg_username = username
    user.name = name
    if avatar_path:
        user.avatar_path = avatar_path
    if owner_tg_id is not None and tg_id == owner_tg_id:
        user.role = Role.OWNER.value
    now = utcnow()
    user.membership_checked_at = now
    user.last_seen_at = now
    user.access_revoked_at = None
    db.flush()
    log_activity(db, user.id, "login", "user", user.id, {"created": created})
    return user


def touch_seen(db: Session, user: models.User) -> None:
    now = utcnow()
    if user.last_seen_at is None or now - user.last_seen_at > SEEN_THROTTLE:
        user.last_seen_at = now


def mark_membership_ok(db: Session, user: models.User) -> None:
    user.membership_checked_at = utcnow()


def revoke_access(db: Session, user: models.User) -> None:
    """Человек вышел из чата — доступ закрыт до следующего успешного входа."""
    user.access_revoked_at = utcnow()
    db.flush()
    log_activity(db, None, "access_revoked", "user", user.id)


def due_for_recheck(db: Session, max_age: timedelta, limit: int = 50) -> list[models.User]:
    cutoff = utcnow() - max_age
    stmt = (
        select(models.User)
        .where(
            models.User.tg_id.is_not(None),
            models.User.access_revoked_at.is_(None),
            (models.User.membership_checked_at.is_(None))
            | (models.User.membership_checked_at < cutoff),
        )
        .limit(limit)
    )
    return list(db.scalars(stmt))

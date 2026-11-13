"""Пользователи: аккаунт на сайте = аккаунт в Telegram. Создаются только при входе."""

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app import db as database
from app import models
from app.config import Settings, get_settings
from app.constants import USER_COLORS, Role
from app.db import utcnow
from app.services import members
from app.services.core import log_activity

SEEN_THROTTLE = timedelta(minutes=1)
# Отметка необязательна: занято — не ждём обычные пять секунд, отметим в следующий раз.
SEEN_WAIT_MS = 300


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
    chats: dict[int, bool | None] | None = None,
) -> models.User:
    """Вход подтверждён: создаёт участника или обновляет имя, @username и аватар из Telegram.

    `chats` — в каких чатах проектов человек состоит (см. `members.sync_user`); None — Telegram
    недоступен, членство неизвестно: проекты и отметка о проверке остаются как были."""
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
    # В запасном режиме (Telegram недоступен, chats пуст) проверку не продлеваем: иначе вышедший
    # из чата входил бы вечно, пока связи нет.
    if chats is not None:
        user.membership_checked_at = now
    user.last_seen_at = now
    user.access_revoked_at = None
    db.flush()
    members.sync_user(db, user, chats)
    log_activity(db, user.id, "login", "user", user.id, {"created": created})
    return user


def touch_seen(db: Session, user: models.User) -> None:
    """Отмечает, что человек на сайте, не чаще раза в минуту.

    Пишется отдельной короткой транзакцией, а не правкой в транзакции запроса: та уходит в базу при
    первом же запросе к данным и держит блокировку записи до конца запроса — пока принимается кусок
    файла, считается sha256 или файл отдаётся медленному клиенту, писать не может больше никто
    (на боевом сайте это были `database is locked`)."""
    now = utcnow()
    if user.last_seen_at is not None and now - user.last_seen_at <= SEEN_THROTTLE:
        return
    if _write_seen(user.id, now):
        # Объект запроса знает о новой отметке, но не считает себя изменённым: записи не будет.
        set_committed_value(user, "last_seen_at", now)


def _write_seen(user_id: int, now: datetime) -> bool:
    with database.session_factory()() as short:
        short.connection().exec_driver_sql(f"PRAGMA busy_timeout={SEEN_WAIT_MS}")
        try:
            short.execute(
                update(models.User).where(models.User.id == user_id).values(last_seen_at=now)
            )
            short.commit()
            return True
        except OperationalError:  # база занята: не ломаем из-за этого запрос человека
            short.rollback()
            return False
        finally:
            # Соединение вернётся в пул: пусть дальше все ждут столько же, сколько раньше.
            short.connection().exec_driver_sql(f"PRAGMA busy_timeout={database.BUSY_TIMEOUT_MS}")


def revoke_access(db: Session, user: models.User) -> None:
    """Человек вышел из чата — доступ закрыт до следующего успешного входа."""
    user.access_revoked_at = utcnow()
    db.flush()
    log_activity(db, None, "access_revoked", "user", user.id)


def revoke_orphans(db: Session, settings: Settings | None = None) -> int:
    """Доступ закрывается тем, кто не состоит ни в одном проекте (вышел из всех чатов).

    Суперадмина и аккаунты без Telegram не трогаем. Вернётся человек в чат и войдёт заново —
    доступ вернётся.
    """
    settings = settings or get_settings()
    has_project = select(models.ProjectMember.user_id).where(models.ProjectMember.active.is_(True))
    orphans = db.scalars(
        select(models.User).where(
            models.User.tg_id.is_not(None),
            models.User.access_revoked_at.is_(None),
            models.User.id.not_in(has_project),
        )
    )
    closed = 0
    for user in list(orphans):
        if settings.is_superadmin(user.tg_id):
            continue
        revoke_access(db, user)
        closed += 1
    return closed


def confirmed_recently(db: Session, tg_id: int, max_age: timedelta) -> bool:
    """Запасной путь входа, когда Telegram не отвечает: человека недавно подтверждал чат,
    доступ ему не закрывали, и он всё ещё участник какого-нибудь проекта."""
    user = db.scalar(select(models.User).where(models.User.tg_id == tg_id))
    if user is None or user.access_revoked_at is not None or user.membership_checked_at is None:
        return False
    if utcnow() - user.membership_checked_at > max_age:
        return False
    return bool(members.active_project_ids(db, user.id))

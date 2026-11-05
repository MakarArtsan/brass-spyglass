"""Участники проектов: роль и цвет человека хранятся на паре «человек + проект».

Один проект = один закрытый чат. Кто состоит в чате, тот `active`; вышел — `active` снимается, но
запись, роль и всё, что человек загрузил, остаются (авторство не теряется). При повторном вступлении
роль восстанавливается.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import Settings, get_settings
from app.constants import Role
from app.db import utcnow
from app.services.core import log_activity


def get(db: Session, project_id: int, user_id: int) -> models.ProjectMember | None:
    return db.scalar(
        select(models.ProjectMember).where(
            models.ProjectMember.project_id == project_id, models.ProjectMember.user_id == user_id
        )
    )


def ensure(
    db: Session,
    project: models.Project,
    user: models.User,
    *,
    role: Role | None = None,
    settings: Settings | None = None,
) -> models.ProjectMember:
    """Участник проекта: создаёт запись или возвращает вступившего заново (роль возвращается).

    Первая роль в проекте — «Команда»; суперадмин (`SUPERADMIN_TG_IDS`, `OWNER_TG_ID`) — «Владелец».
    """
    settings = settings or get_settings()
    member = get(db, project.id, user.id)
    if member is None:
        first = role or (Role.OWNER if settings.is_superadmin(user.tg_id) else Role.TEAM)
        member = models.ProjectMember(
            project_id=project.id, user_id=user.id, role=first.value, color=user.color
        )
        db.add(member)
    elif not member.active:
        member.active = True
        member.left_at = None
        member.joined_at = utcnow()
    if role is not None:
        member.role = role.value
    db.flush()
    return member


def leave(db: Session, member: models.ProjectMember) -> None:
    if member.active:
        member.active = False
        member.left_at = utcnow()
        db.flush()


def sync_user(
    db: Session,
    user: models.User,
    chats: dict[int, bool | None] | None,
    settings: Settings | None = None,
) -> None:
    """Привязывает человека к проектам по тому, в чьих чатах он состоит.

    `chats`: чат → состоит (True) / не состоит (False) / не удалось узнать (None).
    Вступил — участник (роль возвращается). Вышел — `active` снят, роль и авторство остаются.
    Что неизвестно, не трогается: сбой Telegram никого не выгоняет. Суперадмин — владелец везде
    и из проекта не «выходит»; участником его делает чат (или проект без чата), а не статус.
    """
    settings = settings or get_settings()
    superadmin = settings.is_superadmin(user.tg_id)
    for project in db.scalars(select(models.Project)):
        if project.tg_chat_id is None:
            if superadmin:  # у проекта нет чата, людей из чата в нём нет
                ensure(db, project, user, settings=settings)
            continue
        state = (chats or {}).get(project.tg_chat_id)
        if state is True:
            ensure(db, project, user, settings=settings)
        elif state is False and not superadmin:
            member = get(db, project.id, user.id)
            if member is not None:
                leave(db, member)


def sync_chat(
    db: Session, project: models.Project, tg_ids: set[int], settings: Settings | None = None
) -> tuple[int, int]:
    """Приводит участников проекта к списку его чата: возвращает (вступили, вышли).

    Тех, кто в чате есть, но на сайт ещё не входил, не создаёт: аккаунт появляется при первом входе.
    Суперадмин и аккаунты без Telegram (`tg_id` пуст) не выходят из проекта.
    """
    settings = settings or get_settings()
    now = utcnow()
    joined = left = 0
    for user in db.scalars(select(models.User).where(models.User.tg_id.in_(tg_ids))):
        user.membership_checked_at = now  # подтверждён в чате: на этом держится запасной путь входа
        member = get(db, project.id, user.id)
        if member is None or not member.active:
            ensure(db, project, user, settings=settings)
            joined += 1
    active = db.scalars(
        select(models.ProjectMember).where(
            models.ProjectMember.project_id == project.id, models.ProjectMember.active.is_(True)
        )
    )
    for member in list(active):
        user = db.get(models.User, member.user_id)
        if user is None or user.tg_id is None or user.tg_id in tg_ids:
            continue
        if settings.is_superadmin(user.tg_id):
            continue
        leave(db, member)
        left += 1
    if joined or left:
        log_activity(
            db, None, "members_sync", "project", project.id,
            {"joined": joined, "left": left}, project_id=project.id,
        )  # fmt: skip
    return joined, left


def active_project_ids(db: Session, user_id: int) -> list[int]:
    return list(
        db.scalars(
            select(models.ProjectMember.project_id).where(
                models.ProjectMember.user_id == user_id, models.ProjectMember.active.is_(True)
            )
        )
    )

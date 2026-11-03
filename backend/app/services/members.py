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


def active_project_ids(db: Session, user_id: int) -> list[int]:
    return list(
        db.scalars(
            select(models.ProjectMember.project_id).where(
                models.ProjectMember.user_id == user_id, models.ProjectMember.active.is_(True)
            )
        )
    )

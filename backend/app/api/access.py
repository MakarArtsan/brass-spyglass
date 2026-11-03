"""Доступ к проекту: `/api/p/<slug>/…`, членство и роль.

Чужой проект и несуществующий выглядят одинаково (404): по ответам нельзя подобрать адреса и
узнать названия чужих проектов. Здесь же сессия получает проект (`scope`), после чего каждый
запрос к данным проекта фильтруется сам.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, scope
from app.auth import session
from app.config import Settings, get_settings
from app.constants import Role
from app.db import get_db
from app.permissions import Actor
from app.services import members, projects

DbDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[models.User, Depends(session.current_user)]


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")


@dataclass(frozen=True, slots=True)
class ProjectCtx:
    project: models.Project
    user: models.User
    role: Role

    @property
    def actor(self) -> Actor:
        return Actor(id=self.user.id, role=self.role, project_id=self.project.id)


def role_in(
    db: Session, project: models.Project, user: models.User, settings: Settings | None = None
) -> Role | None:
    """Роль человека в проекте или None, если проекта для него нет.

    Суперадмин видит все проекты и в каждом владелец. Остальные — только проекты своих чатов
    (`project_member.active`). Архивный проект команда видит только на чтение (как гость).
    """
    settings = settings or get_settings()
    if settings.is_superadmin(user.tg_id):
        return Role.OWNER
    member = members.get(db, project.id, user.id)
    if member is None or not member.active:
        return None
    role = Role(member.role)
    return Role.GUEST if project.archived_at is not None else role


def project_access(slug: str, db: DbDep, user: UserDep) -> ProjectCtx:
    project = projects.get_by_slug(db, slug)
    role = role_in(db, project, user) if project is not None else None
    if project is None or role is None:
        raise not_found()
    scope.select_project(db, project.id, project.slug)
    return ProjectCtx(project, user, role)


def project_actor(ctx: Annotated[ProjectCtx, Depends(project_access)]) -> Actor:
    return ctx.actor


ActorDep = Annotated[Actor, Depends(project_actor)]
CtxDep = Annotated[ProjectCtx, Depends(project_access)]

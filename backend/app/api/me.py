"""Кто вошёл, его проекты, текущий проект и участники проекта."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, permissions
from app.api import access
from app.auth import session
from app.config import get_settings
from app.db import get_db
from app.schemas import (
    AbilitiesOut,
    MeOut,
    ProjectBrief,
    ProjectOut,
    ProjectRename,
    SessionOut,
    UserOut,
)
from app.services import members, projects

# Вне проекта: кто вошёл, список его проектов, аватары.
router = APIRouter(dependencies=[Depends(session.same_origin)])
# Внутри проекта (`/api/p/<slug>/…`): роль человека в проекте, проект, участники.
project_router = APIRouter(dependencies=[Depends(session.same_origin)])


def _user_out(user: models.User, member: models.ProjectMember | None = None) -> UserOut:
    out = UserOut.model_validate(user)
    out.has_avatar = bool(user.avatar_path)
    if member is not None:  # роль и цвет принадлежат паре «человек + проект»
        out.role, out.color = member.role, member.color
    return out


def my_projects(db: Session, user: models.User) -> list[ProjectBrief]:
    """Проекты, открытые человеку: суперадмину все, остальным — свои чаты."""
    settings = get_settings()
    stmt = select(models.Project).order_by(models.Project.id)
    briefs: list[ProjectBrief] = []
    for project in db.scalars(stmt):
        role = access.role_in(db, project, user, settings)
        if role is None:
            continue
        briefs.append(
            ProjectBrief(
                slug=project.slug,
                title=project.title,
                title_en=project.title_en,
                role=role.value,
                archived=project.archived_at is not None,
                pending=project.approved_at is None,
            )
        )
    return briefs


@router.get("/session", response_model=SessionOut)
def session_info(
    user: Annotated[models.User, Depends(session.current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionOut:
    return SessionOut(
        user=_user_out(user),
        is_superadmin=get_settings().is_superadmin(user.tg_id),
        projects=my_projects(db, user),
        can_create_projects=projects.can_create(db, user),
        pending_count=len(projects.pending(db)) if get_settings().is_superadmin(user.tg_id) else 0,
    )


@router.get("/projects", response_model=list[ProjectBrief])
def projects_list(
    user: Annotated[models.User, Depends(session.current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ProjectBrief]:
    return my_projects(db, user)


@router.get("/users/{user_id}/avatar")
def avatar(
    user_id: int,
    _: Annotated[models.User, Depends(session.current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    user = db.get(models.User, user_id)
    if user is None or not user.avatar_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет аватара")
    root = get_settings().cache_dir.resolve()
    path = (root / user.avatar_path).resolve()
    if not path.is_relative_to(root) or not Path(path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет аватара")
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )


@project_router.get("/me", response_model=MeOut)
def project_me(ctx: access.CtxDep, db: Annotated[Session, Depends(get_db)]) -> MeOut:
    actor = ctx.actor
    member = members.get(db, ctx.project.id, ctx.user.id)  # у суперадмина вне чата записи нет
    return MeOut(
        user=_user_out(ctx.user, member),
        abilities=AbilitiesOut(
            upload=permissions.can_upload(actor),
            export=permissions.can_export(actor),
            journal=permissions.can_view_journal(actor),
            manage_users=permissions.can_manage_users(actor),
            restore=permissions.can_restore(actor),
            edit_project=permissions.can_edit_project(actor),
            import_scenario=permissions.can_import(actor),
        ),
    )


@project_router.get("/project", response_model=ProjectOut)
def project(ctx: access.CtxDep) -> models.Project:
    return ctx.project


@project_router.patch("/project", response_model=ProjectOut)
def rename_project(
    body: ProjectRename, ctx: access.CtxDep, db: Annotated[Session, Depends(get_db)]
) -> models.Project:
    """Переименовать проект. Только владелец; адрес проекта не меняется."""
    return projects.rename(db, ctx.actor, title=body.title, title_en=body.title_en)


@project_router.get("/users", response_model=list[UserOut])
def list_users(ctx: access.CtxDep, db: Annotated[Session, Depends(get_db)]) -> list[UserOut]:
    """Участники проекта (состоящие в его чате) с ролью и цветом в этом проекте."""
    rows = db.execute(
        select(models.User, models.ProjectMember)
        .join(models.ProjectMember, models.ProjectMember.user_id == models.User.id)
        .where(
            models.ProjectMember.project_id == ctx.project.id,
            models.ProjectMember.active.is_(True),
            models.User.access_revoked_at.is_(None),
        )
        .order_by(models.User.id)
    )
    return [_user_out(user, member) for user, member in rows]

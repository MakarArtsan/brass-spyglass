"""Текущий пользователь, проект и участники."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, permissions
from app.auth import session
from app.config import get_settings
from app.db import get_db
from app.permissions import Actor
from app.schemas import AbilitiesOut, MeOut, ProjectOut, UserOut
from app.services import projects

router = APIRouter(dependencies=[Depends(session.same_origin)])


def _user_out(user: models.User) -> UserOut:
    out = UserOut.model_validate(user)
    out.has_avatar = bool(user.avatar_path)
    return out


@router.get("/me", response_model=MeOut)
def me(
    user: Annotated[models.User, Depends(session.current_user)],
    actor: Annotated[Actor, Depends(session.actor_of)],
) -> MeOut:
    return MeOut(
        user=_user_out(user),
        abilities=AbilitiesOut(
            upload=permissions.can_upload(actor),
            export=permissions.can_export(actor),
            journal=permissions.can_view_journal(actor),
            manage_users=permissions.can_manage_users(actor),
            restore=permissions.can_restore(actor),
        ),
    )


@router.get("/project", response_model=ProjectOut)
def project(
    _: Annotated[models.User, Depends(session.current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> models.Project:
    found = projects.get_project(db)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не создан")
    return found


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: Annotated[models.User, Depends(session.current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[UserOut]:
    rows = db.scalars(
        select(models.User).where(models.User.access_revoked_at.is_(None)).order_by(models.User.id)
    )
    return [_user_out(u) for u in rows]


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

"""Помощники для тестов: участники и актёры."""

from itertools import count

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.constants import Role
from app.permissions import Actor
from app.services import members, users

_tg_ids = count(2000)


def make_user(db: Session, role: Role = Role.TEAM, name: str = "Тест") -> models.User:
    user = users.upsert_from_telegram(
        db,
        tg_id=next(_tg_ids),
        username=None,
        name=name,
        avatar_path=None,
        owner_tg_id=None,
    )
    user.role = role.value
    project = db.scalar(select(models.Project).order_by(models.Project.id).limit(1))
    if project is not None:  # роль живёт на паре «человек + проект»
        members.ensure(db, project, user, role=role)
    db.flush()
    return user


def actor(user: models.User) -> Actor:
    return Actor(id=user.id, role=Role(user.role), project_id=_default_project_id(user))


def _default_project_id(user: models.User) -> int | None:
    from sqlalchemy.orm import object_session

    db = object_session(user)
    project = db.scalar(select(models.Project).order_by(models.Project.id).limit(1)) if db else None
    return project.id if project else None

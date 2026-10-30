"""Помощники для тестов: участники и актёры."""

from itertools import count

from sqlalchemy.orm import Session

from app import models
from app.constants import Role
from app.permissions import Actor
from app.services import users

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
    db.flush()
    return user


def actor(user: models.User) -> Actor:
    return Actor(id=user.id, role=Role(user.role))

"""Уведомления на сайте: колокольчик с числом непрочитанного и список, клик ведёт в карточку."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import models
from app.api import serialize
from app.api.entities import DbDep, UserDep
from app.auth import session
from app.constants import EntityType
from app.services import notifications

router = APIRouter(dependencies=[Depends(session.same_origin)])

# Куда ведёт клик. У сцены, шота и ассета есть своя карточка, у остальных — страница раздела.
CARD_URL = {
    EntityType.SHOT.value: "/shots?shot={id}",
    EntityType.SCENE.value: "/scenes/{id}",
    EntityType.ASSET.value: "/assets?asset={id}",
    EntityType.SETUP_PAYOFF.value: "/setups",
    EntityType.SOUND_CUE.value: "/sound",
    EntityType.TASK.value: "/tasks",
    EntityType.FILE.value: "/media",
}


def _items(db: DbDep, rows: list[models.Notification]) -> list[dict[str, Any]]:
    people = serialize.authors(db, {r.actor_id for r in rows})
    labels = serialize.entity_labels(db, {(r.entity_type, r.entity_id) for r in rows})
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "count": r.count,
            "snippet": r.snippet,
            "actor": people.get(r.actor_id) if r.actor_id else None,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "label": labels.get((r.entity_type, r.entity_id)),
            "url": CARD_URL.get(r.entity_type, "/").format(id=r.entity_id),
            "created_at": r.created_at,
            "read": r.read_at is not None,
        }
        for r in rows
    ]


@router.get("/notifications")
def list_notifications(
    db: DbDep, user: UserDep, limit: int = Query(default=30, ge=1, le=100)
) -> dict[str, Any]:
    return {
        "unread": notifications.unread_count(db, user.id),
        "items": _items(db, notifications.recent(db, user.id, limit)),
    }


@router.post("/notifications/read-all")
def read_all(db: DbDep, user: UserDep) -> dict[str, int]:
    notifications.mark_all_read(db, user.id)
    return {"unread": 0}


@router.post("/notifications/{notification_id}/read")
def read_one(notification_id: int, db: DbDep, user: UserDep) -> dict[str, int]:
    if not notifications.mark_read(db, user.id, notification_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Уведомление не найдено")
    db.flush()
    return {"unread": notifications.unread_count(db, user.id)}

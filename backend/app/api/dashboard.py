"""Дашборд: все числа за один запрос. Считает `metrics.py`, здесь только сборка ответа и лента."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import metrics, models, permissions
from app.api import serialize
from app.api.entities import ActorDep, DbDep, UserDep
from app.auth import session
from app.config import get_settings
from app.db import utcnow
from app.permissions import Actor
from app.services import projects
from app.services.core import NotFoundError

router = APIRouter(dependencies=[Depends(session.same_origin)])

FEED_LIMIT = 10
FEED_DIFF_FIELDS = 3  # у правки показываем не больше трёх полей «было → стало»


def _feed(db: Session) -> list[dict[str, Any]]:
    """Последние действия команды; у загруженных файлов есть превью. Живёт на SSE-обновлениях."""
    rows = list(
        db.scalars(
            select(models.Activity)
            .where(models.Activity.action.not_in(metrics.NOISE_ACTIONS))
            .order_by(models.Activity.id.desc())
            .limit(FEED_LIMIT)
        )
    )
    people = serialize.authors(db, {r.actor_id for r in rows})
    labels = serialize.entity_labels(db, {(r.entity_type, r.entity_id) for r in rows})
    file_ids = {r.entity_id for r in rows if r.entity_type == "file" and r.entity_id is not None}
    files = (
        {
            f.id: f
            for f in db.scalars(
                select(models.File).where(
                    models.File.id.in_(file_ids), models.File.deleted_at.is_(None)
                )
            )
        }
        if file_ids
        else {}
    )
    items = []
    for r in rows:
        diff = r.diff if isinstance(r.diff, dict) else {}
        file = files.get(r.entity_id) if r.entity_type == "file" else None
        items.append(
            {
                "id": r.id,
                "at": r.at,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "label": labels.get((r.entity_type, r.entity_id)) if r.entity_id else None,
                "actor": people.get(r.actor_id) if r.actor_id else None,
                "diff": _changes(diff) if r.action in ("status", "update") else None,
                "thumb_url": serialize.file_urls(file).get("thumb") if file else None,
                "file_kind": file.kind if file else None,
            }
        )
    return items


def _changes(diff: dict[str, Any]) -> dict[str, Any]:
    """Только пары «было → стало»: полный дифф создания может быть большим и в ленте не нужен."""
    pairs = {k: v for k, v in diff.items() if isinstance(v, list) and len(v) == 2}
    return dict(list(pairs.items())[:FEED_DIFF_FIELDS])


@router.get("/dashboard")
def get_dashboard(db: DbDep, user: UserDep, actor: ActorDep) -> dict[str, Any]:
    project = projects.get_project(db)
    if project is None:
        raise NotFoundError("Проект не создан")
    data = metrics.dashboard_data(db, project, get_settings(), utcnow(), user.id)
    data["feed"] = _feed(db) if _can_see_feed(actor) else []
    ids: set[int | None] = {c["user_id"] for c in data["contribution"]}
    for bar in data["activity"]["bars"]:
        ids.update(bar["by_user"])
    ids.update(item["actor"]["id"] for item in data["feed"] if item["actor"])
    data["people"] = serialize.authors(db, ids)
    return data


def _can_see_feed(actor: Actor) -> bool:
    """Лента — по сути журнал, а гостю журнал не показывается (ТЗ)."""
    return permissions.can_view_journal(actor)

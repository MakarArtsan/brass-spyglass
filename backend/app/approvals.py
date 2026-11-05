"""Решение суперадмина по заявке на проект: подтвердить или отклонить.

Один путь для двух входов — кнопка на сайте и кнопка в сообщении бота: меняет проект (сервис),
запускает или останавливает индексатор чата и сообщает владельцам проекта. Бот пишет им в личные
сообщения: человек нажимал Start при входе, поэтому писать ему можно.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import FastAPI

from app import db as database
from app import models
from app.config import get_settings
from app.services import core, projects

log = logging.getLogger(__name__)

Action = Literal["approve", "reject"]


@dataclass(frozen=True)
class Outcome:
    title: str
    slug: str
    action: Action


@dataclass(frozen=True)
class _Applied:
    outcome: Outcome
    chat_id: int | None
    owner_tg_ids: list[int]


def _apply(action: Action, project_id: int, user_id: int) -> _Applied:
    with database.session_factory()() as db:
        user = db.get(models.User, user_id)
        project = db.get(models.Project, project_id)
        if user is None or project is None:
            raise core.NotFoundError("Такого проекта нет")
        settings = get_settings()
        if action == "approve":
            projects.approve(db, user, project, settings)
            chat = project.tg_chat_id
        else:
            chat = projects.reject(db, user, project, settings)
        owner_ids = [o.tg_id for o in projects.owners(db, project) if o.tg_id is not None]
        applied = _Applied(Outcome(project.title, project.slug, action), chat, owner_ids)
        db.commit()
        return applied


def message_for(outcome: Outcome) -> str:
    if outcome.action == "approve":
        return f"Проект «{outcome.title}» подтверждён: команда может загружать файлы."
    return f"Заявка на проект «{outcome.title}» отклонена."


async def decide(app: FastAPI, action: Action, project_id: int, user_id: int) -> Outcome:
    """Применяет решение и всё, что за ним следует. Ошибки сервиса (нет прав, уже подтверждён) идут
    вызывающему как есть: сайт превратит их в ответ, бот — в сообщение."""
    applied = await asyncio.to_thread(_apply, action, project_id, user_id)
    pool: Any = getattr(app.state, "indexer_pool", None)
    if pool is not None and applied.chat_id is not None:
        try:
            if action == "approve":
                await pool.ensure(applied.chat_id)  # теперь можно собирать медиа чата
            else:
                await pool.remove(applied.chat_id)
        except Exception:
            log.exception("индексатор чата %s не переключён", applied.chat_id)
    for tg_id in applied.owner_tg_ids:
        await app.state.tg.notify(tg_id, message_for(applied.outcome))
    return applied.outcome

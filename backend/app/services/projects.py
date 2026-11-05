"""Проекты: у каждого адрес `/p/<slug>` и свой закрытый чат команды."""

import re
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, permissions, scope
from app.config import Settings, get_settings
from app.permissions import Actor
from app.services.core import log_activity

# Дубай: UTC+4 круглый год, без перехода на летнее время, поэтому tzdata не нужен.
DUBAI = timezone(timedelta(hours=4))

DEFAULT_SLUG = "brass-spyglass"

DEFAULT_PROJECT = {
    "slug": DEFAULT_SLUG,
    "title": "Битва при кривом зеркале",
    "title_en": "The Brass Spyglass",
    "contest": "1 Billion AI Film Award 2027",
    # Подача до 20.11.2026 по времени Дубая (UTC+4), до конца суток; это 22:59:59 по Москве (UTC+3).
    # Час закрытия приёма организаторы нигде не публикуют — конец суток это допущение.
    # Внутренний срок 18.11.2026 — тоже до конца суток.
    "deadline_official": datetime(2026, 11, 20, 23, 59, 59, tzinfo=DUBAI).astimezone(UTC),
    "deadline_internal": datetime(2026, 11, 18, 23, 59, 59, tzinfo=DUBAI).astimezone(UTC),
    "fps": 24,
    "width": 1920,
    "height": 1080,
    "target_min_sec": 300,
    "target_max_sec": 420,
    "storage_limit_gb": 5.0,  # тариф Amvera
}


def get_project(db: Session) -> models.Project | None:
    return db.scalar(select(models.Project).order_by(models.Project.id).limit(1))


def slugify(text: str, fallback: str = "project") -> str:
    """Адрес из названия: латиница, цифры и дефисы; пусто — запасное имя."""
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]
    return base or fallback


def unique_slug(db: Session, wanted: str) -> str:
    slug, n = wanted, 2
    while db.scalar(select(models.Project.id).where(models.Project.slug == slug)) is not None:
        slug, n = f"{wanted}-{n}", n + 1
    return slug


def rename(
    db: Session,
    actor: Actor,
    *,
    title: str | None = None,
    title_en: str | None = None,
) -> models.Project:
    """Меняет название проекта (рус. и/или англ.). Адрес `/p/<slug>` остаётся прежним: ссылки,
    закладки и подписанные ссылки не ломаются. Пишет в журнал пары «было → стало»."""
    permissions.require(permissions.can_edit_project(actor), "Переименовать проект может владелец")
    project = current(db)
    diff: dict[str, list[str]] = {}
    for field, value in (("title", title), ("title_en", title_en)):
        value = None if value is None else value.strip()
        if value and value != getattr(project, field):
            diff[field] = [getattr(project, field), value]
            setattr(project, field, value)
    if diff:
        log_activity(db, actor.id, "update", "project", project.id, diff, project_id=project.id)
    return project


def current(db: Session) -> models.Project:
    """Проект, в котором работает сессия (выбран `access.project_access`)."""
    project = db.get(models.Project, scope.current_project_id(db))
    if project is None:
        raise scope.ProjectScopeError("Проекта нет")
    return project


def get_by_slug(db: Session, slug: str) -> models.Project | None:
    return db.scalar(select(models.Project).where(models.Project.slug == slug))


def get_by_chat(db: Session, chat_id: int) -> models.Project | None:
    return db.scalar(select(models.Project).where(models.Project.tg_chat_id == chat_id))


def ensure_default_project(db: Session, settings: Settings | None = None) -> models.Project:
    """Первый запуск: создаёт проект фильма. Дальше настройки правят в интерфейсе.

    Чат, который до мультипроектности задавался переменной `TG_CHAT_ID`, становится чатом этого
    проекта (если у него своего чата ещё нет и чат не занят другим проектом)."""
    settings = settings or get_settings()
    project = get_project(db)
    if project is None:
        project = models.Project(**DEFAULT_PROJECT)
        db.add(project)
        db.flush()
        log_activity(db, None, "create", "project", project.id, project_id=project.id)
    chat = settings.tg_chat_id
    if chat is not None and project.tg_chat_id is None and get_by_chat(db, chat) is None:
        project.tg_chat_id = chat
        db.flush()
    return project

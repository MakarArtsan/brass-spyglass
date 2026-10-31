"""Проект фильма. Схема допускает второй проект, интерфейса под него нет."""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.services.core import log_activity

# Дубай: UTC+4 круглый год, без перехода на летнее время, поэтому tzdata не нужен.
DUBAI = timezone(timedelta(hours=4))

DEFAULT_PROJECT = {
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


def ensure_default_project(db: Session) -> models.Project:
    """Первый запуск: создаёт проект фильма. Дальше настройки правят в интерфейсе."""
    project = get_project(db)
    if project is None:
        project = models.Project(**DEFAULT_PROJECT)
        db.add(project)
        db.flush()
        log_activity(db, None, "create", "project", project.id, project_id=project.id)
    return project

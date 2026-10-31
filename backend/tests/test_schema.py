"""Схема: миграции совпадают с моделями, WAL, справочники в CHECK."""

import sqlite3
from datetime import timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from app import db as database
from app import models
from app.constants import Status, values
from app.services import projects


def test_migrations_match_models(db):
    conn = database.get_engine().connect()
    diff = compare_metadata(MigrationContext.configure(conn), models.Base.metadata)
    conn.close()
    assert diff == []


def test_sqlite_runs_in_wal_with_foreign_keys(db):
    with database.get_engine().connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_all_entities_from_the_spec_exist(db):
    expected = {
        "project", "user", "scene", "shot", "asset", "asset_state", "shot_asset", "setup_payoff",
        "sound_cue", "task", "file", "attachment", "tg_topic", "tg_media", "comment", "activity",
        "job", "export_job",
    }  # fmt: skip
    assert expected <= set(models.Base.metadata.tables)


def test_default_project_matches_spec(db):
    project = projects.get_project(db)
    assert (project.title_en, project.fps, project.width, project.height) == (
        "The Brass Spyglass",
        24,
        1920,
        1080,
    )
    assert (project.target_min_sec, project.target_max_sec) == (300, 420)
    assert project.deadline_internal < project.deadline_official
    assert project.deadline_official.isoformat() == "2026-11-20T19:59:59+00:00"  # 23:59:59 по Дубаю
    moscow = timezone(
        timedelta(hours=3)
    )  # UTC+3 круглый год, как и Дубай +4 — без перехода на лето
    assert project.deadline_official.astimezone(moscow).isoformat() == "2026-11-20T22:59:59+03:00"
    assert project.storage_limit_gb == 5  # тариф Amvera


def test_projects_seed_is_idempotent(db):
    projects.ensure_default_project(db)
    projects.ensure_default_project(db)
    assert db.query(models.Project).count() == 1


def test_status_values_match_excel_tracker():
    assert values(Status) == ("not_started", "in_progress", "review", "rework", "done", "cut")


def test_check_constraints_reject_unknown_values(db):
    db.add(models.Scene(project_id=1, number=1, order=1, title="x", status="сломано"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_naive_datetime_is_refused():
    from datetime import datetime

    with pytest.raises(ValueError, match="часового пояса"):
        database.UTCDateTime().process_bind_param(datetime(2026, 11, 18), None)


def test_foreign_key_to_missing_user_is_refused(db):
    db.add(models.Task(project_id=1, code="T-1", title="x", created_by=424242))
    with pytest.raises((IntegrityError, sqlite3.IntegrityError)):
        db.flush()

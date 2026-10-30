"""Миграция 0002 на заполненной базе этапа 0: данные не теряются, справочники переименованы."""

import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command

NOW = "2026-10-30 00:00:00"


def _cfg() -> Config:
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg


def test_0002_renames_placeholder_values_and_enforces_new_checks(env):
    (env / "db").mkdir(parents=True)
    cfg = _cfg()
    command.upgrade(cfg, "0001")

    path = env / "db" / "app.sqlite"
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "insert into project(id,title,title_en,contest,deadline_official,deadline_internal,fps,"
        "width,height,target_min_sec,target_max_sec,storage_limit_gb,created_at,updated_at)"
        " values (1,'t','t','c',?,?,24,1920,1080,300,420,10,?,?)",
        (NOW, NOW, NOW, NOW),
    )
    db.execute(
        'insert into scene(project_id,number,"order",title,status,planned_sec,'
        "created_at,updated_at) values (1,1,1,'S','not_started',25,?,?)",
        (NOW, NOW),
    )
    for i, (size, tool, stage) in enumerate(
        [
            ("close", "kling", "post"),
            ("extreme_close", "seedance", "selection"),
            ("insert", "other", "final"),
        ],
        start=1,
    ):
        db.execute(
            'insert into shot(project_id,scene_id,code,"order",size,tool,stage,status,duration_sec,'
            "takes_count,created_at,updated_at) values (1,1,?,?,?,?,?,'not_started',3,0,?,?)",
            (f"01.0{i}", i, size, tool, stage, NOW, NOW),
        )
    db.execute(
        "insert into task(project_id,code,block,title,status,created_at,updated_at)"
        " values (1,'T-1','Монтаж','a','not_started',?,?),(1,'T-2','своё','b','not_started',?,?)",
        (NOW, NOW, NOW, NOW),
    )
    db.commit()
    db.close()

    command.upgrade(cfg, "head")

    db = sqlite3.connect(path)
    shots = db.execute("select code,size,tool,stage from shot order by code").fetchall()
    assert shots == [
        ("01.01", "close", "other_video", "in_edit"),
        ("01.02", "detail", "seedance", "take_selection"),
        ("01.03", None, "other_video", "final"),
    ]
    assert db.execute("select code,block from task order by code").fetchall() == [
        ("T-1", "editing"),
        ("T-2", None),
    ]
    assert db.execute("pragma foreign_key_check").fetchall() == []
    for bad in (
        "update shot set size='extreme_wide'",
        "update task set block='nope'",
    ):
        try:
            db.execute(bad)
        except sqlite3.IntegrityError:
            continue
        raise AssertionError(f"ограничение не сработало: {bad}")

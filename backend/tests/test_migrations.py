"""Миграции на заполненной базе: 0002 не теряет данные и переименовывает справочники, 0003 меняет лимит диска."""

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


def _head() -> str:
    """Последняя миграция: тесты проверяют «база дошла до конца», а не конкретный номер."""
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(_cfg()).get_current_head()
    assert head is not None
    return head


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


def test_0003_replaces_only_the_untouched_10gb_placeholder(env):
    (env / "db").mkdir(parents=True)
    cfg = _cfg()
    command.upgrade(cfg, "0002")

    path = env / "db" / "app.sqlite"
    db = sqlite3.connect(path)
    for project_id, limit in ((1, 10), (2, 8)):  # заглушка этапа 0 и лимит, поправленный вручную
        db.execute(
            "insert into project(id,title,title_en,contest,deadline_official,deadline_internal,fps,"
            "width,height,target_min_sec,target_max_sec,storage_limit_gb,created_at,updated_at)"
            " values (?,'t','t','c',?,?,24,1920,1080,300,420,?,?,?)",
            (project_id, NOW, NOW, limit, NOW, NOW),
        )
    db.commit()
    db.close()

    command.upgrade(cfg, "head")

    db = sqlite3.connect(path)
    assert db.execute("select id,storage_limit_gb from project order by id").fetchall() == [
        (1, 5.0),
        (2, 8.0),
    ]


# --- 0006: пересоздание `file` и `job` на базе, где на них ссылаются другие таблицы -------------------


def _populated_0005(env: Path) -> Path:
    """База на ревизии 0005 с данными, как на боевом сайте: на файл ссылается вложение, на задачу
    очереди — экспорт. Пустая база (как в прежних тестах) этого не показывала."""
    (env / "db").mkdir(parents=True)
    command.upgrade(_cfg(), "0005")
    path = env / "db" / "app.sqlite"
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "insert into project(id,title,title_en,contest,deadline_official,deadline_internal,fps,"
        "width,height,target_min_sec,target_max_sec,storage_limit_gb,created_at,updated_at)"
        " values (1,'t','t','c',?,?,24,1920,1080,300,420,5,?,?)",
        (NOW, NOW, NOW, NOW),
    )
    db.execute(
        "insert into file(id,project_id,kind,source,version_no,is_current,uploaded_at,"
        "original_name,path) values (1,1,'image','upload',1,1,?,'a.png','000001/original.png')",
        (NOW,),
    )
    db.execute(
        "insert into attachment(file_id,entity_type,entity_id,purpose,created_at)"
        " values (1,'shot',1,'reference',?)",
        (NOW,),
    )
    db.execute(
        "insert into job(id,type,payload,status,progress,created_at)"
        " values (1,'export','{}','done',1,?)",
        (NOW,),
    )
    db.execute(
        "insert into export_job(project_id,target,scope,options,created_at,job_id)"
        " values (1,'resolve','all','{}',?,1)",
        (NOW,),
    )
    db.commit()
    db.close()
    return path


def test_0006_runs_on_a_database_where_other_tables_point_at_file_and_job(env):
    path = _populated_0005(env)
    command.upgrade(_cfg(), "head")

    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    assert db.execute("select version_num from alembic_version").fetchone() == (_head(),)  # head
    # данные на месте, ссылки целы
    assert db.execute("select id, original_name, no_compress from file").fetchall() == [
        (1, "a.png", 0)
    ]
    assert db.execute("select file_id from attachment").fetchall() == [(1,)]
    assert db.execute("select job_id from export_job").fetchall() == [(1,)]
    assert db.execute("pragma foreign_key_check").fetchall() == []
    # новые поля и новый тип задачи работают, проверка значений на месте
    db.execute("update file set compress_state='done', original_size_bytes=10 where id=1")
    db.execute(
        "insert into job(type,payload,status,progress,created_at)"
        " values ('compress','{}','queued',0,?)",
        (NOW,),
    )
    for bad in (
        "update file set compress_state='nonsense' where id=1",
        "insert into job(type,payload,status,progress,created_at)"
        " values ('nonsense','{}','queued',0,'" + NOW + "')",
    ):
        try:
            db.execute(bad)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError(f"CHECK не сработал: {bad}")
    # и внешние ключи по-прежнему охраняются
    try:
        db.execute(
            "insert into attachment(file_id,entity_type,entity_id,purpose,created_at)"
            " values (999,'shot',1,'reference',?)",
            (NOW,),
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("внешний ключ перестал работать")
    db.close()


def test_a_leftover_from_a_failed_migration_does_not_block_the_next_start(env):
    """После сбоя пересоздания в базе остаётся `_alembic_tmp_<таблица>`: следующий запуск падал бы
    «table already exists» бесконечно (так и случилось на боевом сайте)."""
    path = _populated_0005(env)
    db = sqlite3.connect(path)
    db.execute("create table _alembic_tmp_file (id integer primary key)")
    db.execute("create table _alembic_tmp_job (id integer primary key)")
    db.commit()
    db.close()

    command.upgrade(_cfg(), "head")

    db = sqlite3.connect(path)
    assert db.execute("select version_num from alembic_version").fetchone() == (_head(),)  # head
    left = db.execute("select name from sqlite_master where name like '_alembic_tmp%'").fetchall()
    assert left == []
    assert db.execute("select count(*) from file").fetchone() == (1,)


def test_app_connections_keep_foreign_keys_on_after_migrating(env):
    from app import db as database
    from app.migrate import upgrade_to_head

    _populated_0005(env)
    engine = database.init_engine()
    with engine.begin() as conn:  # так миграции запускают тесты и скрипты: на чужом соединении
        upgrade_to_head(conn)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


# --- 0007: проекты получают адрес и чат, участники — роль на паре «человек + проект» ------------------


def _populated_0006(env: Path) -> Path:
    path = _populated_0005(env)
    command.upgrade(_cfg(), "0006")
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("update project set title_en='The Brass Spyglass: Битва!' where id=1")
    for uid, name, role, color, revoked in (
        (1, "Артём", "owner", "#aa0000", None),
        (2, "Лена", "team", "#00aa00", None),
        (3, "Игорь", "director", "#0000aa", NOW),
    ):
        db.execute(
            "insert into user(id,tg_id,name,color,role,created_at,updated_at,access_revoked_at)"
            " values (?,?,?,?,?,?,?,?)",
            (uid, 100 + uid, name, color, role, NOW, NOW, revoked),
        )
    db.commit()
    db.close()
    return path


def test_0007_gives_projects_slugs_and_turns_users_into_members(env):
    path = _populated_0006(env)
    command.upgrade(_cfg(), "head")

    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    assert db.execute("select version_num from alembic_version").fetchone() == (_head(),)
    assert db.execute("select slug, tg_chat_id, archived_at from project").fetchall() == [
        ("the-brass-spyglass", None, None)
    ]
    members = db.execute(
        "select user_id, role, color, active from project_member order by user_id"
    ).fetchall()
    assert members == [
        (1, "owner", "#aa0000", 1),
        (2, "team", "#00aa00", 1),
        (3, "director", "#0000aa", 0),  # вышедший остаётся записью, но не активен
    ]
    assert db.execute("pragma foreign_key_check").fetchall() == []
    # у файлов и вложений всё на месте
    assert db.execute("select count(*) from file").fetchone() == (1,)
    assert db.execute("select count(*) from attachment").fetchone() == (1,)
    # адрес и чат уникальны, роль проверяется
    for bad in (
        "insert into project(title,title_en,contest,deadline_official,deadline_internal,fps,width,"
        "height,target_min_sec,target_max_sec,storage_limit_gb,created_at,updated_at,slug)"
        f" values ('a','a','c','{NOW}','{NOW}',24,1,1,1,2,5,'{NOW}','{NOW}','the-brass-spyglass')",
        "insert into project_member(project_id,user_id,role,color,active,joined_at,created_at,"
        f"updated_at) values (1,1,'owner','#000000',1,'{NOW}','{NOW}','{NOW}')",  # дубль пары
        "insert into project_member(project_id,user_id,role,color,active,joined_at,created_at,"
        f"updated_at) values (1,3,'nonsense','#000000',1,'{NOW}','{NOW}','{NOW}')",
    ):
        try:
            db.execute(bad)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError(f"ограничение не сработало: {bad[:60]}")
    db.close()


def test_0007_gives_distinct_slugs_when_names_collide_or_are_not_latin(env):
    path = _populated_0006(env)
    db = sqlite3.connect(path)
    for pid, title in ((2, "Битва"), (3, "Битва")):
        db.execute(
            "insert into project(id,title,title_en,contest,deadline_official,deadline_internal,fps,"
            "width,height,target_min_sec,target_max_sec,storage_limit_gb,created_at,updated_at)"
            " values (?,?,?,'c',?,?,24,1,1,1,2,5,?,?)",
            (pid, title, title, NOW, NOW, NOW, NOW),
        )
    db.commit()
    db.close()
    command.upgrade(_cfg(), "head")
    db = sqlite3.connect(path)
    slugs = [r[0] for r in db.execute("select slug from project order by id")]
    assert slugs == ["the-brass-spyglass", "project-2", "project-3"]
    db.close()


# --- 0008: у уведомления появляется проект ------------------------------------------------------------


def _notification(db: sqlite3.Connection, nid: int, user_id: int, kind: str = "comment") -> None:
    db.execute(
        "insert into notification(id,user_id,actor_id,kind,entity_type,entity_id,count,snippet,"
        "created_at,read_at) values (?,?,NULL,?,'shot',5,2,'привет',?,NULL)",
        (nid, user_id, kind, NOW),
    )


def test_0008_attaches_existing_notifications_to_the_first_project(env):
    path = _populated_0006(env)
    command.upgrade(_cfg(), "0007")
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "insert into project(id,title,title_en,contest,deadline_official,deadline_internal,fps,"
        "width,height,target_min_sec,target_max_sec,storage_limit_gb,created_at,updated_at,slug)"
        " values (2,'Второй','Second','c',?,?,24,1,1,1,2,5,?,?,'second')",
        (NOW, NOW, NOW, NOW),
    )
    for nid, uid, kind in ((1, 1, "comment"), (2, 2, "file"), (3, 2, "version")):
        _notification(db, nid, uid, kind)
    db.commit()
    db.close()

    command.upgrade(_cfg(), "head")

    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    assert db.execute(
        "select id, project_id, kind, count, snippet from notification order by id"
    ).fetchall() == [
        (1, 1, "comment", 2, "привет"),
        (2, 1, "file", 2, "привет"),
        (3, 1, "version", 2, "привет"),
    ]
    assert db.execute("pragma foreign_key_check").fetchall() == []
    columns = {r[1]: r for r in db.execute("pragma table_info(notification)")}
    assert columns["project_id"][3] == 1  # NOT NULL
    assert db.execute(
        "select name from sqlite_master where name='ix_notification_project_id'"
    ).fetchone()
    assert db.execute("pragma foreign_key_list(notification)").fetchall()
    # прежние ограничения и индекс на месте, а проект обязателен
    for bad in (
        "insert into notification(user_id,project_id,kind,entity_type,entity_id,count,created_at)"
        f" values (1,1,'nonsense','shot',1,1,'{NOW}')",
        "insert into notification(user_id,project_id,kind,entity_type,entity_id,count,created_at)"
        f" values (1,999,'comment','shot',1,1,'{NOW}')",  # нет такого проекта
        "insert into notification(user_id,kind,entity_type,entity_id,count,created_at)"
        f" values (1,'comment','shot',1,1,'{NOW}')",  # без проекта
    ):
        try:
            db.execute(bad)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError(f"ограничение не сработало: {bad[:70]}")
    assert db.execute("select name from sqlite_master where name='ix_notification_user'").fetchone()
    db.close()


def test_0008_drops_notifications_when_there_is_no_project_to_attach_them_to(env):
    path = _populated_0006(env)
    command.upgrade(_cfg(), "0007")
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=OFF")  # так готовим странное состояние, в рабочей базе его нет
    for table in ("project_member", "project"):
        db.execute(f"delete from {table}")
    _notification(db, 1, 1)
    db.commit()
    db.close()

    command.upgrade(_cfg(), "head")

    db = sqlite3.connect(path)
    assert db.execute("select version_num from alembic_version").fetchone() == (_head(),)
    assert db.execute("select count(*) from notification").fetchone() == (0,)
    db.close()

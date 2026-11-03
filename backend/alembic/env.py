import logging
from logging.config import fileConfig

from sqlalchemy import Connection

from alembic import context
from app import models
from app.config import get_settings
from app.db import db_url, make_engine

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = models.Base.metadata
log = logging.getLogger("alembic.env")


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or db_url(get_settings())


def _drop_batch_leftovers(connection: Connection) -> None:
    """Пересоздание таблицы идёт через `_alembic_tmp_<имя>`. Если оно оборвалось, временная таблица
    остаётся в базе, и каждый следующий запуск падал бы «table already exists». В нормальной работе
    таких таблиц нет (приложение одно), так что их можно сносить."""
    names = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master"
        " WHERE type='table' AND name LIKE '\\_alembic\\_tmp\\_%' ESCAPE '\\'"
    ).scalars()
    for name in list(names):
        log.warning("удаляю остаток прерванной миграции: %s", name)
        connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{name}"')


def _migrate(connection: Connection) -> None:
    sqlite = connection.dialect.name == "sqlite"
    if sqlite:
        # Пересоздание таблицы (DROP TABLE + RENAME) при включённых внешних ключах падает, если на
        # таблицу ссылаются строки других таблиц (так упала 0006: на `file` ссылаются вложения). Так
        # что на время миграции проверку выключаем, как велит документация SQLite: PRAGMA действует
        # только вне транзакции, поэтому до первой записи; а после смотрим `foreign_key_check`.
        # Приложение включает проверку на каждом соединении само (db.py).
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _drop_batch_leftovers(connection)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # ALTER в SQLite только через пересоздание таблицы
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
    if sqlite:
        broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if broken:  # не роняем запуск: данные целы, но человеку стоит об этом знать
            log.warning("после миграции в базе есть строки с битыми ссылками: %s", len(broken))


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _migrate(connection)
        return
    get_settings().ensure_dirs()
    engine = make_engine(_url())
    with engine.connect() as conn:
        _migrate(conn)
        conn.commit()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

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


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or db_url(get_settings())


def _migrate(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # ALTER в SQLite только через пересоздание таблицы
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


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

"""Миграции Alembic при старте приложения."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import Connection

from alembic import command

ALEMBIC_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = ALEMBIC_DIR / "alembic.ini"


def _config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade_to_head(connection: Connection | None = None) -> None:
    cfg = _config()
    if connection is not None:
        cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")

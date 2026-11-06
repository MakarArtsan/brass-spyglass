"""Кто собирает медиа чата проекта: юзербот или бот

Revision ID: 0011
Revises: 0010

У проекта появляется `collector`. Все существующие проекты — `userbot`: фильм собран юзерботом с
историей, и это не меняется. Код приложения не импортируется (см. 0001): значения списка записаны
здесь же. Таблица пересоздаётся (`batch_alter_table`), поэтому миграция проверяется на базе с данными,
где на `project` ссылаются другие таблицы (`test_migrations.py`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column("collector", sa.String(length=8), nullable=False, server_default="userbot")
        )
        batch.create_check_constraint("collector", "collector IN ('userbot', 'bot')")


def downgrade() -> None:
    raise NotImplementedError("Откат 0011 не поддерживается")

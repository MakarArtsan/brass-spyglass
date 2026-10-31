"""Индекс Telegram: состояние чтения тем, имя файла и адрес ссылки у медиа

Revision ID: 0004
Revises: 0003

Только добавление столбцов с умолчанием: данные не меняются, миграция обратима по смыслу, но откат
не поддерживается (как и в 0002/0003). Код приложения не импортируется (см. 0001).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tg_topic") as batch:
        batch.add_column(
            sa.Column("history_complete", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
        batch.add_column(sa.Column("oldest_message_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("tg_media") as batch:
        batch.add_column(sa.Column("file_name", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("url", sa.String(length=2000), nullable=True))


def downgrade() -> None:
    raise NotImplementedError("Откат 0004 не поддерживается")

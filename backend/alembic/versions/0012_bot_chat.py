"""Чаты, подключённые боту командой /connect

Revision ID: 0012
Revises: 0011

Новая таблица, данные не затрагиваются. Код приложения не импортируется (см. 0001): время — обычный
`sa.DateTime`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_chat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("connected_by_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("bot_admin", sa.Boolean(), nullable=False),
        sa.Column("forum", sa.Boolean(), nullable=False),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_chat")),
        sa.UniqueConstraint("chat_id", name=op.f("uq_bot_chat_chat_id")),
    )
    with op.batch_alter_table("bot_chat") as batch:
        batch.create_index(
            batch.f("ix_bot_chat_connected_by_tg_id"), ["connected_by_tg_id"], unique=False
        )


def downgrade() -> None:
    raise NotImplementedError("Откат 0012 не поддерживается")

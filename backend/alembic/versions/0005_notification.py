"""Уведомления на сайте: кто-то оставил комментарий или добавил файл на карточку

Revision ID: 0005
Revises: 0004

Новая таблица, данные не затрагиваются. Код приложения не импортируется (см. 0001): время — обычный
`sa.DateTime`, как и в остальных таблицах (UTC без tzinfo, оболочку над ним даёт приложение).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("snippet", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('comment', 'file', 'version')", name=op.f("ck_notification_kind")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["user.id"], name=op.f("fk_notification_actor_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_notification_user_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification")),
    )
    with op.batch_alter_table("notification") as batch:
        batch.create_index("ix_notification_user", ["user_id", "read_at", "id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Откат 0005 не поддерживается")

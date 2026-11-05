"""Подтверждение проектов: пока суперадмин не подтвердил, команда не загружает файлы

Revision ID: 0009
Revises: 0008

У проекта появляются `approved_at` (когда подтвердили) и `approved_by` (кто). Все существующие проекты
считаются подтверждёнными (дата подтверждения — дата создания): работа фильма не меняется. Новые проекты,
которые заводят не суперадмины, ждут подтверждения. Код приложения не импортируется (см. 0001).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("approved_by", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_project_approved_by_user"), "user", ["approved_by"], ["id"]
        )
    op.execute("UPDATE project SET approved_at = created_at WHERE approved_at IS NULL")


def downgrade() -> None:
    raise NotImplementedError("Откат 0009 не поддерживается")

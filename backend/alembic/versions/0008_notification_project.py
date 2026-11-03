"""Мультипроектность, шаг 2: у уведомления есть проект

Revision ID: 0008
Revises: 0007

Уведомление ведёт на карточку конкретного проекта, поэтому человек, состоящий в двух проектах, не должен
видеть в одном проекте уведомления другого. Существующие уведомления относятся к существующему проекту.
Код приложения не импортируется (см. 0001).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification") as batch:
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE notification SET project_id = (SELECT id FROM project ORDER BY id LIMIT 1)"
        " WHERE project_id IS NULL"
    )
    # Уведомление без проекта (проекта в базе нет вовсе) не нужно: оно ни к чему не ведёт.
    op.execute("DELETE FROM notification WHERE project_id IS NULL")
    with op.batch_alter_table("notification") as batch:
        batch.alter_column("project_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            op.f("fk_notification_project_id_project"), "project", ["project_id"], ["id"]
        )
        batch.create_index("ix_notification_project_id", ["project_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Откат 0008 не поддерживается")

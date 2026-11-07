"""Коллажи: таблицы `collage` и `collage_photo`

Revision ID: 0013
Revises: 0012

Новые таблицы, данные не затрагиваются. Код приложения не импортируется (см. 0001): время — обычный
`sa.DateTime`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"], name=op.f("fk_collage_created_by_user")
        ),
        sa.ForeignKeyConstraint(["file_id"], ["file.id"], name=op.f("fk_collage_file_id_file")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_collage_project_id_project")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collage")),
    )
    with op.batch_alter_table("collage") as batch:
        batch.create_index(batch.f("ix_collage_project_id"), ["project_id"], unique=False)
    op.create_table(
        "collage_photo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collage_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collage_id"], ["collage.id"], name=op.f("fk_collage_photo_collage_id_collage")
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["file.id"], name=op.f("fk_collage_photo_file_id_file")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collage_photo")),
        sa.UniqueConstraint("collage_id", "position", name=op.f("uq_collage_photo_collage_id")),
    )
    with op.batch_alter_table("collage_photo") as batch:
        batch.create_index(batch.f("ix_collage_photo_collage_id"), ["collage_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Откат 0013 не поддерживается")

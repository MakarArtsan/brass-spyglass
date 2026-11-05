"""Импорт сценария: таблица `import_run`

Revision ID: 0010
Revises: 0009

Новая таблица, данные не затрагиваются: исходный текст ответа LLM, кто и когда импортировал, сколько
создано. Код приложения не импортируется (см. 0001): время — обычный `sa.DateTime`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=True),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("created", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"], name=op.f("fk_import_run_created_by_user")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_import_run_project_id_project")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_run")),
    )
    with op.batch_alter_table("import_run") as batch:
        batch.create_index(batch.f("ix_import_run_project_id"), ["project_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Откат 0010 не поддерживается")

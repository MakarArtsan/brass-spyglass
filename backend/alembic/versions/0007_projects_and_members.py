"""Мультипроектность, шаг 1: адрес проекта, чат проекта, участники проекта

Revision ID: 0007
Revises: 0006

У проекта появляются `slug` (адрес `/p/<slug>`), `tg_chat_id` (закрытый чат команды) и `archived_at`.
Новая таблица `project_member`: роль и цвет человека хранятся на паре «человек + проект». Все
существующие участники становятся участниками существующих проектов с теми же ролью и цветом, так
что на работе сайта ничего не меняется. Код приложения не импортируется (см. 0001).
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("owner", "director", "team", "guest")


def _slug(text: str, fallback: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return base[:60] or fallback


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("slug", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("tg_chat_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))

    bind = op.get_bind()
    taken: set[str] = set()
    for project_id, title_en in bind.execute(
        sa.text("SELECT id, title_en FROM project ORDER BY id")
    ):
        slug = _slug(title_en, f"project-{project_id}")
        if slug in taken:
            slug = f"{slug}-{project_id}"
        taken.add(slug)
        bind.execute(
            sa.text("UPDATE project SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": project_id},
        )

    with op.batch_alter_table("project") as batch:
        batch.alter_column("slug", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint(op.f("uq_project_slug"), ["slug"])
        batch.create_unique_constraint(op.f("uq_project_tg_chat_id"), ["tg_chat_id"])

    op.create_table(
        "project_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("color", sa.String(length=9), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("left_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('" + "', '".join(ROLES) + "')", name=op.f("ck_project_member_role")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_project_member_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_project_member_user_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_member")),
        sa.UniqueConstraint("project_id", "user_id", name=op.f("uq_project_member_project_id")),
    )
    with op.batch_alter_table("project_member") as batch:
        batch.create_index("ix_project_member_project_id", ["project_id"], unique=False)
        batch.create_index("ix_project_member_user", ["user_id", "active"], unique=False)

    # Все нынешние участники — участники существующих проектов, с теми же ролью и цветом.
    op.execute(
        """
        INSERT INTO project_member
            (project_id, user_id, role, color, active, joined_at, left_at, created_at, updated_at)
        SELECT p.id, u.id, u.role, u.color,
               CASE WHEN u.access_revoked_at IS NULL THEN 1 ELSE 0 END,
               u.created_at, u.access_revoked_at, u.created_at, u.updated_at
        FROM project p CROSS JOIN "user" u
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Откат 0007 не поддерживается")

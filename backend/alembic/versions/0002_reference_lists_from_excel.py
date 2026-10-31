"""Справочники по листу «Справочник» Excel, новые поля сцены/шота/сетапа, блок задач

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Новые значения справочников (slug'и; тексты из Excel — в app/constants.py).
SHOT_SIZE = ("wide", "medium", "close", "detail", "pov_spyglass", "split_mirror")
TOOL = ("seedance", "other_video", "ai_image", "blender_3d", "graphics", "live_action")
STAGE = (
    "storyboard", "blockout", "prompt", "generation", "take_selection", "in_edit", "final",
)  # fmt: skip
ASSET_TYPE = (
    "character", "crowd", "animal", "prop", "faux_prop", "location", "ship", "effect", "style",
)  # fmt: skip
SOUND_TYPE = ("dialogue", "sfx", "music", "silence", "ambience")
TASK_BLOCK = ("contest", "preproduction", "generation", "editing", "sound", "delivery")

# Заглушечные значения этапа 0 → значения из Excel (то, чему нет пары, станет пустым).
OLD_TO_NEW = {
    ("shot", "size"): {"extreme_wide": None, "extreme_close": "detail", "insert": None},
    ("shot", "tool"): {"kling": "other_video", "veo": "other_video", "runway": "other_video",
                       "other": "other_video"},
    ("shot", "stage"): {"selection": "take_selection", "post": "in_edit"},
    ("asset", "type"): {"other": "prop"},
}  # fmt: skip

TASK_BLOCK_BY_LABEL = {
    "Конкурс": "contest", "Препродакшн": "preproduction", "Генерация": "generation",
    "Монтаж": "editing", "Звук": "sound", "Сдача": "delivery",
}  # fmt: skip


def _in(column: str, values: tuple[str, ...], nullable: bool) -> str:
    items = ", ".join(f"'{v}'" for v in values)
    expr = f"{column} IN ({items})"
    return f"{column} IS NULL OR {expr}" if nullable else expr


def _remap_values() -> None:
    bind = op.get_bind()
    for (table, column), mapping in OLD_TO_NEW.items():
        for old, new in mapping.items():
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"),
                {"new": new, "old": old},
            )
    for label, slug in TASK_BLOCK_BY_LABEL.items():
        bind.execute(
            sa.text("UPDATE task SET block = :s WHERE block = :l"), {"s": slug, "l": label}
        )
    allowed = ", ".join(f"'{v}'" for v in TASK_BLOCK)
    bind.execute(sa.text(f"UPDATE task SET block = NULL WHERE block NOT IN ({allowed})"))


def upgrade() -> None:
    # 1. Снимаем старые CHECK (иначе новые значения не пройдут), 2. переименовываем данные,
    # 3. ставим новые CHECK. Каждый batch_alter_table пересоздаёт таблицу — SQLite иначе не умеет.
    for table, names in {
        "shot": ("ck_shot_size", "ck_shot_tool", "ck_shot_stage"),
        "asset": ("ck_asset_type",),
        "sound_cue": ("ck_sound_cue_type",),
    }.items():
        with op.batch_alter_table(table) as batch:
            for name in names:
                batch.drop_constraint(op.f(name), type_="check")

    _remap_values()

    with op.batch_alter_table("scene") as batch:
        batch.add_column(sa.Column("characters", sa.Text(), nullable=True))
        batch.add_column(sa.Column("key_assets", sa.Text(), nullable=True))
        batch.add_column(sa.Column("lines_en", sa.Text(), nullable=True))

    with op.batch_alter_table("shot") as batch:
        batch.add_column(sa.Column("sound_note", sa.Text(), nullable=True))
        batch.create_check_constraint(op.f("ck_shot_size"), _in("size", SHOT_SIZE, True))
        batch.create_check_constraint(op.f("ck_shot_tool"), _in("tool", TOOL, True))
        batch.create_check_constraint(op.f("ck_shot_stage"), _in("stage", STAGE, True))

    with op.batch_alter_table("asset") as batch:
        batch.create_check_constraint(op.f("ck_asset_type"), _in("type", ASSET_TYPE, False))

    with op.batch_alter_table("sound_cue") as batch:
        batch.create_check_constraint(op.f("ck_sound_cue_type"), _in("type", SOUND_TYPE, False))

    with op.batch_alter_table("task") as batch:
        batch.alter_column("block", existing_type=sa.String(length=200), type_=sa.String(length=16))
        batch.create_check_constraint(op.f("ck_task_block"), _in("block", TASK_BLOCK, True))

    with op.batch_alter_table("setup_payoff") as batch:
        batch.add_column(sa.Column("number", sa.Integer(), nullable=True))
    op.create_index(
        "uq_setup_payoff_number",
        "setup_payoff",
        ["project_id", "number"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    raise NotImplementedError("Откат 0002 не поддерживается: справочники необратимо переименованы")

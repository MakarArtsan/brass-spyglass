"""Сжатие картинок при загрузке: поля файла и тип задачи `compress`

Revision ID: 0006
Revises: 0005

У файла появляются отметка «Без сжатия», итог сжатия, размер и путь оригинала (он лежит 7 дней в
/data/originals). В очереди — новый тип задачи. Код приложения не импортируется (см. 0001).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_TYPES = ("preview", "proxy", "waveform", "tg_import", "export", "backup", "compress")
COMPRESS_STATES = ("done", "small_gain", "failed")


def _in(column: str, values: tuple[str, ...], nullable: bool = False) -> str:
    expr = f"{column} IN ({', '.join(repr(v) for v in values)})"
    return f"{column} IS NULL OR {expr}" if nullable else expr


def upgrade() -> None:
    with op.batch_alter_table("file") as batch:
        batch.add_column(
            sa.Column("no_compress", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
        batch.add_column(sa.Column("compress_state", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("compressed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("original_size_bytes", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("original_path", sa.String(length=1000), nullable=True))
        batch.create_check_constraint(
            op.f("ck_file_compress_state"), _in("compress_state", COMPRESS_STATES, nullable=True)
        )
    with op.batch_alter_table("job") as batch:
        batch.drop_constraint(op.f("ck_job_type"), type_="check")
        batch.create_check_constraint(op.f("ck_job_type"), _in("type", JOB_TYPES))


def downgrade() -> None:
    raise NotImplementedError("Откат 0006 не поддерживается")

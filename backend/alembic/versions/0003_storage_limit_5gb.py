"""Лимит диска /data: тариф Amvera даёт 5 ГБ вместо заглушки в 10 ГБ

Revision ID: 0003
Revises: 0002

Только данные, схема не меняется. Заменяется нетронутая заглушка этапа 0 (10 ГБ): если лимит
уже поправили вручную, он остаётся как есть. Код приложения не импортируется (см. 0001).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE project SET storage_limit_gb = 5 WHERE storage_limit_gb = 10"))


def downgrade() -> None:
    raise NotImplementedError("Откат 0003 не поддерживается: неизвестно, какие лимиты были 10 ГБ")

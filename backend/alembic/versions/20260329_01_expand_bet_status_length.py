from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260329_01"
down_revision = "20260328_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "bet",
        "status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
        existing_server_default=sa.text("'PLACED'"),
    )


def downgrade() -> None:
    op.alter_column(
        "bet",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
        existing_server_default=sa.text("'PLACED'"),
    )

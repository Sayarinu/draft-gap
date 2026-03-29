from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260328_02"
down_revision = "20260328_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bet", sa.Column("market_type", sa.String(length=32), nullable=False, server_default="match_winner"))
    op.add_column("bet", sa.Column("selection_key", sa.String(length=64), nullable=False, server_default="team_a"))
    op.add_column("bet", sa.Column("line_value", sa.Numeric(6, 2), nullable=True))
    op.add_column("bet", sa.Column("source_book", sa.String(length=32), nullable=False, server_default="thunderpick"))
    op.add_column("bet", sa.Column("source_market_name", sa.String(length=255), nullable=True))
    op.add_column("bet", sa.Column("source_selection_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("bet", "source_selection_name")
    op.drop_column("bet", "source_market_name")
    op.drop_column("bet", "source_book")
    op.drop_column("bet", "line_value")
    op.drop_column("bet", "selection_key")
    op.drop_column("bet", "market_type")

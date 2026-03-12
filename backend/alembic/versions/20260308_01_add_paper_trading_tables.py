
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260308_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
    op.create_table(
        "bankroll",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("initial_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("staking_model", sa.String(length=32), nullable=False, server_default=sa.text("'kelly_quarter'")),
        sa.Column("kelly_fraction", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.250")),
        sa.Column("max_bet_pct", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.0500")),
        sa.Column("min_edge_threshold", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.0300")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_bankroll_name", "bankroll", ["name"], unique=False)

    op.create_table(
        "bet",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("bankroll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pandascore_match_id", sa.Integer(), nullable=False),
        sa.Column("model_run_id", sa.Integer(), nullable=True),
        sa.Column("team_a", sa.String(length=255), nullable=False),
        sa.Column("team_b", sa.String(length=255), nullable=False),
        sa.Column("league", sa.String(length=255), nullable=True),
        sa.Column("series_format", sa.String(length=8), nullable=True),
        sa.Column("bet_on", sa.String(length=255), nullable=False),
        sa.Column("model_prob", sa.Numeric(6, 5), nullable=False),
        sa.Column("book_odds_locked", sa.Numeric(8, 4), nullable=False),
        sa.Column("book_prob_adj", sa.Numeric(6, 5), nullable=False),
        sa.Column("edge", sa.Numeric(6, 5), nullable=False),
        sa.Column("ev", sa.Numeric(12, 4), nullable=False),
        sa.Column("recommended_stake", sa.Numeric(12, 2), nullable=False),
        sa.Column("actual_stake", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'PLACED'")),
        sa.Column("profit_loss", sa.Numeric(12, 2), nullable=True),
        sa.Column("closing_odds", sa.Numeric(8, 4), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["bankroll_id"], ["bankroll.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_run_id"], ["ml_model_run.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pandascore_match_id"),
    )
    op.create_index("ix_bet_status_placed", "bet", ["status", "placed_at"], unique=False)
    op.create_index("ix_bet_bankroll_status", "bet", ["bankroll_id", "status"], unique=False)

    op.create_table(
        "bankroll_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("bankroll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_bets", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("wins", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("losses", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("roi_pct", sa.Numeric(8, 5), nullable=False, server_default=sa.text("0.00000")),
        sa.Column("peak_balance", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["bankroll_id"], ["bankroll.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bankroll_snapshot_bankroll_id", "bankroll_snapshot", ["bankroll_id"], unique=False)
    op.create_index("ix_bankroll_snapshot_snapshot_at", "bankroll_snapshot", ["snapshot_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bankroll_snapshot_snapshot_at", table_name="bankroll_snapshot")
    op.drop_index("ix_bankroll_snapshot_bankroll_id", table_name="bankroll_snapshot")
    op.drop_table("bankroll_snapshot")
    op.drop_index("ix_bet_bankroll_status", table_name="bet")
    op.drop_index("ix_bet_status_placed", table_name="bet")
    op.drop_table("bet")
    op.drop_index("ix_bankroll_name", table_name="bankroll")
    op.drop_table("bankroll")

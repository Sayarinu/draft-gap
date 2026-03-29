from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260328_01"
down_revision = "20260327_01"
branch_labels = None
depends_on = None


def _drop_match_id_unique_constraint() -> None:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = current_schema()
              AND tc.table_name = 'bet'
              AND tc.constraint_type = 'UNIQUE'
              AND kcu.column_name = 'pandascore_match_id'
            """
        )
    )
    for constraint_name in {row[0] for row in result if row[0]}:
        op.drop_constraint(constraint_name, "bet", type_="unique")


def upgrade() -> None:
    op.add_column("bet", sa.Column("series_key", sa.String(length=255), nullable=True))
    op.add_column("bet", sa.Column("bet_sequence", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("bet", sa.Column("entry_phase", sa.String(length=32), nullable=False, server_default="prematch"))
    op.add_column("bet", sa.Column("entry_score_team_a", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("bet", sa.Column("entry_score_team_b", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("bet", sa.Column("current_score_team_a", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("bet", sa.Column("current_score_team_b", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("bet", sa.Column("odds_source_status", sa.String(length=16), nullable=False, server_default="available"))
    op.add_column("bet", sa.Column("feed_health_status", sa.String(length=32), nullable=False, server_default="tracked"))
    op.add_column("bet", sa.Column("live_rebet_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("bet", sa.Column("model_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.execute("UPDATE bet SET series_key = CONCAT('ps:', pandascore_match_id::text) WHERE series_key IS NULL")
    op.alter_column("bet", "series_key", nullable=False)

    _drop_match_id_unique_constraint()
    op.create_index("ix_bet_match_status", "bet", ["pandascore_match_id", "status"], unique=False)
    op.create_index("ix_bet_series_key_status", "bet", ["series_key", "status", "placed_at"], unique=False)

    op.create_table(
        "bet_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("bankroll_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pandascore_match_id", sa.Integer(), nullable=False),
        sa.Column("series_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("amount_delta", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["bankroll_id"], ["bankroll.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bet_id"], ["bet.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bet_event_bankroll_id", "bet_event", ["bankroll_id"], unique=False)
    op.create_index("ix_bet_event_bet_id", "bet_event", ["bet_id"], unique=False)
    op.create_index("ix_bet_event_pandascore_match_id", "bet_event", ["pandascore_match_id"], unique=False)
    op.create_index("ix_bet_event_series_key", "bet_event", ["series_key"], unique=False)
    op.create_index("ix_bet_event_event_type", "bet_event", ["event_type"], unique=False)
    op.create_index("ix_bet_event_created_at", "bet_event", ["created_at"], unique=False)
    op.create_index("ix_bet_event_series_created", "bet_event", ["series_key", "created_at"], unique=False)
    op.create_index("ix_bet_event_bankroll_created", "bet_event", ["bankroll_id", "created_at"], unique=False)

    op.execute(
        """
        INSERT INTO bet_event (
            bankroll_id,
            bet_id,
            pandascore_match_id,
            series_key,
            event_type,
            amount_delta,
            payload_json,
            created_at
        )
        SELECT
            bankroll_id,
            id,
            pandascore_match_id,
            series_key,
            CASE
                WHEN status IN ('WON', 'LOST') THEN 'legacy_import_settled'
                ELSE 'legacy_import_open'
            END,
            CASE
                WHEN status IN ('PLACED', 'LIVE', 'SETTLEMENT_PENDING', 'ORPHANED_FEED') THEN -actual_stake
                WHEN status = 'VOID' THEN 0
                WHEN status = 'WON' THEN COALESCE(profit_loss, 0)
                WHEN status = 'LOST' THEN COALESCE(profit_loss, 0)
                ELSE 0
            END,
            jsonb_build_object('status', status),
            placed_at
        FROM bet
        """
    )


def downgrade() -> None:
    op.drop_index("ix_bet_event_bankroll_created", table_name="bet_event")
    op.drop_index("ix_bet_event_series_created", table_name="bet_event")
    op.drop_index("ix_bet_event_created_at", table_name="bet_event")
    op.drop_index("ix_bet_event_event_type", table_name="bet_event")
    op.drop_index("ix_bet_event_series_key", table_name="bet_event")
    op.drop_index("ix_bet_event_pandascore_match_id", table_name="bet_event")
    op.drop_index("ix_bet_event_bet_id", table_name="bet_event")
    op.drop_index("ix_bet_event_bankroll_id", table_name="bet_event")
    op.drop_table("bet_event")

    op.drop_index("ix_bet_series_key_status", table_name="bet")
    op.drop_index("ix_bet_match_status", table_name="bet")
    op.create_unique_constraint("bet_pandascore_match_id_key", "bet", ["pandascore_match_id"])

    op.drop_column("bet", "model_snapshot_json")
    op.drop_column("bet", "live_rebet_allowed")
    op.drop_column("bet", "feed_health_status")
    op.drop_column("bet", "odds_source_status")
    op.drop_column("bet", "current_score_team_b")
    op.drop_column("bet", "current_score_team_a")
    op.drop_column("bet", "entry_score_team_b")
    op.drop_column("bet", "entry_score_team_a")
    op.drop_column("bet", "entry_phase")
    op.drop_column("bet", "bet_sequence")
    op.drop_column("bet", "series_key")

"""add homepage snapshot tables

Revision ID: 20260327_01
Revises: 20260308_01
Create Date: 2026-03-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260327_01"
down_revision = "20260308_01"
branch_labels = None
depends_on = None


def _create_snapshot_table(table_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_window_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{table_name}_is_active", table_name, ["is_active"], unique=False)
    op.create_index(f"ix_{table_name}_version", table_name, ["version"], unique=True)
    op.create_index(
        f"ix_{table_name}_active_generated",
        table_name,
        ["is_active", "generated_at"],
        unique=False,
    )


def upgrade() -> None:
    _create_snapshot_table("upcoming_with_odds_snapshot")
    _create_snapshot_table("live_with_odds_snapshot")
    _create_snapshot_table("betting_results_snapshot")
    _create_snapshot_table("bankroll_summary_snapshot")
    _create_snapshot_table("power_rankings_snapshot")
    _create_snapshot_table("homepage_snapshot_manifest")


def _drop_snapshot_table(table_name: str) -> None:
    op.drop_index(f"ix_{table_name}_active_generated", table_name=table_name)
    op.drop_index(f"ix_{table_name}_version", table_name=table_name)
    op.drop_index(f"ix_{table_name}_is_active", table_name=table_name)
    op.drop_table(table_name)


def downgrade() -> None:
    _drop_snapshot_table("homepage_snapshot_manifest")
    _drop_snapshot_table("power_rankings_snapshot")
    _drop_snapshot_table("bankroll_summary_snapshot")
    _drop_snapshot_table("betting_results_snapshot")
    _drop_snapshot_table("live_with_odds_snapshot")
    _drop_snapshot_table("upcoming_with_odds_snapshot")

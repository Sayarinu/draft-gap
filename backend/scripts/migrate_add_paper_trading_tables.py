
from __future__ import annotations

from sqlalchemy import text

from database import engine


def run_migration() -> None:
    statements: list[str] = [
        'CREATE EXTENSION IF NOT EXISTS "pgcrypto";',
        """
        CREATE TABLE IF NOT EXISTS bankroll (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL UNIQUE,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            initial_balance NUMERIC(12,2) NOT NULL,
            current_balance NUMERIC(12,2) NOT NULL,
            staking_model VARCHAR(32) NOT NULL DEFAULT 'kelly_quarter',
            kelly_fraction NUMERIC(4,3) NOT NULL DEFAULT 0.250,
            max_bet_pct NUMERIC(5,4) NOT NULL DEFAULT 0.0500,
            min_edge_threshold NUMERIC(5,4) NOT NULL DEFAULT 0.0300,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_bankroll_name ON bankroll (name);",
        """
        CREATE TABLE IF NOT EXISTS bet (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            bankroll_id UUID NOT NULL REFERENCES bankroll(id) ON DELETE CASCADE,
            pandascore_match_id INTEGER NOT NULL UNIQUE,
            model_run_id INTEGER NULL REFERENCES ml_model_run(id) ON DELETE SET NULL,
            team_a VARCHAR(255) NOT NULL,
            team_b VARCHAR(255) NOT NULL,
            league VARCHAR(255) NULL,
            series_format VARCHAR(8) NULL,
            bet_on VARCHAR(255) NOT NULL,
            model_prob NUMERIC(6,5) NOT NULL,
            book_odds_locked NUMERIC(8,4) NOT NULL,
            book_prob_adj NUMERIC(6,5) NOT NULL,
            edge NUMERIC(6,5) NOT NULL,
            ev NUMERIC(12,4) NOT NULL,
            recommended_stake NUMERIC(12,2) NOT NULL,
            actual_stake NUMERIC(12,2) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'PLACED',
            profit_loss NUMERIC(12,2) NULL,
            closing_odds NUMERIC(8,4) NULL,
            placed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            settled_at TIMESTAMPTZ NULL
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_bet_status_placed ON bet (status, placed_at);",
        "CREATE INDEX IF NOT EXISTS ix_bet_bankroll_status ON bet (bankroll_id, status);",
        """
        CREATE TABLE IF NOT EXISTS bankroll_snapshot (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            bankroll_id UUID NOT NULL REFERENCES bankroll(id) ON DELETE CASCADE,
            snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            balance NUMERIC(12,2) NOT NULL,
            total_bets INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            roi_pct NUMERIC(8,5) NOT NULL DEFAULT 0.00000,
            peak_balance NUMERIC(12,2) NOT NULL
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_bankroll_snapshot_bankroll_id ON bankroll_snapshot (bankroll_id);",
        "CREATE INDEX IF NOT EXISTS ix_bankroll_snapshot_snapshot_at ON bankroll_snapshot (snapshot_at);",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


if __name__ == "__main__":
    run_migration()
    print("Paper-trading tables migration completed.")

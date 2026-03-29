from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from models_ml import (
    Bankroll,
    BankrollSnapshot,
    BankrollSummarySnapshot,
    Bet,
    BettingResultsSnapshot,
    HomepageSnapshotManifest,
    LiveWithOddsSnapshot,
    MLModelRun,
    PowerRankingsSnapshot,
    UpcomingWithOddsSnapshot,
)


def create_bankroll(
    *,
    name: str = "DraftGap Agent",
    initial_balance: Decimal = Decimal("1000.00"),
    current_balance: Decimal = Decimal("1000.00"),
) -> Bankroll:
    return Bankroll(
        name=name,
        currency="USD",
        initial_balance=initial_balance,
        current_balance=current_balance,
        staking_model="kelly_quarter",
        kelly_fraction=Decimal("0.250"),
        max_bet_pct=Decimal("0.0500"),
        min_edge_threshold=Decimal("0.0300"),
    )


def create_snapshot(
    bankroll_id: object,
    *,
    balance: Decimal = Decimal("1000.00"),
    peak_balance: Decimal = Decimal("1100.00"),
    total_bets: int = 0,
    wins: int = 0,
    losses: int = 0,
) -> BankrollSnapshot:
    return BankrollSnapshot(
        bankroll_id=bankroll_id,
        balance=balance,
        total_bets=total_bets,
        wins=wins,
        losses=losses,
        roi_pct=Decimal("0.00000"),
        peak_balance=peak_balance,
    )


def create_bet(
    bankroll_id: object,
    *,
    pandascore_match_id: int,
    model_run_id: int | None = None,
    team_a: str = "Alpha",
    team_b: str = "Beta",
    league: str | None = "LCK",
    bet_on: str = "Alpha",
    market_type: str = "match_winner",
    selection_key: str = "team_a",
    line_value: Decimal | None = None,
    status: str = "PLACED",
    model_prob: Decimal = Decimal("0.60000"),
    book_odds_locked: Decimal = Decimal("2.2000"),
    book_prob_adj: Decimal = Decimal("0.45000"),
    edge: Decimal = Decimal("0.15000"),
    ev: Decimal = Decimal("15.0000"),
    recommended_stake: Decimal = Decimal("50.00"),
    actual_stake: Decimal = Decimal("50.00"),
    profit_loss: Decimal | None = None,
    closing_odds: Decimal | None = None,
    placed_at: datetime | None = None,
    settled_at: datetime | None = None,
) -> Bet:
    return Bet(
        bankroll_id=bankroll_id,
        pandascore_match_id=pandascore_match_id,
        model_run_id=model_run_id,
        team_a=team_a,
        team_b=team_b,
        league=league,
        series_format="BO3",
        series_key=f"ps:{pandascore_match_id}",
        bet_sequence=1,
        entry_phase="prematch",
        entry_score_team_a=0,
        entry_score_team_b=0,
        current_score_team_a=0,
        current_score_team_b=0,
        odds_source_status="available",
        feed_health_status="tracked",
        live_rebet_allowed=False,
        model_snapshot_json=None,
        market_type=market_type,
        selection_key=selection_key,
        line_value=line_value,
        source_book="thunderpick",
        source_market_name="Match Winner",
        source_selection_name=bet_on,
        bet_on=bet_on,
        model_prob=model_prob,
        book_odds_locked=book_odds_locked,
        book_prob_adj=book_prob_adj,
        edge=edge,
        ev=ev,
        recommended_stake=recommended_stake,
        actual_stake=actual_stake,
        status=status,
        profit_loss=profit_loss,
        closing_odds=closing_odds,
        placed_at=placed_at or datetime.now(timezone.utc),
        settled_at=settled_at,
    )


def create_model_run(
    *,
    model_type: str = "xgboost",
    model_version: str = "test-model",
    artifact_path: str = "/tmp/model.xgb",
    is_active: bool = False,
    created_at: datetime | None = None,
) -> MLModelRun:
    return MLModelRun(
        model_type=model_type,
        model_version=model_version,
        artifact_path=artifact_path,
        is_active=is_active,
        feature_names_json="[]",
        config_json="{}",
        created_at=created_at or datetime.now(timezone.utc),
    )


def create_api_snapshot(
    snapshot_type: str,
    *,
    payload_json: dict[str, object],
    version: str | None = None,
    generated_at: datetime | None = None,
    source_window_started_at: datetime | None = None,
    source_window_completed_at: datetime | None = None,
    status: str = "success",
    is_active: bool = True,
):
    snapshot_classes = {
        "upcoming": UpcomingWithOddsSnapshot,
        "live": LiveWithOddsSnapshot,
        "results": BettingResultsSnapshot,
        "bankroll": BankrollSummarySnapshot,
        "rankings": PowerRankingsSnapshot,
        "homepage": HomepageSnapshotManifest,
    }
    snapshot_cls = snapshot_classes[snapshot_type]
    now = generated_at or datetime.now(timezone.utc)
    return snapshot_cls(
        version=version or f"{snapshot_type}-test-version",
        payload_json=payload_json,
        generated_at=now,
        source_window_started_at=source_window_started_at or now,
        source_window_completed_at=source_window_completed_at or now,
        status=status,
        is_active=is_active,
    )

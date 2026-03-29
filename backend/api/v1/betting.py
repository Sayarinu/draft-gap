from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_db, require_admin_api_key
from betting.bet_manager import (
    build_settlement_preview_payload,
    get_active_positions_by_series,
    get_model_evaluation_summary,
    get_open_bet_schedule_statuses,
    get_or_create_agent_bankroll,
    repair_orphaned_bets,
    reset_trading_state_preserve_ml,
    settle_completed_bets,
)
from betting.odds_engine import roi_pct
from models_ml import (
    Bankroll,
    BankrollSnapshot,
    BankrollSummarySnapshot,
    Bet,
    BetEvent,
    BettingResultsSnapshot,
)
from services.pandascore import league_name_or_slug_allowed
from services.homepage_snapshots import apply_snapshot_headers, get_active_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/betting", tags=["betting"])


def _to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


class BankrollResponse(BaseModel):
    initial_balance: float
    current_balance: float
    win_rate_pct: float
    total_profit: float
    roi_pct: float


class BetItemResponse(BaseModel):
    id: str
    pandascore_match_id: int
    team_a: str
    team_b: str
    league: str | None = None
    series_format: str | None = None
    bet_on: str
    market_type: str = "match_winner"
    selection_key: str = "team_a"
    line_value: float | None = None
    book_odds_locked: float
    model_prob: float
    book_prob_adj: float
    edge: float
    ev: float
    actual_stake: float
    status: str
    profit: float | None = None
    placed_at: str
    settled_at: str | None = None


class ResultsItemResponse(BaseModel):
    id: str
    betDateTime: str
    league: str
    team1: str
    team2: str
    betOn: str
    marketType: str = "match_winner"
    selectionKey: str = "team_a"
    lineValue: float | None = None
    lockedOdds: float
    stake: float
    result: str
    profit: float


class PaginatedResultsResponse(BaseModel):
    items: list[ResultsItemResponse]
    page: int
    per_page: int
    total_items: int
    total_pages: int
    available_leagues: list[str] = []


class ResultsSummaryResponse(BaseModel):
    wins: int
    losses: int
    settled: int
    total_staked: float
    total_profit: float
    win_rate: float
    roi: float


class ResultsCumulativePointResponse(BaseModel):
    label: str
    profit: float


class ResultsOutcomeDatumResponse(BaseModel):
    name: str
    value: int


class ResultsLeagueProfitDatumResponse(BaseModel):
    league: str
    profit: float


class ResultsAnalyticsResponse(BaseModel):
    summary: ResultsSummaryResponse
    cumulative_profit_data: list[ResultsCumulativePointResponse]
    outcome_data: list[ResultsOutcomeDatumResponse]
    league_profit_data: list[ResultsLeagueProfitDatumResponse]
    available_leagues: list[str] = []


class BettingSummaryResponse(BaseModel):
    total_bets: int
    settled_bets: int
    wins: int
    losses: int
    win_rate_pct: float
    total_staked: float
    total_profit: float
    roi_pct: float
    avg_edge_pct: float
    avg_odds: float


class ResetBankrollResponse(BaseModel):
    status: str
    bankroll_id: str
    current_balance: float


class ActiveBetBadgeResponse(BaseModel):
    id: str | None = None
    pandascore_match_id: int
    series_key: str | None = None
    bet_sequence: int | None = None
    team_a: str | None = None
    team_b: str | None = None
    bet_on: str
    market_type: str | None = None
    selection_key: str | None = None
    line_value: float | None = None
    source_market_name: str | None = None
    source_selection_name: str | None = None
    locked_odds: float
    stake: float
    status: str | None = None
    league: str | None = None
    entry_phase: str | None = None
    entry_score_team_a: int | None = None
    entry_score_team_b: int | None = None
    current_score_team_a: int | None = None
    current_score_team_b: int | None = None
    odds_source_status: str | None = None
    feed_health_status: str | None = None
    placed_at: str | None = None


class ActiveSeriesResponse(BaseModel):
    series_key: str
    pandascore_match_id: int
    team_a: str
    team_b: str
    league: str | None = None
    position_count: int
    total_exposure: float
    team_stake_totals: dict[str, float] = {}
    net_side: str | None = None
    net_stake_delta: float = 0.0
    has_conflicting_positions: bool = False
    single_position_summary: dict[str, object] = {}
    multi_position_summary: dict[str, object] = {}
    latest_position: ActiveBetBadgeResponse
    positions: list[ActiveBetBadgeResponse]


class OpenBetScheduleStatusResponse(BaseModel):
    id: str
    pandascore_match_id: int
    team_a: str
    team_b: str
    bet_on: str
    market_type: str = "match_winner"
    selection_key: str = "team_a"
    line_value: float | None = None
    locked_odds: float
    stake: float
    schedule_status: str
    league: str | None = None
    model_run_id: int | None = None
    series_key: str
    bet_sequence: int


class EdgeCalibrationResponse(BaseModel):
    bucket: str
    bets: int
    win_rate_pct: float
    roi_pct: float


class SplitPerformanceResponse(BaseModel):
    key: str
    bets: int
    wins: int
    losses: int
    roi_pct: float


class ModelEvaluationResponse(BaseModel):
    model_run_id: int | None = None
    model_version: str | None = None
    model_type: str | None = None
    settled_bets: int
    wins: int
    losses: int
    realized_roi_pct: float
    avg_clv_proxy_pct: float
    edge_calibration: list[EdgeCalibrationResponse]
    league_performance: list[SplitPerformanceResponse]
    series_format_performance: list[SplitPerformanceResponse]


class RepairOrphanedBetsResponse(BaseModel):
    repaired: int
    voided: int
    reconciled_balance_delta: float


ResultsPerPage = Annotated[int, Query(ge=1, le=100)]
ResultsPage = Annotated[int, Query(ge=1, le=500)]
FilterQuery = Annotated[str | None, Query(max_length=200)]


def _normalize_filter_parts(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def _get_settled_results_rows(session: Session) -> tuple[list[Bet], list[str]]:
    bankroll = get_or_create_agent_bankroll(session)
    rows = (
        session.query(Bet)
        .filter(
            Bet.bankroll_id == bankroll.id,
            Bet.status.in_(["WON", "LOST"]),
        )
        .order_by(Bet.settled_at.desc(), Bet.placed_at.desc())
        .all()
    )
    available_leagues = sorted(
        {
            (row.league or "UNKNOWN").strip()
            for row in rows
            if (row.league or "UNKNOWN").strip()
        }
    )
    return rows, available_leagues


def _result_item_from_bet(row: Bet) -> ResultsItemResponse:
    return ResultsItemResponse(
        id=str(row.id),
        betDateTime=str(row.placed_at),
        league=row.league or "UNKNOWN",
        team1=row.team_a,
        team2=row.team_b,
        betOn=row.bet_on,
        marketType=row.market_type,
        selectionKey=row.selection_key,
        lineValue=float(row.line_value) if row.line_value is not None else None,
        lockedOdds=float(row.book_odds_locked),
        stake=float(row.actual_stake),
        result=row.status,
        profit=float(row.profit_loss or 0),
    )


def _filter_result_items(
    items: list[ResultsItemResponse],
    *,
    search: str | None = None,
    league: str | None = None,
) -> list[ResultsItemResponse]:
    requested_leagues = set(_normalize_filter_parts(league))
    query = (search or "").strip().lower()
    filtered = items
    if requested_leagues:
        filtered = [
            item for item in filtered if item.league.strip().lower() in requested_leagues
        ]
    if query:
        filtered = [
            item
            for item in filtered
            if any(
                query in part.lower()
                for part in [item.league, item.team1, item.team2, item.betOn]
            )
        ]
    return filtered


def _paginate_results_items(
    items: list[ResultsItemResponse],
    *,
    page: int,
    per_page: int,
    available_leagues: list[str],
) -> PaginatedResultsResponse:
    total_items = len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    safe_page = min(max(page, 1), total_pages)
    start = (safe_page - 1) * per_page
    end = start + per_page
    return PaginatedResultsResponse(
        items=items[start:end],
        page=safe_page,
        per_page=per_page,
        total_items=total_items,
        total_pages=total_pages,
        available_leagues=available_leagues,
    )


def _build_results_analytics_payload(items: list[ResultsItemResponse]) -> ResultsAnalyticsResponse:
    wins = 0
    losses = 0
    total_staked = 0.0
    total_profit = 0.0

    for item in items:
        total_staked += item.stake
        total_profit += item.profit
        if item.result == "WON":
            wins += 1
        elif item.result == "LOST":
            losses += 1

    settled = wins + losses
    win_rate = (wins / settled) * 100 if settled > 0 else 0.0
    roi = (total_profit / total_staked) * 100 if total_staked > 0 else 0.0

    running_profit = 0.0
    cumulative_profit_data: list[ResultsCumulativePointResponse] = []
    for item in sorted(items, key=lambda row: row.betDateTime):
        running_profit = round(running_profit + item.profit, 2)
        date = item.betDateTime
        label = date
        try:
            parsed = datetime.fromisoformat(date.replace("Z", "+00:00"))
            label = f"{parsed.month}/{parsed.day}"
        except Exception:
            pass
        cumulative_profit_data.append(
            ResultsCumulativePointResponse(label=label, profit=running_profit)
        )

    by_league: dict[str, float] = defaultdict(float)
    for item in items:
        by_league[item.league] += item.profit
    league_profit_data = [
        ResultsLeagueProfitDatumResponse(league=league, profit=round(profit, 2))
        for league, profit in sorted(
            by_league.items(),
            key=lambda entry: entry[1],
            reverse=True,
        )[:10]
    ]

    return ResultsAnalyticsResponse(
        summary=ResultsSummaryResponse(
            wins=wins,
            losses=losses,
            settled=settled,
            total_staked=round(total_staked, 2),
            total_profit=round(total_profit, 2),
            win_rate=round(win_rate, 2),
            roi=round(roi, 2),
        ),
        cumulative_profit_data=cumulative_profit_data,
        outcome_data=[
            ResultsOutcomeDatumResponse(name="Won", value=wins),
            ResultsOutcomeDatumResponse(name="Lost", value=losses),
        ],
        league_profit_data=league_profit_data,
        available_leagues=sorted({item.league for item in items if item.league.strip()}),
    )


def _build_bankroll_response(session: Session) -> BankrollResponse:
    bankroll = get_or_create_agent_bankroll(session)
    session.refresh(bankroll)
    settled = session.query(Bet).filter(Bet.bankroll_id == bankroll.id, Bet.status.in_(["WON", "LOST"])).all()
    wins = sum(1 for bet in settled if bet.status == "WON")
    losses = sum(1 for bet in settled if bet.status == "LOST")
    total_staked = sum(_to_decimal(bet.actual_stake) for bet in settled)
    total_profit = sum(_to_decimal(bet.profit_loss) for bet in settled if bet.profit_loss is not None)
    win_rate = (wins / len(settled) * 100.0) if settled else 0.0

    return BankrollResponse(
        initial_balance=float(bankroll.initial_balance),
        current_balance=float(bankroll.current_balance),
        win_rate_pct=win_rate,
        total_profit=float(total_profit),
        roi_pct=float(roi_pct(total_profit, total_staked)),
    )


@router.get("/bankroll", response_model=BankrollResponse)
def get_bankroll(
    response: Response,
    session: Session = Depends(get_db),
) -> BankrollResponse:
    snapshot = get_active_snapshot(session, BankrollSummarySnapshot)
    apply_snapshot_headers(response, snapshot, key="bankroll")
    payload = snapshot.payload_json if snapshot else {}
    summary_payload = payload.get("summary")
    if isinstance(summary_payload, dict):
        return BankrollResponse.model_validate(summary_payload)
    return _build_bankroll_response(session)


class SettledBetBreakdownItem(BaseModel):
    pandascore_match_id: int
    result: str
    stake: float
    profit: float


class BankrollBreakdownResponse(BaseModel):
    initial_balance: float
    current_balance: float
    active_stake_total: float
    active_stake_allowed: float
    active_stake_filtered: float
    settled_profit: float
    settled_bets: list[SettledBetBreakdownItem]


@router.get("/bankroll/breakdown", response_model=BankrollBreakdownResponse)
def get_bankroll_breakdown(
    session: Session = Depends(get_db),
) -> BankrollBreakdownResponse:
    bankroll = get_or_create_agent_bankroll(session)
    session.refresh(bankroll)
    active = (
        session.query(Bet)
        .filter(Bet.bankroll_id == bankroll.id, Bet.status.in_(["PLACED", "LIVE", "SETTLEMENT_PENDING", "ORPHANED_FEED"]))
        .all()
    )
    settled = (
        session.query(Bet)
        .filter(
            Bet.bankroll_id == bankroll.id,
            Bet.status.in_(["WON", "LOST"]),
        )
        .order_by(Bet.settled_at.desc(), Bet.placed_at.desc())
        .all()
    )
    active_stake_total = sum(_to_decimal(b.actual_stake) for b in active)
    active_stake_allowed = sum(
        _to_decimal(b.actual_stake) for b in active if league_name_or_slug_allowed(b.league)
    )
    active_stake_filtered = active_stake_total - active_stake_allowed
    settled_profit = sum(
        _to_decimal(b.profit_loss) for b in settled if b.profit_loss is not None
    )
    return BankrollBreakdownResponse(
        initial_balance=float(bankroll.initial_balance),
        current_balance=float(bankroll.current_balance),
        active_stake_total=float(active_stake_total),
        active_stake_allowed=float(active_stake_allowed),
        active_stake_filtered=float(active_stake_filtered),
        settled_profit=float(settled_profit),
        settled_bets=[
            SettledBetBreakdownItem(
                pandascore_match_id=b.pandascore_match_id,
                result=b.status,
                stake=float(b.actual_stake),
                profit=float(b.profit_loss or 0),
            )
            for b in settled
        ],
    )


@router.get("/bets", response_model=list[BetItemResponse])
def get_bets(
    status: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    session: Session = Depends(get_db),
) -> list[BetItemResponse]:
    bankroll = get_or_create_agent_bankroll(session)
    query = session.query(Bet).filter(Bet.bankroll_id == bankroll.id)
    if status:
        statuses = [part.strip().upper() for part in status.split(",") if part.strip()]
        if statuses:
            query = query.filter(Bet.status.in_(statuses))
    rows = query.order_by(Bet.placed_at.desc()).limit(limit).all()
    return [
        BetItemResponse(
            id=str(row.id),
            pandascore_match_id=row.pandascore_match_id,
            team_a=row.team_a,
            team_b=row.team_b,
            league=row.league,
            series_format=row.series_format,
            bet_on=row.bet_on,
            market_type=row.market_type,
            selection_key=row.selection_key,
            line_value=float(row.line_value) if row.line_value is not None else None,
            book_odds_locked=float(row.book_odds_locked),
            model_prob=float(row.model_prob),
            book_prob_adj=float(row.book_prob_adj),
            edge=float(row.edge),
            ev=float(row.ev),
            actual_stake=float(row.actual_stake),
            status=row.status,
            profit=float(row.profit_loss) if row.profit_loss is not None else None,
            placed_at=str(row.placed_at),
            settled_at=str(row.settled_at) if row.settled_at is not None else None,
        )
        for row in rows
    ]


@router.get("/bets/active", response_model=list[ActiveBetBadgeResponse], response_model_exclude_none=True)
def get_active_bets(
    response: Response,
    session: Session = Depends(get_db),
) -> list[ActiveBetBadgeResponse]:
    snapshot = get_active_snapshot(session, BankrollSummarySnapshot)
    apply_snapshot_headers(response, snapshot, key="bankroll")
    payload = snapshot.payload_json if snapshot else {}
    active_bets = payload.get("active_bets", [])
    if isinstance(active_bets, list) and active_bets:
        return [ActiveBetBadgeResponse.model_validate(row) for row in active_bets]
    return [
        ActiveBetBadgeResponse.model_validate(row)
        for series in get_active_positions_by_series(session)
        for row in series["positions"]
    ]


@router.get("/bets/active-series", response_model=list[ActiveSeriesResponse])
def get_active_series(
    session: Session = Depends(get_db),
) -> list[ActiveSeriesResponse]:
    return [
        ActiveSeriesResponse(
            **{
                **series,
                "latest_position": ActiveBetBadgeResponse.model_validate(series["latest_position"]),
                "positions": [ActiveBetBadgeResponse.model_validate(row) for row in series["positions"]],
            }
        )
        for series in get_active_positions_by_series(session)
    ]


@router.get("/bets/open-status", response_model=list[OpenBetScheduleStatusResponse])
def get_open_bet_statuses(
    session: Session = Depends(get_db),
) -> list[OpenBetScheduleStatusResponse]:
    return [
        OpenBetScheduleStatusResponse(**row)
        for row in get_open_bet_schedule_statuses(session)
    ]


@router.get("/models/evaluation", response_model=list[ModelEvaluationResponse])
def get_model_evaluation(
    session: Session = Depends(get_db),
) -> list[ModelEvaluationResponse]:
    return [
        ModelEvaluationResponse(**row)
        for row in get_model_evaluation_summary(session)
    ]


@router.get("/results", response_model=PaginatedResultsResponse)
def get_results(
    response: Response,
    per_page: ResultsPerPage = 50,
    page: ResultsPage = 1,
    search: FilterQuery = None,
    league: FilterQuery = None,
    session: Session = Depends(get_db),
) -> PaginatedResultsResponse:
    snapshot = get_active_snapshot(session, BettingResultsSnapshot)
    apply_snapshot_headers(response, snapshot, key="results")
    rows, available_leagues = _get_settled_results_rows(session)
    items = [_result_item_from_bet(row) for row in rows]
    filtered = _filter_result_items(items, search=search, league=league)
    return _paginate_results_items(
        filtered,
        page=page,
        per_page=per_page,
        available_leagues=available_leagues,
    )


@router.get("/results/analytics", response_model=ResultsAnalyticsResponse)
def get_results_analytics(
    response: Response,
    search: FilterQuery = None,
    league: FilterQuery = None,
    session: Session = Depends(get_db),
) -> ResultsAnalyticsResponse:
    snapshot = get_active_snapshot(session, BettingResultsSnapshot)
    apply_snapshot_headers(response, snapshot, key="results")
    rows, available_leagues = _get_settled_results_rows(session)
    items = _filter_result_items(
        [_result_item_from_bet(row) for row in rows],
        search=search,
        league=league,
    )
    analytics = _build_results_analytics_payload(items)
    analytics.available_leagues = available_leagues
    return analytics


@router.get("/summary", response_model=BettingSummaryResponse)
def get_summary(session: Session = Depends(get_db)) -> BettingSummaryResponse:
    bankroll = get_or_create_agent_bankroll(session)
    all_bets = session.query(Bet).filter(Bet.bankroll_id == bankroll.id).all()
    settled = [bet for bet in all_bets if bet.status in {"WON", "LOST"}]
    wins = sum(1 for bet in settled if bet.status == "WON")
    losses = sum(1 for bet in settled if bet.status == "LOST")
    total_staked = sum(_to_decimal(bet.actual_stake) for bet in settled)
    total_profit = sum(_to_decimal(bet.profit_loss) for bet in settled if bet.profit_loss is not None)
    avg_edge = 0.0
    avg_odds = 0.0
    if all_bets:
        avg_edge = float(sum(_to_decimal(bet.edge) for bet in all_bets) / Decimal(len(all_bets))) * 100.0
        avg_odds = float(sum(_to_decimal(bet.book_odds_locked) for bet in all_bets) / Decimal(len(all_bets)))
    return BettingSummaryResponse(
        total_bets=len(all_bets),
        settled_bets=len(settled),
        wins=wins,
        losses=losses,
        win_rate_pct=(wins / len(settled) * 100.0) if settled else 0.0,
        total_staked=float(total_staked),
        total_profit=float(total_profit),
        roi_pct=float(roi_pct(total_profit, total_staked)),
        avg_edge_pct=avg_edge,
        avg_odds=avg_odds,
    )


@router.post("/bankroll/reset", response_model=ResetBankrollResponse)
def reset_bankroll(
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_db),
) -> ResetBankrollResponse:
    bankroll = get_or_create_agent_bankroll(session)
    session.query(BetEvent).filter(BetEvent.bankroll_id == bankroll.id).delete(synchronize_session=False)
    session.query(Bet).filter(Bet.bankroll_id == bankroll.id).delete(synchronize_session=False)
    session.query(BankrollSnapshot).filter(BankrollSnapshot.bankroll_id == bankroll.id).delete(
        synchronize_session=False
    )
    bankroll.current_balance = bankroll.initial_balance
    session.commit()
    return ResetBankrollResponse(
        status="success",
        bankroll_id=str(bankroll.id),
        current_balance=float(bankroll.current_balance),
    )


class ResetTradingStateResponse(BaseModel):
    status: str
    bankroll_id: str
    current_balance: float
    bet_events_deleted: int
    bets_deleted: int
    bankroll_snapshots_deleted: int
    prediction_logs_deleted: int
    upcoming_snapshots_deleted: int
    live_snapshots_deleted: int
    betting_results_snapshots_deleted: int
    bankroll_summary_snapshots_deleted: int
    power_rankings_snapshots_deleted: int
    homepage_manifest_snapshots_deleted: int
    snapshot_refresh_error: str | None = None


@router.post("/trading-state/reset", response_model=ResetTradingStateResponse)
def reset_trading_state(
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_db),
) -> ResetTradingStateResponse:
    summary = reset_trading_state_preserve_ml(session)
    bankroll = get_or_create_agent_bankroll(session)
    snapshot_refresh_error: str | None = None
    try:
        from tasks import run_snapshot_refresh_after_settlement

        run_snapshot_refresh_after_settlement()
    except Exception as exc:
        logger.exception("run_snapshot_refresh_after_settlement_failed")
        snapshot_refresh_error = str(exc)
    return ResetTradingStateResponse(
        status="success",
        bankroll_id=str(bankroll.id),
        current_balance=float(bankroll.current_balance),
        bet_events_deleted=summary["bet_events_deleted"],
        bets_deleted=summary["bets_deleted"],
        bankroll_snapshots_deleted=summary["bankroll_snapshots_deleted"],
        prediction_logs_deleted=summary["prediction_logs_deleted"],
        upcoming_snapshots_deleted=summary["upcoming_snapshots_deleted"],
        live_snapshots_deleted=summary["live_snapshots_deleted"],
        betting_results_snapshots_deleted=summary["betting_results_snapshots_deleted"],
        bankroll_summary_snapshots_deleted=summary["bankroll_summary_snapshots_deleted"],
        power_rankings_snapshots_deleted=summary["power_rankings_snapshots_deleted"],
        homepage_manifest_snapshots_deleted=summary["homepage_manifest_snapshots_deleted"],
        snapshot_refresh_error=snapshot_refresh_error,
    )


class ReconcileResponse(BaseModel):
    previous_balance: float
    computed_balance: float
    current_balance: float
    adjusted: bool


@router.post("/bankroll/reconcile", response_model=ReconcileResponse)
def reconcile_bankroll(
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_db),
) -> ReconcileResponse:
    bankroll = get_or_create_agent_bankroll(session)
    session.refresh(bankroll)
    previous = float(bankroll.current_balance)
    initial = _to_decimal(bankroll.initial_balance)
    all_bets = session.query(Bet).filter(Bet.bankroll_id == bankroll.id).all()
    active_stake_total = sum(
        _to_decimal(b.actual_stake) for b in all_bets if b.status in {"PLACED", "LIVE", "SETTLEMENT_PENDING", "ORPHANED_FEED"}
    )
    settled_pnl = sum(
        _to_decimal(b.profit_loss) for b in all_bets if b.status in {"WON", "LOST"}
    )
    computed = initial - active_stake_total + settled_pnl
    adjusted = abs(computed - _to_decimal(bankroll.current_balance)) > Decimal("0.001")
    if adjusted:
        bankroll.current_balance = computed
        session.commit()
        session.refresh(bankroll)
    return ReconcileResponse(
        previous_balance=previous,
        computed_balance=float(computed),
        current_balance=float(bankroll.current_balance),
        adjusted=adjusted,
    )


class SettleResponse(BaseModel):
    settled: int
    won: int
    lost: int
    removed: int
    voided: int = 0
    orphaned: int = 0
    profit: float


@router.post("/settle", response_model=SettleResponse)
def manual_settle(
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_db),
) -> SettleResponse:
    summary = settle_completed_bets(session)
    try:
        from tasks import run_snapshot_refresh_after_settlement

        run_snapshot_refresh_after_settlement()
    except Exception:
        logger.exception("run_snapshot_refresh_after_settlement_failed")
    return SettleResponse(
        settled=summary["settled"],
        won=summary["won"],
        lost=summary["lost"],
        removed=summary["removed"],
        voided=summary.get("voided", 0),
        orphaned=summary.get("orphaned", 0),
        profit=summary["profit"],
    )


@router.get("/settlement-preview")
def settlement_preview(
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return build_settlement_preview_payload(session)


@router.post("/bets/repair-orphaned", response_model=RepairOrphanedBetsResponse)
def repair_orphaned(
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_db),
) -> RepairOrphanedBetsResponse:
    return RepairOrphanedBetsResponse(**repair_orphaned_bets(session))

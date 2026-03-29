from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TypedDict

from sqlalchemy.orm import Session

from betting.markets import BetCandidate
from betting.odds_engine import compute_edge, compute_ev, implied_prob, kelly_stake, remove_vig, roi_pct
from entity_resolution.canonical_store import normalize_team_for_settlement
from entity_resolution.resolver import EntityResolver
from ml.predictor_v2 import predict_for_pandascore_match, predict_live_rebet_context
from ml.series_distribution import (
    compute_exact_score_probabilities,
    expected_log_growth,
    handicap_cover_probability,
    infer_map_win_probability,
    total_maps_probability,
)
from models_ml import (
    Bankroll,
    BankrollSnapshot,
    BankrollSummarySnapshot,
    Bet,
    BetEvent,
    BettingResultsSnapshot,
    HomepageSnapshotManifest,
    LiveWithOddsSnapshot,
    MLModelRun,
    PowerRankingsSnapshot,
    PredictionLog,
    UpcomingWithOddsSnapshot,
)
from services.bookie import (
    find_market_set_for_match,
    find_odds_for_match,
    read_market_catalog_from_file,
    read_odds_from_file,
    resolve_match_odds,
)
from services.pandascore import (
    classify_match_betting_eligibility,
    fetch_json_sync,
    fetch_lol_matches_by_ids_sync,
    league_name_or_slug_allowed,
    match_allowed_tier,
    read_upcoming_matches_from_file,
)


class PlacementSummary(TypedDict):
    placed: int
    skipped_existing: int
    skipped_missing_inputs: int
    waiting_for_better_odds: int
    total_staked: float
    skipped_by_reason: dict[str, int]


class SettlementSummary(TypedDict):
    settled: int
    won: int
    lost: int
    removed: int
    voided: int
    orphaned: int
    profit: float


class OpenBetStatusSummary(TypedDict):
    id: str
    pandascore_match_id: int
    team_a: str
    team_b: str
    bet_on: str
    locked_odds: float
    stake: float
    schedule_status: str
    league: str | None
    model_run_id: int | None
    series_key: str
    bet_sequence: int
    market_type: str
    selection_key: str
    line_value: float | None


class EdgeBucketSummary(TypedDict):
    bucket: str
    bets: int
    win_rate_pct: float
    roi_pct: float


class SplitPerformanceSummary(TypedDict):
    key: str
    bets: int
    wins: int
    losses: int
    roi_pct: float


class MatchBettingStatusSummary(TypedDict, total=False):
    pandascore_match_id: int
    series_key: str
    status: str
    bet_on: str
    locked_odds: float
    stake: float
    market_type: str
    selection_key: str
    line_value: float | None
    position_count: int
    reason_code: str | None
    short_detail: str | None
    within_force_window: bool
    force_bet_after: str | None
    chosen_edge: float | None
    min_edge_threshold: float | None
    confidence: float | None
    confidence_threshold: float | None
    ev: float | None
    bookie_match_confidence: str | None
    matched_row_team1: str | None
    matched_row_team2: str | None
    is_bettable: bool
    eligibility_reason: str | None
    normalized_identity: str | None
    odds_source_kind: str | None
    odds_source_status: str | None
    market_offer_count: int
    has_match_winner_offer: bool
    terminal_outcome: str
    rejected_candidates: list[dict[str, object]]
    series_decision_context: dict[str, object]


class ModelEvaluationSummary(TypedDict):
    model_run_id: int | None
    model_version: str | None
    model_type: str | None
    settled_bets: int
    wins: int
    losses: int
    realized_roi_pct: float
    avg_clv_proxy_pct: float
    edge_calibration: list[EdgeBucketSummary]
    league_performance: list[SplitPerformanceSummary]
    series_format_performance: list[SplitPerformanceSummary]


class MatchDecisionDiagnostic(TypedDict, total=False):
    pandascore_match_id: int
    scheduled_at: str | None
    league: str | None
    team_a: str
    team_b: str
    series_format: str
    status: str
    reason_code: str | None
    reason_detail: str | None
    short_detail: str | None
    within_force_window: bool
    force_bet_after: str | None
    position_count: int
    is_bettable: bool
    eligibility_reason: str | None
    odds_source_kind: str | None
    odds_source_status: str | None
    market_offer_count: int
    has_match_winner_offer: bool
    terminal_outcome: str
    diagnostics: dict[str, object]


class ActivePositionSummary(TypedDict):
    id: str
    pandascore_match_id: int
    series_key: str
    bet_sequence: int
    team_a: str
    team_b: str
    bet_on: str
    market_type: str
    selection_key: str
    line_value: float | None
    source_market_name: str | None
    source_selection_name: str | None
    locked_odds: float
    stake: float
    status: str
    league: str | None
    entry_phase: str
    entry_score_team_a: int
    entry_score_team_b: int
    current_score_team_a: int
    current_score_team_b: int
    odds_source_status: str
    feed_health_status: str
    placed_at: str


class ActiveSeriesSummary(TypedDict):
    series_key: str
    pandascore_match_id: int
    team_a: str
    team_b: str
    league: str | None
    position_count: int
    total_exposure: float
    team_stake_totals: dict[str, float]
    net_side: str | None
    net_stake_delta: float
    has_conflicting_positions: bool
    single_position_summary: dict[str, object]
    multi_position_summary: dict[str, object]
    latest_position: ActivePositionSummary
    positions: list[ActivePositionSummary]


def _to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _candidate_label(candidate: dict[str, object]) -> str:
    market_type = str(candidate.get("market_type") or "match_winner")
    selection_key = str(candidate.get("selection_key") or "")
    line_value = candidate.get("line_value")
    if market_type == "match_winner":
        return str(candidate.get("chosen_team") or selection_key)
    if market_type == "map_handicap":
        return f"{candidate.get('chosen_team') or selection_key} {line_value:+.1f}" if isinstance(line_value, (int, float)) else str(candidate.get("chosen_team") or selection_key)
    return selection_key.replace("_", " ").title()


OPEN_BET_STATUSES = {"PLACED", "LIVE", "SETTLEMENT_PENDING", "ORPHANED_FEED"}
SETTLED_BET_STATUSES = {"WON", "LOST", "VOID"}
ACTIVE_BET_VISIBILITY_STATUSES = {"PLACED", "LIVE", "SETTLEMENT_PENDING", "ORPHANED_FEED"}
REBET_ENTRY_PHASE = "live_mid_series"
PREMATCH_ENTRY_PHASE = "prematch"
REBET_MIN_EDGE_DELTA = Decimal("0.02000")
REBET_MIN_ODDS_IMPROVEMENT = Decimal("0.1200")
REBET_COOLDOWN = timedelta(minutes=8)
SERIES_CONFLICT_COOLDOWN = timedelta(minutes=10)
SERIES_MIN_EV_IMPROVEMENT = Decimal("1.00")
SERIES_MAX_BET_MULTIPLIER = Decimal("3.0")
DERIVATIVE_MARKET_STAKE_MULTIPLIER = Decimal("0.60")
MIN_CANDIDATE_CONFIDENCE = Decimal("0.54")
MIN_DERIVATIVE_CONFIDENCE = Decimal("0.57")
MIN_CANDIDATE_EV = Decimal("0.25")

REJECTED_REASON_PRIORITY = {
    "low_confidence": 0,
    "low_ev": 1,
    "invalid_stake": 2,
    "invalid_odds": 3,
    "invalid_line": 4,
    "unsupported_market": 5,
}


def _percent_string(value: Decimal) -> str:
    return f"{(float(value) * 100.0):.1f}%"


def _short_detail_for_reason(
    reason_code: str | None,
    *,
    chosen_edge: Decimal | None = None,
    min_edge_threshold: Decimal | None = None,
    confidence: Decimal | None = None,
    confidence_threshold: Decimal | None = None,
    ev: Decimal | None = None,
) -> str | None:
    normalized = str(reason_code or "").strip().lower()
    if normalized == "below_edge_waiting" and chosen_edge is not None and min_edge_threshold is not None:
        return f"EDGE {_percent_string(chosen_edge)} < {_percent_string(min_edge_threshold)}"
    if normalized == "low_confidence" and confidence is not None and confidence_threshold is not None:
        return f"CONFIDENCE {float(confidence):.2f} < {float(confidence_threshold):.2f}"
    if normalized == "low_ev" and ev is not None:
        return f"EV ${float(ev):.2f} < ${float(MIN_CANDIDATE_EV):.2f}"
    if normalized == "missing_bookie_odds":
        return "NO THUNDERPICK MATCH"
    if normalized == "team_resolution_failed":
        return "TEAM MATCH FAILED"
    if normalized == "model_unavailable":
        return "MODEL OFFLINE"
    if normalized == "prediction_unavailable":
        return "NO QUALIFYING BET"
    if normalized == "invalid_stake":
        return "STAKE TOO SMALL"
    if normalized == "invalid_odds":
        return "INVALID ODDS"
    if normalized == "invalid_line":
        return "INVALID MARKET LINE"
    if normalized == "unsupported_market":
        return "UNSUPPORTED MARKET"
    if normalized == "league_not_bettable":
        return "LEAGUE EXCLUDED"
    if normalized == "tier_not_bettable":
        return "TIER EXCLUDED"
    if normalized == "status_generation_failed":
        return "STATUS GENERATION FAILED"
    return None


def _rank_rejected_reason(reason: str) -> tuple[int, str]:
    return (REJECTED_REASON_PRIORITY.get(reason, 99), reason)


def _top_rejected_candidates(rejected: list[dict[str, object]], *, limit: int = 3) -> list[dict[str, object]]:
    return sorted(
        rejected,
        key=lambda item: _rank_rejected_reason(str(item.get("reason") or "")),
    )[:limit]


def _primary_rejected_reason(rejected: list[dict[str, object]]) -> str | None:
    counts = Counter(str(item.get("reason") or "") for item in rejected if item.get("reason"))
    if not counts:
        return None
    return min(counts.keys(), key=lambda reason: (-counts[reason],) + _rank_rejected_reason(reason))


def _attach_candidate_diagnostics(
    payload: dict[str, object],
    *,
    bankroll: Bankroll,
    market_type: str | None = None,
    chosen_edge: Decimal | None = None,
    confidence: Decimal | None = None,
    ev: Decimal | None = None,
    bookie_match_confidence: str | None = None,
    matched_row_team1: str | None = None,
    matched_row_team2: str | None = None,
    rejected_candidates: list[dict[str, object]] | None = None,
    short_detail_reason: str | None = None,
) -> dict[str, object]:
    normalized_market_type = market_type or str(payload.get("market_type") or "match_winner")
    confidence_floor = MIN_CANDIDATE_CONFIDENCE if normalized_market_type == "match_winner" else MIN_DERIVATIVE_CONFIDENCE
    edge_value = chosen_edge if chosen_edge is not None else _to_decimal(payload.get("chosen_edge"), default=Decimal("0"))
    confidence_value = confidence if confidence is not None else _to_decimal(payload.get("confidence"), default=Decimal("0"))
    ev_value = ev if ev is not None else _to_decimal(payload.get("ev"), default=Decimal("0"))
    top_rejected = _top_rejected_candidates(rejected_candidates or [])
    payload["chosen_edge"] = edge_value
    payload["min_edge_threshold"] = _to_decimal(bankroll.min_edge_threshold)
    payload["confidence"] = confidence_value
    payload["confidence_threshold"] = confidence_floor
    payload["ev"] = ev_value
    payload["bookie_match_confidence"] = bookie_match_confidence
    payload["matched_row_team1"] = matched_row_team1
    payload["matched_row_team2"] = matched_row_team2
    payload["rejected_candidates"] = top_rejected
    payload["short_detail"] = _short_detail_for_reason(
        short_detail_reason or str(payload.get("reason_code") or ""),
        chosen_edge=edge_value,
        min_edge_threshold=_to_decimal(bankroll.min_edge_threshold),
        confidence=confidence_value,
        confidence_threshold=confidence_floor,
        ev=ev_value,
    )
    return payload


def _attach_match_metadata(
    payload: dict[str, object],
    *,
    eligibility: dict[str, object] | None = None,
    odds_resolution: dict[str, object] | None = None,
    terminal_outcome: str | None = None,
) -> dict[str, object]:
    eligibility_payload = eligibility or {}
    odds_payload = odds_resolution or {}
    payload["is_bettable"] = bool(eligibility_payload.get("is_bettable", True))
    payload["eligibility_reason"] = str(eligibility_payload.get("eligibility_reason") or "") or None
    payload["normalized_identity"] = str(eligibility_payload.get("normalized_identity") or "") or None
    payload["odds_source_kind"] = str(odds_payload.get("odds_source_kind") or "") or None
    payload["odds_source_status"] = str(odds_payload.get("odds_source_status") or "") or None
    payload["market_offer_count"] = int(odds_payload.get("market_offer_count") or 0)
    payload["has_match_winner_offer"] = bool(odds_payload.get("has_match_winner_offer"))
    payload["terminal_outcome"] = terminal_outcome or str(payload.get("status") or "unknown")
    return payload


def make_series_key(match_id: int) -> str:
    return f"ps:{match_id}"


def _open_bets_query(session: Session):
    return session.query(Bet).filter(Bet.status.in_(sorted(OPEN_BET_STATUSES)))


def _same_team(left: str | None, right: str | None) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


def _score_from_match(match: dict[str, object]) -> tuple[int, int]:
    results = match.get("results") or []
    opponents = match.get("opponents") or []
    if len(opponents) < 2:
        return (0, 0)
    opp1_id = (opponents[0].get("opponent") or {}).get("id")
    score_a = 0
    score_b = 0
    for result in results:
        score = int(result.get("score") or 0)
        if result.get("team_id") == opp1_id:
            score_a = score
        else:
            score_b = score
    return (score_a, score_b)


def _series_format_label(number_of_games: int) -> str:
    return "BO5" if number_of_games >= 5 else ("BO3" if number_of_games >= 3 else "BO1")


def _record_bet_event(
    session: Session,
    *,
    bankroll_id: object,
    pandascore_match_id: int,
    series_key: str,
    event_type: str,
    amount_delta: Decimal = Decimal("0.00"),
    bet_id: object | None = None,
    payload: dict[str, object] | None = None,
) -> BetEvent:
    event = BetEvent(
        bankroll_id=bankroll_id,
        bet_id=bet_id,
        pandascore_match_id=pandascore_match_id,
        series_key=series_key,
        event_type=event_type,
        amount_delta=amount_delta,
        payload_json=payload,
    )
    session.add(event)
    return event


def _build_series_exposure_snapshot(
    positions: list[Bet],
    *,
    team_a: str,
    team_b: str,
) -> dict[str, object]:
    stake_by_team = {
        team_a: Decimal("0.00"),
        team_b: Decimal("0.00"),
    }
    odds_weight = {
        team_a: Decimal("0.00"),
        team_b: Decimal("0.00"),
    }
    for position in positions:
        team_name = team_a if _same_team(position.bet_on, team_a) else team_b
        stake = _to_decimal(position.actual_stake)
        stake_by_team[team_name] = stake_by_team.get(team_name, Decimal("0.00")) + stake
        odds_weight[team_name] = odds_weight.get(team_name, Decimal("0.00")) + (
            _to_decimal(position.book_odds_locked) * stake
        )

    team_a_stake = stake_by_team.get(team_a, Decimal("0.00"))
    team_b_stake = stake_by_team.get(team_b, Decimal("0.00"))
    if team_a_stake > team_b_stake:
        net_side = team_a
    elif team_b_stake > team_a_stake:
        net_side = team_b
    else:
        net_side = None

    average_odds = {
        team_name: (
            odds_weight[team_name] / stake_by_team[team_name]
            if stake_by_team[team_name] > 0
            else None
        )
        for team_name in (team_a, team_b)
    }
    return {
        "position_count": len(positions),
        "total_stake": team_a_stake + team_b_stake,
        "stake_by_team": stake_by_team,
        "average_odds_by_team": average_odds,
        "net_side": net_side,
        "net_stake_delta": abs(team_a_stake - team_b_stake),
        "has_conflicting_positions": team_a_stake > 0 and team_b_stake > 0,
    }


def _candidate_win_profit(
    positions: list[Bet],
    winning_team: str,
    *,
    team_a: str,
    team_b: str,
    additional_bet: dict[str, object] | None = None,
) -> Decimal:
    all_positions = list(positions)
    if additional_bet is not None:
        all_positions.append(
            Bet(
                bankroll_id=None,
                pandascore_match_id=int(additional_bet.get("pandascore_match_id") or 0),
                model_run_id=additional_bet.get("model_run_id"),
                team_a=str(additional_bet.get("team_a") or team_a),
                team_b=str(additional_bet.get("team_b") or team_b),
                league=None,
                series_format="BO3",
                series_key=str(additional_bet.get("series_key") or ""),
                bet_sequence=0,
                entry_phase=str(additional_bet.get("entry_phase") or PREMATCH_ENTRY_PHASE),
                entry_score_team_a=int(additional_bet.get("entry_score_team_a") or 0),
                entry_score_team_b=int(additional_bet.get("entry_score_team_b") or 0),
                current_score_team_a=int(additional_bet.get("current_score_team_a") or 0),
                current_score_team_b=int(additional_bet.get("current_score_team_b") or 0),
                odds_source_status="available",
                feed_health_status="tracked",
                live_rebet_allowed=bool(additional_bet.get("live_rebet_allowed")),
                model_snapshot_json=None,
                bet_on=str(additional_bet.get("chosen_team") or ""),
                model_prob=_to_decimal(additional_bet.get("chosen_model_prob")),
                book_odds_locked=_to_decimal(additional_bet.get("chosen_book_odds")),
                book_prob_adj=_to_decimal(additional_bet.get("chosen_book_prob")),
                edge=_to_decimal(additional_bet.get("chosen_edge")),
                ev=_to_decimal(additional_bet.get("ev")),
                recommended_stake=_to_decimal(additional_bet.get("stake")),
                actual_stake=_to_decimal(additional_bet.get("stake")),
                status="PLACED",
            )
        )

    total = Decimal("0.00")
    for position in all_positions:
        stake = _to_decimal(position.actual_stake)
        side = team_a if _same_team(position.bet_on, team_a) else team_b
        if _same_team(side, winning_team):
            total += stake * (_to_decimal(position.book_odds_locked) - Decimal("1.00"))
        else:
            total -= stake
    return total


def _series_expected_value(
    positions: list[Bet],
    *,
    team_a: str,
    team_b: str,
    prob_a: Decimal,
    prob_b: Decimal,
    additional_bet: dict[str, object] | None = None,
) -> Decimal:
    win_profit_a = _candidate_win_profit(
        positions,
        team_a,
        team_a=team_a,
        team_b=team_b,
        additional_bet=additional_bet,
    )
    win_profit_b = _candidate_win_profit(
        positions,
        team_b,
        team_a=team_a,
        team_b=team_b,
        additional_bet=additional_bet,
    )
    return (prob_a * win_profit_a) + (prob_b * win_profit_b)


def _series_exposure_cap(bankroll: Bankroll) -> Decimal:
    initial_balance = _to_decimal(bankroll.initial_balance)
    max_bet_pct = _to_decimal(bankroll.max_bet_pct)
    cap = initial_balance * max_bet_pct * SERIES_MAX_BET_MULTIPLIER
    return cap if cap > Decimal("75.00") else Decimal("75.00")


def _mark_bet_status(
    session: Session,
    bet: Bet,
    next_status: str,
    *,
    event_type: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    if bet.status == next_status:
        return
    bet.status = next_status
    if event_type:
        _record_bet_event(
            session,
            bankroll_id=bet.bankroll_id,
            bet_id=bet.id,
            pandascore_match_id=bet.pandascore_match_id,
            series_key=bet.series_key,
            event_type=event_type,
            payload=payload,
        )


def _team_names(match: dict[str, object]) -> tuple[str, str]:
    opponents = match.get("opponents") or []
    team_a = ((opponents[0].get("opponent") or {}).get("name") if len(opponents) > 0 else None) or "TBD"
    team_b = ((opponents[1].get("opponent") or {}).get("name") if len(opponents) > 1 else None) or "TBD"
    return (str(team_a), str(team_b))


def _team_acronyms(match: dict[str, object]) -> tuple[str | None, str | None]:
    opponents = match.get("opponents") or []
    team_a = ((opponents[0].get("opponent") or {}).get("acronym") if len(opponents) > 0 else None) or None
    team_b = ((opponents[1].get("opponent") or {}).get("acronym") if len(opponents) > 1 else None) or None
    return (str(team_a) if team_a else None, str(team_b) if team_b else None)


def _fetch_running_matches() -> list[dict[str, object]]:
    try:
        data = fetch_json_sync(
            "/lol/matches",
            params={"filter[status]": "running", "per_page": 100, "sort": "begin_at"},
        )
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _fetch_match_by_id(match_id: int) -> dict[str, object] | None:
    try:
        data = fetch_json_sync(f"/lol/matches/{match_id}")
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _winner_name_from_match(match: dict[str, object] | None) -> str | None:
    if not match:
        return None
    winner = match.get("winner") or {}
    winner_name = str(winner.get("name") or "").strip()
    return winner_name or None


def _resolve_winner_display_name(match: dict[str, object] | None) -> str | None:
    if not match:
        return None
    direct = _winner_name_from_match(match)
    if direct:
        return direct
    winner_obj = match.get("winner")
    winner_id: int | None = None
    if isinstance(winner_obj, dict):
        wid = winner_obj.get("id")
        if isinstance(wid, (int, float)):
            winner_id = int(wid)
    if winner_id is None:
        wid_raw = match.get("winner_id")
        if isinstance(wid_raw, (int, float)):
            winner_id = int(wid_raw)
    if winner_id is None:
        return None
    opponents = match.get("opponents") or []
    for opp in opponents:
        if not isinstance(opp, dict):
            continue
        team = opp.get("opponent") or {}
        if not isinstance(team, dict):
            continue
        tid = team.get("id")
        if isinstance(tid, (int, float)) and int(tid) == winner_id:
            name = str(team.get("name") or "").strip()
            return name or None
    return None


def _schedule_status_from_match(match: dict[str, object] | None) -> str:
    if not match:
        return "missing_from_feed"
    status = str(match.get("status") or "").strip().lower()
    if status in {"running", "started", "live"}:
        return "scheduled_live"
    if status in {"finished", "completed"}:
        return "completed_pending_settlement"
    if status in {"canceled", "cancelled"}:
        return "cancelled"
    if _winner_name_from_match(match):
        return "completed_pending_settlement"
    return "scheduled_upcoming"


def match_belongs_on_upcoming_odds_feed(match: dict[str, object]) -> bool:
    return _schedule_status_from_match(match) == "scheduled_upcoming"


def _group_bucket(edge_value: Decimal) -> str:
    pct = float(edge_value) * 100.0
    if pct < 5:
        return "<5%"
    if pct < 10:
        return "5-10%"
    if pct < 15:
        return "10-15%"
    return "15%+"


def _get_bankroll(bankroll_map: dict[str, Bankroll], session: Session, bankroll_id: object) -> Bankroll | None:
    bankroll = bankroll_map.get(str(bankroll_id))
    if bankroll is not None:
        return bankroll
    bankroll = session.get(Bankroll, bankroll_id)
    if bankroll is None:
        return None
    bankroll_map[str(bankroll_id)] = bankroll
    return bankroll


def _bet_has_live_history(bet: Bet, live_history_bet_ids: set[object]) -> bool:
    if bet.status in {"LIVE", "SETTLEMENT_PENDING"}:
        return True
    if str(bet.entry_phase or PREMATCH_ENTRY_PHASE) == REBET_ENTRY_PHASE:
        return True
    if int(bet.current_score_team_a or 0) > 0 or int(bet.current_score_team_b or 0) > 0:
        return True
    return bet.id in live_history_bet_ids


def _match_has_bookie_odds(
    match: dict[str, object] | None,
    market_catalog: object,
    *,
    fallback_team_a: str,
    fallback_team_b: str,
) -> bool:
    if not isinstance(match, dict):
        return False
    team_a, team_b = _team_names(match)
    acr_a, acr_b = _team_acronyms(match)
    market_set = find_market_set_for_match(
        team_a or fallback_team_a,
        team_b or fallback_team_b,
        market_catalog,
        acronym1=acr_a,
        acronym2=acr_b,
    )
    offers = market_set.get("offers") if isinstance(market_set, dict) else None
    return isinstance(offers, list) and len(offers) > 0


def _void_bet(
    session: Session,
    bet: Bet,
    *,
    bankroll: Bankroll,
    reason: str,
    payload: dict[str, object] | None = None,
) -> None:
    stake = _to_decimal(bet.actual_stake)
    bankroll.current_balance = bankroll.current_balance + stake
    bet.profit_loss = Decimal("0.00")
    bet.feed_health_status = "cancelled"
    bet.settled_at = datetime.now(timezone.utc)
    bet.odds_source_status = "missing" if reason == "odds_removed_before_start" else bet.odds_source_status
    _mark_bet_status(
        session,
        bet,
        "VOID",
        event_type="voided",
        payload={"reason": reason, **(payload or {})},
    )
    _record_bet_event(
        session,
        bankroll_id=bet.bankroll_id,
        bet_id=bet.id,
        pandascore_match_id=bet.pandascore_match_id,
        series_key=bet.series_key,
        event_type="wallet_void_refund",
        amount_delta=stake,
        payload={"reason": reason},
    )


def refund_and_delete_missing_open_bets(session: Session) -> dict[str, int | float]:
    open_bets = _open_bets_query(session).all()
    if not open_bets:
        return {"removed": 0, "refunded": 0.0, "voided": 0, "orphaned": 0, "live": 0, "pending": 0}

    upcoming_matches = read_upcoming_matches_from_file() or []
    upcoming_matches_by_id = {
        int(match.get("id") or 0): match
        for match in upcoming_matches
        if int(match.get("id") or 0) > 0
    }
    upcoming_ids = set(upcoming_matches_by_id)
    running_matches = _fetch_running_matches()
    running_ids = {int(match.get("id") or 0) for match in running_matches if int(match.get("id") or 0) > 0}
    bankroll_map: dict[str, Bankroll] = {}
    open_bet_ids = [bet.id for bet in open_bets]
    live_history_bet_ids = {
        bet_id
        for (bet_id,) in (
            session.query(BetEvent.bet_id)
            .filter(
                BetEvent.bet_id.in_(open_bet_ids),
                BetEvent.event_type.in_(["live_started", "settlement_pending", "settled"]),
            )
            .all()
        )
        if bet_id is not None
    }
    market_catalog = read_market_catalog_from_file()
    catalog_matches = market_catalog.get("matches") if isinstance(market_catalog, dict) else None
    has_catalog_snapshot = isinstance(market_catalog, dict) and (
        bool(market_catalog.get("scraped_at"))
        or (isinstance(catalog_matches, list) and len(catalog_matches) > 0)
    )
    restored = 0
    voided = 0
    orphaned = 0
    live = 0
    pending = 0

    for bet in open_bets:
        payload = {
            "existing_status": bet.status,
            "pandascore_match_id": bet.pandascore_match_id,
        }
        if bet.pandascore_match_id in running_ids:
            bet.current_score_team_a, bet.current_score_team_b = _score_from_match(
                next((row for row in running_matches if int(row.get("id") or 0) == bet.pandascore_match_id), {})
            )
            bet.feed_health_status = "tracked"
            bet.odds_source_status = "available" if bet.odds_source_status == "available" else bet.odds_source_status
            _mark_bet_status(session, bet, "LIVE", event_type="live_started", payload=payload)
            live += 1
            continue
        if bet.pandascore_match_id in upcoming_ids:
            upcoming_match = upcoming_matches_by_id.get(bet.pandascore_match_id)
            file_schedule = _schedule_status_from_match(
                upcoming_match if isinstance(upcoming_match, dict) else None
            )
            if file_schedule == "scheduled_upcoming":
                if (
                    has_catalog_snapshot
                    and upcoming_match is not None
                    and isinstance(upcoming_match, dict)
                    and not _bet_has_live_history(bet, live_history_bet_ids)
                    and not _match_has_bookie_odds(
                        upcoming_match,
                        market_catalog,
                        fallback_team_a=bet.team_a,
                        fallback_team_b=bet.team_b,
                    )
                ):
                    bankroll = _get_bankroll(bankroll_map, session, bet.bankroll_id)
                    if bankroll is None:
                        continue
                    _void_bet(
                        session,
                        bet,
                        bankroll=bankroll,
                        reason="odds_removed_before_start",
                        payload=payload,
                    )
                    voided += 1
                    continue
                if bet.status != "PLACED":
                    restored += 1
                bet.feed_health_status = "tracked"
                _mark_bet_status(session, bet, "PLACED")
                continue
            if file_schedule == "scheduled_live":
                um = upcoming_match if isinstance(upcoming_match, dict) else {}
                bet.current_score_team_a, bet.current_score_team_b = _score_from_match(um)
                bet.feed_health_status = "tracked"
                bet.odds_source_status = "available" if bet.odds_source_status == "available" else bet.odds_source_status
                _mark_bet_status(session, bet, "LIVE", event_type="live_started", payload=payload)
                live += 1
                continue
            if file_schedule == "completed_pending_settlement":
                um = upcoming_match if isinstance(upcoming_match, dict) else {}
                bet.current_score_team_a, bet.current_score_team_b = _score_from_match(um)
                bet.feed_health_status = "tracked"
                _mark_bet_status(
                    session,
                    bet,
                    "SETTLEMENT_PENDING",
                    event_type="settlement_pending",
                    payload=payload,
                )
                pending += 1
                continue
            if file_schedule == "cancelled":
                um = upcoming_match if isinstance(upcoming_match, dict) else {}
                if bool(um.get("forfeit")) and _resolve_winner_display_name(upcoming_match if isinstance(upcoming_match, dict) else None):
                    bet.current_score_team_a, bet.current_score_team_b = _score_from_match(um)
                    bet.feed_health_status = "tracked"
                    _mark_bet_status(
                        session,
                        bet,
                        "SETTLEMENT_PENDING",
                        event_type="settlement_pending",
                        payload=payload,
                    )
                    pending += 1
                    continue
                bankroll = _get_bankroll(bankroll_map, session, bet.bankroll_id)
                if bankroll is None:
                    continue
                _void_bet(session, bet, bankroll=bankroll, reason="match_cancelled", payload=payload)
                voided += 1
                continue
        match = _fetch_match_by_id(bet.pandascore_match_id)
        schedule_status = _schedule_status_from_match(match)
        if schedule_status == "scheduled_upcoming":
            if bet.status != "PLACED":
                restored += 1
            bet.feed_health_status = "tracked"
            _mark_bet_status(session, bet, "PLACED")
            continue
        if schedule_status == "scheduled_live":
            bet.current_score_team_a, bet.current_score_team_b = _score_from_match(match)
            bet.feed_health_status = "tracked"
            _mark_bet_status(session, bet, "LIVE", event_type="live_started", payload=payload)
            live += 1
            continue
        if schedule_status == "completed_pending_settlement":
            bet.current_score_team_a, bet.current_score_team_b = _score_from_match(match or {})
            bet.feed_health_status = "tracked"
            _mark_bet_status(
                session,
                bet,
                "SETTLEMENT_PENDING",
                event_type="settlement_pending",
                payload=payload,
            )
            pending += 1
            continue
        if schedule_status == "cancelled":
            if bool((match or {}).get("forfeit")) and _resolve_winner_display_name(match):
                bet.current_score_team_a, bet.current_score_team_b = _score_from_match(match or {})
                bet.feed_health_status = "tracked"
                _mark_bet_status(
                    session,
                    bet,
                    "SETTLEMENT_PENDING",
                    event_type="settlement_pending",
                    payload=payload,
                )
                pending += 1
                continue
            bankroll = _get_bankroll(bankroll_map, session, bet.bankroll_id)
            if bankroll is None:
                continue
            _void_bet(session, bet, bankroll=bankroll, reason="match_cancelled", payload=payload)
            voided += 1
            continue

        bet.feed_health_status = "missing"
        _mark_bet_status(
            session,
            bet,
            "ORPHANED_FEED",
            event_type="feed_missing_detected",
            payload={"reason": "missing_from_feed", **payload},
        )
        orphaned += 1

    if any((restored, voided, orphaned, live, pending)):
        session.commit()
    return {
        "removed": 0,
        "refunded": 0.0,
        "voided": voided,
        "orphaned": orphaned,
        "live": live,
        "pending": pending,
    }


def get_or_create_agent_bankroll(session: Session) -> Bankroll:
    bankroll = session.query(Bankroll).filter(Bankroll.name == "DraftGap Agent").first()
    if bankroll is not None:
        return bankroll
    bankroll = Bankroll(
        name="DraftGap Agent",
        currency="USD",
        initial_balance=Decimal("1000.00"),
        current_balance=Decimal("1000.00"),
        staking_model="kelly_quarter",
        kelly_fraction=Decimal("0.250"),
        max_bet_pct=Decimal("0.0500"),
        min_edge_threshold=Decimal("0.0300"),
    )
    session.add(bankroll)
    session.commit()
    session.refresh(bankroll)
    return bankroll


class TradingStateResetSummary(TypedDict):
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


def reset_trading_state_preserve_ml(session: Session) -> TradingStateResetSummary:
    bankroll = get_or_create_agent_bankroll(session)
    bid = bankroll.id
    bet_events_deleted = session.query(BetEvent).filter(BetEvent.bankroll_id == bid).delete(
        synchronize_session=False
    )
    bets_deleted = session.query(Bet).filter(Bet.bankroll_id == bid).delete(synchronize_session=False)
    bankroll_snapshots_deleted = session.query(BankrollSnapshot).filter(
        BankrollSnapshot.bankroll_id == bid
    ).delete(synchronize_session=False)
    bankroll.current_balance = bankroll.initial_balance
    prediction_logs_deleted = session.query(PredictionLog).delete(synchronize_session=False)
    upcoming_snapshots_deleted = session.query(UpcomingWithOddsSnapshot).delete(synchronize_session=False)
    live_snapshots_deleted = session.query(LiveWithOddsSnapshot).delete(synchronize_session=False)
    betting_results_snapshots_deleted = session.query(BettingResultsSnapshot).delete(synchronize_session=False)
    bankroll_summary_snapshots_deleted = session.query(BankrollSummarySnapshot).delete(
        synchronize_session=False
    )
    power_rankings_snapshots_deleted = session.query(PowerRankingsSnapshot).delete(synchronize_session=False)
    homepage_manifest_snapshots_deleted = session.query(HomepageSnapshotManifest).delete(
        synchronize_session=False
    )
    session.commit()
    session.refresh(bankroll)
    return {
        "bet_events_deleted": int(bet_events_deleted or 0),
        "bets_deleted": int(bets_deleted or 0),
        "bankroll_snapshots_deleted": int(bankroll_snapshots_deleted or 0),
        "prediction_logs_deleted": int(prediction_logs_deleted or 0),
        "upcoming_snapshots_deleted": int(upcoming_snapshots_deleted or 0),
        "live_snapshots_deleted": int(live_snapshots_deleted or 0),
        "betting_results_snapshots_deleted": int(betting_results_snapshots_deleted or 0),
        "bankroll_summary_snapshots_deleted": int(bankroll_summary_snapshots_deleted or 0),
        "power_rankings_snapshots_deleted": int(power_rankings_snapshots_deleted or 0),
        "homepage_manifest_snapshots_deleted": int(homepage_manifest_snapshots_deleted or 0),
    }


FORCE_BET_WINDOW = timedelta(hours=4)
BLOCKED_STATUS_BY_REASON = {
    "missing_bookie_odds": "blocked_missing_odds",
    "team_resolution_failed": "blocked_team_resolution_failed",
    "model_unavailable": "blocked_model_unavailable",
    "prediction_unavailable": "blocked_prediction_unavailable",
    "tbd_team": "blocked_tbd",
    "invalid_stake": "blocked_invalid_stake",
    "league_not_bettable": "blocked_league_not_bettable",
    "tier_not_bettable": "blocked_tier_not_bettable",
    "status_generation_failed": "blocked_status_generation_failed",
}
MISSING_INPUT_REASONS = {
    "invalid_match_id",
    "missing_bookie_odds",
    "team_resolution_failed",
    "model_unavailable",
    "prediction_unavailable",
    "tbd_team",
    "invalid_stake",
    "league_not_bettable",
    "tier_not_bettable",
    "status_generation_failed",
}


def _parse_match_scheduled_at(match: dict[str, object]) -> datetime | None:
    value = str(match.get("scheduled_at") or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _datetime_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _force_bet_after(match: dict[str, object]) -> datetime | None:
    scheduled_at = _parse_match_scheduled_at(match)
    if scheduled_at is None:
        return None
    return scheduled_at - FORCE_BET_WINDOW


def _placement_status_for_reason(reason_code: str) -> str:
    if reason_code == "below_edge_waiting":
        return "waiting_for_better_odds"
    return BLOCKED_STATUS_BY_REASON.get(reason_code, f"blocked_{reason_code}")


def _build_reason_result(
    match_id: int,
    match: dict[str, object],
    reason_code: str,
    *,
    reason_detail: str | None = None,
    force_bet_after: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current_time = now or datetime.now(timezone.utc)
    computed_force_bet_after = force_bet_after if force_bet_after is not None else _force_bet_after(match)
    within_force_window = (
        isinstance(computed_force_bet_after, datetime)
        and current_time >= computed_force_bet_after
    )
    return {
        "pandascore_match_id": match_id,
        "series_key": make_series_key(match_id),
        "status": _placement_status_for_reason(reason_code),
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "short_detail": _short_detail_for_reason(reason_code),
        "force_bet_after": computed_force_bet_after,
        "within_force_window": within_force_window,
        "should_force_bet": within_force_window,
    }


def _market_pair_probability(
    offers: list[dict[str, object]],
    selection_key: str,
    fallback_odds: Decimal,
) -> Decimal:
    if len(offers) >= 2:
        paired = [
            _to_decimal(offer.get("decimal_odds"))
            for offer in offers
            if _to_decimal(offer.get("decimal_odds")) > Decimal("1")
        ]
        if len(paired) >= 2:
            selected = next(
                (_to_decimal(offer.get("decimal_odds")) for offer in offers if str(offer.get("selection_key")) == selection_key),
                fallback_odds,
            )
            other = next(
                (_to_decimal(offer.get("decimal_odds")) for offer in offers if str(offer.get("selection_key")) != selection_key),
                None,
            )
            if other is not None and selected > Decimal("1") and other > Decimal("1"):
                prob_a, prob_b = remove_vig(selected, other)
                return prob_a if str(offers[0].get("selection_key")) == selection_key else (prob_a if str(offers[0].get("selection_key")) != selection_key and selected == other else (prob_a if selected == _to_decimal(offers[0].get("decimal_odds")) else prob_b))
    return implied_prob(fallback_odds)


def _expected_log_growth_decimal(model_prob: Decimal, odds: Decimal, stake: Decimal, bankroll: Decimal) -> Decimal:
    if bankroll <= Decimal("0"):
        return Decimal("0")
    fraction = float(max(Decimal("0"), stake / bankroll))
    return Decimal(str(expected_log_growth(float(model_prob), float(odds), fraction)))


def _group_market_offers(offers: list[dict[str, object]]) -> dict[tuple[str, float | None], list[dict[str, object]]]:
    grouped: dict[tuple[str, float | None], list[dict[str, object]]] = {}
    for offer in offers:
        key = (str(offer.get("market_type") or ""), _to_float(offer.get("line_value")) if offer.get("line_value") is not None else None)
        grouped.setdefault(key, []).append(offer)
    return grouped


def _selection_team_name(selection_key: str, *, team_a: str, team_b: str) -> str | None:
    if selection_key.startswith("team_a"):
        return team_a
    if selection_key.startswith("team_b"):
        return team_b
    return None


def _market_stake_multiplier(market_type: str) -> Decimal:
    return Decimal("1.0") if market_type == "match_winner" else DERIVATIVE_MARKET_STAKE_MULTIPLIER


def _build_market_candidates(
    *,
    bankroll: Bankroll,
    match_id: int,
    series_key: str,
    team_a: str,
    team_b: str,
    number_of_games: int,
    confidence: Decimal,
    series_prob_a: Decimal,
    series_prob_b: Decimal,
    map_win_prob_a: Decimal,
    exact_score_rows: object,
    offers: list[dict[str, object]],
    model_run_id: int | None,
    force_bet_after: datetime | None,
    within_force_window: bool,
    entry_phase: str,
    score_a: int,
    score_b: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped = _group_market_offers(offers)
    candidates: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    bankroll_balance = _to_decimal(bankroll.current_balance)
    exact_scores = exact_score_rows if isinstance(exact_score_rows, list) else []

    for (market_type, line_value), market_offers in grouped.items():
        for offer in market_offers:
            selection_key = str(offer.get("selection_key") or "")
            book_odds = _to_decimal(offer.get("decimal_odds"))
            if book_odds <= Decimal("1"):
                rejected.append(
                    {
                        "market_type": market_type,
                        "selection_key": selection_key,
                        "reason": "invalid_odds",
                        "book_odds": float(book_odds),
                    }
                )
                continue

            chosen_team = _selection_team_name(selection_key, team_a=team_a, team_b=team_b)
            if market_type == "match_winner":
                model_prob = series_prob_a if selection_key == "team_a" else series_prob_b
                opposite_key = "team_b" if selection_key == "team_a" else "team_a"
                opposite_offer = next((row for row in market_offers if str(row.get("selection_key")) == opposite_key), None)
                book_prob = remove_vig(book_odds, _to_decimal(opposite_offer.get("decimal_odds"))) [0] if opposite_offer is not None else implied_prob(book_odds)
            elif market_type == "map_handicap":
                if line_value is None or chosen_team is None:
                    rejected.append(
                        {
                            "market_type": market_type,
                            "selection_key": selection_key,
                            "reason": "invalid_line",
                            "line_value": line_value,
                        }
                    )
                    continue
                side = "team_a" if selection_key.startswith("team_a") else "team_b"
                model_prob = Decimal(str(handicap_cover_probability(exact_scores, side=side, line_value=float(line_value))))
                paired_offer = next(
                    (
                        row
                        for row in market_offers
                        if str(row.get("selection_key", "")).split("_", 1)[0] != str(selection_key).split("_", 1)[0]
                    ),
                    None,
                )
                if paired_offer is not None:
                    book_prob = remove_vig(book_odds, _to_decimal(paired_offer.get("decimal_odds")))[0]
                else:
                    book_prob = implied_prob(book_odds)
            elif market_type == "total_maps":
                if line_value is None:
                    rejected.append(
                        {
                            "market_type": market_type,
                            "selection_key": selection_key,
                            "reason": "invalid_line",
                            "line_value": line_value,
                        }
                    )
                    continue
                total_side = "over" if selection_key.startswith("over_") else "under"
                model_prob = Decimal(str(total_maps_probability(exact_scores, bet=total_side, line_value=float(line_value))))
                paired_offer = next(
                    (
                        row
                        for row in market_offers
                        if str(row.get("selection_key", "")).split("_", 1)[0] != str(selection_key).split("_", 1)[0]
                    ),
                    None,
                )
                if paired_offer is not None:
                    book_prob = remove_vig(book_odds, _to_decimal(paired_offer.get("decimal_odds")))[0]
                else:
                    book_prob = implied_prob(book_odds)
            else:
                rejected.append({"market_type": market_type, "selection_key": selection_key, "reason": "unsupported_market"})
                continue

            market_confidence_floor = MIN_CANDIDATE_CONFIDENCE if market_type == "match_winner" else MIN_DERIVATIVE_CONFIDENCE
            if confidence < market_confidence_floor:
                rejected.append(
                    {
                        "market_type": market_type,
                        "selection_key": selection_key,
                        "reason": "low_confidence",
                        "confidence": float(confidence),
                        "confidence_threshold": float(market_confidence_floor),
                    }
                )
                continue

            edge = compute_edge(model_prob, book_prob)
            raw_stake = kelly_stake(
                model_prob,
                book_odds,
                bankroll_balance,
                fraction=bankroll.kelly_fraction,
                max_pct=bankroll.max_bet_pct,
                min_stake=Decimal("25.00"),
            )
            stake = raw_stake * _market_stake_multiplier(market_type)
            if stake <= Decimal("0"):
                rejected.append(
                    {
                        "market_type": market_type,
                        "selection_key": selection_key,
                        "reason": "invalid_stake",
                        "stake": float(stake),
                    }
                )
                continue

            ev = compute_ev(model_prob, book_odds, stake)
            if ev < MIN_CANDIDATE_EV:
                rejected.append(
                    {
                        "market_type": market_type,
                        "selection_key": selection_key,
                        "reason": "low_ev",
                        "ev": float(ev),
                        "min_ev": float(MIN_CANDIDATE_EV),
                    }
                )
                continue

            candidates.append(
                {
                    "pandascore_match_id": match_id,
                    "series_key": series_key,
                    "team_a": team_a,
                    "team_b": team_b,
                    "team_a_model_prob": series_prob_a,
                    "team_b_model_prob": series_prob_b,
                    "team_a_book_odds": None,
                    "team_b_book_odds": None,
                    "market_type": market_type,
                    "selection_key": selection_key,
                    "line_value": line_value,
                    "chosen_team": chosen_team or (selection_key.replace("_", " ").title()),
                    "chosen_model_prob": model_prob,
                    "chosen_book_prob": book_prob,
                    "chosen_book_odds": book_odds,
                    "chosen_edge": edge,
                    "stake": stake,
                    "ev": ev,
                    "expected_log_growth": _expected_log_growth_decimal(model_prob, book_odds, stake, bankroll_balance),
                    "model_run_id": model_run_id,
                    "number_of_games": number_of_games,
                    "force_bet_after": force_bet_after,
                    "within_force_window": within_force_window,
                    "should_force_bet": within_force_window and market_type == "match_winner",
                    "entry_phase": entry_phase,
                    "entry_score_team_a": score_a,
                    "entry_score_team_b": score_b,
                    "current_score_team_a": score_a,
                    "current_score_team_b": score_b,
                    "odds_source_status": "available",
                    "live_rebet_allowed": entry_phase == REBET_ENTRY_PHASE and market_type == "match_winner",
                    "confidence": confidence,
                    "source_book": str(offer.get("source_book") or "thunderpick"),
                    "source_market_name": offer.get("source_market_name"),
                    "source_selection_name": offer.get("source_selection_name"),
                    "model_snapshot_json": {
                        "entry_phase": entry_phase,
                        "series_score_a": score_a,
                        "series_score_b": score_b,
                        "number_of_games": number_of_games,
                        "series_prob_a": float(series_prob_a),
                        "series_prob_b": float(series_prob_b),
                        "map_win_prob_a": float(map_win_prob_a),
                        "candidate_market_type": market_type,
                    },
                }
            )

    candidates.sort(
        key=lambda candidate: (
            _to_decimal(candidate.get("expected_log_growth")),
            _to_decimal(candidate.get("ev")),
            _to_decimal(candidate.get("chosen_edge")),
        ),
        reverse=True,
    )
    return candidates, rejected


def _choose_bookie_favorite_candidate(
    bankroll: Bankroll,
    team_a: str,
    team_b: str,
    odds_a: Decimal,
    odds_b: Decimal,
    *,
    number_of_games: int,
    model_run_id: int | None = None,
    force_bet_after: datetime | None = None,
    reason_detail: str | None = None,
) -> dict[str, object] | None:
    true_prob_a, true_prob_b = remove_vig(odds_a, odds_b)
    if odds_a <= odds_b:
        chosen_team = team_a
        chosen_model_prob = true_prob_a
        chosen_book_prob = true_prob_a
        chosen_book_odds = odds_a
    else:
        chosen_team = team_b
        chosen_model_prob = true_prob_b
        chosen_book_prob = true_prob_b
        chosen_book_odds = odds_b

    stake = kelly_stake(
        chosen_model_prob,
        chosen_book_odds,
        bankroll.current_balance,
        fraction=bankroll.kelly_fraction,
        max_pct=bankroll.max_bet_pct,
        min_stake=Decimal("25.00"),
    )
    if stake <= Decimal("0"):
        return None

    return {
        "team_a": team_a,
        "team_b": team_b,
        "market_type": "match_winner",
        "selection_key": "team_a" if chosen_team == team_a else "team_b",
        "line_value": None,
        "chosen_team": chosen_team,
        "chosen_model_prob": chosen_model_prob,
        "chosen_book_prob": chosen_book_prob,
        "chosen_book_odds": chosen_book_odds,
        "chosen_edge": Decimal("0"),
        "stake": stake,
        "ev": compute_ev(chosen_model_prob, chosen_book_odds, stake),
        "expected_log_growth": _expected_log_growth_decimal(chosen_model_prob, chosen_book_odds, stake, _to_decimal(bankroll.current_balance)),
        "model_run_id": model_run_id,
        "number_of_games": number_of_games,
        "force_bet_after": force_bet_after,
        "within_force_window": True,
        "should_force_bet": True,
        "reason_detail": reason_detail or "Forced bet fallback used bookie favorite.",
        "source_book": "thunderpick",
        "source_market_name": "Match Winner",
        "source_selection_name": chosen_team,
    }


def _evaluate_match_for_betting(
    session: Session,
    resolver: EntityResolver,
    bankroll: Bankroll,
    match: dict[str, object],
    bookie_odds: object,
    *,
    now: datetime,
    model_available: bool,
) -> dict[str, object]:
    match_id = int(match.get("id") or 0)
    series_key = make_series_key(match_id)
    force_bet_after = _force_bet_after(match)
    within_force_window = isinstance(force_bet_after, datetime) and now >= force_bet_after
    eligibility = classify_match_betting_eligibility(match)
    number_of_games = int(match.get("number_of_games") or 1)
    team_a, team_b = _team_names(match)
    score_a, score_b = _score_from_match(match)
    entry_phase = PREMATCH_ENTRY_PHASE if (score_a == 0 and score_b == 0) else REBET_ENTRY_PHASE
    if not bool(eligibility.get("is_bettable")):
        return _attach_match_metadata(
            _build_reason_result(
                match_id,
                match,
                str(eligibility.get("eligibility_reason") or "league_not_bettable"),
                reason_detail="Match is visible in the feed but excluded from betting eligibility.",
                force_bet_after=force_bet_after,
                now=now,
            ),
            eligibility=eligibility,
            terminal_outcome="excluded",
        )
    if team_a == "TBD" or team_b == "TBD":
        return _attach_match_metadata(
            _build_reason_result(
                match_id,
                match,
                "tbd_team",
                reason_detail="One or both teams are still TBD.",
                force_bet_after=force_bet_after,
                now=now,
            ),
            eligibility=eligibility,
            terminal_outcome="blocked",
        )

    acr_a, acr_b = _team_acronyms(match)
    market_set = find_market_set_for_match(team_a, team_b, bookie_odds, acronym1=acr_a, acronym2=acr_b)
    market_offers = list(market_set.get("offers", [])) if isinstance(market_set.get("offers"), list) else []
    matched_row_team1 = str(market_set.get("matched_row_team1") or "") or None
    matched_row_team2 = str(market_set.get("matched_row_team2") or "") or None
    bookie_match_confidence = str(market_set.get("confidence") or "") or None
    odds_resolution = resolve_match_odds(
        team_a,
        team_b,
        odds_list=read_odds_from_file(),
        market_catalog=bookie_odds,
        acronym1=acr_a,
        acronym2=acr_b,
    )
    odds_a_raw = odds_resolution["odds1"]
    odds_b_raw = odds_resolution["odds2"]
    if not market_offers:
        result = _build_reason_result(
            match_id,
            match,
            "missing_bookie_odds",
            reason_detail="No matching Thunderpick markets were found for this match.",
            force_bet_after=force_bet_after,
            now=now,
        )
        result["odds_source_status"] = "missing"
        return _attach_match_metadata(_attach_candidate_diagnostics(
            result,
            bankroll=bankroll,
            bookie_match_confidence=bookie_match_confidence,
            matched_row_team1=matched_row_team1,
            matched_row_team2=matched_row_team2,
            short_detail_reason="missing_bookie_odds",
        ), eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="blocked")
    odds_a = _to_decimal(odds_a_raw) if odds_a_raw is not None else Decimal("0")
    odds_b = _to_decimal(odds_b_raw) if odds_b_raw is not None else Decimal("0")

    opponents = match.get("opponents") or []
    ps_id_a = ((opponents[0].get("opponent") or {}).get("id") if len(opponents) > 0 else None) or None
    ps_id_b = ((opponents[1].get("opponent") or {}).get("id") if len(opponents) > 1 else None) or None
    team_model_a = resolver.resolve_team(team_a, "pandascore", pandascore_id=ps_id_a, abbreviation=acr_a)
    team_model_b = resolver.resolve_team(team_b, "pandascore", pandascore_id=ps_id_b, abbreviation=acr_b)
    if team_model_a is None or team_model_b is None:
        if within_force_window:
            candidate = _choose_bookie_favorite_candidate(
                bankroll,
                team_a,
                team_b,
                odds_a,
                odds_b,
                number_of_games=number_of_games,
                force_bet_after=force_bet_after,
                reason_detail="Forced bet fallback used bookie favorite because team resolution failed.",
            )
            if candidate is not None:
                candidate["series_key"] = series_key
                candidate["entry_phase"] = entry_phase
                candidate["entry_score_team_a"] = score_a
                candidate["entry_score_team_b"] = score_b
                candidate["current_score_team_a"] = score_a
                candidate["current_score_team_b"] = score_b
                candidate["odds_source_status"] = "available"
                candidate["team_a_model_prob"] = candidate.get("chosen_model_prob")
                candidate["team_b_model_prob"] = Decimal("1.00") - _to_decimal(candidate.get("chosen_model_prob"))
                _attach_candidate_diagnostics(
                    candidate,
                    bankroll=bankroll,
                    market_type="match_winner",
                    chosen_edge=_to_decimal(candidate.get("chosen_edge")),
                    ev=_to_decimal(candidate.get("ev")),
                    bookie_match_confidence=bookie_match_confidence,
                    matched_row_team1=matched_row_team1,
                    matched_row_team2=matched_row_team2,
                )
                return _attach_match_metadata(candidate, eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="pending")
        result = _build_reason_result(
            match_id,
            match,
            "team_resolution_failed",
            reason_detail="Could not resolve one or both teams for model prediction.",
            force_bet_after=force_bet_after,
            now=now,
        )
        return _attach_match_metadata(_attach_candidate_diagnostics(
            result,
            bankroll=bankroll,
            bookie_match_confidence=bookie_match_confidence,
            matched_row_team1=matched_row_team1,
            matched_row_team2=matched_row_team2,
            short_detail_reason="team_resolution_failed",
        ), eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="blocked")

    league_slug = str(((match.get("league") or {}).get("slug") or ""))
    model_odds_a, model_odds_b, _, _, model_run_id = predict_for_pandascore_match(
        session,
        team_model_a.id,
        team_model_b.id,
        number_of_games=number_of_games,
        score_a=0,
        score_b=0,
        league_slug=league_slug,
    )
    if model_odds_a is None or model_odds_b is None:
        if within_force_window:
            candidate = _choose_bookie_favorite_candidate(
                bankroll,
                team_a,
                team_b,
                odds_a,
                odds_b,
                number_of_games=number_of_games,
                model_run_id=model_run_id,
                force_bet_after=force_bet_after,
                reason_detail="Forced bet fallback used bookie favorite because model output was unavailable.",
            )
            if candidate is not None:
                candidate["series_key"] = series_key
                candidate["entry_phase"] = entry_phase
                candidate["entry_score_team_a"] = score_a
                candidate["entry_score_team_b"] = score_b
                candidate["current_score_team_a"] = score_a
                candidate["current_score_team_b"] = score_b
                candidate["odds_source_status"] = "available"
                candidate["team_a_model_prob"] = candidate.get("chosen_model_prob")
                candidate["team_b_model_prob"] = Decimal("1.00") - _to_decimal(candidate.get("chosen_model_prob"))
                _attach_candidate_diagnostics(
                    candidate,
                    bankroll=bankroll,
                    market_type="match_winner",
                    chosen_edge=_to_decimal(candidate.get("chosen_edge")),
                    ev=_to_decimal(candidate.get("ev")),
                    bookie_match_confidence=bookie_match_confidence,
                    matched_row_team1=matched_row_team1,
                    matched_row_team2=matched_row_team2,
                )
                return _attach_match_metadata(candidate, eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="pending")
        result = _build_reason_result(
            match_id,
            match,
            "model_unavailable" if not model_available else "prediction_unavailable",
            reason_detail="No model prediction was available for this match.",
            force_bet_after=force_bet_after,
            now=now,
        )
        return _attach_match_metadata(_attach_candidate_diagnostics(
            result,
            bankroll=bankroll,
            bookie_match_confidence=bookie_match_confidence,
            matched_row_team1=matched_row_team1,
            matched_row_team2=matched_row_team2,
            short_detail_reason=str(result.get("reason_code") or ""),
        ), eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="blocked")

    recommendation = predict_live_rebet_context(
        session,
        team_model_a.id,
        team_model_b.id,
        number_of_games=number_of_games,
        score_a=score_a,
        score_b=score_b,
        league_slug=league_slug,
        bookie_odds_a=float(odds_a) if odds_a > Decimal("1") else None,
        bookie_odds_b=float(odds_b) if odds_b > Decimal("1") else None,
    )
    if recommendation is None:
        result = _build_reason_result(
            match_id,
            match,
            "prediction_unavailable",
            reason_detail="No model prediction was available for this match.",
            force_bet_after=force_bet_after,
            now=now,
        )
        return _attach_match_metadata(_attach_candidate_diagnostics(
            result,
            bankroll=bankroll,
            bookie_match_confidence=bookie_match_confidence,
            matched_row_team1=matched_row_team1,
            matched_row_team2=matched_row_team2,
            short_detail_reason="prediction_unavailable",
        ), eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="blocked")

    series_prob_a = _to_decimal(recommendation.get("series_win_prob_a"), default=implied_prob(_to_decimal(model_odds_a)))
    series_prob_b = _to_decimal(recommendation.get("series_win_prob_b"), default=implied_prob(_to_decimal(model_odds_b)))
    map_win_prob_a = _to_decimal(
        recommendation.get("adjusted_game_win_prob_a"),
        default=Decimal(str(infer_map_win_probability(float(series_prob_a), number_of_games))),
    )
    confidence = _to_decimal(recommendation.get("confidence"), default=Decimal("0.50"))
    exact_score_rows = compute_exact_score_probabilities(float(map_win_prob_a), number_of_games)
    candidates, rejected_candidates = _build_market_candidates(
        bankroll=bankroll,
        match_id=match_id,
        series_key=series_key,
        team_a=team_a,
        team_b=team_b,
        number_of_games=number_of_games,
        confidence=confidence,
        series_prob_a=series_prob_a,
        series_prob_b=series_prob_b,
        map_win_prob_a=map_win_prob_a,
        exact_score_rows=exact_score_rows,
        offers=market_offers,
        model_run_id=model_run_id,
        force_bet_after=force_bet_after,
        within_force_window=within_force_window,
        entry_phase=entry_phase,
        score_a=score_a,
        score_b=score_b,
    )
    if not candidates:
        if within_force_window and odds_a > Decimal("1") and odds_b > Decimal("1"):
            candidate = _choose_bookie_favorite_candidate(
                bankroll,
                team_a,
                team_b,
                odds_a,
                odds_b,
                number_of_games=number_of_games,
                model_run_id=model_run_id,
                force_bet_after=force_bet_after,
                reason_detail="Forced bet fallback used match winner because no multi-market candidate qualified.",
            )
            if candidate is not None:
                candidate["series_key"] = series_key
                candidate["entry_phase"] = entry_phase
                candidate["entry_score_team_a"] = score_a
                candidate["entry_score_team_b"] = score_b
                candidate["current_score_team_a"] = score_a
                candidate["current_score_team_b"] = score_b
                candidate["odds_source_status"] = "available"
                candidate["team_a_model_prob"] = series_prob_a
                candidate["team_b_model_prob"] = series_prob_b
                _attach_candidate_diagnostics(
                    candidate,
                    bankroll=bankroll,
                    market_type="match_winner",
                    chosen_edge=_to_decimal(candidate.get("chosen_edge")),
                    confidence=confidence,
                    ev=_to_decimal(candidate.get("ev")),
                    bookie_match_confidence=bookie_match_confidence,
                    matched_row_team1=matched_row_team1,
                    matched_row_team2=matched_row_team2,
                    rejected_candidates=rejected_candidates,
                )
                return _attach_match_metadata(candidate, eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="pending")
        primary_reason = _primary_rejected_reason(rejected_candidates) or "prediction_unavailable"
        result = _build_reason_result(
            match_id,
            match,
            primary_reason,
            reason_detail="Thunderpick markets were found, but no candidate cleared the model confidence or EV gates.",
            force_bet_after=force_bet_after,
            now=now,
        )
        return _attach_match_metadata(_attach_candidate_diagnostics(
            result,
            bankroll=bankroll,
            confidence=confidence,
            bookie_match_confidence=bookie_match_confidence,
            matched_row_team1=matched_row_team1,
            matched_row_team2=matched_row_team2,
            rejected_candidates=rejected_candidates,
            short_detail_reason=primary_reason,
        ), eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="blocked")

    best = candidates[0]
    _attach_candidate_diagnostics(
        best,
        bankroll=bankroll,
        market_type=str(best.get("market_type") or "match_winner"),
        chosen_edge=_to_decimal(best.get("chosen_edge")),
        confidence=confidence,
        ev=_to_decimal(best.get("ev")),
        bookie_match_confidence=bookie_match_confidence,
        matched_row_team1=matched_row_team1,
        matched_row_team2=matched_row_team2,
        rejected_candidates=rejected_candidates,
    )
    best["recommended_bet"] = {
        "market_type": best.get("market_type"),
        "selection_key": best.get("selection_key"),
        "line_value": best.get("line_value"),
        "bet_on": best.get("chosen_team"),
        "locked_odds": float(_to_decimal(best.get("chosen_book_odds"))),
        "edge": float(_to_decimal(best.get("chosen_edge"))),
        "stake": float(_to_decimal(best.get("stake"))),
    }
    return _attach_match_metadata(best, eligibility=eligibility, odds_resolution=odds_resolution, terminal_outcome="pending")


def _choose_match_bet_candidate(
    session: Session,
    resolver: EntityResolver,
    bankroll: Bankroll,
    match: dict[str, object],
    bookie_odds: object,
) -> dict[str, object] | None:
    from ml.predictor_v2 import get_prediction_runtime_status

    result = _evaluate_match_for_betting(
        session,
        resolver,
        bankroll,
        match,
        bookie_odds,
        now=datetime.now(timezone.utc),
        model_available=get_prediction_runtime_status(session).get("active_model_id") is not None,
    )
    return result if "chosen_team" in result else None


def _next_bet_sequence(session: Session, series_key: str) -> int:
    latest = (
        session.query(Bet)
        .filter(Bet.series_key == series_key)
        .order_by(Bet.bet_sequence.desc(), Bet.placed_at.desc())
        .first()
    )
    return int(latest.bet_sequence) + 1 if latest is not None else 1


def _can_place_rebet(
    existing_positions: list[Bet],
    candidate: dict[str, object],
    *,
    bankroll: Bankroll,
    now: datetime,
) -> tuple[bool, str | None, dict[str, object]]:
    team_a = str(candidate.get("team_a") or "")
    team_b = str(candidate.get("team_b") or "")
    candidate_market_type = str(candidate.get("market_type") or "match_winner")
    exposure = _build_series_exposure_snapshot(existing_positions, team_a=team_a, team_b=team_b)
    candidate_team = str(candidate.get("chosen_team") or "")
    candidate_stake = _to_decimal(candidate.get("stake"))
    candidate_side_stake = _to_decimal(exposure["stake_by_team"].get(candidate_team, Decimal("0.00"))) if isinstance(exposure["stake_by_team"], dict) else Decimal("0.00")
    other_team = team_b if _same_team(candidate_team, team_a) else team_a
    other_side_stake = _to_decimal(exposure["stake_by_team"].get(other_team, Decimal("0.00"))) if isinstance(exposure["stake_by_team"], dict) else Decimal("0.00")
    series_ev_before = _series_expected_value(
        existing_positions,
        team_a=team_a,
        team_b=team_b,
        prob_a=_to_decimal(candidate.get("team_a_model_prob"), default=_to_decimal(candidate.get("chosen_model_prob"))),
        prob_b=_to_decimal(candidate.get("team_b_model_prob"), default=Decimal("1.00") - _to_decimal(candidate.get("chosen_model_prob"))),
    )
    series_ev_after = _series_expected_value(
        existing_positions,
        team_a=team_a,
        team_b=team_b,
        prob_a=_to_decimal(candidate.get("team_a_model_prob"), default=_to_decimal(candidate.get("chosen_model_prob"))),
        prob_b=_to_decimal(candidate.get("team_b_model_prob"), default=Decimal("1.00") - _to_decimal(candidate.get("chosen_model_prob"))),
        additional_bet=candidate,
    )
    context = {
        "position_count": exposure["position_count"],
        "team_stake_totals": {
            team_a: float(_to_decimal(exposure["stake_by_team"].get(team_a, Decimal("0.00")))),
            team_b: float(_to_decimal(exposure["stake_by_team"].get(team_b, Decimal("0.00")))),
        },
        "net_side": exposure["net_side"],
        "net_stake_delta": float(_to_decimal(exposure["net_stake_delta"])),
        "has_conflicting_positions": bool(exposure["has_conflicting_positions"]),
        "candidate_team": candidate_team,
        "candidate_stake": float(candidate_stake),
        "series_ev_before": float(series_ev_before),
        "series_ev_after": float(series_ev_after),
        "series_ev_delta": float(series_ev_after - series_ev_before),
    }
    if not existing_positions:
        return (True, None, context)

    if str(candidate.get("entry_phase") or PREMATCH_ENTRY_PHASE) != REBET_ENTRY_PHASE:
        return (False, "existing_open_position", context)

    if candidate_market_type != "match_winner":
        return (False, "cross_market_stacking_blocked", context)

    if any(str(position.market_type or "match_winner") != candidate_market_type for position in existing_positions):
        return (False, "cross_market_stacking_blocked", context)

    total_stake_after = _to_decimal(exposure["total_stake"]) + candidate_stake
    if total_stake_after > _series_exposure_cap(bankroll):
        return (False, "series_exposure_cap", context)

    same_side_positions = [
        position
        for position in existing_positions
        if _same_team(position.bet_on, candidate_team)
    ]
    opposite_side_positions = [
        position
        for position in existing_positions
        if not _same_team(position.bet_on, candidate_team)
    ]
    if same_side_positions:
        latest_same_side = max(same_side_positions, key=lambda item: item.placed_at)
        if latest_same_side.placed_at and latest_same_side.placed_at >= now - REBET_COOLDOWN:
            return (False, "series_conflict_cooldown", context)
        prior_edge = _to_decimal(latest_same_side.edge)
        current_edge = _to_decimal(candidate.get("chosen_edge"))
        prior_odds = _to_decimal(latest_same_side.book_odds_locked)
        current_odds = _to_decimal(candidate.get("chosen_book_odds"))
        if current_edge < prior_edge + REBET_MIN_EDGE_DELTA and current_odds < prior_odds + REBET_MIN_ODDS_IMPROVEMENT:
            return (False, "existing_position_preferred", context)

    if opposite_side_positions:
        latest_conflict = max(opposite_side_positions, key=lambda item: item.placed_at)
        if latest_conflict.placed_at and latest_conflict.placed_at >= now - SERIES_CONFLICT_COOLDOWN:
            return (False, "series_conflict_cooldown", context)
        if series_ev_after < series_ev_before + SERIES_MIN_EV_IMPROVEMENT:
            return (False, "hedge_not_improving", context)
        if candidate_side_stake + candidate_stake > other_side_stake + _to_decimal(exposure["net_stake_delta"]):
            return (False, "hedge_not_improving", context)

    if series_ev_after <= series_ev_before:
        return (False, "series_net_ev_negative", context)

    return (True, None, context)


def get_upcoming_match_betting_statuses(
    session: Session,
    matches: list[dict[str, object]] | None = None,
) -> list[MatchBettingStatusSummary]:
    from ml.predictor_v2 import get_prediction_runtime_status

    bankroll = get_or_create_agent_bankroll(session)
    raw_matches = matches if matches is not None else (read_upcoming_matches_from_file() or [])
    upcoming_matches = [
        m for m in raw_matches if isinstance(m, dict) and match_belongs_on_upcoming_odds_feed(m)
    ]
    if not upcoming_matches:
        return []

    existing_bets_by_match: dict[int, list[Bet]] = {}
    for bet in (
        session.query(Bet)
        .filter(Bet.bankroll_id == bankroll.id, Bet.status.in_(sorted(OPEN_BET_STATUSES)))
        .order_by(Bet.placed_at.desc())
        .all()
    ):
        existing_bets_by_match.setdefault(int(bet.pandascore_match_id), []).append(bet)
    bookie_odds = read_market_catalog_from_file()
    resolver = EntityResolver(session)
    now = datetime.now(timezone.utc)
    model_available = get_prediction_runtime_status(session).get("active_model_id") is not None
    statuses: list[MatchBettingStatusSummary] = []

    for match in upcoming_matches:
        match_id = int(match.get("id") or 0)
        if match_id <= 0:
            continue
        eligibility = classify_match_betting_eligibility(match)

        existing_positions = existing_bets_by_match.get(match_id, [])
        if existing_positions:
            existing_bet = existing_positions[0]
            team_a_name, team_b_name = _team_names(match)
            exposure = _build_series_exposure_snapshot(existing_positions, team_a=team_a_name, team_b=team_b_name)
            statuses.append(
                {
                    "pandascore_match_id": match_id,
                    "series_key": existing_bet.series_key,
                    "status": "placed",
                    "bet_on": existing_bet.bet_on,
                    "market_type": existing_bet.market_type,
                    "selection_key": existing_bet.selection_key,
                    "line_value": float(existing_bet.line_value) if existing_bet.line_value is not None else None,
                    "locked_odds": float(existing_bet.book_odds_locked),
                    "stake": float(existing_bet.actual_stake),
                    "position_count": len(existing_positions),
                    "is_bettable": bool(eligibility.get("is_bettable", True)),
                    "eligibility_reason": str(eligibility.get("eligibility_reason") or "") or None,
                    "normalized_identity": str(eligibility.get("normalized_identity") or "") or None,
                    "terminal_outcome": "placed",
                    "series_decision_context": {
                        "team_stake_totals": {
                            team_a_name: float(_to_decimal(exposure["stake_by_team"].get(team_a_name, Decimal("0.00")))),
                            team_b_name: float(_to_decimal(exposure["stake_by_team"].get(team_b_name, Decimal("0.00")))),
                        },
                        "net_side": exposure["net_side"],
                        "net_stake_delta": float(_to_decimal(exposure["net_stake_delta"])),
                        "has_conflicting_positions": bool(exposure["has_conflicting_positions"]),
                    },
                }
            )
            continue

        candidate = _evaluate_match_for_betting(
            session,
            resolver,
            bankroll,
            match,
            bookie_odds,
            now=now,
            model_available=model_available,
        )
        candidate_status = str(candidate.get("status") or "")
        if "chosen_team" not in candidate:
            statuses.append(
                {
                    "pandascore_match_id": match_id,
                    "series_key": str(candidate.get("series_key") or make_series_key(match_id)),
                    "status": candidate_status or "blocked_status_generation_failed",
                    "reason_code": str(candidate.get("reason_code") or ""),
                    "short_detail": str(candidate.get("short_detail") or "") or _short_detail_for_reason(
                        str(candidate.get("reason_code") or ""),
                        chosen_edge=_to_decimal(candidate.get("chosen_edge")) if candidate.get("chosen_edge") is not None else None,
                        min_edge_threshold=_to_decimal(candidate.get("min_edge_threshold")) if candidate.get("min_edge_threshold") is not None else _to_decimal(bankroll.min_edge_threshold),
                        confidence=_to_decimal(candidate.get("confidence")) if candidate.get("confidence") is not None else None,
                        confidence_threshold=_to_decimal(candidate.get("confidence_threshold")) if candidate.get("confidence_threshold") is not None else None,
                        ev=_to_decimal(candidate.get("ev")) if candidate.get("ev") is not None else None,
                    ),
                    "within_force_window": bool(candidate.get("within_force_window")),
                    "force_bet_after": _datetime_to_iso(
                        candidate.get("force_bet_after") if isinstance(candidate.get("force_bet_after"), datetime) else None
                    ),
                    "chosen_edge": _to_float(candidate.get("chosen_edge")) if candidate.get("chosen_edge") is not None else None,
                    "min_edge_threshold": _to_float(candidate.get("min_edge_threshold")) if candidate.get("min_edge_threshold") is not None else None,
                    "confidence": _to_float(candidate.get("confidence")) if candidate.get("confidence") is not None else None,
                    "confidence_threshold": _to_float(candidate.get("confidence_threshold")) if candidate.get("confidence_threshold") is not None else None,
                    "ev": _to_float(candidate.get("ev")) if candidate.get("ev") is not None else None,
                    "bookie_match_confidence": str(candidate.get("bookie_match_confidence") or "") or None,
                    "matched_row_team1": str(candidate.get("matched_row_team1") or "") or None,
                    "matched_row_team2": str(candidate.get("matched_row_team2") or "") or None,
                    "is_bettable": bool(candidate.get("is_bettable", eligibility.get("is_bettable", True))),
                    "eligibility_reason": str(candidate.get("eligibility_reason") or eligibility.get("eligibility_reason") or "") or None,
                    "normalized_identity": str(candidate.get("normalized_identity") or eligibility.get("normalized_identity") or "") or None,
                    "odds_source_kind": str(candidate.get("odds_source_kind") or "") or None,
                    "odds_source_status": str(candidate.get("odds_source_status") or "") or None,
                    "market_offer_count": int(candidate.get("market_offer_count") or 0),
                    "has_match_winner_offer": bool(candidate.get("has_match_winner_offer")),
                    "terminal_outcome": str(candidate.get("terminal_outcome") or ("excluded" if not eligibility.get("is_bettable", True) else "blocked")),
                    "rejected_candidates": candidate.get("rejected_candidates", []),
                    "series_decision_context": {"rejected_candidates": candidate.get("rejected_candidates", [])},
                }
            )
            continue

        force_bet_after = candidate.get("force_bet_after")
        chosen_edge = candidate["chosen_edge"]
        should_force_bet = bool(candidate.get("should_force_bet"))
        if should_force_bet:
            statuses.append(
                {
                    "pandascore_match_id": match_id,
                    "series_key": str(candidate.get("series_key") or make_series_key(match_id)),
                    "status": "pending_force_bet",
                    "reason_code": "eligible_force_bet",
                    "market_type": str(candidate.get("market_type") or "match_winner"),
                    "selection_key": str(candidate.get("selection_key") or "team_a"),
                    "line_value": _to_float(candidate.get("line_value")) if candidate.get("line_value") is not None else None,
                    "short_detail": str(candidate.get("short_detail") or "") or None,
                    "within_force_window": bool(candidate.get("within_force_window")),
                    "force_bet_after": _datetime_to_iso(force_bet_after if isinstance(force_bet_after, datetime) else None),
                    "chosen_edge": _to_float(candidate.get("chosen_edge")) if candidate.get("chosen_edge") is not None else None,
                    "min_edge_threshold": _to_float(candidate.get("min_edge_threshold")) if candidate.get("min_edge_threshold") is not None else None,
                    "confidence": _to_float(candidate.get("confidence")) if candidate.get("confidence") is not None else None,
                    "confidence_threshold": _to_float(candidate.get("confidence_threshold")) if candidate.get("confidence_threshold") is not None else None,
                    "ev": _to_float(candidate.get("ev")) if candidate.get("ev") is not None else None,
                    "bookie_match_confidence": str(candidate.get("bookie_match_confidence") or "") or None,
                    "matched_row_team1": str(candidate.get("matched_row_team1") or "") or None,
                    "matched_row_team2": str(candidate.get("matched_row_team2") or "") or None,
                    "is_bettable": bool(candidate.get("is_bettable", eligibility.get("is_bettable", True))),
                    "eligibility_reason": str(candidate.get("eligibility_reason") or eligibility.get("eligibility_reason") or "") or None,
                    "normalized_identity": str(candidate.get("normalized_identity") or eligibility.get("normalized_identity") or "") or None,
                    "odds_source_kind": str(candidate.get("odds_source_kind") or "") or None,
                    "odds_source_status": str(candidate.get("odds_source_status") or "") or None,
                    "market_offer_count": int(candidate.get("market_offer_count") or 0),
                    "has_match_winner_offer": bool(candidate.get("has_match_winner_offer")),
                    "terminal_outcome": str(candidate.get("terminal_outcome") or "pending"),
                    "rejected_candidates": candidate.get("rejected_candidates", []),
                    "position_count": 0,
                    "series_decision_context": {"rejected_candidates": candidate.get("rejected_candidates", [])},
                }
            )
            continue
        if chosen_edge >= bankroll.min_edge_threshold:
            statuses.append(
                {
                    "pandascore_match_id": match_id,
                    "series_key": str(candidate.get("series_key") or make_series_key(match_id)),
                    "status": "pending_auto_bet",
                    "reason_code": "eligible_auto_bet",
                    "market_type": str(candidate.get("market_type") or "match_winner"),
                    "selection_key": str(candidate.get("selection_key") or "team_a"),
                    "line_value": _to_float(candidate.get("line_value")) if candidate.get("line_value") is not None else None,
                    "short_detail": str(candidate.get("short_detail") or "") or None,
                    "within_force_window": bool(candidate.get("within_force_window")),
                    "force_bet_after": _datetime_to_iso(force_bet_after if isinstance(force_bet_after, datetime) else None),
                    "chosen_edge": _to_float(candidate.get("chosen_edge")) if candidate.get("chosen_edge") is not None else None,
                    "min_edge_threshold": _to_float(candidate.get("min_edge_threshold")) if candidate.get("min_edge_threshold") is not None else None,
                    "confidence": _to_float(candidate.get("confidence")) if candidate.get("confidence") is not None else None,
                    "confidence_threshold": _to_float(candidate.get("confidence_threshold")) if candidate.get("confidence_threshold") is not None else None,
                    "ev": _to_float(candidate.get("ev")) if candidate.get("ev") is not None else None,
                    "bookie_match_confidence": str(candidate.get("bookie_match_confidence") or "") or None,
                    "matched_row_team1": str(candidate.get("matched_row_team1") or "") or None,
                    "matched_row_team2": str(candidate.get("matched_row_team2") or "") or None,
                    "is_bettable": bool(candidate.get("is_bettable", eligibility.get("is_bettable", True))),
                    "eligibility_reason": str(candidate.get("eligibility_reason") or eligibility.get("eligibility_reason") or "") or None,
                    "normalized_identity": str(candidate.get("normalized_identity") or eligibility.get("normalized_identity") or "") or None,
                    "odds_source_kind": str(candidate.get("odds_source_kind") or "") or None,
                    "odds_source_status": str(candidate.get("odds_source_status") or "") or None,
                    "market_offer_count": int(candidate.get("market_offer_count") or 0),
                    "has_match_winner_offer": bool(candidate.get("has_match_winner_offer")),
                    "terminal_outcome": str(candidate.get("terminal_outcome") or "pending"),
                    "rejected_candidates": candidate.get("rejected_candidates", []),
                    "position_count": 0,
                    "series_decision_context": {"rejected_candidates": candidate.get("rejected_candidates", [])},
                }
            )
            continue
        statuses.append(
            {
                "pandascore_match_id": match_id,
                "series_key": str(candidate.get("series_key") or make_series_key(match_id)),
                "status": "waiting_for_better_odds",
                "reason_code": "below_edge_waiting",
                "market_type": str(candidate.get("market_type") or "match_winner"),
                "selection_key": str(candidate.get("selection_key") or "team_a"),
                "line_value": _to_float(candidate.get("line_value")) if candidate.get("line_value") is not None else None,
                "short_detail": str(candidate.get("short_detail") or "") or _short_detail_for_reason(
                    "below_edge_waiting",
                    chosen_edge=_to_decimal(candidate.get("chosen_edge")) if candidate.get("chosen_edge") is not None else _to_decimal(chosen_edge),
                    min_edge_threshold=_to_decimal(candidate.get("min_edge_threshold")) if candidate.get("min_edge_threshold") is not None else _to_decimal(bankroll.min_edge_threshold),
                    confidence=_to_decimal(candidate.get("confidence")) if candidate.get("confidence") is not None else None,
                    confidence_threshold=_to_decimal(candidate.get("confidence_threshold")) if candidate.get("confidence_threshold") is not None else None,
                    ev=_to_decimal(candidate.get("ev")) if candidate.get("ev") is not None else None,
                ),
                "within_force_window": bool(candidate.get("within_force_window")),
                "force_bet_after": _datetime_to_iso(force_bet_after if isinstance(force_bet_after, datetime) else None),
                "chosen_edge": _to_float(candidate.get("chosen_edge")) if candidate.get("chosen_edge") is not None else None,
                "min_edge_threshold": _to_float(candidate.get("min_edge_threshold")) if candidate.get("min_edge_threshold") is not None else None,
                "confidence": _to_float(candidate.get("confidence")) if candidate.get("confidence") is not None else None,
                "confidence_threshold": _to_float(candidate.get("confidence_threshold")) if candidate.get("confidence_threshold") is not None else None,
                "ev": _to_float(candidate.get("ev")) if candidate.get("ev") is not None else None,
                "bookie_match_confidence": str(candidate.get("bookie_match_confidence") or "") or None,
                "matched_row_team1": str(candidate.get("matched_row_team1") or "") or None,
                "matched_row_team2": str(candidate.get("matched_row_team2") or "") or None,
                "is_bettable": bool(candidate.get("is_bettable", eligibility.get("is_bettable", True))),
                "eligibility_reason": str(candidate.get("eligibility_reason") or eligibility.get("eligibility_reason") or "") or None,
                "normalized_identity": str(candidate.get("normalized_identity") or eligibility.get("normalized_identity") or "") or None,
                "odds_source_kind": str(candidate.get("odds_source_kind") or "") or None,
                "odds_source_status": str(candidate.get("odds_source_status") or "") or None,
                "market_offer_count": int(candidate.get("market_offer_count") or 0),
                "has_match_winner_offer": bool(candidate.get("has_match_winner_offer")),
                "terminal_outcome": str(candidate.get("terminal_outcome") or "waiting"),
                "rejected_candidates": candidate.get("rejected_candidates", []),
                "position_count": 0,
                "series_decision_context": {"rejected_candidates": candidate.get("rejected_candidates", [])},
            }
        )

    return statuses


def get_match_betting_diagnostics(
    session: Session,
    *,
    search: str | None = None,
    match_id: int | None = None,
    include_live: bool = True,
    include_placed: bool = False,
    limit: int = 25,
) -> dict[str, object]:
    from ml.predictor_v2 import get_prediction_runtime_status

    bankroll = get_or_create_agent_bankroll(session)
    upcoming_matches = read_upcoming_matches_from_file() or []
    live_matches = _fetch_running_matches() if include_live else []
    unique_matches: dict[int, dict[str, object]] = {}
    for match in upcoming_matches + live_matches:
        current_match_id = int(match.get("id") or 0)
        if current_match_id > 0:
            unique_matches[current_match_id] = match

    existing_bets_by_match: dict[int, list[Bet]] = {}
    for bet in (
        session.query(Bet)
        .filter(Bet.bankroll_id == bankroll.id, Bet.status.in_(sorted(OPEN_BET_STATUSES)))
        .order_by(Bet.placed_at.desc())
        .all()
    ):
        existing_bets_by_match.setdefault(int(bet.pandascore_match_id), []).append(bet)

    lowered_search = (search or "").strip().lower()
    bookie_odds = read_market_catalog_from_file()
    resolver = EntityResolver(session)
    now = datetime.now(timezone.utc)
    model_available = get_prediction_runtime_status(session).get("active_model_id") is not None

    rows: list[MatchDecisionDiagnostic] = []
    for current_match_id, match in sorted(
        unique_matches.items(),
        key=lambda item: _parse_match_scheduled_at(item[1]) or datetime.max.replace(tzinfo=timezone.utc),
    ):
        if match_id is not None and current_match_id != match_id:
            continue

        team_a, team_b = _team_names(match)
        league = ((match.get("league") or {}).get("name") or None)
        eligibility = classify_match_betting_eligibility(match)
        haystack = " ".join(filter(None, [team_a, team_b, str(league or "")])).lower()
        if lowered_search and lowered_search not in haystack:
            continue

        existing_positions = existing_bets_by_match.get(current_match_id, [])
        if existing_positions and not include_placed:
            continue

        scheduled_at = _datetime_to_iso(_parse_match_scheduled_at(match))
        if existing_positions:
            latest_position = existing_positions[0]
            rows.append(
                {
                    "pandascore_match_id": current_match_id,
                    "scheduled_at": scheduled_at,
                    "league": str(league) if league is not None else None,
                    "team_a": team_a,
                    "team_b": team_b,
                    "series_format": _series_format_label(int(match.get("number_of_games") or 1)),
                    "status": "placed",
                    "reason_code": None,
                    "reason_detail": None,
                    "short_detail": None,
                    "within_force_window": False,
                    "force_bet_after": None,
                    "position_count": len(existing_positions),
                    "is_bettable": bool(eligibility.get("is_bettable", True)),
                    "eligibility_reason": str(eligibility.get("eligibility_reason") or "") or None,
                    "odds_source_kind": str(latest_position.odds_source_status or "") or None,
                    "odds_source_status": str(latest_position.odds_source_status or "") or None,
                    "market_offer_count": 0,
                    "has_match_winner_offer": False,
                    "terminal_outcome": "placed",
                    "diagnostics": {
                        "bet_on": latest_position.bet_on,
                        "market_type": latest_position.market_type,
                        "locked_odds": float(latest_position.book_odds_locked),
                        "stake": float(latest_position.actual_stake),
                    },
                }
            )
            if len(rows) >= limit:
                break
            continue

        candidate = _evaluate_match_for_betting(
            session,
            resolver,
            bankroll,
            match,
            bookie_odds,
            now=now,
            model_available=model_available,
        )
        rows.append(
            {
                "pandascore_match_id": current_match_id,
                "scheduled_at": scheduled_at,
                "league": str(league) if league is not None else None,
                "team_a": team_a,
                "team_b": team_b,
                "series_format": _series_format_label(int(match.get("number_of_games") or 1)),
                "status": str(candidate.get("status") or ("pending_auto_bet" if "chosen_team" in candidate else "unknown")),
                "reason_code": str(candidate.get("reason_code") or "") or None,
                "reason_detail": str(candidate.get("reason_detail") or "") or None,
                "short_detail": str(candidate.get("short_detail") or "") or None,
                "within_force_window": bool(candidate.get("within_force_window")),
                "force_bet_after": _datetime_to_iso(candidate.get("force_bet_after") if isinstance(candidate.get("force_bet_after"), datetime) else None),
                "position_count": 0,
                "is_bettable": bool(candidate.get("is_bettable", eligibility.get("is_bettable", True))),
                "eligibility_reason": str(candidate.get("eligibility_reason") or eligibility.get("eligibility_reason") or "") or None,
                "odds_source_kind": str(candidate.get("odds_source_kind") or "") or None,
                "odds_source_status": str(candidate.get("odds_source_status") or "") or None,
                "market_offer_count": int(candidate.get("market_offer_count") or 0),
                "has_match_winner_offer": bool(candidate.get("has_match_winner_offer")),
                "terminal_outcome": str(candidate.get("terminal_outcome") or ("pending" if "chosen_team" in candidate else "blocked")),
                "diagnostics": {
                    "chosen_team": candidate.get("chosen_team"),
                    "market_type": candidate.get("market_type"),
                    "selection_key": candidate.get("selection_key"),
                    "line_value": _to_float(candidate.get("line_value")) if candidate.get("line_value") is not None else None,
                    "chosen_edge": _to_float(candidate.get("chosen_edge")) if candidate.get("chosen_edge") is not None else None,
                    "min_edge_threshold": _to_float(candidate.get("min_edge_threshold")) if candidate.get("min_edge_threshold") is not None else None,
                    "confidence": _to_float(candidate.get("confidence")) if candidate.get("confidence") is not None else None,
                    "confidence_threshold": _to_float(candidate.get("confidence_threshold")) if candidate.get("confidence_threshold") is not None else None,
                    "ev": _to_float(candidate.get("ev")) if candidate.get("ev") is not None else None,
                    "bookie_match_confidence": candidate.get("bookie_match_confidence"),
                    "matched_row_team1": candidate.get("matched_row_team1"),
                    "matched_row_team2": candidate.get("matched_row_team2"),
                    "is_bettable": candidate.get("is_bettable", eligibility.get("is_bettable", True)),
                    "eligibility_reason": candidate.get("eligibility_reason") or eligibility.get("eligibility_reason"),
                    "odds_source_kind": candidate.get("odds_source_kind"),
                    "odds_source_status": candidate.get("odds_source_status"),
                    "market_offer_count": int(candidate.get("market_offer_count") or 0),
                    "has_match_winner_offer": bool(candidate.get("has_match_winner_offer")),
                    "terminal_outcome": candidate.get("terminal_outcome") or ("pending" if "chosen_team" in candidate else "blocked"),
                    "rejected_candidates": candidate.get("rejected_candidates", []),
                },
            }
        )
        if len(rows) >= limit:
            break

    by_status: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        reason = str(row.get("reason_code") or "")
        if reason:
            by_reason[reason] = by_reason.get(reason, 0) + 1

    return {
        "summary": {
            "total_matches": len(rows),
            "by_status": by_status,
            "by_reason": by_reason,
            "waiting_matches": by_status.get("waiting_for_better_odds", 0),
            "blocked_matches": sum(count for status, count in by_status.items() if status.startswith("blocked_")),
            "pending_matches": by_status.get("pending_auto_bet", 0) + by_status.get("pending_force_bet", 0),
            "placed_matches": by_status.get("placed", 0),
        },
        "matches": rows,
    }


def auto_place_bets(session: Session) -> PlacementSummary:
    from ml.predictor_v2 import get_prediction_runtime_status

    refund_and_delete_missing_open_bets(session)
    bankroll = get_or_create_agent_bankroll(session)
    matches = (read_upcoming_matches_from_file() or []) + _fetch_running_matches()
    bookie_odds = read_market_catalog_from_file()
    resolver = EntityResolver(session)
    summary: PlacementSummary = {
        "placed": 0,
        "skipped_existing": 0,
        "skipped_missing_inputs": 0,
        "waiting_for_better_odds": 0,
        "total_staked": 0.0,
        "skipped_by_reason": {},
    }
    now = datetime.now(timezone.utc)
    model_available = get_prediction_runtime_status(session).get("active_model_id") is not None
    for match in matches:
        match_id = int(match.get("id") or 0)
        if match_id <= 0:
            summary["skipped_missing_inputs"] += 1
            summary["skipped_by_reason"]["invalid_match_id"] = summary["skipped_by_reason"].get("invalid_match_id", 0) + 1
            continue

        eligibility = classify_match_betting_eligibility(match)
        if not bool(eligibility.get("is_bettable")):
            summary["skipped_missing_inputs"] += 1
            reason = str(eligibility.get("eligibility_reason") or "league_not_bettable")
            summary["skipped_by_reason"][reason] = summary["skipped_by_reason"].get(reason, 0) + 1
            continue

        candidate = _evaluate_match_for_betting(
            session,
            resolver,
            bankroll,
            match,
            bookie_odds,
            now=now,
            model_available=model_available,
        )
        if "chosen_team" not in candidate:
            reason_code = str(candidate.get("reason_code") or "unknown")
            if reason_code in MISSING_INPUT_REASONS or reason_code == "tier_filtered":
                summary["skipped_missing_inputs"] += 1
            summary["skipped_by_reason"][reason_code] = summary["skipped_by_reason"].get(reason_code, 0) + 1
            continue

        chosen_edge = candidate["chosen_edge"]
        should_force_bet = bool(candidate.get("should_force_bet"))
        if chosen_edge < bankroll.min_edge_threshold and not should_force_bet:
            summary["waiting_for_better_odds"] += 1
            summary["skipped_by_reason"]["below_edge_waiting"] = summary["skipped_by_reason"].get("below_edge_waiting", 0) + 1
            continue

        existing_positions = (
            session.query(Bet)
            .filter(
                Bet.bankroll_id == bankroll.id,
                Bet.series_key == str(candidate.get("series_key") or make_series_key(match_id)),
                Bet.status.in_(sorted(OPEN_BET_STATUSES)),
            )
            .order_by(Bet.placed_at.desc())
            .all()
        )
        can_place, skip_reason, series_decision_context = _can_place_rebet(
            existing_positions,
            candidate,
            bankroll=bankroll,
            now=now,
        )
        if not can_place:
            summary["skipped_existing"] += 1
            if skip_reason:
                summary["skipped_by_reason"][skip_reason] = summary["skipped_by_reason"].get(skip_reason, 0) + 1
            continue
        candidate["series_decision_context"] = series_decision_context

        bet = Bet(
            bankroll_id=bankroll.id,
            pandascore_match_id=match_id,
            model_run_id=candidate["model_run_id"],
            team_a=candidate["team_a"],
            team_b=candidate["team_b"],
            league=((match.get("league") or {}).get("name") or None),
            series_format="BO5" if candidate["number_of_games"] >= 5 else ("BO3" if candidate["number_of_games"] >= 3 else "BO1"),
            series_key=str(candidate.get("series_key") or make_series_key(match_id)),
            bet_sequence=_next_bet_sequence(session, str(candidate.get("series_key") or make_series_key(match_id))),
            entry_phase=str(candidate.get("entry_phase") or PREMATCH_ENTRY_PHASE),
            entry_score_team_a=int(candidate.get("entry_score_team_a") or 0),
            entry_score_team_b=int(candidate.get("entry_score_team_b") or 0),
            current_score_team_a=int(candidate.get("current_score_team_a") or 0),
            current_score_team_b=int(candidate.get("current_score_team_b") or 0),
            odds_source_status=str(candidate.get("odds_source_status") or "available"),
            feed_health_status="tracked",
            live_rebet_allowed=bool(candidate.get("live_rebet_allowed")),
            model_snapshot_json=candidate.get("model_snapshot_json") if isinstance(candidate.get("model_snapshot_json"), dict) else None,
            market_type=str(candidate.get("market_type") or "match_winner"),
            selection_key=str(candidate.get("selection_key") or "team_a"),
            line_value=_to_decimal(candidate.get("line_value")) if candidate.get("line_value") is not None else None,
            source_book=str(candidate.get("source_book") or "thunderpick"),
            source_market_name=str(candidate.get("source_market_name")) if candidate.get("source_market_name") is not None else None,
            source_selection_name=str(candidate.get("source_selection_name")) if candidate.get("source_selection_name") is not None else None,
            bet_on=candidate["chosen_team"],
            model_prob=candidate["chosen_model_prob"],
            book_odds_locked=candidate["chosen_book_odds"],
            book_prob_adj=candidate["chosen_book_prob"],
            edge=chosen_edge,
            ev=candidate["ev"],
            recommended_stake=candidate["stake"],
            actual_stake=candidate["stake"],
            status="LIVE" if str(candidate.get("entry_phase")) == REBET_ENTRY_PHASE else "PLACED",
            placed_at=now,
        )
        session.add(bet)
        session.flush()
        bankroll.current_balance = max(Decimal("0"), bankroll.current_balance - candidate["stake"])
        _record_bet_event(
            session,
            bankroll_id=bankroll.id,
            bet_id=bet.id,
            pandascore_match_id=match_id,
            series_key=bet.series_key,
            event_type="placed",
            amount_delta=Decimal("0") - _to_decimal(candidate["stake"]),
            payload={
                "entry_phase": bet.entry_phase,
                "bet_sequence": bet.bet_sequence,
                "series_score_a": bet.entry_score_team_a,
                "series_score_b": bet.entry_score_team_b,
                "market_type": bet.market_type,
                "selection_key": bet.selection_key,
                "line_value": float(bet.line_value) if bet.line_value is not None else None,
                "series_decision_context": series_decision_context,
                "rejected_candidates": candidate.get("rejected_candidates", []),
            },
        )
        summary["total_staked"] += float(candidate["stake"])
        summary["placed"] += 1

    session.commit()
    return summary


def match_snapshot_for_settlement_preview(match: dict[str, object]) -> dict[str, object]:
    return {
        "id": int(match.get("id") or 0),
        "status": match.get("status"),
        "scheduled_at": match.get("scheduled_at"),
        "begin_at": match.get("begin_at"),
        "end_at": match.get("end_at"),
        "forfeit": match.get("forfeit"),
        "winner": match.get("winner"),
        "winner_id": match.get("winner_id"),
        "results": match.get("results"),
    }


def build_settlement_preview_payload(session: Session) -> dict[str, object]:
    open_bets = _open_bets_query(session).all()
    ids = sorted({b.pandascore_match_id for b in open_bets if int(b.pandascore_match_id or 0) > 0})
    by_id = fetch_lol_matches_by_ids_sync(ids)
    bets_out: list[dict[str, object]] = []
    for b in open_bets:
        bets_out.append(
            {
                "id": str(b.id),
                "pandascore_match_id": b.pandascore_match_id,
                "status": b.status,
                "market_type": b.market_type,
                "team_a": b.team_a,
                "team_b": b.team_b,
                "bet_on": b.bet_on,
                "actual_stake": float(b.actual_stake),
                "series_key": b.series_key,
            }
        )
    matches_out: dict[str, dict[str, object]] = {
        str(mid): match_snapshot_for_settlement_preview(m) for mid, m in by_id.items()
    }
    return {"open_bets": bets_out, "matches_by_id": matches_out}


def settle_completed_bets(session: Session) -> SettlementSummary:
    cleanup = refund_and_delete_missing_open_bets(session)
    open_bets = _open_bets_query(session).all()
    summary: SettlementSummary = {
        "settled": 0,
        "won": 0,
        "lost": 0,
        "removed": int(cleanup["removed"]),
        "voided": int(cleanup.get("voided", 0)),
        "orphaned": int(cleanup.get("orphaned", 0)),
        "profit": 0.0,
    }
    if not open_bets:
        return summary

    match_ids = sorted({b.pandascore_match_id for b in open_bets if int(b.pandascore_match_id or 0) > 0})
    matches_by_id = fetch_lol_matches_by_ids_sync(match_ids)

    bankroll_map: dict[str, Bankroll] = {}
    bookie_odds = read_odds_from_file()
    now = datetime.now(timezone.utc)
    session_needs_commit = False

    for bet in open_bets:
        mid = int(bet.pandascore_match_id or 0)
        m = matches_by_id.get(mid)
        if m is None:
            fetched = _fetch_match_by_id(mid)
            if isinstance(fetched, dict) and int(fetched.get("id") or 0) > 0:
                m = fetched
                matches_by_id[int(fetched["id"])] = fetched
        if not isinstance(m, dict):
            continue

        st = str(m.get("status") or "").strip().lower()

        if st in {"running", "started", "live"}:
            bankroll = _get_bankroll(bankroll_map, session, bet.bankroll_id)
            if bankroll is None:
                continue
            bet.current_score_team_a, bet.current_score_team_b = _score_from_match(m)
            bet.feed_health_status = "tracked"
            if bet.status != "LIVE":
                _mark_bet_status(
                    session,
                    bet,
                    "LIVE",
                    event_type="live_started",
                    payload={"pandascore_match_id": bet.pandascore_match_id},
                )
            session_needs_commit = True
            continue

        if st in {"not_started", "postponed"}:
            continue

        if st in {"canceled", "cancelled"}:
            if not bool(m.get("forfeit")):
                bankroll = _get_bankroll(bankroll_map, session, bet.bankroll_id)
                if bankroll is None:
                    continue
                _void_bet(
                    session,
                    bet,
                    bankroll=bankroll,
                    reason="match_cancelled",
                    payload={"pandascore_match_id": bet.pandascore_match_id},
                )
                summary["voided"] += 1
                session_needs_commit = True
                continue
            if not _resolve_winner_display_name(m):
                continue
        elif st not in {"finished", "completed"}:
            continue

        winner_name = _resolve_winner_display_name(m)
        if bet.market_type == "match_winner" and not winner_name:
            continue

        bankroll = _get_bankroll(bankroll_map, session, bet.bankroll_id)
        if bankroll is None:
            continue

        score_a, score_b = _score_from_match(m)
        total_maps = score_a + score_b
        if bet.market_type == "match_winner":
            bet_won = normalize_team_for_settlement(session, str(winner_name)) == normalize_team_for_settlement(
                session, bet.bet_on
            )
        elif bet.market_type == "map_handicap":
            if total_maps <= 0 or bet.line_value is None:
                bet.status = "ORPHANED_FEED"
                bet.feed_health_status = "settlement_missing_series_score"
                summary["orphaned"] += 1
                session_needs_commit = True
                continue
            bet_team_score = score_a if _same_team(bet.bet_on, bet.team_a) else score_b
            other_score = score_b if _same_team(bet.bet_on, bet.team_a) else score_a
            bet_won = (Decimal(str(bet_team_score)) + _to_decimal(bet.line_value)) > Decimal(str(other_score))
        elif bet.market_type == "total_maps":
            if total_maps <= 0 or bet.line_value is None:
                bet.status = "ORPHANED_FEED"
                bet.feed_health_status = "settlement_missing_series_score"
                summary["orphaned"] += 1
                session_needs_commit = True
                continue
            if str(bet.selection_key).startswith("over_"):
                bet_won = Decimal(str(total_maps)) > _to_decimal(bet.line_value)
            else:
                bet_won = Decimal(str(total_maps)) < _to_decimal(bet.line_value)
        else:
            bet.status = "ORPHANED_FEED"
            bet.feed_health_status = "settlement_unsupported_market"
            summary["orphaned"] += 1
            session_needs_commit = True
            continue

        stake = _to_decimal(bet.actual_stake)
        odds = _to_decimal(bet.book_odds_locked)
        if bet_won:
            gross_return = stake * odds
            profit_loss = stake * (odds - Decimal("1"))
            bankroll.current_balance = bankroll.current_balance + gross_return
            bet.status = "WON"
            summary["won"] += 1
        else:
            profit_loss = Decimal("0") - stake
            bet.status = "LOST"
            summary["lost"] += 1
        bet.profit_loss = profit_loss
        bet.settled_at = now
        bet.feed_health_status = "settled"
        summary["settled"] += 1
        summary["profit"] += float(profit_loss)
        _record_bet_event(
            session,
            bankroll_id=bet.bankroll_id,
            bet_id=bet.id,
            pandascore_match_id=bet.pandascore_match_id,
            series_key=bet.series_key,
            event_type="settled",
            amount_delta=(stake * odds) if bet_won else Decimal("0.00"),
            payload={"result": bet.status, "winner_name": winner_name or ""},
        )

        close_a, close_b = find_odds_for_match(bet.team_a, bet.team_b, bookie_odds)
        if close_a is not None and close_b is not None:
            if bet.bet_on.strip().lower() == bet.team_a.strip().lower():
                bet.closing_odds = _to_decimal(close_a)
            elif bet.bet_on.strip().lower() == bet.team_b.strip().lower():
                bet.closing_odds = _to_decimal(close_b)

    if summary["settled"] > 0:
        for bankroll in bankroll_map.values():
            settled_bets = session.query(Bet).filter(
                Bet.bankroll_id == bankroll.id,
                Bet.status.in_(["WON", "LOST"]),
            ).all()
            wins = sum(1 for b in settled_bets if b.status == "WON")
            losses = sum(1 for b in settled_bets if b.status == "LOST")
            total_staked = sum(_to_decimal(b.actual_stake) for b in settled_bets)
            total_profit = sum(_to_decimal(b.profit_loss) for b in settled_bets if b.profit_loss is not None)

            latest_snapshot = (
                session.query(BankrollSnapshot)
                .filter(BankrollSnapshot.bankroll_id == bankroll.id)
                .order_by(BankrollSnapshot.snapshot_at.desc())
                .first()
            )
            peak_balance = bankroll.current_balance
            if latest_snapshot is not None:
                peak_balance = max(peak_balance, latest_snapshot.peak_balance)

            snapshot = BankrollSnapshot(
                bankroll_id=bankroll.id,
                snapshot_at=now,
                balance=bankroll.current_balance,
                total_bets=len(settled_bets),
                wins=wins,
                losses=losses,
                roi_pct=roi_pct(total_profit, total_staked),
                peak_balance=peak_balance,
            )
            session.add(snapshot)
        session.commit()
    elif session_needs_commit:
        session.commit()

    return summary


def get_open_bet_schedule_statuses(session: Session) -> list[OpenBetStatusSummary]:
    refund_and_delete_missing_open_bets(session)
    bankroll = get_or_create_agent_bankroll(session)
    open_bets = (
        session.query(Bet)
        .filter(Bet.bankroll_id == bankroll.id, Bet.status.in_(sorted(OPEN_BET_STATUSES)))
        .order_by(Bet.placed_at.desc())
        .all()
    )
    if not open_bets:
        return []

    upcoming_matches = read_upcoming_matches_from_file() or []
    upcoming_matches_by_id = {
        int(m.get("id") or 0): m
        for m in upcoming_matches
        if int(m.get("id") or 0) > 0 and isinstance(m, dict)
    }
    running_matches = _fetch_running_matches()
    running_ids = {int(match.get("id") or 0) for match in running_matches if int(match.get("id") or 0) > 0}

    statuses: list[OpenBetStatusSummary] = []
    for bet in open_bets:
        if not league_name_or_slug_allowed(bet.league):
            continue
        if bet.pandascore_match_id in upcoming_matches_by_id:
            schedule_status = _schedule_status_from_match(upcoming_matches_by_id[bet.pandascore_match_id])
        elif bet.pandascore_match_id in running_ids:
            schedule_status = "scheduled_live"
        else:
            schedule_status = _schedule_status_from_match(_fetch_match_by_id(bet.pandascore_match_id))
        if schedule_status != "scheduled_upcoming":
            continue
        statuses.append(
            {
                "id": str(bet.id),
                "pandascore_match_id": bet.pandascore_match_id,
                "team_a": bet.team_a,
                "team_b": bet.team_b,
                "bet_on": bet.bet_on,
                "market_type": bet.market_type,
                "selection_key": bet.selection_key,
                "line_value": float(bet.line_value) if bet.line_value is not None else None,
                "locked_odds": float(bet.book_odds_locked),
                "stake": float(bet.actual_stake),
                "schedule_status": schedule_status,
                "league": bet.league,
                "model_run_id": bet.model_run_id,
                "series_key": bet.series_key,
                "bet_sequence": bet.bet_sequence,
            }
        )
    return statuses


def serialize_active_position(row: Bet) -> ActivePositionSummary:
    return {
        "id": str(row.id),
        "pandascore_match_id": row.pandascore_match_id,
        "series_key": row.series_key,
        "bet_sequence": row.bet_sequence,
        "team_a": row.team_a,
        "team_b": row.team_b,
        "bet_on": row.bet_on,
        "market_type": row.market_type,
        "selection_key": row.selection_key,
        "line_value": float(row.line_value) if row.line_value is not None else None,
        "source_market_name": row.source_market_name,
        "source_selection_name": row.source_selection_name,
        "locked_odds": float(row.book_odds_locked),
        "stake": float(row.actual_stake),
        "status": row.status,
        "league": row.league,
        "entry_phase": row.entry_phase,
        "entry_score_team_a": row.entry_score_team_a,
        "entry_score_team_b": row.entry_score_team_b,
        "current_score_team_a": row.current_score_team_a,
        "current_score_team_b": row.current_score_team_b,
        "odds_source_status": row.odds_source_status,
        "feed_health_status": row.feed_health_status,
        "placed_at": _datetime_to_iso(row.placed_at),
    }


def _build_single_position_summary(position: Bet) -> dict[str, object]:
    return {
        "label": f"Bet: {_candidate_label({'market_type': position.market_type, 'selection_key': position.selection_key, 'line_value': float(position.line_value) if position.line_value is not None else None, 'chosen_team': position.bet_on})} @ {float(position.book_odds_locked):.2f}",
        "side": position.bet_on,
        "locked_odds": float(position.book_odds_locked),
        "stake": float(position.actual_stake),
    }


def _build_multi_position_summary(
    *,
    positions: list[Bet],
    team_a: str,
    team_b: str,
    exposure: dict[str, object],
) -> dict[str, object]:
    team_a_stake = _to_decimal(exposure["stake_by_team"].get(team_a, Decimal("0.00")))
    team_b_stake = _to_decimal(exposure["stake_by_team"].get(team_b, Decimal("0.00")))
    net_side = exposure["net_side"]
    return {
        "label": f"{len(positions)} bets",
        "bet_count": len(positions),
        "team_a_stake": float(team_a_stake),
        "team_b_stake": float(team_b_stake),
        "team_a_label": team_a,
        "team_b_label": team_b,
        "net_side": net_side,
        "net_stake_delta": float(_to_decimal(exposure["net_stake_delta"])),
    }


def get_active_positions_by_series(session: Session) -> list[ActiveSeriesSummary]:
    bankroll = get_or_create_agent_bankroll(session)
    rows = (
        session.query(Bet)
        .filter(Bet.bankroll_id == bankroll.id, Bet.status.in_(sorted(ACTIVE_BET_VISIBILITY_STATUSES)))
        .order_by(Bet.placed_at.desc())
        .all()
    )
    grouped: dict[str, list[Bet]] = {}
    for row in rows:
        if not league_name_or_slug_allowed(row.league):
            continue
        grouped.setdefault(row.series_key, []).append(row)

    series_summaries: list[ActiveSeriesSummary] = []
    for series_key, positions in grouped.items():
        positions = sorted(
            positions,
            key=lambda item: (int(item.bet_sequence), item.placed_at),
            reverse=True,
        )
        latest = positions[0]
        exposure = _build_series_exposure_snapshot(positions, team_a=latest.team_a, team_b=latest.team_b)
        team_a_stake = _to_decimal(exposure["stake_by_team"].get(latest.team_a, Decimal("0.00")))
        team_b_stake = _to_decimal(exposure["stake_by_team"].get(latest.team_b, Decimal("0.00")))
        series_summaries.append(
            {
                "series_key": series_key,
                "pandascore_match_id": latest.pandascore_match_id,
                "team_a": latest.team_a,
                "team_b": latest.team_b,
                "league": latest.league,
                "position_count": len(positions),
                "total_exposure": float(sum(_to_decimal(position.actual_stake) for position in positions)),
                "team_stake_totals": {
                    latest.team_a: float(team_a_stake),
                    latest.team_b: float(team_b_stake),
                },
                "net_side": exposure["net_side"],
                "net_stake_delta": float(_to_decimal(exposure["net_stake_delta"])),
                "has_conflicting_positions": bool(exposure["has_conflicting_positions"]),
                "single_position_summary": _build_single_position_summary(latest),
                "multi_position_summary": _build_multi_position_summary(
                    positions=positions,
                    team_a=latest.team_a,
                    team_b=latest.team_b,
                    exposure=exposure,
                ),
                "latest_position": serialize_active_position(latest),
                "positions": [serialize_active_position(position) for position in positions],
            }
        )
    return sorted(series_summaries, key=lambda row: row["latest_position"]["placed_at"], reverse=True)


def repair_orphaned_bets(session: Session) -> dict[str, int | float]:
    repaired = 0
    voided = 0
    reconciled = Decimal("0.00")
    orphaned = (
        session.query(Bet)
        .filter(Bet.status == "ORPHANED_FEED")
        .order_by(Bet.placed_at.desc())
        .all()
    )
    if not orphaned:
        return {"repaired": 0, "voided": 0, "reconciled_balance_delta": 0.0}

    bankroll_cache: dict[str, Bankroll] = {}
    for bet in orphaned:
        match = _fetch_match_by_id(bet.pandascore_match_id)
        schedule_status = _schedule_status_from_match(match)
        if schedule_status in {"scheduled_upcoming", "scheduled_live"}:
            bet.feed_health_status = "repaired"
            _mark_bet_status(
                session,
                bet,
                "LIVE" if schedule_status == "scheduled_live" else "PLACED",
                event_type="repair_restored",
                payload={"schedule_status": schedule_status},
            )
            repaired += 1
            continue
        if schedule_status == "cancelled":
            bankroll = _get_bankroll(bankroll_cache, session, bet.bankroll_id)
            if bankroll is None:
                continue
            stake = _to_decimal(bet.actual_stake)
            bankroll.current_balance = bankroll.current_balance + stake
            reconciled += stake
            bet.feed_health_status = "cancelled"
            bet.profit_loss = Decimal("0.00")
            bet.settled_at = datetime.now(timezone.utc)
            _mark_bet_status(session, bet, "VOID", event_type="voided", payload={"reason": "repair_cancelled"})
            _record_bet_event(
                session,
                bankroll_id=bet.bankroll_id,
                bet_id=bet.id,
                pandascore_match_id=bet.pandascore_match_id,
                series_key=bet.series_key,
                event_type="wallet_void_refund",
                amount_delta=stake,
                payload={"reason": "repair_cancelled"},
            )
            voided += 1
    if repaired or voided:
        session.commit()
    return {
        "repaired": repaired,
        "voided": voided,
        "reconciled_balance_delta": float(reconciled),
    }


def get_model_evaluation_summary(session: Session) -> list[ModelEvaluationSummary]:
    bankroll = get_or_create_agent_bankroll(session)
    settled_bets = (
        session.query(Bet)
        .filter(
            Bet.bankroll_id == bankroll.id,
            Bet.status.in_(["WON", "LOST"]),
        )
        .order_by(Bet.settled_at.desc(), Bet.placed_at.desc())
        .all()
    )
    if not settled_bets:
        return []

    runs_by_id = {
        run.id: run
        for run in session.query(MLModelRun)
        .filter(MLModelRun.id.in_([bet.model_run_id for bet in settled_bets if bet.model_run_id is not None]))
        .all()
    }

    grouped: dict[int | None, list[Bet]] = {}
    for bet in settled_bets:
        grouped.setdefault(bet.model_run_id, []).append(bet)

    summaries: list[ModelEvaluationSummary] = []
    for model_run_id, bets in grouped.items():
        run = runs_by_id.get(model_run_id) if model_run_id is not None else None
        wins = sum(1 for bet in bets if bet.status == "WON")
        losses = sum(1 for bet in bets if bet.status == "LOST")
        total_staked = sum(_to_decimal(bet.actual_stake) for bet in bets)
        total_profit = sum(_to_decimal(bet.profit_loss) for bet in bets if bet.profit_loss is not None)

        clv_values: list[Decimal] = []
        edge_groups: dict[str, list[Bet]] = {}
        league_groups: dict[str, list[Bet]] = {}
        series_groups: dict[str, list[Bet]] = {}
        for bet in bets:
            if bet.closing_odds is not None:
                clv_values.append(implied_prob(_to_decimal(bet.closing_odds)) - implied_prob(_to_decimal(bet.book_odds_locked)))
            edge_groups.setdefault(_group_bucket(_to_decimal(bet.edge)), []).append(bet)
            league_groups.setdefault((bet.league or "UNKNOWN").upper(), []).append(bet)
            series_groups.setdefault((bet.series_format or "UNKNOWN").upper(), []).append(bet)

        edge_calibration: list[EdgeBucketSummary] = []
        for bucket, bucket_bets in sorted(edge_groups.items()):
            bucket_staked = sum(_to_decimal(b.actual_stake) for b in bucket_bets)
            bucket_profit = sum(_to_decimal(b.profit_loss) for b in bucket_bets if b.profit_loss is not None)
            bucket_wins = sum(1 for b in bucket_bets if b.status == "WON")
            edge_calibration.append(
                {
                    "bucket": bucket,
                    "bets": len(bucket_bets),
                    "win_rate_pct": (bucket_wins / len(bucket_bets) * 100.0) if bucket_bets else 0.0,
                    "roi_pct": float(roi_pct(bucket_profit, bucket_staked)),
                }
            )

        def _split_summary(groups: dict[str, list[Bet]]) -> list[SplitPerformanceSummary]:
            summaries_inner: list[SplitPerformanceSummary] = []
            for key, group_bets in sorted(groups.items()):
                staked = sum(_to_decimal(b.actual_stake) for b in group_bets)
                profit = sum(_to_decimal(b.profit_loss) for b in group_bets if b.profit_loss is not None)
                wins_inner = sum(1 for b in group_bets if b.status == "WON")
                losses_inner = sum(1 for b in group_bets if b.status == "LOST")
                summaries_inner.append(
                    {
                        "key": key,
                        "bets": len(group_bets),
                        "wins": wins_inner,
                        "losses": losses_inner,
                        "roi_pct": float(roi_pct(profit, staked)),
                    }
                )
            return summaries_inner

        avg_clv_proxy = float(sum(clv_values, Decimal("0")) / Decimal(len(clv_values))) * 100.0 if clv_values else 0.0
        summaries.append(
            {
                "model_run_id": model_run_id,
                "model_version": run.model_version if run is not None else None,
                "model_type": run.model_type if run is not None else None,
                "settled_bets": len(bets),
                "wins": wins,
                "losses": losses,
                "realized_roi_pct": float(roi_pct(total_profit, total_staked)),
                "avg_clv_proxy_pct": avg_clv_proxy,
                "edge_calibration": edge_calibration,
                "league_performance": _split_summary(league_groups),
                "series_format_performance": _split_summary(series_groups),
            }
        )

    summaries.sort(key=lambda item: ((item["model_run_id"] or 0), item["settled_bets"]), reverse=True)
    return summaries

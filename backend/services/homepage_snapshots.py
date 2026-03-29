from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar
from uuid import uuid4

from fastapi import Response
from sqlalchemy.orm import Session

from betting.bet_manager import (
    get_active_positions_by_series,
    get_or_create_agent_bankroll,
    get_upcoming_match_betting_statuses,
    match_belongs_on_upcoming_odds_feed,
)
from models_ml import (
    BankrollSummarySnapshot,
    BettingResultsSnapshot,
    HomepageSnapshotManifest,
    LiveWithOddsSnapshot,
    PowerRankingsSnapshot,
    UpcomingWithOddsSnapshot,
)

SnapshotModel = TypeVar(
    "SnapshotModel",
    UpcomingWithOddsSnapshot,
    LiveWithOddsSnapshot,
    BettingResultsSnapshot,
    BankrollSummarySnapshot,
    PowerRankingsSnapshot,
    HomepageSnapshotManifest,
)

SNAPSHOT_STALE_MINUTES = {
    "upcoming": 10,
    "live": 4,
    "results": 10,
    "bankroll": 10,
    "rankings": 120,
    "homepage": 10,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def datetime_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_snapshot_version(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def get_active_snapshot(
    session: Session,
    snapshot_model: type[SnapshotModel],
) -> SnapshotModel | None:
    return (
        session.query(snapshot_model)
        .filter(snapshot_model.is_active.is_(True))
        .order_by(snapshot_model.generated_at.desc(), snapshot_model.id.desc())
        .first()
    )


def create_snapshot(
    session: Session,
    snapshot_model: type[SnapshotModel],
    *,
    payload: dict[str, Any],
    version: str,
    status: str,
    source_window_started_at: datetime | None,
    source_window_completed_at: datetime | None,
    activate: bool,
) -> SnapshotModel:
    if activate:
        (
            session.query(snapshot_model)
            .filter(snapshot_model.is_active.is_(True))
            .update({"is_active": False}, synchronize_session=False)
        )

    snapshot = snapshot_model(
        version=version,
        payload_json=payload,
        generated_at=utc_now(),
        source_window_started_at=source_window_started_at,
        source_window_completed_at=source_window_completed_at,
        status=status,
        is_active=activate,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def record_snapshot_failure(
    session: Session,
    snapshot_model: type[SnapshotModel],
    *,
    version: str,
    source_window_started_at: datetime | None,
    source_window_completed_at: datetime | None,
    message: str,
) -> SnapshotModel:
    return create_snapshot(
        session,
        snapshot_model,
        payload={"error": message},
        version=version,
        status="failed",
        source_window_started_at=source_window_started_at,
        source_window_completed_at=source_window_completed_at,
        activate=False,
    )


def snapshot_metadata(
    snapshot: SnapshotModel | None,
    *,
    key: str,
) -> dict[str, Any]:
    if snapshot is None:
        return {
            "generated_at": None,
            "data_as_of": None,
            "snapshot_version": None,
            "is_stale": True,
            "status": "missing",
        }
    freshness_anchor = snapshot.source_window_completed_at or snapshot.generated_at
    if freshness_anchor.tzinfo is None:
        freshness_anchor = freshness_anchor.replace(tzinfo=timezone.utc)
    generated_at = snapshot.generated_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    stale_after_minutes = SNAPSHOT_STALE_MINUTES.get(key, 10)
    is_stale = freshness_anchor < utc_now() - timedelta(minutes=stale_after_minutes)
    return {
        "generated_at": datetime_to_iso(generated_at),
        "data_as_of": datetime_to_iso(freshness_anchor),
        "snapshot_version": snapshot.version,
        "is_stale": is_stale,
        "status": snapshot.status,
    }


def apply_snapshot_headers(
    response: Response,
    snapshot: SnapshotModel | None,
    *,
    key: str,
) -> None:
    meta = snapshot_metadata(snapshot, key=key)
    if meta["snapshot_version"]:
        response.headers["ETag"] = f'"{meta["snapshot_version"]}"'
        response.headers["X-Snapshot-Version"] = str(meta["snapshot_version"])
    if meta["generated_at"]:
        response.headers["X-Snapshot-Generated-At"] = str(meta["generated_at"])
    if meta["data_as_of"]:
        response.headers["X-Data-As-Of"] = str(meta["data_as_of"])
    response.headers["X-Is-Stale"] = "true" if meta["is_stale"] else "false"


def _sanitize_match_betting_statuses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        next_row = dict(row)
        next_row.pop("reason_detail", None)
        sanitized.append(next_row)
    return sanitized


def build_betting_results_payload(session: Session, limit: int = 500) -> dict[str, Any]:
    from api.v1 import betting as betting_api

    bankroll = get_or_create_agent_bankroll(session)
    rows = (
        session.query(betting_api.Bet)
        .filter(
            betting_api.Bet.bankroll_id == bankroll.id,
            betting_api.Bet.status.in_(["WON", "LOST"]),
        )
        .order_by(betting_api.Bet.settled_at.desc(), betting_api.Bet.placed_at.desc())
        .limit(limit)
        .all()
    )
    items = [
        betting_api.ResultsItemResponse(
            id=str(row.id),
            betDateTime=str(row.placed_at),
            league=row.league or "UNKNOWN",
            team1=row.team_a,
            team2=row.team_b,
            betOn=row.bet_on,
            lockedOdds=float(row.book_odds_locked),
            stake=float(row.actual_stake),
            result=row.status,
            profit=float(row.profit_loss or 0),
        ).model_dump()
        for row in rows
    ]
    return {"items": items}


def build_results_items_with_fallback(
    session: Session,
    *,
    snapshot: BettingResultsSnapshot | None = None,
    limit: int = 500,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_snapshot = snapshot or get_active_snapshot(session, BettingResultsSnapshot)
    snapshot_items = list((active_snapshot.payload_json if active_snapshot else {}).get("items", []))
    live_payload = build_betting_results_payload(session, limit=limit)
    live_items = list(live_payload.get("items", []))
    meta = snapshot_metadata(active_snapshot, key="results")
    use_fallback = (
        active_snapshot is None
        or (len(snapshot_items) == 0 and len(live_items) > 0)
        or bool(meta.get("is_stale"))
    )
    return (
        live_items if use_fallback else snapshot_items[:limit],
        {
            **snapshot_metadata(active_snapshot, key="results"),
            "source": "fallback_live" if use_fallback else "snapshot",
            "item_count": len(live_items if use_fallback else snapshot_items),
        },
    )


def build_bankroll_summary_payload(session: Session) -> dict[str, Any]:
    return build_bankroll_summary_payload_for_matches(session)


def build_bankroll_summary_payload_for_matches(
    session: Session,
    *,
    upcoming_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from api.v1 import betting as betting_api

    bankroll_summary = betting_api._build_bankroll_response(session).model_dump()
    active_positions_by_series = get_active_positions_by_series(session)
    active_bets = [
        betting_api.ActiveBetBadgeResponse.model_validate(position).model_dump()
        for series in active_positions_by_series
        for position in series["positions"]
    ]
    match_betting_statuses = _sanitize_match_betting_statuses(
        get_upcoming_match_betting_statuses(session, matches=upcoming_matches)
    )
    return {
        "summary": bankroll_summary,
        "active_bets": active_bets,
        "active_positions_by_series": active_positions_by_series,
        "match_betting_statuses": match_betting_statuses,
    }


def build_bankroll_summary_with_fallback(
    session: Session,
    *,
    snapshot: BankrollSummarySnapshot | None = None,
    upcoming_matches: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    active_snapshot = snapshot or get_active_snapshot(session, BankrollSummarySnapshot)
    snapshot_payload = active_snapshot.payload_json if active_snapshot else {}
    snapshot_summary = snapshot_payload.get("summary")
    snapshot_active_bets = list(snapshot_payload.get("active_bets", []))
    snapshot_active_positions_by_series = list(snapshot_payload.get("active_positions_by_series", []))
    snapshot_match_betting_statuses = _sanitize_match_betting_statuses(list(snapshot_payload.get("match_betting_statuses", [])))
    live_payload = build_bankroll_summary_payload_for_matches(
        session,
        upcoming_matches=upcoming_matches,
    )
    live_summary = live_payload.get("summary")
    live_active_bets = list(live_payload.get("active_bets", []))
    live_active_positions_by_series = list(live_payload.get("active_positions_by_series", []))
    live_match_betting_statuses = _sanitize_match_betting_statuses(list(live_payload.get("match_betting_statuses", [])))
    bankroll_meta = snapshot_metadata(active_snapshot, key="bankroll")
    use_fallback = active_snapshot is None or (
        not isinstance(snapshot_summary, dict)
        and isinstance(live_summary, dict)
    ) or bool(bankroll_meta.get("is_stale"))
    summary = live_summary if use_fallback else snapshot_summary
    active_bets = live_active_bets if use_fallback else snapshot_active_bets
    active_positions_by_series = (
        live_active_positions_by_series if use_fallback else snapshot_active_positions_by_series
    )
    match_betting_statuses = (
        live_match_betting_statuses if use_fallback else snapshot_match_betting_statuses
    )
    return (
        summary if isinstance(summary, dict) else None,
        active_bets,
        active_positions_by_series,
        match_betting_statuses,
        {
            **snapshot_metadata(active_snapshot, key="bankroll"),
            "source": "fallback_live" if use_fallback else "snapshot",
            "item_count": len(match_betting_statuses),
        },
    )


def build_upcoming_snapshot_payload() -> dict[str, Any]:
    from api.v1 import pandascore as pandascore_api

    cached = pandascore_api.read_upcoming_matches_from_file()
    raw = cached if cached is not None else []
    matches = [m for m in raw if isinstance(m, dict) and match_belongs_on_upcoming_odds_feed(m)]
    rows = pandascore_api._build_upcoming_with_odds_from_matches(matches)
    items: list[dict[str, Any]] = []
    for match, row in zip(matches, rows):
        serialized = pandascore_api._serialize_upcoming_row(row).model_dump()
        serialized["tournament_tier"] = (match.get("tournament") or {}).get("tier")
        items.append(serialized)
    return {
        "items": items,
        "source_matches": matches,
    }


def build_upcoming_matches_with_fallback(
    session: Session,
    *,
    snapshot: UpcomingWithOddsSnapshot | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_snapshot = snapshot or get_active_snapshot(session, UpcomingWithOddsSnapshot)
    snapshot_payload = active_snapshot.payload_json if active_snapshot else {}
    snapshot_matches = list(snapshot_payload.get("source_matches", []))
    meta = snapshot_metadata(active_snapshot, key="upcoming")
    use_fallback = active_snapshot is None or len(snapshot_matches) == 0 or meta["is_stale"]
    matches = snapshot_matches
    fallback_failed = False
    if use_fallback:
        try:
            matches = list(read_upcoming_matches_from_file() or [])
        except Exception:
            fallback_failed = True
            matches = list(snapshot_matches) if snapshot_matches else []
    status_out = {
        **meta,
        "source": "fallback_live" if use_fallback else "snapshot",
        "item_count": len(matches),
    }
    if use_fallback and not fallback_failed:
        status_out["is_stale"] = False
        status_out["data_as_of"] = datetime_to_iso(utc_now())
    return (matches, status_out)


def build_upcoming_items_with_fallback(
    session: Session,
    *,
    snapshot: UpcomingWithOddsSnapshot | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_snapshot = snapshot or get_active_snapshot(session, UpcomingWithOddsSnapshot)
    snapshot_items = list((active_snapshot.payload_json if active_snapshot else {}).get("items", []))
    upcoming_meta = snapshot_metadata(active_snapshot, key="upcoming")
    use_fallback = active_snapshot is None or len(snapshot_items) == 0 or bool(upcoming_meta.get("is_stale"))
    items = snapshot_items
    if use_fallback:
        try:
            items = list(build_upcoming_snapshot_payload().get("items", []))
        except Exception:
            items = []
    return (
        items,
        {
            **snapshot_metadata(active_snapshot, key="upcoming"),
            "source": "fallback_live" if use_fallback else "snapshot",
            "item_count": len(items),
        },
    )


def build_live_snapshot_payload() -> dict[str, Any]:
    from betting.bet_manager import _evaluate_match_for_betting, get_or_create_agent_bankroll
    from database import SessionLocal
    from entity_resolution.resolver import EntityResolver
    from api.v1 import pandascore as pandascore_api
    from ml.predictor_v2 import get_prediction_runtime_status
    from services.bookie import read_market_catalog_from_file, read_odds_from_file, resolve_match_odds
    from services.pandascore import fetch_json_sync, match_allowed_tier

    raw_matches = fetch_json_sync(
        "/lol/matches",
        params={"filter[status]": "running", "per_page": 50, "sort": "begin_at"},
    )
    matches = [
        row
        for row in (raw_matches if isinstance(raw_matches, list) else [])
        if match_allowed_tier(row)
    ]
    bookie_odds = read_market_catalog_from_file()
    moneyline_odds = read_odds_from_file()
    rows: list[dict[str, Any]] = []
    session = SessionLocal()
    bankroll = get_or_create_agent_bankroll(session)
    resolver = EntityResolver(session)
    model_available = get_prediction_runtime_status(session).get("active_model_id") is not None
    for match in matches:
        row = dict(match)
        team1, team2 = pandascore_api._get_team_names_from_match(match)
        acr1, acr2 = pandascore_api._get_team_acronyms_from_match(match)
        odds_resolution = resolve_match_odds(
            team1,
            team2,
            odds_list=moneyline_odds,
            market_catalog=bookie_odds,
            acronym1=acr1,
            acronym2=acr2,
        )
        row["bookie_odds_team1"] = odds_resolution["odds1"]
        row["bookie_odds_team2"] = odds_resolution["odds2"]
        row["bookie_odds_status_team1"] = "available" if odds_resolution["odds1"] is not None else "missing"
        row["bookie_odds_status_team2"] = "available" if odds_resolution["odds2"] is not None else "missing"
        row["odds_source_kind"] = odds_resolution["odds_source_kind"]
        row["odds_source_status"] = odds_resolution["odds_source_status"]
        row["model_odds_team1"] = None
        row["model_odds_team2"] = None
        row["pre_match_odds_team1"] = None
        row["pre_match_odds_team2"] = None
        row["markets"] = pandascore_api._market_rows_for_match(match, bookie_odds)
        results = match.get("results") or []
        opps = match.get("opponents") or []
        score1 = 0
        score2 = 0
        if len(results) >= 2 and len(opps) >= 2:
            opp1_id = (opps[0].get("opponent") or {}).get("id")
            for result in results:
                if result.get("team_id") == opp1_id:
                    score1 = result.get("score", 0)
                else:
                    score2 = result.get("score", 0)
        number_of_games = match.get("number_of_games") or 1
        from ml.series_probability import number_of_games_to_format

        row["series_score_team1"] = score1
        row["series_score_team2"] = score2
        row["series_format"] = number_of_games_to_format(number_of_games)
        candidate = _evaluate_match_for_betting(
            session,
            resolver,
            bankroll,
            match,
            bookie_odds,
            now=utc_now(),
            model_available=model_available,
        )
        row["recommended_bet"] = candidate.get("recommended_bet") if isinstance(candidate.get("recommended_bet"), dict) else None
        rows.append(row)
    session.close()
    pandascore_api._attach_v2_model_odds(rows, snapshot_kind="live")
    return {
        "items": [
            pandascore_api._serialize_live_row(row).model_dump()
            for row in rows
        ]
    }


def build_live_items_with_fallback(
    session: Session,
    *,
    snapshot: LiveWithOddsSnapshot | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_snapshot = snapshot or get_active_snapshot(session, LiveWithOddsSnapshot)
    snapshot_items = list((active_snapshot.payload_json if active_snapshot else {}).get("items", []))
    live_meta = snapshot_metadata(active_snapshot, key="live")
    use_fallback = active_snapshot is None or len(snapshot_items) == 0 or bool(live_meta.get("is_stale"))
    items = snapshot_items
    if use_fallback:
        try:
            items = list(build_live_snapshot_payload().get("items", []))
        except Exception:
            items = []
    return (
        items,
        {
            **snapshot_metadata(active_snapshot, key="live"),
            "source": "fallback_live" if use_fallback else "snapshot",
            "item_count": len(items),
        },
    )


def build_power_rankings_payload() -> dict[str, Any]:
    from api.v1 import rankings as rankings_api

    return {
        "items": [row.model_dump() for row in rankings_api.compute_power_rankings(None)]
    }


def build_rankings_items_with_fallback(
    session: Session,
    *,
    snapshot: PowerRankingsSnapshot | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_snapshot = snapshot or get_active_snapshot(session, PowerRankingsSnapshot)
    snapshot_items = list((active_snapshot.payload_json if active_snapshot else {}).get("items", []))
    use_fallback = active_snapshot is None or len(snapshot_items) == 0
    items = snapshot_items
    if use_fallback:
        try:
            items = list(build_power_rankings_payload().get("items", []))
        except Exception:
            items = []
    return (
        items,
        {
            **snapshot_metadata(active_snapshot, key="rankings"),
            "source": "fallback_live" if use_fallback else "snapshot",
            "item_count": len(items),
        },
    )


def build_homepage_bootstrap_payload(
    session: Session,
    *,
    homepage_snapshot: HomepageSnapshotManifest | None = None,
) -> dict[str, Any]:
    from api.v1 import pandascore as pandascore_api

    snapshot = homepage_snapshot or get_active_snapshot(session, HomepageSnapshotManifest)
    snapshot_payload = snapshot.payload_json if snapshot else {}
    upcoming_snapshot = get_active_snapshot(session, UpcomingWithOddsSnapshot)
    live_snapshot = get_active_snapshot(session, LiveWithOddsSnapshot)
    results_snapshot = get_active_snapshot(session, BettingResultsSnapshot)
    bankroll_snapshot = get_active_snapshot(session, BankrollSummarySnapshot)
    rankings_snapshot = get_active_snapshot(session, PowerRankingsSnapshot)

    upcoming_items, upcoming_status = build_upcoming_items_with_fallback(
        session,
        snapshot=upcoming_snapshot,
    )
    upcoming_matches, _ = build_upcoming_matches_with_fallback(
        session,
        snapshot=upcoming_snapshot,
    )
    live_items, live_status = build_live_items_with_fallback(
        session,
        snapshot=live_snapshot,
    )
    _, results_status = build_results_items_with_fallback(session, snapshot=results_snapshot)
    bankroll_summary, active_bets, active_positions_by_series, match_betting_statuses, bankroll_status = build_bankroll_summary_with_fallback(
        session,
        snapshot=bankroll_snapshot,
        upcoming_matches=upcoming_matches,
    )
    rankings_items, rankings_status = build_rankings_items_with_fallback(
        session,
        snapshot=rankings_snapshot,
    )

    manifest_active_bets = snapshot_payload.get("active_bets")
    manifest_match_betting_statuses = snapshot_payload.get("match_betting_statuses")
    manifest_rankings = snapshot_payload.get("power_rankings_preview")
    manifest_upcoming = snapshot_payload.get("upcoming")

    refresh_status = pandascore_api.get_odds_refresh_global_status_payload()

    manifest_upcoming_items = (
        list(manifest_upcoming.get("items", []))
        if isinstance(manifest_upcoming, dict)
        else []
    )
    homepage_upcoming = pandascore_api.paginate_upcoming_snapshot_items(
        upcoming_items if len(upcoming_items) > 0 else manifest_upcoming_items,
        page=1,
        per_page=10,
        tier="s,a",
    ).model_dump()

    return {
        "generated_at": snapshot_payload.get("generated_at")
        or snapshot_metadata(snapshot, key="homepage").get("generated_at")
        or datetime_to_iso(utc_now()),
        "results_generated_at": snapshot_payload.get("results_generated_at") or results_status.get("generated_at"),
        "upcoming": homepage_upcoming,
        "live": pandascore_api.paginate_live_snapshot_items(
            live_items,
            page=1,
            per_page=20,
        ).model_dump(),
        "bankroll": bankroll_summary,
        "active_bets": active_bets,
        "active_positions_by_series": active_positions_by_series,
        "match_betting_statuses": match_betting_statuses,
        "power_rankings_preview": manifest_rankings
        if isinstance(manifest_rankings, list) and len(manifest_rankings) > 0
        else rankings_items[:10],
        "refresh_status": {
            "in_progress": refresh_status.get("in_progress", False),
            "progress": refresh_status.get("progress", 0),
            "stage": refresh_status.get("stage", ""),
            "last_completed_at": refresh_status.get("last_completed_at"),
            "next_scheduled_at": refresh_status.get("next_scheduled_at"),
        },
        "section_status": {
            "homepage": {
                **snapshot_metadata(snapshot, key="homepage"),
                "source": "snapshot" if snapshot is not None else "fallback_live",
            },
            "upcoming": upcoming_status,
            "live": live_status,
            "results": results_status,
            "bankroll": bankroll_status,
            "rankings": rankings_status,
        },
    }


def build_homepage_manifest_payload(session: Session) -> dict[str, Any]:
    return build_homepage_bootstrap_payload(session)

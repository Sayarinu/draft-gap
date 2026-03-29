from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from betting.bet_manager import get_match_betting_diagnostics, get_or_create_agent_bankroll
from betting.bet_manager import get_upcoming_match_betting_statuses
from ml.model_manifest import get_manifest_path, read_model_manifest
from ml.predictor_v2 import get_prediction_runtime_status
from models_ml import (
    BankrollSummarySnapshot,
    Bet,
    BettingResultsSnapshot,
    HomepageSnapshotManifest,
    LiveWithOddsSnapshot,
    MLModelRun,
    PowerRankingsSnapshot,
    UpcomingWithOddsSnapshot,
)
from services.homepage_snapshots import (
    build_homepage_bootstrap_payload,
    build_upcoming_items_with_fallback,
    build_upcoming_matches_with_fallback,
    get_active_snapshot,
    snapshot_metadata,
)
from services.pandascore import classify_match_betting_eligibility

logger = logging.getLogger(__name__)

ODDS_ATTACHMENT_STATUS_TTL_SECONDS = 86400
ODDS_ATTACHMENT_STATUS_KEY_PREFIX = "runtime:odds_attachment:"
THUNDERPICK_SCRAPE_STATUS_PATH = Path(os.getenv("PANDASCORE_OUTPUT_DIR", "/cache/pandascore")) / "thunderpick_scrape_status.json"

_odds_attachment_local_status: dict[str, dict[str, Any]] = {}
_redis_client: Redis | None = None
_redis_init_attempted = False


def _utc_now_iso() -> str:
    from services.odds_refresh_status import _utc_now_iso as refresh_iso

    return refresh_iso()


def _get_redis() -> Redis | None:
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url:
        return None
    try:
        client = Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
    except Exception as e:
        logger.warning(
            "runtime_diagnostics redis unavailable: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )
        _redis_client = None
    return _redis_client


def record_odds_attachment_status(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_kind = kind.strip().lower() or "unknown"
    next_payload = {
        **payload,
        "kind": normalized_kind,
        "updated_at": _utc_now_iso(),
    }
    _odds_attachment_local_status[normalized_kind] = next_payload
    client = _get_redis()
    if client is None:
        return next_payload
    try:
        client.set(
            f"{ODDS_ATTACHMENT_STATUS_KEY_PREFIX}{normalized_kind}",
            json.dumps(next_payload),
            ex=ODDS_ATTACHMENT_STATUS_TTL_SECONDS,
        )
    except RedisError as e:
        logger.warning(
            "record_odds_attachment_status failed: kind=%s error_type=%s error=%s",
            normalized_kind,
            type(e).__name__,
            str(e),
        )
    return next_payload


def get_odds_attachment_status(kind: str) -> dict[str, Any] | None:
    normalized_kind = kind.strip().lower() or "unknown"
    client = _get_redis()
    if client is not None:
        try:
            raw = client.get(f"{ODDS_ATTACHMENT_STATUS_KEY_PREFIX}{normalized_kind}")
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
        except (RedisError, json.JSONDecodeError) as e:
            logger.warning(
                "get_odds_attachment_status failed: kind=%s error_type=%s error=%s",
                normalized_kind,
                type(e).__name__,
                str(e),
            )
    return _odds_attachment_local_status.get(normalized_kind)


def _snapshot_item_count(snapshot: object | None) -> int | None:
    payload = getattr(snapshot, "payload_json", None)
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if isinstance(items, list):
        return len(items)
    return None


def build_snapshot_status_payload(session: Session) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, tuple[type[object], str]] = {
        "upcoming": (UpcomingWithOddsSnapshot, "upcoming"),
        "live": (LiveWithOddsSnapshot, "live"),
        "results": (BettingResultsSnapshot, "results"),
        "bankroll": (BankrollSummarySnapshot, "bankroll"),
        "rankings": (PowerRankingsSnapshot, "rankings"),
        "homepage": (HomepageSnapshotManifest, "homepage"),
    }
    payload: dict[str, dict[str, Any]] = {}
    for name, (model, key) in snapshots.items():
        snapshot = get_active_snapshot(session, model)
        meta = snapshot_metadata(snapshot, key=key)
        meta["item_count"] = _snapshot_item_count(snapshot)
        payload[name] = meta
    return payload


def build_betting_state_payload(session: Session) -> dict[str, Any]:
    bankroll = get_or_create_agent_bankroll(session)
    session.refresh(bankroll)
    all_bets = session.query(Bet).filter(Bet.bankroll_id == bankroll.id).all()
    settled_bets = [row for row in all_bets if row.status in {"WON", "LOST"}]
    open_bets = [row for row in all_bets if row.status == "PLACED"]
    return {
        "bankroll_id": str(bankroll.id),
        "initial_balance": float(bankroll.initial_balance),
        "current_balance": float(bankroll.current_balance),
        "total_bets": len(all_bets),
        "settled_bets": len(settled_bets),
        "open_bets": len(open_bets),
    }


def build_force_window_blockers_payload(session: Session) -> dict[str, Any]:
    statuses = get_upcoming_match_betting_statuses(session)
    within_force_window = [
        row for row in statuses if bool(row.get("within_force_window"))
    ]
    blocked = [
        row for row in within_force_window
        if str(row.get("status") or "").startswith("blocked_")
    ]
    waiting = [
        row for row in within_force_window
        if str(row.get("status") or "") == "waiting_for_better_odds"
    ]

    blocked_by_reason: dict[str, int] = {}
    for row in blocked:
        reason_code = str(row.get("reason_code") or "unknown")
        blocked_by_reason[reason_code] = blocked_by_reason.get(reason_code, 0) + 1

    return {
        "matches_with_status": len(statuses),
        "within_force_window_matches": len(within_force_window),
        "blocked_matches": len(blocked),
        "waiting_matches": len(waiting),
        "blocked_by_reason": blocked_by_reason,
    }


def _artifact_paths_for_run(run: MLModelRun | None) -> list[Path]:
    if run is None:
        return []
    base = Path(run.artifact_path)
    if run.model_type == "xgboost":
        return [base.with_suffix(".xgb"), base.with_suffix(".meta")]
    if run.model_type == "mlp":
        return [base.with_suffix(".pt"), base.with_suffix(".scaler")]
    return [base]


def build_model_runtime_payload(session: Session) -> dict[str, Any]:
    runtime_status = get_prediction_runtime_status(session)
    manifest = read_model_manifest() or {}
    manifest_path = get_manifest_path()
    active_db_model = (
        session.query(MLModelRun)
        .filter(MLModelRun.is_active.is_(True))
        .order_by(MLModelRun.created_at.desc())
        .first()
    )
    loaded_run = None
    active_model_id = runtime_status.get("active_model_id")
    if isinstance(active_model_id, int):
        loaded_run = session.get(MLModelRun, active_model_id)

    loaded_artifacts = _artifact_paths_for_run(loaded_run)
    manifest_run = None
    manifest_run_id = manifest.get("source_run_id")
    if isinstance(manifest_run_id, int):
        manifest_run = session.get(MLModelRun, manifest_run_id)
    manifest_artifacts = _artifact_paths_for_run(manifest_run)

    return {
        "db_active_model_id": active_db_model.id if active_db_model is not None else None,
        "db_active_model_version": active_db_model.model_version if active_db_model is not None else None,
        "db_active_model_type": active_db_model.model_type if active_db_model is not None else None,
        "loaded_model_id": active_model_id,
        "loaded_model_version": runtime_status.get("active_model_version"),
        "loaded_model_path": runtime_status.get("active_model_path"),
        "loaded_model_type": loaded_run.model_type if loaded_run is not None else None,
        "loaded_artifact_paths": [str(path) for path in loaded_artifacts],
        "loaded_artifacts_available": all(path.exists() for path in loaded_artifacts) if loaded_artifacts else False,
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "manifest_run_id": manifest.get("source_run_id"),
        "manifest_version": manifest.get("model_version"),
        "manifest_model_type": manifest.get("model_type"),
        "manifest_artifact_path": manifest.get("active_artifact_path"),
        "manifest_artifact_paths": [str(path) for path in manifest_artifacts],
        "manifest_artifacts_available": all(path.exists() for path in manifest_artifacts) if manifest_artifacts else False,
        "game_data_row_count": runtime_status.get("game_data_row_count"),
    }


def build_runtime_status_payload(session: Session) -> dict[str, Any]:
    from api.v1.pandascore import get_odds_refresh_global_status_payload

    snapshot_status = build_snapshot_status_payload(session)
    betting_state = build_betting_state_payload(session)
    force_window_blockers = build_force_window_blockers_payload(session)
    model_runtime = build_model_runtime_payload(session)
    refresh_status = get_odds_refresh_global_status_payload()
    odds_attachment_status = {
        "upcoming": get_odds_attachment_status("upcoming"),
        "live": get_odds_attachment_status("live"),
    }
    thunderpick_scrape_status = read_thunderpick_scrape_status()

    detected_issues: list[str] = []
    if betting_state["settled_bets"] > 0 and not snapshot_status["results"].get("item_count"):
        detected_issues.append("Settled bets exist in the database but the active results snapshot is empty or missing.")
    if betting_state["total_bets"] > 0 and not snapshot_status["homepage"].get("snapshot_version"):
        detected_issues.append("Bet history exists but the homepage manifest snapshot is missing.")
    if model_runtime.get("loaded_model_id") is None:
        detected_issues.append("No loadable active model is available in the API runtime.")
    if (
        model_runtime.get("manifest_run_id") is not None
        and model_runtime.get("loaded_model_id") is not None
        and model_runtime.get("manifest_run_id") != model_runtime.get("loaded_model_id")
    ):
        detected_issues.append("Loaded model does not match the promoted manifest run.")

    return {
        "model_runtime": model_runtime,
        "snapshot_status": snapshot_status,
        "betting_state": betting_state,
        "force_window_blockers": force_window_blockers,
        "refresh_status": refresh_status,
        "odds_attachment_status": odds_attachment_status,
        "thunderpick_scrape_status": thunderpick_scrape_status,
        "detected_issues": detected_issues,
    }


def read_thunderpick_scrape_status() -> dict[str, Any] | None:
    try:
        if not THUNDERPICK_SCRAPE_STATUS_PATH.is_file():
            return None
        with open(THUNDERPICK_SCRAPE_STATUS_PATH, encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(
            "read_thunderpick_scrape_status failed: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )
        return None


def _component_status(ok: bool) -> str:
    return "ok" if ok else "error"


def build_operator_debug_payload(
    session: Session,
    *,
    search: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    runtime_status = build_runtime_status_payload(session)
    betting_diagnostics = get_match_betting_diagnostics(
        session,
        search=search,
        include_live=True,
        include_placed=False,
        limit=limit,
    )

    model_runtime = runtime_status["model_runtime"]
    snapshot_status = runtime_status["snapshot_status"]
    refresh_status = runtime_status["refresh_status"]
    odds_attachment_status = runtime_status["odds_attachment_status"]
    thunderpick_scrape_status = runtime_status.get("thunderpick_scrape_status")
    force_window_blockers = runtime_status["force_window_blockers"]
    detected_issues = list(runtime_status["detected_issues"])

    component_checks = [
        {
            "component": "model_runtime",
            "status": _component_status(model_runtime.get("loaded_model_id") is not None),
            "summary": "Model loaded" if model_runtime.get("loaded_model_id") is not None else "No model loaded in API runtime",
            "details": {
                "loaded_model_id": model_runtime.get("loaded_model_id"),
                "loaded_model_version": model_runtime.get("loaded_model_version"),
                "loaded_artifacts_available": model_runtime.get("loaded_artifacts_available"),
                "manifest_run_id": model_runtime.get("manifest_run_id"),
            },
        },
        {
            "component": "upcoming_snapshot",
            "status": _component_status(bool(snapshot_status["upcoming"].get("snapshot_version"))),
            "summary": "Upcoming snapshot present" if snapshot_status["upcoming"].get("snapshot_version") else "Upcoming snapshot missing",
            "details": snapshot_status["upcoming"],
        },
        {
            "component": "live_snapshot",
            "status": _component_status(bool(snapshot_status["live"].get("snapshot_version"))),
            "summary": "Live snapshot present" if snapshot_status["live"].get("snapshot_version") else "Live snapshot missing",
            "details": snapshot_status["live"],
        },
        {
            "component": "homepage_snapshot",
            "status": _component_status(bool(snapshot_status["homepage"].get("snapshot_version"))),
            "summary": "Homepage snapshot present" if snapshot_status["homepage"].get("snapshot_version") else "Homepage snapshot missing",
            "details": snapshot_status["homepage"],
        },
        {
            "component": "odds_attachment_upcoming",
            "status": _component_status(odds_attachment_status.get("upcoming") is not None),
            "summary": "Upcoming odds attachment recorded" if odds_attachment_status.get("upcoming") else "No upcoming odds attachment status recorded",
            "details": odds_attachment_status.get("upcoming"),
        },
        {
            "component": "odds_attachment_live",
            "status": _component_status(odds_attachment_status.get("live") is not None),
            "summary": "Live odds attachment recorded" if odds_attachment_status.get("live") else "No live odds attachment status recorded",
            "details": odds_attachment_status.get("live"),
        },
        {
            "component": "thunderpick_scraper",
            "status": _component_status(thunderpick_scrape_status is not None),
            "summary": (
                "Thunderpick scrape summary recorded"
                if thunderpick_scrape_status
                else "No Thunderpick scrape summary recorded"
            ),
            "details": thunderpick_scrape_status,
        },
        {
            "component": "betting_pipeline",
            "status": _component_status(force_window_blockers.get("blocked_matches", 0) == 0),
            "summary": (
                "No force-window blockers"
                if force_window_blockers.get("blocked_matches", 0) == 0
                else f"{force_window_blockers.get('blocked_matches', 0)} force-window blockers"
            ),
            "details": force_window_blockers,
        },
        {
            "component": "refresh_scheduler",
            "status": _component_status(not bool(refresh_status.get("in_progress")) or refresh_status.get("progress", 0) >= 0),
            "summary": "Refresh scheduler reachable",
            "details": refresh_status,
        },
    ]

    recommendations: list[str] = []
    if model_runtime.get("loaded_model_id") is None:
        recommendations.append("Promote or reload an active model before trusting any betting output.")
    if not snapshot_status["upcoming"].get("snapshot_version"):
        recommendations.append("Refresh upcoming snapshots so live production data is available to the homepage and betting diagnostics.")
    if force_window_blockers.get("blocked_matches", 0) > 0:
        blocked_by_reason = force_window_blockers.get("blocked_by_reason") or {}
        top_reason = max(blocked_by_reason, key=blocked_by_reason.get) if blocked_by_reason else None
        if top_reason:
            recommendations.append(f"Investigate the dominant blocker `{top_reason}` first in the betting diagnostics output.")
    if thunderpick_scrape_status and thunderpick_scrape_status.get("degraded_mode"):
        recommendations.append("Thunderpick scraping is running in degraded text-fallback mode; inspect scrape samples and rejected rows before changing match thresholds.")
    if betting_diagnostics["summary"].get("waiting_matches", 0) > 0:
        recommendations.append("Review waiting matches with edge/confidence diagnostics before changing global thresholds.")
    if not recommendations:
        recommendations.append("No obvious systemic blocker detected; inspect a specific match via the betting diagnostics search filter.")

    return {
        "generated_at": _utc_now_iso(),
        "runtime_status": runtime_status,
        "betting_diagnostics": betting_diagnostics,
        "component_checks": component_checks,
        "recommendations": recommendations,
        "detected_issues": detected_issues,
    }


def _safe_int(value: object) -> int | None:
    try:
        out = int(value)
    except Exception:
        return None
    return out if out > 0 else None


def _compare_match_row(
    match_id: int,
    homepage_row: dict[str, Any] | None,
    snapshot_row: dict[str, Any] | None,
    source_match: dict[str, Any] | None,
    betting_status: dict[str, Any] | None,
) -> dict[str, Any]:
    eligibility = classify_match_betting_eligibility(source_match or {})
    homepage_team_a = str((homepage_row or {}).get("team1_name") or "").strip()
    homepage_team_b = str((homepage_row or {}).get("team2_name") or "").strip()
    snapshot_team_a = str((snapshot_row or {}).get("team1_name") or "").strip()
    snapshot_team_b = str((snapshot_row or {}).get("team2_name") or "").strip()
    source_match_opponents = (source_match or {}).get("opponents") or []
    source_team_a = str(((source_match_opponents[0].get("opponent") or {}).get("name") if len(source_match_opponents) > 0 else "") or "").strip()
    source_team_b = str(((source_match_opponents[1].get("opponent") or {}).get("name") if len(source_match_opponents) > 1 else "") or "").strip()

    display_team_a = homepage_team_a or snapshot_team_a or source_team_a or str((betting_status or {}).get("team_a") or "").strip()
    display_team_b = homepage_team_b or snapshot_team_b or source_team_b or str((betting_status or {}).get("team_b") or "").strip()
    scheduled_at = (
        str((homepage_row or {}).get("scheduled_at") or "").strip()
        or str((snapshot_row or {}).get("scheduled_at") or "").strip()
        or str((source_match or {}).get("scheduled_at") or "").strip()
        or str((betting_status or {}).get("scheduled_at") or "").strip()
        or None
    )
    league = (
        str((homepage_row or {}).get("league_name") or "").strip()
        or str((snapshot_row or {}).get("league_name") or "").strip()
        or str((((source_match or {}).get("league") or {}).get("name") or "")).strip()
        or str((betting_status or {}).get("league") or "").strip()
        or None
    )
    discrepancy_codes: list[str] = []
    in_homepage = homepage_row is not None
    in_snapshot = snapshot_row is not None
    in_source = source_match is not None
    in_betting = betting_status is not None
    if in_homepage and not in_snapshot:
        discrepancy_codes.append("homepage_only")
    if in_homepage and not in_source:
        discrepancy_codes.append("homepage_missing_source_match")
    if in_homepage and not in_betting:
        discrepancy_codes.append("homepage_missing_betting_status")
    if in_snapshot and not in_source:
        discrepancy_codes.append("snapshot_missing_source_match")
    if in_source and not in_snapshot:
        discrepancy_codes.append("source_missing_snapshot_item")
    if in_source and not in_betting:
        discrepancy_codes.append("source_missing_betting_status")
    if in_betting and not in_source:
        discrepancy_codes.append("betting_status_missing_source_match")

    return {
        "pandascore_match_id": match_id,
        "scheduled_at": scheduled_at,
        "league": league,
        "team_a": display_team_a or "TBD",
        "team_b": display_team_b or "TBD",
        "in_homepage_visible": in_homepage,
        "in_upcoming_snapshot": in_snapshot,
        "in_upcoming_source_matches": in_source,
        "in_betting_statuses": in_betting,
        "betting_status": str((betting_status or {}).get("status") or "") or None,
        "reason_code": str((betting_status or {}).get("reason_code") or "") or None,
        "short_detail": str((betting_status or {}).get("short_detail") or "") or None,
        "is_bettable": bool((betting_status or {}).get("is_bettable", eligibility.get("is_bettable", False))),
        "eligibility_reason": str((betting_status or {}).get("eligibility_reason") or eligibility.get("eligibility_reason") or "") or None,
        "bookie_odds_present": bool(
            (homepage_row or {}).get("bookie_odds_team1") is not None
            or (homepage_row or {}).get("bookie_odds_team2") is not None
            or (snapshot_row or {}).get("bookie_odds_team1") is not None
            or (snapshot_row or {}).get("bookie_odds_team2") is not None
        ),
        "odds_source_kind": str((betting_status or {}).get("odds_source_kind") or (homepage_row or {}).get("odds_source_kind") or (snapshot_row or {}).get("odds_source_kind") or "") or None,
        "discrepancy_codes": discrepancy_codes,
    }


def build_match_feed_comparison_payload(
    session: Session,
    *,
    search: str | None = None,
    limit: int = 50,
    mismatches_only: bool = False,
) -> dict[str, Any]:
    upcoming_snapshot = get_active_snapshot(session, UpcomingWithOddsSnapshot)
    homepage_snapshot = get_active_snapshot(session, HomepageSnapshotManifest)
    homepage_payload = build_homepage_bootstrap_payload(session, homepage_snapshot=homepage_snapshot)
    homepage_items = list(((homepage_payload.get("upcoming") or {}).get("items") or []))
    snapshot_items, snapshot_status = build_upcoming_items_with_fallback(
        session,
        snapshot=upcoming_snapshot,
    )
    source_matches, source_status = build_upcoming_matches_with_fallback(
        session,
        snapshot=upcoming_snapshot,
    )
    betting_statuses = get_upcoming_match_betting_statuses(session, matches=source_matches)

    homepage_by_id = {
        match_id: item
        for item in homepage_items
        if (match_id := _safe_int(item.get("id"))) is not None
    }
    snapshot_by_id = {
        match_id: item
        for item in snapshot_items
        if (match_id := _safe_int(item.get("id"))) is not None
    }
    source_by_id = {
        match_id: match
        for match in source_matches
        if (match_id := _safe_int(match.get("id"))) is not None
    }
    betting_by_id = {
        match_id: row
        for row in betting_statuses
        if (match_id := _safe_int(row.get("pandascore_match_id"))) is not None
    }

    lowered_search = (search or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for match_id in sorted(set(homepage_by_id) | set(snapshot_by_id) | set(source_by_id) | set(betting_by_id)):
        row = _compare_match_row(
            match_id,
            homepage_by_id.get(match_id),
            snapshot_by_id.get(match_id),
            source_by_id.get(match_id),
            betting_by_id.get(match_id),
        )
        haystack = " ".join(
            filter(
                None,
                [
                    str(row.get("team_a") or ""),
                    str(row.get("team_b") or ""),
                    str(row.get("league") or ""),
                    str(row.get("betting_status") or ""),
                    " ".join(str(code) for code in row.get("discrepancy_codes", [])),
                ],
            )
        ).lower()
        if lowered_search and lowered_search not in haystack:
            continue
        if mismatches_only and not row["discrepancy_codes"]:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break

    summary = {
        "homepage_visible_count": len(homepage_by_id),
        "upcoming_snapshot_count": len(snapshot_by_id),
        "upcoming_source_match_count": len(source_by_id),
        "betting_status_count": len(betting_by_id),
        "homepage_missing_betting_status_count": sum(
            1 for row in rows if "homepage_missing_betting_status" in row["discrepancy_codes"]
        ),
        "homepage_missing_source_match_count": sum(
            1 for row in rows if "homepage_missing_source_match" in row["discrepancy_codes"]
        ),
        "snapshot_missing_source_match_count": sum(
            1 for row in rows if "snapshot_missing_source_match" in row["discrepancy_codes"]
        ),
        "source_missing_snapshot_item_count": sum(
            1 for row in rows if "source_missing_snapshot_item" in row["discrepancy_codes"]
        ),
        "source_missing_betting_status_count": sum(
            1 for row in rows if "source_missing_betting_status" in row["discrepancy_codes"]
        ),
        "rows_returned": len(rows),
        "mismatches_only": mismatches_only,
    }
    return {
        "summary": summary,
        "sources": {
            "homepage": {
                "generated_at": str(homepage_payload.get("generated_at") or "") or None,
                "visible_count": len(homepage_by_id),
            },
            "upcoming_snapshot": snapshot_status,
            "upcoming_source_matches": source_status,
        },
        "matches": rows,
    }


def render_operator_debug_report(payload: dict[str, Any]) -> str:
    runtime_status = payload.get("runtime_status") or {}
    betting_diagnostics = payload.get("betting_diagnostics") or {}
    component_checks = payload.get("component_checks") or []
    recommendations = payload.get("recommendations") or []
    matches = betting_diagnostics.get("matches") or []
    summary = betting_diagnostics.get("summary") or {}

    lines = [
        "DRAFT GAP DEBUG REPORT",
        f"generated_at: {payload.get('generated_at')}",
        "",
        "SYSTEM CHECKS",
    ]
    for check in component_checks:
        status = str(check.get("status") or "unknown").upper()
        lines.append(f"- [{status}] {check.get('component')}: {check.get('summary')}")

    lines.extend(
        [
            "",
            "RUNTIME SUMMARY",
            f"- detected_issues: {len(runtime_status.get('detected_issues') or [])}",
            f"- total_bets: {((runtime_status.get('betting_state') or {}).get('total_bets'))}",
            f"- blocked_force_window_matches: {((runtime_status.get('force_window_blockers') or {}).get('blocked_matches'))}",
            f"- waiting_matches: {summary.get('waiting_matches')}",
            f"- pending_matches: {summary.get('pending_matches')}",
            "",
            "THUNDERPICK SCRAPE",
            f"- dom_match_count: {((runtime_status.get('thunderpick_scrape_status') or {}).get('dom_match_count'))}",
            f"- text_match_count: {((runtime_status.get('thunderpick_scrape_status') or {}).get('text_match_count'))}",
            f"- accepted_match_count: {((runtime_status.get('thunderpick_scrape_status') or {}).get('accepted_match_count'))}",
            f"- rejected_candidate_count: {((runtime_status.get('thunderpick_scrape_status') or {}).get('rejected_candidate_count'))}",
            f"- degraded_mode: {((runtime_status.get('thunderpick_scrape_status') or {}).get('degraded_mode'))}",
            "",
            "TOP MATCH DIAGNOSTICS",
        ]
    )
    if not matches:
        lines.append("- none")
    else:
        for match in matches:
            details = match.get("diagnostics") or {}
            lines.append(
                f"- {match.get('team_a')} vs {match.get('team_b')} [{match.get('status')}] "
                f"{match.get('short_detail') or match.get('reason_code') or ''}".strip()
            )
            lines.append(
                f"  match_id={match.get('pandascore_match_id')} edge={details.get('chosen_edge')} "
                f"threshold={details.get('min_edge_threshold')} confidence={details.get('confidence')} "
                f"ev={details.get('ev')} bookie_match={details.get('bookie_match_confidence')}"
            )

    lines.extend(["", "RECOMMENDATIONS"])
    for recommendation in recommendations:
        lines.append(f"- {recommendation}")

    return "\n".join(lines)

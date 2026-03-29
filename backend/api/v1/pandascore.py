from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
from typing import Annotated, TypeVar

import httpx
from redis import Redis  # type: ignore[import-untyped]
from redis.exceptions import RedisError  # type: ignore[import-untyped]
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from celery.result import AsyncResult  # type: ignore[import-untyped]

from api.dependencies import get_db, require_admin_api_key
from database import SessionLocal
from models_ml import LiveWithOddsSnapshot, MLModelRun, UpcomingWithOddsSnapshot
from services.homepage_snapshots import (
    apply_snapshot_headers,
    get_active_snapshot,
)
from services.odds_refresh_status import (
    clear_current_task_id,
    get_current_task_id,
    get_last_completed_at,
)
from services.runtime_diagnostics import record_odds_attachment_status
from services.pandascore import (
    download_upcoming_lol_fixtures_async,
    fetch_all_lol_leagues_async,
    fetch_all_series_async,
    fetch_all_tournaments_async,
    fetch_league_upcoming_matches_async,
    fetch_running_lol_matches_async,
    fetch_upcoming_lol_matches_async,
    get_output_dir,
    get_token,
    league_slug_or_id_approved,
    match_allowed_tier,
    read_upcoming_matches_from_file,
)
from services.bookie import (
    find_market_set_for_match,
    find_odds_for_match,
    get_odds_cache_path,
    read_market_catalog_from_file,
    read_odds_from_file,
    resolve_match_odds,
)

router = APIRouter(prefix="/pandascore", tags=["pandascore"])
logger = logging.getLogger(__name__)
TItem = TypeVar("TItem")

_odds_response_cache: dict[str, tuple[object, dict[str, float]]] = {}
_manual_refresh_next_available_local: datetime | None = None
_manual_refresh_redis_client: Redis | None = None
_manual_refresh_redis_init_attempted = False

MANUAL_REFRESH_LOCKOUT_SECONDS = 120
MANUAL_REFRESH_NEXT_AVAILABLE_KEY = "odds:manual_refresh_next_available_at"


def _mtime_safe(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _source_mtimes_upcoming() -> dict[str, float]:
    base = get_output_dir()
    return {
        "thunderpick": _mtime_safe(get_odds_cache_path()),
        "pandascore_upcoming": _mtime_safe(base / "lol_matches_upcoming.json"),
        "active_model": _active_model_cache_key(),
    }


def _source_mtimes_live() -> dict[str, float]:
    return {
        "thunderpick": _mtime_safe(get_odds_cache_path()),
        "active_model": _active_model_cache_key(),
    }


def _active_model_cache_key() -> float:
    session = SessionLocal()
    try:
        active = (
            session.query(MLModelRun)
            .filter(MLModelRun.is_active.is_(True))
            .order_by(MLModelRun.created_at.desc())
            .first()
        )
        if active is None:
            return 0.0
        created_at = getattr(active, "created_at", None)
        created_at_value = created_at.timestamp() if created_at is not None else 0.0
        return float(active.id) + created_at_value
    except Exception:
        logger.exception("pandascore.active_model_cache_key failed")
        return 0.0
    finally:
        session.close()


def _get_cached_odds(key: str, current_mtimes: dict[str, float]) -> object | None:
    entry = _odds_response_cache.get(key)
    if entry is None:
        return None
    data, stored_mtimes = entry
    if stored_mtimes != current_mtimes:
        del _odds_response_cache[key]
        return None
    return copy.deepcopy(data)


def _set_cached_odds(key: str, data: object, mtimes: dict[str, float]) -> None:
    _odds_response_cache[key] = (data, dict(mtimes))


class UpcomingOddsItemResponse(BaseModel):
    id: int
    scheduled_at: str
    league_name: str
    team1_name: str
    team1_acronym: str | None = None
    team2_name: str
    team2_acronym: str | None = None
    stream_url: str | None = None
    bookie_odds_team1: float | None = None
    bookie_odds_team2: float | None = None
    bookie_odds_status_team1: str | None = Field(default=None, exclude_if=lambda v: v is None)
    bookie_odds_status_team2: str | None = Field(default=None, exclude_if=lambda v: v is None)
    odds_source_kind: str | None = Field(default=None, exclude_if=lambda v: v is None)
    odds_source_status: str | None = Field(default=None, exclude_if=lambda v: v is None)
    model_odds_team1: float | None = None
    model_odds_team2: float | None = None
    series_format: str
    markets: list[dict[str, object]] = Field(default_factory=list, exclude_if=lambda v: len(v) == 0)
    recommended_bet: dict[str, object] | None = Field(default=None, exclude_if=lambda v: v is None)


class LiveOddsItemResponse(UpcomingOddsItemResponse):
    series_score_team1: int
    series_score_team2: int
    pre_match_odds_team1: float | None = None
    pre_match_odds_team2: float | None = None
    live_recommendation: dict[str, object] | None = Field(default=None, exclude_if=lambda v: v is None)


class PaginatedUpcomingOddsResponse(BaseModel):
    items: list[UpcomingOddsItemResponse]
    page: int = Field(ge=1)
    per_page: int = Field(ge=1)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=1)
    available_leagues: list[str] = []


class PaginatedLiveOddsResponse(BaseModel):
    items: list[LiveOddsItemResponse]
    page: int = Field(ge=1)
    per_page: int = Field(ge=1)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=1)
    available_leagues: list[str] = []


LEAGUE_DISPLAY_NAME_OVERRIDES: dict[str, str] = {
    "north american challengers league": "NACL",
    "north-american-challengers-league": "NACL",
    "esports world cup": "EWC",
    "esports-world-cup": "EWC",
}

HIDDEN_FEED_LEAGUES = {"LJL", "VCS", "NACL"}


def _safe_string(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def _safe_optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalized_league_name(value: object) -> str:
    return str(value or "").strip().upper()


def _display_league_name(league: dict[str, object]) -> str:
    raw_name = _safe_string(league.get("name")).strip()
    raw_slug = _safe_string(league.get("slug")).strip()
    abbreviation = _safe_string(league.get("abbreviation")).strip()

    if abbreviation:
        return abbreviation.upper()

    for candidate in (raw_name.lower(), raw_slug.lower()):
        if candidate in LEAGUE_DISPLAY_NAME_OVERRIDES:
            return LEAGUE_DISPLAY_NAME_OVERRIDES[candidate]

    return raw_name or "—"


def _paginate_items(items: list[TItem], page: int, per_page: int) -> tuple[list[TItem], int]:
    total_items = len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    safe_page = min(max(page, 1), total_pages)
    start = (safe_page - 1) * per_page
    end = start + per_page
    return items[start:end], total_pages


def _normalize_query_parts(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def _item_search_matches(item: dict[str, object], query: str) -> bool:
    if not query:
        return True
    haystack = [
        str(item.get("league_name") or "").lower(),
        str(item.get("team1_name") or "").lower(),
        str(item.get("team2_name") or "").lower(),
        str(item.get("team1_acronym") or "").lower(),
        str(item.get("team2_acronym") or "").lower(),
    ]
    return any(query in part for part in haystack)


def _is_tbd_vs_tbd_item(item: dict[str, object]) -> bool:
    team1 = str(item.get("team1_name") or "TBD").strip().upper() or "TBD"
    team2 = str(item.get("team2_name") or "TBD").strip().upper() or "TBD"
    return team1 == "TBD" and team2 == "TBD"


def _filter_odds_snapshot_items(
    items: list[dict[str, object]],
    *,
    tier: str | None = None,
    league: str | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    requested_tiers = _normalize_query_parts(tier)
    requested_leagues = set(_normalize_query_parts(league))
    query = (search or "").strip().lower()

    tier_filtered = items
    if requested_tiers:
        tier_filtered = [
            item
            for item in tier_filtered
            if str(item.get("tournament_tier") or "").lower() in requested_tiers
        ]

    visible_items = [
        item
        for item in tier_filtered
        if not _is_tbd_vs_tbd_item(item)
        and _normalized_league_name(item.get("league_name")) not in HIDDEN_FEED_LEAGUES
    ]
    available_leagues = sorted(
        {
            str(item.get("league_name") or "").strip()
            for item in visible_items
            if str(item.get("league_name") or "").strip()
        }
    )

    filtered = visible_items
    if requested_leagues:
        filtered = [
            item
            for item in filtered
            if str(item.get("league_name") or "").strip().lower() in requested_leagues
        ]
    if query:
        filtered = [item for item in filtered if _item_search_matches(item, query)]
    return filtered, available_leagues


def paginate_upcoming_snapshot_items(
    items: list[dict[str, object]],
    *,
    page: int,
    per_page: int,
    tier: str | None = None,
    league: str | None = None,
    search: str | None = None,
) -> PaginatedUpcomingOddsResponse:
    filtered_items, available_leagues = _filter_odds_snapshot_items(
        items,
        tier=tier,
        league=league,
        search=search,
    )
    slim_items = [
        UpcomingOddsItemResponse.model_validate(item) for item in filtered_items
    ]
    paged_items, total_pages = _paginate_items(slim_items, page, per_page)
    return PaginatedUpcomingOddsResponse(
        items=paged_items,
        page=min(max(page, 1), total_pages),
        per_page=per_page,
        total_items=len(slim_items),
        total_pages=total_pages,
        available_leagues=available_leagues,
    )


def paginate_live_snapshot_items(
    items: list[dict[str, object]],
    *,
    page: int,
    per_page: int,
    league: str | None = None,
    search: str | None = None,
) -> PaginatedLiveOddsResponse:
    filtered_items, available_leagues = _filter_odds_snapshot_items(
        items,
        league=league,
        search=search,
    )
    slim_items = [LiveOddsItemResponse.model_validate(item) for item in filtered_items]
    paged_items, total_pages = _paginate_items(slim_items, page, per_page)
    return PaginatedLiveOddsResponse(
        items=paged_items,
        page=min(max(page, 1), total_pages),
        per_page=per_page,
        total_items=len(slim_items),
        total_pages=total_pages,
        available_leagues=available_leagues,
    )


def _serialize_upcoming_row(row: dict[str, object]) -> UpcomingOddsItemResponse:
    opps = row.get("opponents") or []
    team1 = (opps[0].get("opponent") or {}) if len(opps) > 0 else {}
    team2 = (opps[1].get("opponent") or {}) if len(opps) > 1 else {}
    league = row.get("league") or {}
    stream_url = None
    streams = row.get("streams_list") or []
    if len(streams) > 0:
        stream_url = _safe_optional_string(streams[0].get("raw_url"))
    return UpcomingOddsItemResponse(
        id=_safe_int(row.get("id")),
        scheduled_at=_safe_string(row.get("scheduled_at")),
        league_name=_display_league_name(league),
        team1_name=_safe_string(team1.get("name")) or "TBD",
        team1_acronym=_safe_optional_string(team1.get("acronym")),
        team2_name=_safe_string(team2.get("name")) or "TBD",
        team2_acronym=_safe_optional_string(team2.get("acronym")),
        stream_url=stream_url,
        bookie_odds_team1=_to_float_or_none(row.get("bookie_odds_team1")),
        bookie_odds_team2=_to_float_or_none(row.get("bookie_odds_team2")),
        bookie_odds_status_team1=_safe_optional_string(row.get("bookie_odds_status_team1")) or "missing",
        bookie_odds_status_team2=_safe_optional_string(row.get("bookie_odds_status_team2")) or "missing",
        odds_source_kind=_safe_optional_string(row.get("odds_source_kind")),
        odds_source_status=_safe_optional_string(row.get("odds_source_status")),
        model_odds_team1=_to_float_or_none(row.get("model_odds_team1")),
        model_odds_team2=_to_float_or_none(row.get("model_odds_team2")),
        series_format=_safe_string(row.get("series_format")) or "BO1",
        markets=row.get("markets") if isinstance(row.get("markets"), list) else [],
        recommended_bet=row.get("recommended_bet") if isinstance(row.get("recommended_bet"), dict) else None,
    )


def _serialize_live_row(row: dict[str, object]) -> LiveOddsItemResponse:
    base = _serialize_upcoming_row(row)
    return LiveOddsItemResponse(
        **base.model_dump(),
        series_score_team1=_safe_int(row.get("series_score_team1")),
        series_score_team2=_safe_int(row.get("series_score_team2")),
        pre_match_odds_team1=_to_float_or_none(row.get("pre_match_odds_team1")),
        pre_match_odds_team2=_to_float_or_none(row.get("pre_match_odds_team2")),
        live_recommendation=row.get("live_recommendation") if isinstance(row.get("live_recommendation"), dict) else None,
    )


def _to_float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _market_rows_for_match(match: dict[str, object], market_catalog: object) -> list[dict[str, object]]:
    team1, team2 = _get_team_names_from_match(match)
    acr1, acr2 = _get_team_acronyms_from_match(match)
    market_set = find_market_set_for_match(team1, team2, market_catalog, acronym1=acr1, acronym2=acr2)
    offers = market_set.get("offers", []) if isinstance(market_set, dict) else []
    rows: list[dict[str, object]] = []
    for offer in offers if isinstance(offers, list) else []:
        if not isinstance(offer, dict):
            continue
        rows.append(
            {
                "market_type": str(offer.get("market_type") or "match_winner"),
                "selection_key": str(offer.get("selection_key") or ""),
                "line_value": _to_float_or_none(offer.get("line_value")),
                "decimal_odds": _to_float_or_none(offer.get("decimal_odds")),
                "market_status": str(offer.get("market_status") or "available"),
                "source_market_name": _safe_optional_string(offer.get("source_market_name")),
                "source_selection_name": _safe_optional_string(offer.get("source_selection_name")),
            }
        )
    rows.sort(key=lambda row: (str(row.get("market_type") or ""), _to_float_or_none(row.get("line_value")) or 0.0, str(row.get("selection_key") or "")))
    return rows


def _build_upcoming_with_odds_from_matches(
    matches: list[dict[str, object]],
) -> list[dict[str, object]]:
    from betting.bet_manager import _evaluate_match_for_betting, get_or_create_agent_bankroll
    from entity_resolution.resolver import EntityResolver
    from ml.predictor_v2 import get_prediction_runtime_status
    from database import SessionLocal

    bookie_odds = read_market_catalog_from_file()
    out: list[dict[str, object]] = []
    session = SessionLocal()
    bankroll = get_or_create_agent_bankroll(session)
    resolver = EntityResolver(session)
    model_available = get_prediction_runtime_status(session).get("active_model_id") is not None
    for m in matches:
        row = dict(m)
        team1, team2 = _get_team_names_from_match(m)
        acr1, acr2 = _get_team_acronyms_from_match(m)
        odds_resolution = resolve_match_odds(
            team1,
            team2,
            odds_list=read_odds_from_file(),
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
        row["markets"] = _market_rows_for_match(m, bookie_odds)
        number_of_games = m.get("number_of_games") or 1
        from ml.series_probability import number_of_games_to_format
        row["series_format"] = number_of_games_to_format(number_of_games)
        candidate = _evaluate_match_for_betting(
            session,
            resolver,
            bankroll,
            m,
            bookie_odds,
            now=datetime.now(timezone.utc),
            model_available=model_available,
        )
        row["recommended_bet"] = candidate.get("recommended_bet") if isinstance(candidate.get("recommended_bet"), dict) else None
        out.append(row)
    session.close()
    _attach_v2_model_odds(out, snapshot_kind="upcoming")
    return out


def warm_upcoming_odds_cache() -> None:
    cached = read_upcoming_matches_from_file()
    if not cached:
        return
    matches = cached
    if not matches:
        return
    out = _build_upcoming_with_odds_from_matches(matches)
    slim_items = [_serialize_upcoming_row(row) for row in out]
    paged_items, total_pages = _paginate_items(slim_items, 1, 10)
    response = PaginatedUpcomingOddsResponse(
        items=paged_items,
        page=1,
        per_page=10,
        total_items=len(slim_items),
        total_pages=total_pages,
    )
    cache_key = "upcoming:1:10:"
    mtimes = _source_mtimes_upcoming()
    _set_cached_odds(cache_key, response, mtimes)
    logger.info(
        "pandascore.warm_upcoming_odds_cache: warmed key=%s count=%s with_model_odds=%s",
        cache_key,
        len(response.items),
        sum(1 for r in response.items if r.model_odds_team1 is not None),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _datetime_to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_manual_refresh_redis_client() -> Redis | None:
    global _manual_refresh_redis_client, _manual_refresh_redis_init_attempted
    if _manual_refresh_redis_init_attempted:
        return _manual_refresh_redis_client
    _manual_refresh_redis_init_attempted = True

    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url:
        return None
    try:
        client = Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        _manual_refresh_redis_client = client
    except Exception as e:
        logger.warning(
            "pandascore.manual_refresh redis unavailable: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )
        _manual_refresh_redis_client = None
    return _manual_refresh_redis_client


def _get_manual_refresh_next_available() -> datetime | None:
    global _manual_refresh_next_available_local

    now = _utc_now()
    client = _get_manual_refresh_redis_client()
    if client is not None:
        try:
            raw = client.get(MANUAL_REFRESH_NEXT_AVAILABLE_KEY)
            dt = _parse_iso_datetime(raw)
            if dt is not None and dt > now:
                return dt
            return None
        except RedisError as e:
            logger.warning(
                "pandascore.manual_refresh redis read failed: error_type=%s error=%s",
                type(e).__name__,
                str(e),
            )

    if _manual_refresh_next_available_local is not None and _manual_refresh_next_available_local > now:
        return _manual_refresh_next_available_local
    return None


def _acquire_manual_refresh_slot() -> tuple[bool, datetime]:
    global _manual_refresh_next_available_local

    now = _utc_now()
    next_available_at = now + timedelta(seconds=MANUAL_REFRESH_LOCKOUT_SECONDS)
    next_iso = _datetime_to_iso(next_available_at)
    client = _get_manual_refresh_redis_client()

    if client is not None:
        try:
            was_set = bool(
                client.set(
                    MANUAL_REFRESH_NEXT_AVAILABLE_KEY,
                    next_iso,
                    ex=MANUAL_REFRESH_LOCKOUT_SECONDS,
                    nx=True,
                )
            )
            if was_set:
                return True, next_available_at

            existing = _parse_iso_datetime(client.get(MANUAL_REFRESH_NEXT_AVAILABLE_KEY))
            if existing is not None and existing > now:
                return False, existing
            client.set(
                MANUAL_REFRESH_NEXT_AVAILABLE_KEY,
                next_iso,
                ex=MANUAL_REFRESH_LOCKOUT_SECONDS,
            )
            return True, next_available_at
        except RedisError as e:
            logger.warning(
                "pandascore.manual_refresh redis write failed: error_type=%s error=%s",
                type(e).__name__,
                str(e),
            )

    if _manual_refresh_next_available_local is not None and _manual_refresh_next_available_local > now:
        return False, _manual_refresh_next_available_local
    _manual_refresh_next_available_local = next_available_at
    return True, next_available_at


class PandascoreSavedItem(BaseModel):
    file: str
    count: int


class PandascoreDownloadResponse(BaseModel):
    message: str
    saved: list[PandascoreSavedItem]
    errors: list[dict[str, object]] | None = None


class OddsRefreshStatusResponse(BaseModel):
    allowed: bool
    next_available_at: str | None = None


class OddsRefreshResponse(BaseModel):
    status: str
    message: str
    task_ids: list[str]


class OddsRefreshProgressResponse(BaseModel):
    status: str
    progress: int
    stage: str
    done: bool
    message: str | None = None


class OddsRefreshGlobalStatusResponse(BaseModel):
    in_progress: bool
    task_id: str | None = None
    progress: int = 0
    stage: str = ""
    last_completed_at: str | None = None
    next_scheduled_at: str | None = None


def _next_quarter_utc() -> datetime:
    now = _utc_now()
    minutes = (now.minute // 15 + 1) * 15
    if minutes >= 60:
        return (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return now.replace(minute=minutes, second=0, microsecond=0)


def require_pandascore_token() -> str:
    try:
        return get_token()
    except ValueError as e:
        logger.error(
            "pandascore.require_pandascore_token failed: endpoint=dependency error_type=ValueError error=%s",
            str(e),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e


PerPage50 = Annotated[int, Query(ge=1, le=50)]
PerPage100 = Annotated[int, Query(ge=1, le=100)]
PageNumber = Annotated[int, Query(ge=1, le=500)]
TierQuery = Annotated[str | None, Query(max_length=32, pattern="^[a-zA-Z,]*$")]
LeagueQuery = Annotated[str | None, Query(max_length=200)]
SearchQuery = Annotated[str | None, Query(max_length=200)]


@router.get(
    "/odds-refresh-status",
    summary="Get manual odds refresh lockout status",
    response_model=OddsRefreshStatusResponse,
)
async def get_odds_refresh_status(
    _: None = Depends(require_admin_api_key),
    token: str = Depends(require_pandascore_token),
) -> OddsRefreshStatusResponse:
    _ = token
    next_available = _get_manual_refresh_next_available()
    if next_available is None:
        return OddsRefreshStatusResponse(allowed=True, next_available_at=None)
    return OddsRefreshStatusResponse(
        allowed=False,
        next_available_at=_datetime_to_iso(next_available),
    )


@router.get(
    "/odds-refresh-global-status",
    summary="Get global odds refresh status (scheduled and in-progress)",
    response_model=OddsRefreshGlobalStatusResponse,
)
def get_odds_refresh_global_status_payload() -> dict[str, object]:
    last_completed_at = get_last_completed_at()
    next_dt = _next_quarter_utc()
    next_scheduled_at = _datetime_to_iso(next_dt)
    current_task_id = get_current_task_id()
    if not current_task_id:
        return OddsRefreshGlobalStatusResponse(
            in_progress=False,
            last_completed_at=last_completed_at,
            next_scheduled_at=next_scheduled_at,
        ).model_dump()
    try:
        from worker import celery_app

        result = AsyncResult(current_task_id, app=celery_app)
        state = str(result.state or "PENDING").upper()
        info = result.info if isinstance(result.info, dict) else {}
        if state in ("SUCCESS", "FAILURE", "REVOKED"):
            clear_current_task_id()
            return OddsRefreshGlobalStatusResponse(
                in_progress=False,
                last_completed_at=last_completed_at,
                next_scheduled_at=next_scheduled_at,
            ).model_dump()
        stage = str(info.get("stage") or state.lower())
        progress_raw = info.get("progress", 0)
        try:
            progress = int(progress_raw)
        except Exception:
            progress = 0
        progress = max(0, min(progress, 100))
        return OddsRefreshGlobalStatusResponse(
            in_progress=True,
            task_id=current_task_id,
            progress=progress,
            stage=stage,
            last_completed_at=last_completed_at,
            next_scheduled_at=next_scheduled_at,
        ).model_dump()
    except Exception as e:
        logger.warning(
            "pandascore.odds_refresh_global_status failed: task_id=%s error_type=%s error=%s",
            current_task_id,
            type(e).__name__,
            str(e),
        )
        clear_current_task_id()
        return OddsRefreshGlobalStatusResponse(
            in_progress=False,
            last_completed_at=last_completed_at,
            next_scheduled_at=next_scheduled_at,
        ).model_dump()


@router.get(
    "/odds-refresh-global-status",
    summary="Get global odds refresh status (scheduled and in-progress)",
    response_model=OddsRefreshGlobalStatusResponse,
)
async def get_odds_refresh_global_status(
    token: str = Depends(require_pandascore_token),
) -> OddsRefreshGlobalStatusResponse:
    _ = token
    return OddsRefreshGlobalStatusResponse.model_validate(
        get_odds_refresh_global_status_payload()
    )


@router.post(
    "/refresh-odds",
    summary="Manually refresh PandaScore + Thunderpick odds",
    status_code=202,
    response_model=OddsRefreshResponse,
)
async def refresh_odds(
    _: None = Depends(require_admin_api_key),
    token: str = Depends(require_pandascore_token),
) -> OddsRefreshResponse:
    _ = token
    allowed, next_available = _acquire_manual_refresh_slot()
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Manual refresh is temporarily locked. Try again later.",
                "next_available_at": _datetime_to_iso(next_available),
            },
        )

    try:
        from tasks import task_refresh_odds_pipeline

        pipeline_job = task_refresh_odds_pipeline.delay()
        return OddsRefreshResponse(
            status="accepted",
            message="Odds refresh pipeline started",
            task_ids=[pipeline_job.id],
        )
    except Exception as e:
        logger.error(
            "pandascore.refresh_odds failed: endpoint=POST /pandascore/refresh-odds error_type=%s error=%s",
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to enqueue odds refresh tasks.",
        ) from e


@router.get(
    "/refresh-odds-progress",
    summary="Get manual odds refresh pipeline progress",
    response_model=OddsRefreshProgressResponse,
)
async def refresh_odds_progress(
    task_id: Annotated[str, Query(min_length=1, max_length=128)],
    _: None = Depends(require_admin_api_key),
    token: str = Depends(require_pandascore_token),
) -> OddsRefreshProgressResponse:
    _ = token
    task_id_clean = task_id.strip()
    if not task_id_clean:
        raise HTTPException(status_code=400, detail="task_id is required")

    try:
        from worker import celery_app

        result = AsyncResult(task_id_clean, app=celery_app)
        state = str(result.state or "PENDING").upper()
        info = result.info if isinstance(result.info, dict) else {}

        stage = str(info.get("stage") or state.lower())
        progress_raw = info.get("progress", 0)
        try:
            progress = int(progress_raw)
        except Exception:
            progress = 0
        progress = max(0, min(progress, 100))

        if state == "SUCCESS":
            return OddsRefreshProgressResponse(
                status="success",
                progress=100,
                stage=str(info.get("stage") or "completed"),
                done=True,
                message=str(info.get("message") or "Refresh pipeline completed"),
            )

        if state in {"FAILURE", "REVOKED"}:
            return OddsRefreshProgressResponse(
                status="error",
                progress=100,
                stage="failed",
                done=True,
                message=str(info) if info else "Refresh pipeline failed",
            )

        if state in {"PROGRESS", "STARTED"}:
            return OddsRefreshProgressResponse(
                status="running",
                progress=progress,
                stage=stage,
                done=False,
                message=str(info.get("message") or ""),
            )

        return OddsRefreshProgressResponse(
            status="pending",
            progress=0,
            stage="queued",
            done=False,
            message="Refresh pipeline queued",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "pandascore.refresh_odds_progress failed: endpoint=GET /pandascore/refresh-odds-progress task_id=%s error_type=%s error=%s",
            task_id_clean,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to read refresh progress.") from e


@router.post(
    "/download",
    summary="Download upcoming LoL fixtures to JSON",
    response_model=PandascoreDownloadResponse,
)
async def trigger_pandascore_download(
    tier: TierQuery = None,
    _: None = Depends(require_admin_api_key),
    token: str = Depends(require_pandascore_token),
) -> PandascoreDownloadResponse:
    tiers = [t.strip() for t in tier.split(",")] if tier else None
    try:
        summary = await download_upcoming_lol_fixtures_async(token=token, tiers=tiers)
    except httpx.ConnectError as e:
        logger.error(
            "pandascore.trigger_pandascore_download failed: endpoint=POST /pandascore/download tier=%s error_type=ConnectError error=%s",
            tier,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Cannot reach PandaScore API (DNS or network error). "
                "Run manually: docker exec draft-gap-api python /app/scripts/download_pandascore.py — "
                f"Original: {e!s}"
            ),
        ) from e
    except ValueError as e:
        logger.error(
            "pandascore.trigger_pandascore_download failed: endpoint=POST /pandascore/download tier=%s error_type=ValueError error=%s",
            tier,
            str(e),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(
            "pandascore.trigger_pandascore_download failed: endpoint=POST /pandascore/download tier=%s error_type=%s error=%s",
            tier,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"PandaScore download failed: {e!s}") from e

    if summary.get("errors"):
        return PandascoreDownloadResponse(
            message="Download completed with some errors",
            saved=summary["saved"],
            errors=summary["errors"],
        )
    return PandascoreDownloadResponse(
        message="Download completed",
        saved=summary["saved"],
    )


def _league_obj_is_approved(league: dict[str, object]) -> bool:
    league_slug_raw = league.get("slug")
    league_slug = str(league_slug_raw) if isinstance(league_slug_raw, str) else None
    league_id_raw = league.get("id")
    league_id = league_id_raw if isinstance(league_id_raw, int) else None
    return league_slug_or_id_approved(league_slug, league_id)


@router.get(
    "/leagues",
    summary="List LoL leagues from PandaScore (paginated and aggregated)",
    response_model=list[dict[str, object]],
)
async def get_lol_leagues(
    _: None = Depends(require_admin_api_key),
    approved_only: bool = False,
    token: str = Depends(require_pandascore_token),
) -> list[dict[str, object]]:
    leagues = await fetch_all_lol_leagues_async(per_page=100, token=token)
    if approved_only:
        leagues = [league for league in leagues if _league_obj_is_approved(league)]
    return leagues


@router.get(
    "/series",
    summary="List PandaScore series (paginated and aggregated)",
    response_model=list[dict[str, object]],
)
async def get_series(
    _: None = Depends(require_admin_api_key),
    token: str = Depends(require_pandascore_token),
) -> list[dict[str, object]]:
    return await fetch_all_series_async(per_page=100, token=token)


@router.get(
    "/tournaments",
    summary="List PandaScore tournaments (paginated and aggregated)",
    response_model=list[dict[str, object]],
)
async def get_tournaments(
    _: None = Depends(require_admin_api_key),
    upcoming_only: bool = True,
    tier: TierQuery = None,
    token: str = Depends(require_pandascore_token),
) -> list[dict[str, object]]:
    tiers = [t.strip().lower() for t in tier.split(",")] if tier else None
    return await fetch_all_tournaments_async(
        upcoming=upcoming_only,
        per_page=100,
        tiers=tiers,
        token=token,
    )


@router.get(
    "/lol/upcoming",
    summary="Get upcoming LoL matches (cached file or live)",
    response_model=list[dict[str, object]],
)
async def get_upcoming_lol_matches(
    per_page: PerPage100 = 50,
    tier: TierQuery = None,
    token: str = Depends(require_pandascore_token),
) -> list[dict[str, object]]:
    requested_tiers = [t.strip().lower() for t in tier.split(",")] if tier else None
    cached = read_upcoming_matches_from_file()
    if cached is not None:
        if requested_tiers:
            filtered = [
                m
                for m in cached
                if (m.get("tournament") or {}).get("tier") in requested_tiers
            ]
            if "a" in requested_tiers:
                filtered = [m for m in filtered if match_allowed_tier(m)]
        else:
            filtered = cached
        return filtered[: min(len(filtered), per_page)]
    tiers = requested_tiers
    try:
        result = await fetch_upcoming_lol_matches_async(
            per_page=min(per_page, 100),
            tiers=tiers,
            token=token,
        )
        if tiers and "a" in tiers:
            result = [m for m in result if match_allowed_tier(m)]
        return result[: min(len(result), per_page)]
    except httpx.ConnectError as e:
        logger.error(
            "pandascore.get_upcoming_lol_matches failed: endpoint=GET /pandascore/lol/upcoming per_page=%s tier=%s error_type=ConnectError error=%s",
            per_page,
            tier,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach PandaScore API (DNS or network error). Original: {e!s}",
        ) from e
    except Exception as e:
        logger.error(
            "pandascore.get_upcoming_lol_matches failed: endpoint=GET /pandascore/lol/upcoming per_page=%s tier=%s error_type=%s error=%s",
            per_page,
            tier,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=str(e)) from e


def _get_team_names_from_match(match: dict[str, object]) -> tuple[str, str]:
    opps = match.get("opponents") or []
    name1 = (
        (opps[0].get("opponent") or {}).get("name") or "TBD"
        if len(opps) > 0
        else "TBD"
    )
    name2 = (
        (opps[1].get("opponent") or {}).get("name") or "TBD"
        if len(opps) > 1
        else "TBD"
    )
    return (name1, name2)


def _get_team_acronyms_from_match(match: dict[str, object]) -> tuple[str | None, str | None]:
    opps = match.get("opponents") or []
    acr1 = (opps[0].get("opponent") or {}).get("acronym") if len(opps) > 0 else None
    acr2 = (opps[1].get("opponent") or {}).get("acronym") if len(opps) > 1 else None
    return (acr1 or None, acr2 or None)


@router.get(
    "/lol/upcoming-with-odds",
    summary="Upcoming LoL matches with model odds and bookie (betting) odds",
    response_model=PaginatedUpcomingOddsResponse,
)
async def get_upcoming_lol_matches_with_odds(
    response: Response,
    per_page: PerPage50 = 10,
    page: PageNumber = 1,
    tier: TierQuery = None,
    league: LeagueQuery = None,
    search: SearchQuery = None,
    session: Session = Depends(get_db),
) -> PaginatedUpcomingOddsResponse:
    safe_per_page = min(max(per_page, 1), 50)
    snapshot = get_active_snapshot(session, UpcomingWithOddsSnapshot)
    apply_snapshot_headers(response, snapshot, key="upcoming")
    items = list((snapshot.payload_json if snapshot else {}).get("items", []))
    if len(items) == 0:
        from services.homepage_snapshots import build_upcoming_snapshot_payload

        items = list(build_upcoming_snapshot_payload().get("items", []))
    return paginate_upcoming_snapshot_items(
        items,
        page=page,
        per_page=safe_per_page,
        tier=tier,
        league=league,
        search=search,
    )


@router.get(
    "/lol/live-with-odds",
    summary="Live LoL matches with series score, conditional model odds, and bookie odds",
    response_model=PaginatedLiveOddsResponse,
)
async def get_live_lol_matches_with_odds(
    response: Response,
    per_page: PerPage50 = 20,
    page: PageNumber = 1,
    league: LeagueQuery = None,
    search: SearchQuery = None,
    session: Session = Depends(get_db),
) -> PaginatedLiveOddsResponse:
    safe_per_page = min(max(per_page, 1), 50)
    snapshot = get_active_snapshot(session, LiveWithOddsSnapshot)
    apply_snapshot_headers(response, snapshot, key="live")
    items = list((snapshot.payload_json if snapshot else {}).get("items", []))
    if len(items) == 0:
        from services.homepage_snapshots import build_live_snapshot_payload
        from services.pandascore import is_degradable_upstream_error

        try:
            items = list(build_live_snapshot_payload().get("items", []))
        except Exception as exc:
            if not is_degradable_upstream_error(exc):
                raise
            logger.warning("live-with-odds fallback degraded: %s", exc)
            items = []
    return paginate_live_snapshot_items(
        items,
        page=page,
        per_page=safe_per_page,
        league=league,
        search=search,
    )


def _attach_v2_model_odds(
    rows: list[dict[str, object]],
    *,
    snapshot_kind: str,
) -> None:
    total_rows = len(rows)
    resolved_rows = 0
    attached_rows = 0
    unresolved_rows = 0
    predictor_returned_none_rows = 0
    no_loadable_model_rows = 0
    tbd_rows = 0
    bookie_rows = sum(
        1
        for row in rows
        if row.get("bookie_odds_team1") is not None or row.get("bookie_odds_team2") is not None
    )
    try:
        from entity_resolution.resolver import EntityResolver
        from ml.predictor_v2 import (
            get_prediction_runtime_status,
            predict_for_pandascore_match,
            predict_live_rebet_context,
        )

        session = SessionLocal()
        try:
            runtime_status = get_prediction_runtime_status(session)
            logger.info(
                "V2 model odds attachment start: total_rows=%s bookie_rows=%s active_model_id=%s active_model_version=%s active_model_path=%s",
                total_rows,
                bookie_rows,
                runtime_status.get("active_model_id"),
                runtime_status.get("active_model_version"),
                runtime_status.get("active_model_path"),
            )
            if runtime_status.get("active_model_id") is None:
                no_loadable_model_rows = total_rows
            resolver = EntityResolver(session)
            for row in rows:
                try:
                    team1, team2 = _get_team_names_from_match(row)
                    if team1 == "TBD" or team2 == "TBD":
                        tbd_rows += 1
                        logger.debug(
                            "V2 model odds skip: match_id=%s team1=%s team2=%s reason=tbd",
                            row.get("id"), team1, team2,
                        )
                        continue

                    opps = row.get("opponents") or []
                    ps_id1 = (opps[0].get("opponent") or {}).get("id") if len(opps) > 0 else None
                    ps_id2 = (opps[1].get("opponent") or {}).get("id") if len(opps) > 1 else None
                    acr1, acr2 = _get_team_acronyms_from_match(row)

                    team_a = resolver.resolve_team(
                        team1, "pandascore",
                        pandascore_id=ps_id1,
                        abbreviation=acr1,
                    )
                    team_b = resolver.resolve_team(
                        team2, "pandascore",
                        pandascore_id=ps_id2,
                        abbreviation=acr2,
                    )
                    if not team_a or not team_b:
                        logger.info(
                            "V2 model odds skip: match_id=%s team1=%s team2=%s ps_id1=%s ps_id2=%s acr1=%s acr2=%s reason=team_not_resolved team_a=%s team_b=%s",
                            row.get("id"), team1, team2, ps_id1, ps_id2, acr1, acr2,
                            "ok" if team_a else "missing", "ok" if team_b else "missing",
                        )
                        unresolved_rows += 1
                        continue
                    resolved_rows += 1

                    number_of_games = row.get("number_of_games") or 1
                    score_a = row.get("series_score_team1", 0)
                    score_b = row.get("series_score_team2", 0)
                    league_slug = ((row.get("league") or {}).get("slug") or "")

                    mo_a, mo_b, pre_a, pre_b, _ = predict_for_pandascore_match(
                        session, team_a.id, team_b.id,
                        number_of_games=number_of_games,
                        score_a=score_a, score_b=score_b,
                        league_slug=league_slug,
                    )
                    if mo_a is not None:
                        row["model_odds_team1"] = mo_a
                        row["model_odds_team2"] = mo_b
                        row["pre_match_odds_team1"] = pre_a
                        row["pre_match_odds_team2"] = pre_b
                        if snapshot_kind == "live":
                            recommendation = predict_live_rebet_context(
                                session,
                                team_a.id,
                                team_b.id,
                                number_of_games=int(number_of_games),
                                score_a=int(score_a or 0),
                                score_b=int(score_b or 0),
                                league_slug=league_slug,
                                bookie_odds_a=_to_float_or_none(row.get("bookie_odds_team1")),
                                bookie_odds_b=_to_float_or_none(row.get("bookie_odds_team2")),
                            )
                            if recommendation is not None:
                                row["live_recommendation"] = recommendation
                        attached_rows += 1
                    else:
                        predictor_returned_none_rows += 1
                        logger.info(
                            "V2 model odds skip: match_id=%s team1=%s team2=%s reason=predictor_returned_none",
                            row.get("id"), team1, team2,
                        )
                except Exception:
                    session.rollback()
                    try:
                        t1, t2 = _get_team_names_from_match(row)
                    except Exception:
                        t1, t2 = "?", "?"
                    logger.exception(
                        "V2 model odds row attach failed: match_id=%s team1=%s team2=%s",
                        row.get("id"), t1, t2,
                    )
                    continue

            runtime_status = get_prediction_runtime_status(session)
            model_rows = runtime_status.get("game_data_row_count")
            logger.info(
                "V2 model odds attachment summary: total_rows=%s resolved_rows=%s attached_rows=%s bookie_rows=%s game_rows=%s",
                total_rows,
                resolved_rows,
                attached_rows,
                bookie_rows,
                model_rows,
            )
            record_odds_attachment_status(
                snapshot_kind,
                {
                    "total_rows": total_rows,
                    "resolved_rows": resolved_rows,
                    "rows_with_bookie_odds": bookie_rows,
                    "rows_with_model_odds": attached_rows,
                    "rows_skipped_unresolved_teams": unresolved_rows,
                    "rows_skipped_predictor_returned_none": predictor_returned_none_rows,
                    "rows_skipped_no_loadable_model": no_loadable_model_rows,
                    "rows_skipped_tbd": tbd_rows,
                    "active_model_id": runtime_status.get("active_model_id"),
                    "active_model_version": runtime_status.get("active_model_version"),
                    "active_model_path": runtime_status.get("active_model_path"),
                    "game_data_row_count": model_rows,
                },
            )
        finally:
            session.close()
    except Exception:
        logger.exception(
            "V2 model odds attachment failed, falling back: total_rows=%s resolved_rows=%s attached_rows=%s",
            total_rows,
            resolved_rows,
            attached_rows,
        )
        record_odds_attachment_status(
            snapshot_kind,
            {
                "total_rows": total_rows,
                "resolved_rows": resolved_rows,
                "rows_with_bookie_odds": bookie_rows,
                "rows_with_model_odds": attached_rows,
                "rows_skipped_unresolved_teams": unresolved_rows,
                "rows_skipped_predictor_returned_none": predictor_returned_none_rows,
                "rows_skipped_no_loadable_model": no_loadable_model_rows,
                "rows_skipped_tbd": tbd_rows,
                "error": "attachment_failed",
            },
        )


@router.get(
    "/leagues/{league_id_or_slug}/upcoming",
    summary="Upcoming matches for a league",
    response_model=list[dict[str, object]],
)
async def get_league_upcoming(
    league_id_or_slug: str,
    per_page: PerPage100 = 50,
    _: None = Depends(require_admin_api_key),
    token: str = Depends(require_pandascore_token),
) -> list[dict[str, object]]:
    lid: int | str = int(league_id_or_slug) if league_id_or_slug.isdigit() else league_id_or_slug
    try:
        return await fetch_league_upcoming_matches_async(
            lid,
            per_page=min(per_page, 100),
            token=token,
        )
    except ValueError as e:
        logger.error(
            "pandascore.get_league_upcoming failed: endpoint=GET /pandascore/leagues/{id}/upcoming league_id_or_slug=%s error_type=ValueError error=%s",
            league_id_or_slug,
            str(e),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.ConnectError as e:
        logger.error(
            "pandascore.get_league_upcoming failed: endpoint=GET /pandascore/leagues/{id}/upcoming league_id_or_slug=%s error_type=ConnectError error=%s",
            league_id_or_slug,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach PandaScore API (DNS or network error). Original: {e!s}",
        ) from e
    except Exception as e:
        logger.error(
            "pandascore.get_league_upcoming failed: endpoint=GET /pandascore/leagues/{id}/upcoming league_id_or_slug=%s error_type=%s error=%s",
            league_id_or_slug,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=str(e)) from e

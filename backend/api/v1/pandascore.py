from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path

import httpx
from redis import Redis  # type: ignore[import-untyped]
from redis.exceptions import RedisError  # type: ignore[import-untyped]
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from celery.result import AsyncResult  # type: ignore[import-untyped]

from database import SessionLocal
from services.odds_refresh_status import (
    clear_current_task_id,
    get_current_task_id,
    get_last_completed_at,
)
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
    find_odds_for_match,
    get_odds_cache_path,
    read_odds_from_file,
)

router = APIRouter(prefix="/pandascore", tags=["pandascore"])
logger = logging.getLogger(__name__)

_odds_response_cache: dict[str, tuple[list[dict[str, object]], dict[str, float]]] = {}
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
    }


def _source_mtimes_live() -> dict[str, float]:
    return {"thunderpick": _mtime_safe(get_odds_cache_path())}


def _get_cached_odds(key: str, current_mtimes: dict[str, float]) -> list[dict[str, object]] | None:
    entry = _odds_response_cache.get(key)
    if entry is None:
        return None
    data, stored_mtimes = entry
    if stored_mtimes != current_mtimes:
        del _odds_response_cache[key]
        return None
    return copy.deepcopy(data)


def _set_cached_odds(key: str, data: list[dict[str, object]], mtimes: dict[str, float]) -> None:
    _odds_response_cache[key] = (data, dict(mtimes))


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


@router.get(
    "/odds-refresh-status",
    summary="Get manual odds refresh lockout status",
    response_model=OddsRefreshStatusResponse,
)
async def get_odds_refresh_status(
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
async def get_odds_refresh_global_status(
    token: str = Depends(require_pandascore_token),
) -> OddsRefreshGlobalStatusResponse:
    _ = token
    last_completed_at = get_last_completed_at()
    next_dt = _next_quarter_utc()
    next_scheduled_at = _datetime_to_iso(next_dt)
    current_task_id = get_current_task_id()
    if not current_task_id:
        return OddsRefreshGlobalStatusResponse(
            in_progress=False,
            last_completed_at=last_completed_at,
            next_scheduled_at=next_scheduled_at,
        )
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
            )
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
        )
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
        )


@router.post(
    "/refresh-odds",
    summary="Manually refresh PandaScore + Thunderpick odds",
    status_code=202,
    response_model=OddsRefreshResponse,
)
async def refresh_odds(
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
    task_id: str,
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
    tier: str | None = None,
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
    token: str = Depends(require_pandascore_token),
) -> list[dict[str, object]]:
    return await fetch_all_series_async(per_page=100, token=token)


@router.get(
    "/tournaments",
    summary="List PandaScore tournaments (paginated and aggregated)",
    response_model=list[dict[str, object]],
)
async def get_tournaments(
    upcoming_only: bool = True,
    tier: str | None = None,
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
    per_page: int = 50,
    tier: str | None = None,
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
    response_model=list[dict[str, object]],
)
async def get_upcoming_lol_matches_with_odds(
    per_page: int = 50,
    tier: str | None = None,
    token: str = Depends(require_pandascore_token),
) -> list[dict[str, object]]:
    cache_key = f"upcoming:{per_page}:{tier or ''}"
    mtimes = _source_mtimes_upcoming()
    cached = _get_cached_odds(cache_key, mtimes)
    if cached is not None:
        logger.info("pandascore.upcoming-with-odds: cache hit key=%s count=%s", cache_key, len(cached))
        return cached

    requested_tiers = [t.strip().lower() for t in tier.split(",")] if tier else None
    cached = read_upcoming_matches_from_file()
    if cached is not None:
        logger.info(
            "pandascore.upcoming-with-odds: using cache cached_count=%s per_page=%s tier=%s",
            len(cached),
            per_page,
            tier,
        )
        if requested_tiers:
            filtered = [
                m
                for m in cached
                if (m.get("tournament") or {}).get("tier") in requested_tiers
            ]
            if "a" in requested_tiers:
                filtered = [m for m in filtered if match_allowed_tier(m)]
            if not filtered:
                logger.info("pandascore.upcoming-with-odds: tier filter removed all, using full cache")
                filtered = cached
        else:
            filtered = cached
        matches = filtered[: min(len(filtered), per_page)]
        logger.info(
            "pandascore.upcoming-with-odds: returning matches_count=%s (filtered=%s)",
            len(matches),
            len(filtered),
        )
    else:
        logger.info(
            "pandascore.upcoming-with-odds: cache miss, fetching from PandaScore API per_page=%s tier=%s",
            per_page,
            tier,
        )
        try:
            result = await fetch_upcoming_lol_matches_async(
                per_page=min(per_page, 100),
                tiers=None,
                token=token,
            )
            if requested_tiers:
                result = [
                    m
                    for m in result
                    if (m.get("tournament") or {}).get("tier") in requested_tiers
                ]
                if "a" in requested_tiers:
                    result = [m for m in result if match_allowed_tier(m)]
            matches = result[: min(len(result), per_page)]
            logger.info(
                "pandascore.upcoming-with-odds: live fetch (tier=%s) result_count=%s matches_count=%s",
                requested_tiers,
                len(result),
                len(matches),
            )
            if not matches and requested_tiers:
                logger.info("pandascore.upcoming-with-odds: retrying without tier filter")
                result = await fetch_upcoming_lol_matches_async(
                    per_page=min(per_page, 100),
                    tiers=None,
                    token=token,
                )
                matches = result[: min(len(result), per_page)]
                logger.info(
                    "pandascore.upcoming-with-odds: retry without tier result_count=%s matches_count=%s",
                    len(result),
                    len(matches),
                )
        except Exception as e:
            logger.error(
                "pandascore.get_upcoming_lol_matches_with_odds failed (cache miss, live fetch): endpoint=GET /pandascore/lol/upcoming-with-odds per_page=%s tier=%s error_type=%s error=%s",
                per_page,
                tier,
                type(e).__name__,
                str(e),
                exc_info=True,
            )
            matches = []

    logger.info(
        "pandascore.upcoming-with-odds: returning total matches=%s",
        len(matches),
    )
    bookie_odds = read_odds_from_file()
    out: list[dict[str, object]] = []
    for m in matches:
        row = dict(m)
        team1, team2 = _get_team_names_from_match(m)
        acr1, acr2 = _get_team_acronyms_from_match(m)
        odds1, odds2 = find_odds_for_match(
            team1, team2, bookie_odds, acronym1=acr1, acronym2=acr2
        )
        row["bookie_odds_team1"] = odds1
        row["bookie_odds_team2"] = odds2
        row["model_odds_team1"] = None
        row["model_odds_team2"] = None

        number_of_games = m.get("number_of_games") or 1
        from ml.series_probability import number_of_games_to_format
        row["series_format"] = number_of_games_to_format(number_of_games)

        out.append(row)

    _attach_v2_model_odds(out)

    _set_cached_odds(cache_key, out, _source_mtimes_upcoming())
    return out


@router.get(
    "/lol/live-with-odds",
    summary="Live LoL matches with series score, conditional model odds, and bookie odds",
    response_model=list[dict[str, object]],
)
async def get_live_lol_matches_with_odds(
    per_page: int = 20,
    token: str = Depends(require_pandascore_token),
) -> list[dict[str, object]]:
    cache_key = f"live:{per_page}"
    mtimes = _source_mtimes_live()
    cached = _get_cached_odds(cache_key, mtimes)
    if cached is not None:
        logger.info("pandascore.live-with-odds: cache hit key=%s count=%s", cache_key, len(cached))
        return cached

    try:
        raw_matches = await fetch_running_lol_matches_async(per_page=min(per_page, 50), token=token)
        matches = [m for m in raw_matches if match_allowed_tier(m)]
    except Exception as e:
        logger.error(
            "pandascore.get_live_lol_matches_with_odds failed: endpoint=GET /pandascore/lol/live-with-odds per_page=%s error_type=%s error=%s",
            per_page,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        matches = []
    bookie_odds = read_odds_from_file()
    out: list[dict[str, object]] = []
    for m in matches:
        row = dict(m)
        team1, team2 = _get_team_names_from_match(m)
        acr1, acr2 = _get_team_acronyms_from_match(m)
        odds1, odds2 = find_odds_for_match(
            team1, team2, bookie_odds, acronym1=acr1, acronym2=acr2
        )
        row["bookie_odds_team1"] = odds1
        row["bookie_odds_team2"] = odds2
        row["model_odds_team1"] = None
        row["model_odds_team2"] = None
        row["pre_match_odds_team1"] = None
        row["pre_match_odds_team2"] = None

        results = m.get("results") or []
        opps = m.get("opponents") or []
        score1, score2 = 0, 0
        if len(results) >= 2 and len(opps) >= 2:
            opp1_id = (opps[0].get("opponent") or {}).get("id")
            for r in results:
                if r.get("team_id") == opp1_id:
                    score1 = r.get("score", 0)
                else:
                    score2 = r.get("score", 0)

        number_of_games = m.get("number_of_games") or 1
        from ml.series_probability import number_of_games_to_format
        series_fmt = number_of_games_to_format(number_of_games)
        row["series_score_team1"] = score1
        row["series_score_team2"] = score2
        row["series_format"] = series_fmt

        out.append(row)

    _attach_v2_model_odds(out)

    _set_cached_odds(cache_key, out, _source_mtimes_live())
    return out


def _attach_v2_model_odds(rows: list[dict[str, object]]) -> None:
    total_rows = len(rows)
    resolved_rows = 0
    attached_rows = 0
    try:
        from entity_resolution.resolver import EntityResolver
        from ml.feature_engineer import load_game_data
        from ml.predictor_v2 import predict_for_pandascore_match

        session = SessionLocal()
        try:
            resolver = EntityResolver(session)
            for row in rows:
                try:
                    team1, team2 = _get_team_names_from_match(row)
                    if team1 == "TBD" or team2 == "TBD":
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
                        continue
                    resolved_rows += 1

                    number_of_games = row.get("number_of_games") or 1
                    score_a = row.get("series_score_team1", 0)
                    score_b = row.get("series_score_team2", 0)
                    league_slug = ((row.get("league") or {}).get("slug") or "")

                    mo_a, mo_b, pre_a, pre_b = predict_for_pandascore_match(
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
                        attached_rows += 1
                    else:
                        logger.info(
                            "V2 model odds skip: match_id=%s team1=%s team2=%s reason=predictor_returned_none",
                            row.get("id"), team1, team2,
                        )
                except Exception:
                    try:
                        t1, t2 = _get_team_names_from_match(row)
                    except Exception:
                        t1, t2 = "?", "?"
                    logger.exception(
                        "V2 model odds row attach failed: match_id=%s team1=%s team2=%s",
                        row.get("id"), t1, t2,
                    )
                    continue

            session.commit()
            model_rows = len(load_game_data(session))
            logger.info(
                "V2 model odds attachment summary: total_rows=%s resolved_rows=%s attached_rows=%s game_rows=%s",
                total_rows,
                resolved_rows,
                attached_rows,
                model_rows,
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


@router.get(
    "/leagues/{league_id_or_slug}/upcoming",
    summary="Upcoming matches for a league",
    response_model=list[dict[str, object]],
)
async def get_league_upcoming(
    league_id_or_slug: str,
    per_page: int = 50,
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



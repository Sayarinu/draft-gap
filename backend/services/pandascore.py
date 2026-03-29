from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TypedDict

import httpx
from config.pandascore_leagues import (
    APPROVED_PANDASCORE_LEAGUE_IDS,
    APPROVED_PANDASCORE_LEAGUE_SLUGS,
    LEGACY_ACCEPTED_NAME_SUBSTRINGS,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.pandascore.co"
DEFAULT_TIMEOUT = 30.0


class PandaScoreUpstreamError(RuntimeError):
    def __init__(
        self,
        *,
        message: str,
        path: str,
        status_code: int | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.status_code = status_code
        self.retryable = retryable


def _is_degradable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def is_degradable_upstream_error(exc: BaseException) -> bool:
    return isinstance(exc, PandaScoreUpstreamError) and exc.retryable


def _wrap_httpx_error(path: str, exc: Exception) -> Exception:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if _is_degradable_status(status_code):
            return PandaScoreUpstreamError(
                message=(
                    f"PandaScore upstream returned {status_code} for {path}"
                ),
                path=path,
                status_code=status_code,
                retryable=True,
            )
        return exc

    if isinstance(exc, httpx.TimeoutException):
        return PandaScoreUpstreamError(
            message=f"PandaScore upstream timed out for {path}",
            path=path,
            retryable=True,
        )

    if isinstance(exc, httpx.RequestError):
        return PandaScoreUpstreamError(
            message=f"PandaScore upstream request failed for {path}: {exc}",
            path=path,
            retryable=True,
        )

    return exc

def _normalize_slug(value: str | None) -> str:
    return (value or "").strip().lower()


def _league_or_tournament_accepted(league_name: str, tournament_name: str) -> bool:
    league_lower = (league_name or "").lower()
    tournament_lower = (tournament_name or "").lower()
    return any(
        accepted in league_lower or accepted in tournament_lower
        for accepted in LEGACY_ACCEPTED_NAME_SUBSTRINGS
    )


def league_slug_or_id_approved(league_slug: str | None, league_id: int | None) -> bool:
    if league_id is not None and league_id in APPROVED_PANDASCORE_LEAGUE_IDS:
        return True
    normalized_slug = _normalize_slug(league_slug)
    return bool(normalized_slug and normalized_slug in APPROVED_PANDASCORE_LEAGUE_SLUGS)


def match_has_approved_league(match: dict[str, object]) -> bool:
    league = match.get("league") or {}
    league_slug = league.get("slug")
    league_id_raw = league.get("id")
    league_id = league_id_raw if isinstance(league_id_raw, int) else None
    if league_slug_or_id_approved(
        str(league_slug) if isinstance(league_slug, str) else None,
        league_id,
    ):
        return True
    league_name = str(league.get("name") or "")
    tournament_name = str((match.get("tournament") or {}).get("name") or "")
    return _league_or_tournament_accepted(league_name, tournament_name)


def match_allowed_tier(match: dict[str, object]) -> bool:
    return classify_match_betting_eligibility(match)["is_bettable"]


def classify_match_betting_eligibility(match: dict[str, object]) -> dict[str, object]:
    league = match.get("league") or {}
    tournament = match.get("tournament") or {}
    league_name = str(league.get("name") or "").strip()
    league_slug = str(league.get("slug") or "").strip()
    tournament_name = str(tournament.get("name") or "").strip()
    tournament_tier = str(tournament.get("tier") or "").strip().lower()
    normalized_identity = league_slug or league_name or tournament_name or None
    if tournament_tier not in ("s", "a"):
        return {
            "is_bettable": False,
            "eligibility_reason": "tier_not_bettable",
            "normalized_identity": normalized_identity,
            "tournament_tier": tournament_tier or None,
        }
    if not match_has_approved_league(match):
        return {
            "is_bettable": False,
            "eligibility_reason": "league_not_bettable",
            "normalized_identity": normalized_identity,
            "tournament_tier": tournament_tier or None,
        }
    return {
        "is_bettable": True,
        "eligibility_reason": None,
        "normalized_identity": normalized_identity,
        "tournament_tier": tournament_tier or None,
    }


def league_name_allowed(league_name: str | None) -> bool:
    if not (league_name or "").strip():
        return True
    lowered = (league_name or "").strip().lower()
    if lowered in APPROVED_PANDASCORE_LEAGUE_SLUGS:
        return True
    return any(accepted in lowered for accepted in LEGACY_ACCEPTED_NAME_SUBSTRINGS)


def league_name_or_slug_allowed(league_name_or_slug: str | None) -> bool:
    return league_name_allowed(league_name_or_slug)


class _SavedItem(TypedDict):
    file: str
    count: int


class DownloadSummary(TypedDict):
    saved: list[_SavedItem]
    errors: list[dict[str, object]]


def get_token() -> str:
    token = os.getenv("PANDA_SCORE_KEY", "").strip()
    if not token:
        raise ValueError("PANDA_SCORE_KEY is not set")
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _build_url(path: str) -> str:
    path = path.lstrip("/")
    return f"{BASE_URL}/{path}" if path else BASE_URL


def fetch_json_sync(
    path: str,
    params: dict[str, object] | None = None,
    token: str | None = None,
) -> list[dict[str, object]] | dict[str, object]:
    t = token or get_token()
    url = _build_url(path)
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = client.get(url, headers=_auth_headers(t), params=params or {})
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise _wrap_httpx_error(path, exc) from exc


SETTLEMENT_MATCH_ID_CHUNK_SIZE = 40


def fetch_lol_matches_by_ids_sync(
    match_ids: list[int],
    *,
    chunk_size: int = SETTLEMENT_MATCH_ID_CHUNK_SIZE,
    token: str | None = None,
) -> dict[int, dict[str, object]]:
    out: dict[int, dict[str, object]] = {}
    ordered = sorted({int(mid) for mid in match_ids if int(mid) > 0})
    if not ordered:
        return out
    t = token or get_token()

    def merge_single(mid: int) -> None:
        try:
            data = fetch_json_sync(f"/lol/matches/{mid}", token=t)
        except Exception:
            return
        if isinstance(data, dict):
            key = int(data.get("id") or 0)
            if key > 0:
                out[key] = data

    for i in range(0, len(ordered), chunk_size):
        chunk = ordered[i : i + chunk_size]
        id_param = ",".join(str(x) for x in chunk)
        per_page = min(100, max(len(chunk), chunk_size))
        try:
            batch = fetch_json_sync(
                "/lol/matches",
                params={"filter[id]": id_param, "per_page": per_page},
                token=t,
            )
        except Exception:
            for mid in chunk:
                if mid not in out:
                    merge_single(mid)
            continue
        rows = batch if isinstance(batch, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            mid = int(row.get("id") or 0)
            if mid > 0:
                out[mid] = row
        for mid in chunk:
            if mid not in out:
                merge_single(mid)

    return out


async def fetch_json(
    path: str,
    params: dict[str, object] | None = None,
    token: str | None = None,
) -> list[dict[str, object]] | dict[str, object]:
    t = token or get_token()
    url = _build_url(path)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers=_auth_headers(t), params=params or {})
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise _wrap_httpx_error(path, exc) from exc


def _rate_limit_remaining(resp: httpx.Response) -> int | None:
    val = resp.headers.get("X-Rate-Limit-Remaining")
    return int(val) if val is not None and val.isdigit() else None


async def fetch_json_with_meta(
    path: str,
    params: dict[str, object] | None = None,
    token: str | None = None,
) -> tuple[list[dict[str, object]] | dict[str, object], int | None]:
    t = token or get_token()
    url = _build_url(path)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(url, headers=_auth_headers(t), params=params or {})
            resp.raise_for_status()
            remaining = _rate_limit_remaining(resp)
            return resp.json(), remaining
        except Exception as exc:
            raise _wrap_httpx_error(path, exc) from exc


TIER_VALUES = ("s", "a", "b", "c", "d")
TIER_1: tuple[str, ...] = ("s", "a")


def _tier_filter_param(tiers: list[str] | None) -> dict[str, str] | None:
    if not tiers:
        return None
    normalized = [t.strip().lower() for t in tiers if t.strip().lower() in TIER_VALUES]
    if not normalized:
        return None
    return {"filter[tier]": ",".join(normalized)}


async def fetch_upcoming_lol_matches_async(
    per_page: int = 50,
    tiers: list[str] | None = None,
    token: str | None = None,
) -> list[dict[str, object]]:
    params: dict[str, object] = {
        "filter[future]": "true",
        "per_page": per_page,
        "sort": "scheduled_at",
    }
    logger.info(
        "pandascore.upcoming: fetching from API path=/lol/matches params=%s",
        params,
    )
    try:
        data = await fetch_json("/lol/matches", params=params, token=token)
        result = data if isinstance(data, list) else []
        logger.info(
            "pandascore.upcoming: API returned %s matches (tiers=%s)",
            len(result),
            tiers,
        )
        if not result:
            logger.warning(
                "pandascore.upcoming: zero matches from PandaScore (filter[future]=true). Check tier filter or run POST /pandascore/download to populate cache."
            )
        return result
    except Exception as e:
        logger.error(
            "pandascore.upcoming: API request failed error_type=%s error=%s",
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        raise


async def fetch_running_lol_matches_async(
    per_page: int = 20,
    token: str | None = None,
) -> list[dict[str, object]]:
    params: dict[str, object] = {
        "filter[status]": "running",
        "per_page": per_page,
        "sort": "begin_at",
    }
    data = await fetch_json("/lol/matches", params=params, token=token)
    return data if isinstance(data, list) else []


def fetch_upcoming_lol_matches_sync(
    per_page: int = 50,
    tiers: list[str] | None = None,
) -> list[dict[str, object]]:
    params: dict[str, object] = {
        "filter[future]": "true",
        "per_page": per_page,
        "sort": "scheduled_at",
    }
    data = fetch_json_sync("/lol/matches", params=params)
    return data if isinstance(data, list) else []


def fetch_lol_leagues_sync(per_page: int = 50) -> list[dict[str, object]]:
    data = fetch_json_sync("/lol/leagues", params={"per_page": per_page})
    return data if isinstance(data, list) else []


def _fetch_all_pages_sync(
    path: str,
    per_page: int = 100,
    params: dict[str, object] | None = None,
    token: str | None = None,
) -> list[dict[str, object]]:
    all_rows: list[dict[str, object]] = []
    page_number = 1
    safe_per_page = min(max(per_page, 1), 100)
    while True:
        page_params: dict[str, object] = {"per_page": safe_per_page, "page[number]": page_number}
        if params:
            page_params.update(params)
        data = fetch_json_sync(path, params=page_params, token=token)
        rows = data if isinstance(data, list) else []
        all_rows.extend(rows)
        if len(rows) < safe_per_page:
            break
        page_number += 1
    return all_rows


async def _fetch_all_pages_async(
    path: str,
    per_page: int = 100,
    params: dict[str, object] | None = None,
    token: str | None = None,
) -> list[dict[str, object]]:
    all_rows: list[dict[str, object]] = []
    page_number = 1
    safe_per_page = min(max(per_page, 1), 100)
    while True:
        page_params: dict[str, object] = {"per_page": safe_per_page, "page[number]": page_number}
        if params:
            page_params.update(params)
        data = await fetch_json(path, params=page_params, token=token)
        rows = data if isinstance(data, list) else []
        all_rows.extend(rows)
        if len(rows) < safe_per_page:
            break
        page_number += 1
    return all_rows


def fetch_all_lol_leagues_sync(per_page: int = 100) -> list[dict[str, object]]:
    return _fetch_all_pages_sync("/lol/leagues", per_page=per_page)


async def fetch_all_lol_leagues_async(
    per_page: int = 100,
    token: str | None = None,
) -> list[dict[str, object]]:
    return await _fetch_all_pages_async("/lol/leagues", per_page=per_page, token=token)


async def fetch_all_series_async(
    per_page: int = 100,
    token: str | None = None,
) -> list[dict[str, object]]:
    return await _fetch_all_pages_async("/series", per_page=per_page, token=token)


async def fetch_all_tournaments_async(
    upcoming: bool = True,
    per_page: int = 100,
    tiers: list[str] | None = None,
    token: str | None = None,
) -> list[dict[str, object]]:
    path = "/tournaments/upcoming" if upcoming else "/tournaments"
    params: dict[str, object] = {}
    tf = _tier_filter_param(tiers)
    if tf:
        params["filter[tier]"] = tf["filter[tier]"]
    return await _fetch_all_pages_async(path, per_page=per_page, params=params, token=token)


def fetch_league_upcoming_matches_sync(
    league_id_or_slug: int | str,
    per_page: int = 50,
) -> list[dict[str, object]]:
    data = fetch_json_sync(
        f"/leagues/{league_id_or_slug}/matches/upcoming",
        params={"per_page": per_page},
    )
    return data if isinstance(data, list) else []


async def fetch_league_upcoming_matches_async(
    league_id_or_slug: int | str,
    per_page: int = 50,
    token: str | None = None,
) -> list[dict[str, object]]:
    data = await fetch_json(
        f"/leagues/{league_id_or_slug}/matches/upcoming",
        params={"per_page": per_page},
        token=token,
    )
    return data if isinstance(data, list) else []


def fetch_series_sync(
    league_id: int | None = None,
    per_page: int = 50,
) -> list[dict[str, object]]:
    params: dict[str, object] = {"per_page": per_page}
    if league_id is not None:
        params["filter[league_id]"] = league_id
    data = fetch_json_sync("/series", params=params)
    return data if isinstance(data, list) else []


def fetch_tournaments_sync(
    league_id: int | None = None,
    upcoming: bool = True,
    per_page: int = 50,
    tiers: list[str] | None = None,
) -> list[dict[str, object]]:
    path = "/tournaments/upcoming" if upcoming else "/tournaments"
    params: dict[str, object] = {"per_page": per_page}
    if league_id is not None:
        params["filter[league_id]"] = league_id
    tf = _tier_filter_param(tiers)
    if tf:
        params["filter[tier]"] = tf["filter[tier]"]
    data = fetch_json_sync(path, params=params)
    return data if isinstance(data, list) else []


def fetch_videogames_sync() -> list[dict[str, object]]:
    data = fetch_json_sync("/videogames")
    return data if isinstance(data, list) else []


def get_output_dir() -> Path:
    return Path(os.getenv("PANDASCORE_OUTPUT_DIR", "/cache/pandascore"))


def read_upcoming_matches_from_file(
    output_dir: str | Path | None = None,
) -> list[dict[str, object]] | None:
    out = Path(output_dir or get_output_dir())
    path = out / "lol_matches_upcoming.json"
    if not path.is_file():
        logger.info(
            "pandascore.upcoming: cache file missing path=%s (run POST /pandascore/download or refresh_pandascore_upcoming task)",
            path,
        )
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        out_list = data if isinstance(data, list) else None
        if out_list is not None:
            logger.info("pandascore.upcoming: read %s matches from cache path=%s", len(out_list), path)
        return out_list
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("pandascore.upcoming: cache read failed path=%s error=%s", path, e)
        return None


def save_json_to_file(
    data: list[dict[str, object]] | dict[str, object], file_path: str | Path
) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def download_upcoming_lol_fixtures(
    output_dir: str | Path | None = None,
    tiers: list[str] | None = None,
) -> DownloadSummary:
    output_dir = Path(
        output_dir or os.getenv("PANDASCORE_OUTPUT_DIR", "/cache/pandascore")
    )
    summary: DownloadSummary = {"saved": [], "errors": []}

    def try_save(name: str, data: list[dict[str, object]] | dict[str, object]) -> None:
        try:
            path = output_dir / f"{name}.json"
            save_json_to_file(data, path)
            count = len(data) if isinstance(data, list) else 1
            summary["saved"].append({"file": f"{name}.json", "count": count})
        except Exception as e:
            summary["errors"].append({"file": name, "error": str(e)})

    try:
        upcoming = fetch_upcoming_lol_matches_sync(per_page=100, tiers=tiers)
        try_save("lol_matches_upcoming", upcoming)

        leagues = fetch_all_lol_leagues_sync(per_page=100)
        try_save("leagues_lol", leagues)

        series = _fetch_all_pages_sync("/series", per_page=100)
        try_save("series", series)

        tournaments = _fetch_all_pages_sync(
            "/tournaments/upcoming",
            per_page=100,
            params=_tier_filter_param(tiers),
        )
        try_save("tournaments_upcoming", tournaments)

        videogames = fetch_videogames_sync()
        try_save("videogames", videogames)

        for league in leagues[:10]:
            lid = league.get("id") or league.get("slug")
            if not lid:
                continue
            try:
                matches = fetch_league_upcoming_matches_sync(lid, per_page=50)
                if matches:
                    safe_name = str(lid).replace("/", "_")
                    try_save(f"league_{safe_name}_upcoming_matches", matches)
            except Exception as e:
                summary["errors"].append({"league": lid, "error": str(e)})

    except ValueError as e:
        summary["errors"].append({"global": str(e)})
    except httpx.HTTPStatusError as e:
        summary["errors"].append(
            {"global": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        )

    return summary


async def download_upcoming_lol_fixtures_async(
    output_dir: str | Path | None = None,
    token: str | None = None,
    tiers: list[str] | None = None,
) -> DownloadSummary:
    output_dir = Path(
        output_dir or os.getenv("PANDASCORE_OUTPUT_DIR", "/cache/pandascore")
    )
    summary: DownloadSummary = {"saved": [], "errors": []}
    t = token or get_token()

    def try_save(name: str, data: list[dict[str, object]] | dict[str, object]) -> None:
        try:
            path = output_dir / f"{name}.json"
            save_json_to_file(data, path)
            count = len(data) if isinstance(data, list) else 1
            summary["saved"].append({"file": f"{name}.json", "count": count})
        except Exception as e:
            summary["errors"].append({"file": name, "error": str(e)})

    match_params: dict[str, object] = {
        "filter[future]": "true",
        "per_page": 100,
        "sort": "scheduled_at",
    }
    tf = _tier_filter_param(tiers)
    if tf:
        match_params["filter[tier]"] = tf["filter[tier]"]

    try:
        upcoming = await fetch_json("/lol/matches", params=match_params, token=t)
        try_save("lol_matches_upcoming", upcoming if isinstance(upcoming, list) else [])

        leagues = await fetch_all_lol_leagues_async(per_page=100, token=t)
        try_save("leagues_lol", leagues)

        series_data = await fetch_all_series_async(per_page=100, token=t)
        try_save("series", series_data)

        tournaments_data = await fetch_all_tournaments_async(
            upcoming=True,
            per_page=100,
            tiers=tiers,
            token=t,
        )
        try_save("tournaments_upcoming", tournaments_data)

        videogames_data = await fetch_json("/videogames", token=t)
        try_save(
            "videogames",
            videogames_data if isinstance(videogames_data, list) else [],
        )

        for league in leagues[:10]:
            lid = league.get("id") or league.get("slug")
            if not lid:
                continue
            try:
                matches = await fetch_json(
                    f"/leagues/{lid}/matches/upcoming",
                    params={"per_page": 50},
                    token=t,
                )
                matches_list = matches if isinstance(matches, list) else []
                if matches_list:
                    safe_name = str(lid).replace("/", "_")
                    try_save(f"league_{safe_name}_upcoming_matches", matches_list)
            except Exception as e:
                summary["errors"].append({"league": lid, "error": str(e)})

    except ValueError as e:
        summary["errors"].append({"global": str(e)})
    except httpx.HTTPStatusError as e:
        summary["errors"].append(
            {"global": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        )

    return summary

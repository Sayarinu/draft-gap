from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

THUNDERPICK_LOL_URL = "https://thunderpick.io/esports/league-of-legends"
ODDS_CACHE_FILENAME = "thunderpick_odds.json"
SCRAPE_STATUS_FILENAME = "thunderpick_scrape_status.json"
DEFAULT_TIMEOUT_MS = 45_000
WAIT_AFTER_LOAD_MS = 12_000

BELGIUM_LOCALE = "en-BE"
BELGIUM_TIMEZONE = "Europe/Brussels"
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

MAX_ATTEMPTS = 3
RETRY_DELAY_RANGE = (30, 45)
MAX_EXTRACTED_MATCHES = 80

logger = logging.getLogger(__name__)


class BookieMatchOdds(TypedDict):
    team1: str
    team2: str
    odds1: float
    odds2: float


class BookieMatchDiagnostic(TypedDict):
    matched: bool
    confidence: str
    team1: str
    team2: str
    normalized_team1: str
    normalized_team2: str
    acronym1: str | None
    acronym2: str | None
    matched_row_team1: str | None
    matched_row_team2: str | None


class MatchOddsResolution(TypedDict):
    odds1: float | None
    odds2: float | None
    confidence: str
    matched_row_team1: str | None
    matched_row_team2: str | None
    odds_source_kind: str
    odds_source_status: str
    market_offer_count: int
    has_match_winner_offer: bool


class ThunderpickMarketOffer(TypedDict):
    source_book: str
    market_type: str
    selection_key: str
    line_value: float | None
    decimal_odds: float
    market_status: str
    scraped_at: str | None
    source_market_name: str | None
    source_selection_name: str | None
    source_payload_json: dict[str, object] | None


class ThunderpickMatchCatalog(TypedDict):
    team1: str
    team2: str
    offers: list[ThunderpickMarketOffer]


class ThunderpickCatalogPayload(TypedDict):
    version: int
    source_book: str
    scraped_at: str | None
    matches: list[ThunderpickMatchCatalog]


TEAM_NAME_ALIASES = {
    "movistar koi": {"mko", "koi"},
    "fnatic": {"fnc"},
    "natus vincere": {"navi"},
    "team vitality": {"vit", "vitality"},
    "los grandes": {"los"},
    "oh my god": {"omg"},
    "team we": {"we"},
    "thundertalk gaming": {"thundertalk", "tt"},
}


def get_odds_cache_dir() -> Path:
    return Path(os.getenv("PANDASCORE_OUTPUT_DIR", "/cache/pandascore"))


def get_odds_cache_path(output_dir: str | Path | None = None) -> Path:
    return Path(output_dir or get_odds_cache_dir()) / ODDS_CACHE_FILENAME


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _raw_match_winner_offer(
    *,
    decimal_odds: float,
    selection_key: str,
    selection_name: str,
    scraped_at: str | None,
) -> ThunderpickMarketOffer:
    return {
        "source_book": "thunderpick",
        "market_type": "match_winner",
        "selection_key": selection_key,
        "line_value": None,
        "decimal_odds": decimal_odds,
        "market_status": "available",
        "scraped_at": scraped_at,
        "source_market_name": "Match Winner",
        "source_selection_name": selection_name,
        "source_payload_json": None,
    }


def _legacy_rows_to_catalog(rows: list[BookieMatchOdds]) -> ThunderpickCatalogPayload:
    scraped_at = _utc_iso_now()
    matches: list[ThunderpickMatchCatalog] = []
    for row in rows:
        matches.append(
            {
                "team1": row["team1"],
                "team2": row["team2"],
                "offers": [
                    _raw_match_winner_offer(
                        decimal_odds=float(row["odds1"]),
                        selection_key="team1",
                        selection_name=row["team1"],
                        scraped_at=scraped_at,
                    ),
                    _raw_match_winner_offer(
                        decimal_odds=float(row["odds2"]),
                        selection_key="team2",
                        selection_name=row["team2"],
                        scraped_at=scraped_at,
                    ),
                ],
            }
        )
    return {
        "version": 2,
        "source_book": "thunderpick",
        "scraped_at": scraped_at,
        "matches": matches,
    }


def read_market_catalog_from_file(
    output_dir: str | Path | None = None,
) -> ThunderpickCatalogPayload:
    path = get_odds_cache_path(output_dir)
    if not path.is_file():
        return {
            "version": 2,
            "source_book": "thunderpick",
            "scraped_at": None,
            "matches": [],
        }
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {
            "version": 2,
            "source_book": "thunderpick",
            "scraped_at": None,
            "matches": [],
        }

    if isinstance(data, list):
        rows = [
            {
                "team1": str(m.get("team1", "")).strip(),
                "team2": str(m.get("team2", "")).strip(),
                "odds1": float(m.get("odds1", 0)),
                "odds2": float(m.get("odds2", 0)),
            }
            for m in data
            if m.get("team1") and m.get("team2") and m.get("odds1") and m.get("odds2")
        ]
        return _legacy_rows_to_catalog(rows)

    matches_payload = data.get("matches") if isinstance(data, dict) else []
    matches: list[ThunderpickMatchCatalog] = []
    if isinstance(matches_payload, list):
        for item in matches_payload:
            if not isinstance(item, dict):
                continue
            offers_payload = item.get("offers")
            offers: list[ThunderpickMarketOffer] = []
            if isinstance(offers_payload, list):
                for offer in offers_payload:
                    if not isinstance(offer, dict):
                        continue
                    try:
                        decimal_odds = float(offer.get("decimal_odds"))
                    except Exception:
                        continue
                    offers.append(
                        {
                            "source_book": str(offer.get("source_book") or "thunderpick"),
                            "market_type": str(offer.get("market_type") or "match_winner"),
                            "selection_key": str(offer.get("selection_key") or ""),
                            "line_value": float(offer["line_value"]) if offer.get("line_value") is not None else None,
                            "decimal_odds": decimal_odds,
                            "market_status": str(offer.get("market_status") or "available"),
                            "scraped_at": str(offer.get("scraped_at")) if offer.get("scraped_at") is not None else None,
                            "source_market_name": str(offer.get("source_market_name")) if offer.get("source_market_name") is not None else None,
                            "source_selection_name": str(offer.get("source_selection_name")) if offer.get("source_selection_name") is not None else None,
                            "source_payload_json": offer.get("source_payload_json") if isinstance(offer.get("source_payload_json"), dict) else None,
                        }
                    )
            if item.get("team1") and item.get("team2") and offers:
                matches.append(
                    {
                        "team1": str(item.get("team1")).strip(),
                        "team2": str(item.get("team2")).strip(),
                        "offers": offers,
                    }
                )
    return {
        "version": int(data.get("version") or 2) if isinstance(data, dict) else 2,
        "source_book": str(data.get("source_book") or "thunderpick") if isinstance(data, dict) else "thunderpick",
        "scraped_at": str(data.get("scraped_at")) if isinstance(data, dict) and data.get("scraped_at") is not None else None,
        "matches": matches,
    }


def read_odds_from_file(
    output_dir: str | Path | None = None,
) -> list[BookieMatchOdds]:
    catalog = read_market_catalog_from_file(output_dir)
    rows: list[BookieMatchOdds] = []
    for match in catalog.get("matches", []):
        team1_offer = next(
            (
                offer
                for offer in match.get("offers", [])
                if offer.get("market_type") == "match_winner" and offer.get("selection_key") == "team1"
            ),
            None,
        )
        team2_offer = next(
            (
                offer
                for offer in match.get("offers", [])
                if offer.get("market_type") == "match_winner" and offer.get("selection_key") == "team2"
            ),
            None,
        )
        if team1_offer and team2_offer:
            rows.append(
                {
                    "team1": str(match.get("team1") or "").strip(),
                    "team2": str(match.get("team2") or "").strip(),
                    "odds1": float(team1_offer.get("decimal_odds") or 0.0),
                    "odds2": float(team2_offer.get("decimal_odds") or 0.0),
                }
            )
    return rows


def _write_odds_cache(results: ThunderpickCatalogPayload | list[BookieMatchOdds], cache_path: Path) -> None:
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            payload = results if isinstance(results, dict) else _legacy_rows_to_catalog(results)
            json.dump(payload, f, indent=2)
        match_count = len(results["matches"]) if isinstance(results, dict) else len(results)
        logger.info("Betting odds scraper: wrote %d matches to %s", match_count, cache_path)
    except OSError as e:
        logger.warning("Betting odds scraper: failed to write cache: %s", e)


def _write_debug_snippet(body_text: str, cache_dir: Path) -> None:
    try:
        snippet_path = cache_dir / "thunderpick_page_snippet.txt"
        with open(snippet_path, "w", encoding="utf-8") as f:
            f.write(body_text[:12000] if body_text else "(Page body was empty or could not be retrieved)\n")
        logger.info("Betting odds scraper: saved page snippet to %s", snippet_path)
    except OSError as e:
        logger.warning("Betting odds scraper: could not write snippet: %s", e)


def _normalize_team_name(name: str) -> str:
    s = (name or "").lower().strip()
    s = "".join(
        ch for ch in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(ch)
    )
    for suffix in (" esports", " esport", " lol", " league of legends"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    s = " ".join(s.replace(".", " ").split())
    return s


def _team_aliases(name: str, acronym: str | None) -> set[str]:
    normalized = _normalize_team_name(name)
    aliases = {normalized}
    aliases.update(TEAM_NAME_ALIASES.get(normalized, set()))
    if acronym:
        aliases.add(acronym.lower().strip())
    return {alias for alias in aliases if alias}


def _name_match_confidence(a: str, b: str, acr_a: str | None) -> int:
    aliases_a = _team_aliases(a, acr_a)
    aliases_b = _team_aliases(b, None)
    if not aliases_a or not aliases_b:
        return 0
    if aliases_a & aliases_b:
        return 3
    na = _normalize_team_name(a)
    nb = _normalize_team_name(b)
    if na and nb and (na in nb or nb in na):
        return 1
    return 0


def find_odds_for_match(
    team1: str,
    team2: str,
    odds_list: list[BookieMatchOdds],
    acronym1: str | None = None,
    acronym2: str | None = None,
) -> tuple[float | None, float | None]:
    odds1, odds2, _ = find_odds_for_match_with_diagnostics(
        team1,
        team2,
        odds_list,
        acronym1=acronym1,
        acronym2=acronym2,
    )
    return (odds1, odds2)


def resolve_match_odds(
    team1: str,
    team2: str,
    *,
    odds_list: list[BookieMatchOdds] | None = None,
    market_catalog: ThunderpickCatalogPayload | list[ThunderpickMatchCatalog] | None = None,
    acronym1: str | None = None,
    acronym2: str | None = None,
) -> MatchOddsResolution:
    moneyline_rows = odds_list if odds_list is not None else read_odds_from_file()
    odds1, odds2, diagnostic = find_odds_for_match_with_diagnostics(
        team1,
        team2,
        moneyline_rows,
        acronym1=acronym1,
        acronym2=acronym2,
    )
    if odds1 is not None or odds2 is not None:
        return {
            "odds1": odds1,
            "odds2": odds2,
            "confidence": diagnostic["confidence"],
            "matched_row_team1": diagnostic["matched_row_team1"],
            "matched_row_team2": diagnostic["matched_row_team2"],
            "odds_source_kind": "moneyline_file",
            "odds_source_status": "available",
            "market_offer_count": 2 if odds1 is not None and odds2 is not None else 1,
            "has_match_winner_offer": odds1 is not None or odds2 is not None,
        }

    catalog = market_catalog if market_catalog is not None else read_market_catalog_from_file()
    market_set = find_market_set_for_match(
        team1,
        team2,
        catalog,
        acronym1=acronym1,
        acronym2=acronym2,
    )
    offers = list(market_set.get("offers", [])) if isinstance(market_set.get("offers"), list) else []
    match_winner_offers = [offer for offer in offers if str(offer.get("market_type") or "") == "match_winner"]
    fallback_odds1 = next(
        (
            float(offer.get("decimal_odds"))
            for offer in match_winner_offers
            if str(offer.get("selection_key") or "") in {"team_a", "team1"}
        ),
        None,
    )
    fallback_odds2 = next(
        (
            float(offer.get("decimal_odds"))
            for offer in match_winner_offers
            if str(offer.get("selection_key") or "") in {"team_b", "team2"}
        ),
        None,
    )
    if fallback_odds1 is not None or fallback_odds2 is not None:
        return {
            "odds1": fallback_odds1,
            "odds2": fallback_odds2,
            "confidence": str(market_set.get("confidence") or "none"),
            "matched_row_team1": str(market_set.get("matched_row_team1") or "") or None,
            "matched_row_team2": str(market_set.get("matched_row_team2") or "") or None,
            "odds_source_kind": "market_catalog_fallback",
            "odds_source_status": "available",
            "market_offer_count": len(offers),
            "has_match_winner_offer": True,
        }
    return {
        "odds1": None,
        "odds2": None,
        "confidence": str(market_set.get("confidence") or diagnostic["confidence"] or "none"),
        "matched_row_team1": str(market_set.get("matched_row_team1") or diagnostic["matched_row_team1"] or "") or None,
        "matched_row_team2": str(market_set.get("matched_row_team2") or diagnostic["matched_row_team2"] or "") or None,
        "odds_source_kind": "missing",
        "odds_source_status": "missing",
        "market_offer_count": len(offers),
        "has_match_winner_offer": False,
    }


def find_odds_for_match_with_diagnostics(
    team1: str,
    team2: str,
    odds_list: list[BookieMatchOdds],
    acronym1: str | None = None,
    acronym2: str | None = None,
) -> tuple[float | None, float | None, BookieMatchDiagnostic]:
    n1 = _normalize_team_name(team1)
    n2 = _normalize_team_name(team2)
    if not n1 or not n2:
        return (
            None,
            None,
            {
                "matched": False,
                "confidence": "none",
                "team1": team1,
                "team2": team2,
                "normalized_team1": n1,
                "normalized_team2": n2,
                "acronym1": acronym1,
                "acronym2": acronym2,
                "matched_row_team1": None,
                "matched_row_team2": None,
            },
        )
    best: tuple[float, float] | None = None
    best_confidence = 0
    matched_row_team1: str | None = None
    matched_row_team2: str | None = None
    for row in odds_list:
        if not (_normalize_team_name(row["team1"]) and _normalize_team_name(row["team2"])):
            continue
        forward_confidence = min(
            _name_match_confidence(team1, row["team1"], acronym1),
            _name_match_confidence(team2, row["team2"], acronym2),
        )
        reverse_confidence = min(
            _name_match_confidence(team1, row["team2"], acronym1),
            _name_match_confidence(team2, row["team1"], acronym2),
        )
        if forward_confidence > best_confidence:
            best_confidence = forward_confidence
            best = (row["odds1"], row["odds2"])
            matched_row_team1 = row["team1"]
            matched_row_team2 = row["team2"]
        if reverse_confidence > best_confidence:
            best_confidence = reverse_confidence
            best = (row["odds2"], row["odds1"])
            matched_row_team1 = row["team2"]
            matched_row_team2 = row["team1"]
    diagnostic: BookieMatchDiagnostic = {
        "matched": best is not None,
        "confidence": {3: "exact", 1: "substring"}.get(best_confidence, "none"),
        "team1": team1,
        "team2": team2,
        "normalized_team1": n1,
        "normalized_team2": n2,
        "acronym1": acronym1,
        "acronym2": acronym2,
        "matched_row_team1": matched_row_team1,
        "matched_row_team2": matched_row_team2,
    }
    if best is None:
        return (None, None, diagnostic)
    return (best[0], best[1], diagnostic)


def _remap_selection_key(selection_key: str, reversed_match: bool) -> str:
    if not reversed_match:
        return selection_key.replace("team1", "team_a").replace("team2", "team_b")

    remapped = selection_key
    remapped = remapped.replace("team1", "__TMP_TEAM1__").replace("team2", "team_a")
    remapped = remapped.replace("__TMP_TEAM1__", "team_b")
    return remapped


def find_market_set_for_match(
    team1: str,
    team2: str,
    market_catalog: ThunderpickCatalogPayload | list[ThunderpickMatchCatalog],
    acronym1: str | None = None,
    acronym2: str | None = None,
) -> dict[str, object]:
    matches = market_catalog.get("matches", []) if isinstance(market_catalog, dict) else market_catalog
    _, _, diagnostic = find_odds_for_match_with_diagnostics(
        team1,
        team2,
        [
            {
                "team1": match["team1"],
                "team2": match["team2"],
                "odds1": float(next((offer["decimal_odds"] for offer in match["offers"] if offer["market_type"] == "match_winner" and offer["selection_key"] == "team1"), 0.0)),
                "odds2": float(next((offer["decimal_odds"] for offer in match["offers"] if offer["market_type"] == "match_winner" and offer["selection_key"] == "team2"), 0.0)),
            }
            for match in matches
        ],
        acronym1=acronym1,
        acronym2=acronym2,
    )
    if not diagnostic["matched"]:
        return {"matched": False, "confidence": "none", "team_a": team1, "team_b": team2, "offers": []}

    for match in matches:
        if (
            match["team1"] == diagnostic["matched_row_team1"]
            and match["team2"] == diagnostic["matched_row_team2"]
        ) or (
            match["team1"] == diagnostic["matched_row_team2"]
            and match["team2"] == diagnostic["matched_row_team1"]
        ):
            reversed_match = _normalize_team_name(match["team1"]) != _normalize_team_name(diagnostic["matched_row_team1"])
            offers: list[ThunderpickMarketOffer] = []
            for offer in match.get("offers", []):
                normalized_offer = dict(offer)
                normalized_offer["selection_key"] = _remap_selection_key(str(offer.get("selection_key") or ""), reversed_match)
                source_selection_name = str(offer.get("source_selection_name") or "")
                if reversed_match:
                    if source_selection_name == match["team1"]:
                        normalized_offer["source_selection_name"] = team2
                    elif source_selection_name == match["team2"]:
                        normalized_offer["source_selection_name"] = team1
                else:
                    if source_selection_name == match["team1"]:
                        normalized_offer["source_selection_name"] = team1
                    elif source_selection_name == match["team2"]:
                        normalized_offer["source_selection_name"] = team2
                offers.append(normalized_offer)  # type: ignore[arg-type]
            return {
                "matched": True,
                "confidence": diagnostic["confidence"],
                "team_a": team1,
                "team_b": team2,
                "matched_row_team1": diagnostic["matched_row_team1"],
                "matched_row_team2": diagnostic["matched_row_team2"],
                "offers": offers,
            }
    return {"matched": False, "confidence": "none", "team_a": team1, "team_b": team2, "offers": []}


def _extract_lol_section(text: str) -> str:
    for marker in ("League of Legends Betting Odds", "What is League of Legends", "What is LoL"):
        idx = text.find(marker)
        if idx > 500:
            return text[:idx]
    return text


_SKIP_RE = re.compile(r"\b(\d{4}|Playoffs|Cup|League|Season|Split|Masters|Challengers|Qualifier)\b", re.I)
_SKIP_NAMES_RE = re.compile(r"^(LIVE|BO\d|Featured|\d+:\d+)$")
_STRIP_PREFIX_TOKEN_RE = re.compile(r"^(China|Korea|Europe|Americas|EMEA|LCK|LPL|LEC|LCS|CBLOL|EWC)$", re.I)
_LEADING_METADATA_TOKEN_RE = re.compile(
    r"^(?:\d{4}|spring|summer|winter|fall|split|stage|playoffs|season|cup|masters|challengers|qualifier|open|week|\d+)$",
    re.I,
)
_INLINE_WS_RE = r"[^\S\r\n]+"
_TEAM_TOKEN_RE = r"[0-9A-Za-zÀ-ÖØ-öø-ÿ][0-9A-Za-zÀ-ÖØ-öø-ÿ.'&+\-]*"
_TEAM_NAME_RE = rf"{_TEAM_TOKEN_RE}(?:{_INLINE_WS_RE}{_TEAM_TOKEN_RE}){{0,5}}"
_DECIMAL_ODDS_RE = r"\d+\.\d{1,2}"
_STRUCTURED_MATCH_PATTERNS = [
    re.compile(
        rf"(?P<team1>{_TEAM_NAME_RE}){_INLINE_WS_RE}(?P<odds1>{_DECIMAL_ODDS_RE}){_INLINE_WS_RE}vs{_INLINE_WS_RE}(?P<odds2>{_DECIMAL_ODDS_RE}){_INLINE_WS_RE}(?P<team2>{_TEAM_NAME_RE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<team1>{_TEAM_NAME_RE}){_INLINE_WS_RE}(?P<odds1>{_DECIMAL_ODDS_RE}){_INLINE_WS_RE}vs{_INLINE_WS_RE}(?P<team2>{_TEAM_NAME_RE}){_INLINE_WS_RE}(?P<odds2>{_DECIMAL_ODDS_RE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<odds1>{_DECIMAL_ODDS_RE}){_INLINE_WS_RE}(?P<team1>{_TEAM_NAME_RE}){_INLINE_WS_RE}vs{_INLINE_WS_RE}(?P<odds2>{_DECIMAL_ODDS_RE}){_INLINE_WS_RE}(?P<team2>{_TEAM_NAME_RE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?P<odds1>{_DECIMAL_ODDS_RE}){_INLINE_WS_RE}(?P<team1>{_TEAM_NAME_RE}){_INLINE_WS_RE}vs{_INLINE_WS_RE}(?P<team2>{_TEAM_NAME_RE}){_INLINE_WS_RE}(?P<odds2>{_DECIMAL_ODDS_RE})",
        re.IGNORECASE,
    ),
]


def _segment_has_match_shape(segment: str) -> bool:
    normalized = " ".join(segment.split())
    if " vs " not in normalized.lower():
        return False
    return len(re.findall(_DECIMAL_ODDS_RE, normalized)) >= 2


def _expand_to_token_boundaries(text: str, start: int, end: int) -> str:
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[start:end]


def _candidate_vs_segments(text: str) -> list[str]:
    segments: list[str] = []
    seen: set[str] = set()

    def add(segment: str) -> None:
        normalized = " ".join(segment.split())
        if not normalized:
            return
        lowered = normalized.lower()
        if lowered in seen or not _segment_has_match_shape(normalized):
            return
        seen.add(lowered)
        segments.append(normalized)

    lines = [raw_line.strip() for raw_line in text.splitlines() if raw_line.strip()]
    for raw_line in lines:
        if _segment_has_match_shape(raw_line):
            add(raw_line)

    if segments:
        return segments

    for idx, raw_line in enumerate(lines):
        if "vs" not in raw_line.lower():
            continue
        candidates = [raw_line]
        if idx + 1 < len(lines):
            candidates.append(f"{raw_line} {lines[idx + 1]}")
        if idx > 0:
            candidates.append(f"{lines[idx - 1]} {raw_line}")
        if idx > 0 and idx + 1 < len(lines):
            candidates.append(f"{lines[idx - 1]} {raw_line} {lines[idx + 1]}")
        for candidate in candidates:
            if _segment_has_match_shape(candidate):
                add(candidate)

    if segments:
        return segments

    for vs_m in re.finditer(r"\bvs\b", text, re.IGNORECASE):
        start = max(0, vs_m.start() - 60)
        end = min(len(text), vs_m.end() + 60)
        add(_expand_to_token_boundaries(text, start, end))

    return segments


def _append_extracted_match(
    results: list[BookieMatchOdds],
    seen: set[tuple[str, str, float, float]],
    *,
    team1: str,
    team2: str,
    odds1: float,
    odds2: float,
    diagnostics: dict[str, object] | None = None,
) -> None:
    clean_team1 = _clean_extracted_team_name(team1)
    clean_team2 = _clean_extracted_team_name(team2)
    if not (1.01 <= odds1 <= 50 and 1.01 <= odds2 <= 50):
        _record_rejected_candidate(diagnostics, team1, team2, "odds_out_of_range")
        return
    if len(clean_team1) < 2 or len(clean_team2) < 2:
        _record_rejected_candidate(diagnostics, clean_team1, clean_team2, "name_too_short")
        return
    if _SKIP_NAMES_RE.match(clean_team1) or _SKIP_NAMES_RE.match(clean_team2):
        _record_rejected_candidate(diagnostics, clean_team1, clean_team2, "skip_token_name")
        return
    if _SKIP_RE.search(clean_team1) or _SKIP_RE.search(clean_team2):
        _record_rejected_candidate(diagnostics, clean_team1, clean_team2, "metadata_name")
        return
    suspicious_reason = _suspicious_name_reason(clean_team1) or _suspicious_name_reason(clean_team2)
    if suspicious_reason:
        _record_rejected_candidate(diagnostics, clean_team1, clean_team2, suspicious_reason)
        return
    key = (clean_team1.lower(), clean_team2.lower(), min(odds1, odds2), max(odds1, odds2))
    if key in seen:
        _record_rejected_candidate(diagnostics, clean_team1, clean_team2, "duplicate")
        return
    seen.add(key)
    results.append(BookieMatchOdds(team1=clean_team1, team2=clean_team2, odds1=odds1, odds2=odds2))
    if diagnostics is not None:
        diagnostics["accepted_count"] = int(diagnostics.get("accepted_count", 0) or 0) + 1
        accepted = diagnostics.setdefault("sample_matches", [])
        if isinstance(accepted, list) and len(accepted) < 5:
            accepted.append(f"{clean_team1} vs {clean_team2}")


def _clean_extracted_team_name(value: str) -> str:
    tokens = [token for token in value.split() if token]
    while tokens and _SKIP_NAMES_RE.match(tokens[0]):
        tokens.pop(0)
    while tokens and _SKIP_NAMES_RE.match(tokens[-1]):
        tokens.pop()
    while tokens and _STRIP_PREFIX_TOKEN_RE.match(tokens[0]):
        tokens.pop(0)
    while len(tokens) > 1 and _LEADING_METADATA_TOKEN_RE.match(tokens[0]):
        tokens.pop(0)
    return " ".join(tokens)


def _suspicious_name_reason(name: str) -> str | None:
    tokens = [token for token in name.split() if token]
    if not tokens:
        return "empty_name"
    if _STRIP_PREFIX_TOKEN_RE.match(tokens[0]):
        return "metadata_prefix"
    if len(tokens[0]) == 1 and len(tokens) > 1:
        return "single_letter_prefix"
    if tokens[0].islower():
        return "midword_capture"
    return None


def _record_rejected_candidate(
    diagnostics: dict[str, object] | None,
    team1: str,
    team2: str,
    reason: str,
) -> None:
    if diagnostics is None:
        return
    diagnostics["rejected_count"] = int(diagnostics.get("rejected_count", 0) or 0) + 1
    rejected = diagnostics.setdefault("sample_rejections", [])
    if isinstance(rejected, list) and len(rejected) < 5:
        rejected.append(
            {
                "team1": team1,
                "team2": team2,
                "reason": reason,
            }
        )


def _extract_from_page_text(
    text: str,
    *,
    diagnostics: dict[str, object] | None = None,
) -> list[BookieMatchOdds]:
    text = _extract_lol_section(text)
    results: list[BookieMatchOdds] = []
    seen: set[tuple[str, str, float, float]] = set()
    segments = _candidate_vs_segments(text)
    if diagnostics is not None:
        diagnostics["candidate_segment_count"] = len(segments)
        diagnostics["raw_candidate_count"] = 0
        diagnostics.setdefault("sample_matches", [])
        diagnostics.setdefault("sample_rejections", [])
        diagnostics.setdefault("accepted_count", 0)
        diagnostics.setdefault("rejected_count", 0)
    for segment in segments:
        for pattern in _STRUCTURED_MATCH_PATTERNS:
            for match in pattern.finditer(segment):
                if diagnostics is not None:
                    diagnostics["raw_candidate_count"] = int(diagnostics.get("raw_candidate_count", 0) or 0) + 1
                _append_extracted_match(
                    results,
                    seen,
                    team1=str(match.group("team1") or ""),
                    team2=str(match.group("team2") or ""),
                    odds1=float(match.group("odds1")),
                    odds2=float(match.group("odds2")),
                    diagnostics=diagnostics,
                )

    return results[:MAX_EXTRACTED_MATCHES]


def _extract_market_offers_from_text_window(
    text: str,
    *,
    team1: str,
    team2: str,
    scraped_at: str | None,
) -> list[ThunderpickMarketOffer]:
    offers: list[ThunderpickMarketOffer] = []
    offer_keys: set[tuple[str, str, float | None]] = set()

    def add_offer(offer: ThunderpickMarketOffer) -> None:
        key = (offer["market_type"], offer["selection_key"], offer["line_value"])
        if key in offer_keys:
            return
        offer_keys.add(key)
        offers.append(offer)

    escaped_team1 = re.escape(team1)
    escaped_team2 = re.escape(team2)

    team1_moneyline = re.search(rf"{escaped_team1}\s+(\d+\.\d{{1,2}})", text, re.IGNORECASE)
    team2_moneyline = re.search(rf"{escaped_team2}\s+(\d+\.\d{{1,2}})", text, re.IGNORECASE)
    if team1_moneyline:
        add_offer(
            _raw_match_winner_offer(
                decimal_odds=float(team1_moneyline.group(1)),
                selection_key="team1",
                selection_name=team1,
                scraped_at=scraped_at,
            )
        )
    if team2_moneyline:
        add_offer(
            _raw_match_winner_offer(
                decimal_odds=float(team2_moneyline.group(1)),
                selection_key="team2",
                selection_name=team2,
                scraped_at=scraped_at,
            )
        )

    handicap_pattern = re.compile(
        rf"({escaped_team1}|{escaped_team2})\s*([+-]\d+\.\d)\s+(\d+\.\d{{1,2}})",
        re.IGNORECASE,
    )
    for match in handicap_pattern.finditer(text):
        selection_name = str(match.group(1)).strip()
        line_value = float(match.group(2))
        odds = float(match.group(3))
        selection_key = "team1" if _normalize_team_name(selection_name) == _normalize_team_name(team1) else "team2"
        line_suffix = f"{line_value:+.1f}"
        add_offer(
            {
                "source_book": "thunderpick",
                "market_type": "map_handicap",
                "selection_key": f"{selection_key}_{line_suffix}",
                "line_value": line_value,
                "decimal_odds": odds,
                "market_status": "available",
                "scraped_at": scraped_at,
                "source_market_name": "Map Handicap",
                "source_selection_name": selection_name,
                "source_payload_json": None,
            }
        )

    total_maps_pattern = re.compile(r"(Over|Under)\s+(\d+\.\d)\s+(\d+\.\d{1,2})", re.IGNORECASE)
    for match in total_maps_pattern.finditer(text):
        direction = str(match.group(1)).strip().lower()
        line_value = float(match.group(2))
        odds = float(match.group(3))
        add_offer(
            {
                "source_book": "thunderpick",
                "market_type": "total_maps",
                "selection_key": f"{direction}_{line_value:.1f}",
                "line_value": line_value,
                "decimal_odds": odds,
                "market_status": "available",
                "scraped_at": scraped_at,
                "source_market_name": "Total Maps",
                "source_selection_name": f"{direction.title()} {line_value:.1f}",
                "source_payload_json": None,
            }
        )

    return offers


def _build_market_catalog_from_page_text(text: str) -> ThunderpickCatalogPayload:
    scraped_at = _utc_iso_now()
    matches: list[ThunderpickMatchCatalog] = []
    base_matches = _extract_from_page_text(text)
    for row in base_matches:
        team1 = row["team1"]
        team2 = row["team2"]
        window = f"{team1} {row['odds1']} vs {team2} {row['odds2']}"
        team_pattern = re.compile(
            rf"({re.escape(team1)}[\s\S]{{0,80}}?{re.escape(team2)}|{re.escape(team2)}[\s\S]{{0,80}}?{re.escape(team1)})",
            re.IGNORECASE,
        )
        window_match = team_pattern.search(text)
        if window_match:
            start = window_match.start()
            end = min(len(text), start + 500)
            window = text[start:end]
        offers = _extract_market_offers_from_text_window(
            window,
            team1=team1,
            team2=team2,
            scraped_at=scraped_at,
        )
        if not any(offer["market_type"] == "match_winner" and offer["selection_key"] == "team1" for offer in offers):
            offers.append(
                _raw_match_winner_offer(
                    decimal_odds=float(row["odds1"]),
                    selection_key="team1",
                    selection_name=team1,
                    scraped_at=scraped_at,
                )
            )
        if not any(offer["market_type"] == "match_winner" and offer["selection_key"] == "team2" for offer in offers):
            offers.append(
                _raw_match_winner_offer(
                    decimal_odds=float(row["odds2"]),
                    selection_key="team2",
                    selection_name=team2,
                    scraped_at=scraped_at,
                )
            )
        matches.append({"team1": team1, "team2": team2, "offers": offers})
    return {
        "version": 2,
        "source_book": "thunderpick",
        "scraped_at": scraped_at,
        "matches": matches,
    }


def _merge_extracted_results(
    dom_results: list[BookieMatchOdds],
    text_results: list[BookieMatchOdds],
) -> list[BookieMatchOdds]:
    merged: list[BookieMatchOdds] = []
    seen: set[tuple[str, str]] = set()
    for row in text_results + dom_results:
        team1 = str(row.get("team1", "")).strip()
        team2 = str(row.get("team2", "")).strip()
        odds1 = float(row.get("odds1", 0.0))
        odds2 = float(row.get("odds2", 0.0))
        if not team1 or not team2:
            continue
        if not (1.01 <= odds1 <= 50 and 1.01 <= odds2 <= 50):
            continue
        n1 = _normalize_team_name(team1)
        n2 = _normalize_team_name(team2)
        if not n1 or not n2:
            continue
        key = tuple(sorted((n1, n2)))
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            BookieMatchOdds(
                team1=team1,
                team2=team2,
                odds1=odds1,
                odds2=odds2,
            )
        )
        if len(merged) >= MAX_EXTRACTED_MATCHES:
            break
    return merged


def _write_scrape_status(cache_dir: Path, payload: dict[str, object]) -> None:
    try:
        with open(cache_dir / SCRAPE_STATUS_FILENAME, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError as e:
        logger.warning("Betting odds scraper: failed to write scrape status: %s", e)


def _is_blocked(body_text: str) -> bool:
    lower = body_text.lower()
    return "you have been blocked" in lower or "something went wrong" in lower or len(body_text) < 200


def _parse_proxy_env() -> dict[str, str] | None:
    raw = os.getenv("BOOKIE_HTTP_PROXY", "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    server = f"{parsed.scheme or 'http'}://{parsed.hostname}:{parsed.port}"
    proxy: dict[str, str] = {"server": server}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


def _run_playwright_attempt(
    timeout_ms: int,
    proxy: dict[str, str] | None,
    cache_dir: Path,
) -> tuple[list[BookieMatchOdds], str, dict[str, object]]:
    from playwright.sync_api import sync_playwright

    results: list[BookieMatchOdds] = []
    body_text = ""
    scrape_diagnostics: dict[str, object] = {
        "dom_match_count": 0,
        "text_match_count": 0,
        "accepted_match_count": 0,
        "raw_text_candidate_count": 0,
        "rejected_candidate_count": 0,
        "candidate_segment_count": 0,
        "sample_matches": [],
        "sample_rejections": [],
    }

    chrome_channel = os.getenv("BOOKIE_USE_CHROME", "").strip().lower() in {"1", "true", "yes"}

    with sync_playwright() as p:
        launch_kwargs: dict[str, object] = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--lang=en-BE",
            ],
        }
        if chrome_channel:
            launch_kwargs["channel"] = "chrome"

        try:
            browser = p.chromium.launch(**launch_kwargs)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning("Betting odds scraper: Chromium launch failed: %s", e)
            return results, body_text, scrape_diagnostics

        try:
            context_kwargs: dict[str, object] = {
                "user_agent": CHROME_USER_AGENT,
                "viewport": {"width": 1920, "height": 1080},
                "locale": BELGIUM_LOCALE,
                "timezone_id": BELGIUM_TIMEZONE,
                "java_script_enabled": True,
                "ignore_https_errors": False,
                "extra_http_headers": {
                    "Accept-Language": "en-BE,en;q=0.9,nl;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Sec-CH-UA": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                    "Sec-CH-UA-Mobile": "?0",
                    "Sec-CH-UA-Platform": '"Windows"',
                    "Upgrade-Insecure-Requests": "1",
                },
            }
            if proxy:
                context_kwargs["proxy"] = proxy
                logger.info(
                    "Betting odds scraper: using proxy server=%s",
                    proxy.get("server", "unknown"),
                )

            context = browser.new_context(**context_kwargs)  # type: ignore[arg-type]
            context.grant_permissions(["geolocation"])
            page = context.new_page()

            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
            except ImportError:
                pass

            pre_delay = random.uniform(1.0, 3.0)
            logger.debug("Betting odds scraper: pre-navigation delay %.1fs", pre_delay)
            time.sleep(pre_delay)

            page.goto(
                THUNDERPICK_LOL_URL,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            page.wait_for_timeout(int(random.uniform(500, 1500)))
            page.wait_for_timeout(WAIT_AFTER_LOAD_MS)

            try:
                page.wait_for_function(
                    "() => document.body && /\\d+\\.\\d{2}/.test(document.body.innerText)",
                    timeout=15_000,
                )
            except Exception:
                pass

            page.evaluate(
                """
                () => {
                    for (let i = 0; i < 6; i += 1) {
                        window.scrollBy(0, Math.max(600, Math.floor(window.innerHeight * 0.9)));
                    }
                }
                """
            )
            page.wait_for_timeout(2_500)

        except Exception as e:
            logger.warning("Betting odds scraper: page load failed: %s", e)
            try:
                body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                body_text = body_text if isinstance(body_text, str) else ""
                logger.warning(
                    "Betting odds scraper: page content on load failure (first 300): %s",
                    (body_text or "(empty)")[:300].replace("\n", " "),
                )
            except Exception:
                pass
            browser.close()
            return results, body_text

        try:
            screenshot_path = str(cache_dir / "thunderpick_debug.png")
            page.screenshot(path=screenshot_path, full_page=False)
            logger.info("Betting odds scraper: saved debug screenshot to %s", screenshot_path)
        except Exception as e:
            logger.debug("Betting odds scraper: screenshot failed: %s", e)

        dom_results: list[BookieMatchOdds] = []
        try:
            scraped = page.evaluate(
                """
                () => {
                    const oddsRegex = /^\\d+\\.\\d{1,2}$/;
                    const blockedTokenRegex = /^(live|bo\\d|vs|featured|today|tomorrow|map\\d+)$/i;
                    const rows = [];
                    const seen = new Set();
                    const all = document.querySelectorAll('[data-testid*="match"], [class*="match"], article, a[href*="esports"], [role="listitem"], div, span, p');
                    for (const el of all) {
                        const text = (el.textContent || '').trim();
                        if (text.length < 12 || text.length > 700) continue;
                        const parts = text.split(/\\s+/).filter(Boolean);
                        const numbers = parts.filter(p => oddsRegex.test(p)).map(Number);
                        const possibleOdds = numbers.filter(n => n >= 1.01 && n <= 50);
                        if (possibleOdds.length >= 2) {
                            const teamLike = parts.filter((p) => {
                                if (oddsRegex.test(p) || !isNaN(Number(p))) return false;
                                const normalized = p.replace(/[.,]/g, '').trim().toLowerCase();
                                if (!normalized || normalized.length < 3 || normalized.length > 30) return false;
                                if (blockedTokenRegex.test(normalized)) return false;
                                return /[a-z]/i.test(normalized);
                            });
                            const teams = teamLike.slice(0, 2);
                            if (teams.length >= 2) {
                                const key = teams.slice().sort().join('|') + '|' + possibleOdds.slice(0, 2).sort((a,b)=>a-b).join('|');
                                if (!seen.has(key)) {
                                    seen.add(key);
                                    rows.push({ team1: teams[0], team2: teams[1], odds1: possibleOdds[0], odds2: possibleOdds[1] });
                                }
                            }
                        }
                    }
                    return rows.slice(0, 80);
                }
                """
            )
            if isinstance(scraped, list) and scraped:
                for r in scraped:
                    if (
                        isinstance(r, dict)
                        and r.get("team1") and r.get("team2")
                        and isinstance(r.get("odds1"), (int, float))
                        and isinstance(r.get("odds2"), (int, float))
                    ):
                        dom_results.append(BookieMatchOdds(
                            team1=str(r["team1"]).strip(),
                            team2=str(r["team2"]).strip(),
                            odds1=float(r["odds1"]),
                            odds2=float(r["odds2"]),
                        ))
                logger.info("Betting odds scraper: DOM extraction found %d matches", len(dom_results))
        except Exception as e:
            logger.warning("Betting odds scraper: DOM evaluate failed: %s", e)

        try:
            body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
            body_text = body_text if isinstance(body_text, str) else ""
        except Exception as e:
            logger.warning("Betting odds scraper: could not get body text: %s", e)

        text_results: list[BookieMatchOdds] = []
        if len(body_text) > 500:
            text_diagnostics: dict[str, object] = {}
            text_results = _extract_from_page_text(body_text, diagnostics=text_diagnostics)
            scrape_diagnostics["text_match_count"] = len(text_results)
            scrape_diagnostics["raw_text_candidate_count"] = int(text_diagnostics.get("raw_candidate_count", 0) or 0)
            scrape_diagnostics["rejected_candidate_count"] = int(text_diagnostics.get("rejected_count", 0) or 0)
            scrape_diagnostics["candidate_segment_count"] = int(text_diagnostics.get("candidate_segment_count", 0) or 0)
            scrape_diagnostics["sample_rejections"] = list(text_diagnostics.get("sample_rejections", []))[:5]
            if text_results:
                logger.info(
                    "Betting odds scraper: text extraction found %d matches (raw=%d rejected=%d segments=%d)",
                    len(text_results),
                    scrape_diagnostics["raw_text_candidate_count"],
                    scrape_diagnostics["rejected_candidate_count"],
                    scrape_diagnostics["candidate_segment_count"],
                )
            elif not dom_results:
                logger.info("Betting odds scraper: text extraction found 0 matches")
        results = _merge_extracted_results(dom_results, text_results)
        scrape_diagnostics["dom_match_count"] = len(dom_results)
        scrape_diagnostics["accepted_match_count"] = len(results)
        scrape_diagnostics["sample_matches"] = [f"{row['team1']} vs {row['team2']}" for row in results[:5]]
        if results:
            sample_pairs = ", ".join(f"{row['team1']} vs {row['team2']}" for row in results[:5])
            logger.info(
                "Betting odds scraper: merged extraction found %d matches (dom=%d text=%d) sample=%s",
                len(results),
                len(dom_results),
                len(text_results),
                sample_pairs or "(none)",
            )
        if scrape_diagnostics["sample_rejections"]:
            logger.info(
                "Betting odds scraper: rejected text candidates=%s",
                scrape_diagnostics["sample_rejections"],
            )

        context.close()
        browser.close()

    return results, body_text, scrape_diagnostics


def _scrape_via_playwright(
    cache_dir: Path,
    cache_path: Path,
    timeout_ms: int,
) -> tuple[list[BookieMatchOdds], str, dict[str, object]]:
    try:
        from playwright.sync_api import sync_playwright as _  # noqa: F401
    except ImportError as e:
        logger.warning("Betting odds scraper: Playwright not available: %s", e)
        return ([], "", {})

    proxy = _parse_proxy_env()
    if proxy:
        logger.info("Betting odds scraper: proxy configured")
    else:
        logger.info(
            "Betting odds scraper: no BOOKIE_HTTP_PROXY set — traffic uses Docker host IP. "
            "Set BOOKIE_HTTP_PROXY (e.g. http://host.docker.internal:8888) to use host VPN."
        )

    results: list[BookieMatchOdds] = []
    body_text = ""
    scrape_diagnostics: dict[str, object] = {}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("Betting odds scraper: Playwright attempt %d/%d", attempt, MAX_ATTEMPTS)
        results, body_text, scrape_diagnostics = _run_playwright_attempt(timeout_ms, proxy, cache_dir)

        if results:
            break

        if attempt < MAX_ATTEMPTS:
            if _is_blocked(body_text):
                delay = random.uniform(*RETRY_DELAY_RANGE)
                logger.warning(
                    "Betting odds scraper: blocked on attempt %d — retrying in %.0fs",
                    attempt,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.warning("Betting odds scraper: 0 matches on attempt %d — retrying", attempt)
                time.sleep(5)

    if not results:
        _log_blocked(body_text)
        _write_debug_snippet(body_text, cache_dir)

    return results, body_text, scrape_diagnostics


def _log_blocked(body_text: str) -> None:
    body_lower = (body_text or "").lower()
    if "you have been blocked" in body_lower:
        logger.warning(
            "Betting odds scraper: request was blocked (Cloudflare). "
            "Set BOOKIE_HTTP_PROXY to route through your host VPN (see docs/bookie-scraper.md)."
        )
    elif "something went wrong" in body_lower:
        logger.warning(
            "Betting odds scraper: page returned 'Something went wrong'. "
            "Check thunderpick_page_snippet.txt in the cache volume."
        )
    preview = (body_text or "(empty)")[:400].replace("\n", " ")
    logger.info(
        "Betting odds scraper: no matches extracted. Page preview: %s...",
        preview,
    )


def scrape_lol_odds(
    output_dir: str | Path | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[BookieMatchOdds]:
    cache_dir = Path(output_dir or get_odds_cache_dir())
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / ODDS_CACHE_FILENAME

    results, body_text, scrape_diagnostics = _scrape_via_playwright(cache_dir, cache_path, timeout_ms)
    scrape_status = {
        "generated_at": _utc_iso_now(),
        "dom_match_count": int(scrape_diagnostics.get("dom_match_count", 0) or 0),
        "text_match_count": int(scrape_diagnostics.get("text_match_count", 0) or 0),
        "accepted_match_count": int(scrape_diagnostics.get("accepted_match_count", 0) or len(results)),
        "raw_text_candidate_count": int(scrape_diagnostics.get("raw_text_candidate_count", 0) or 0),
        "rejected_candidate_count": int(scrape_diagnostics.get("rejected_candidate_count", 0) or 0),
        "candidate_segment_count": int(scrape_diagnostics.get("candidate_segment_count", 0) or 0),
        "sample_matches": list(scrape_diagnostics.get("sample_matches", []))[:5],
        "sample_rejections": list(scrape_diagnostics.get("sample_rejections", []))[:5],
        "degraded_mode": bool(
            int(scrape_diagnostics.get("dom_match_count", 0) or 0) == 0
            and int(scrape_diagnostics.get("text_match_count", 0) or 0) > 0
        ),
    }

    if results:
        market_catalog = _build_market_catalog_from_page_text(body_text) if body_text else {
            "version": 2,
            "source_book": "thunderpick",
            "scraped_at": _utc_iso_now(),
            "matches": [],
        }
        if not market_catalog["matches"]:
            market_catalog = _legacy_rows_to_catalog(results)
        _write_odds_cache(market_catalog, cache_path)
    else:
        logger.warning("Betting odds scraper: all attempts exhausted — no matches extracted")

    _write_scrape_status(cache_dir, scrape_status)
    return results

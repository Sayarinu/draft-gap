
from __future__ import annotations

CANONICAL_SLUGS: frozenset[str] = frozenset({
    "lcs",
    "lec",
    "lck",
    "lpl",
    "cblol",
    "lla",
    "pcs",
    "vcs",
    "ljl",
    "lco",
    "worlds",
    "msi",
    "lcp",
    "americas",
    "emea",
    "pacific",
})

LEAGUE_ALIAS_TO_SLUG: dict[str, str] = {
    "lta north": "lcs",
    "lta north 2022": "lcs",
    "lta north 2023": "lcs",
    "lta north 2024": "lcs",
    "lta north 2025": "lcs",
    "lta north 2026": "lcs",
    "lta south": "cblol",
    "ltas": "cblol",
    "lta south 2022": "cblol",
    "lta south 2023": "cblol",
    "lta south 2024": "cblol",
    "lta south 2025": "cblol",
    "lta south 2026": "cblol",
    "lla": "cblol",
    "liga latinoamérica": "cblol",
    "liga latinoamerica": "cblol",
    "americas": "lcs",
    "lcs nac": "lcs",
    "nac": "lcs",
    "lcs na": "lcs",
    "lcp": "americas",
}


def normalize_league_key(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.lower().strip()


def resolve_league_slug(raw_league: str | None) -> str | None:
    key = normalize_league_key(raw_league)
    if not key:
        return None
    return LEAGUE_ALIAS_TO_SLUG.get(key, key)

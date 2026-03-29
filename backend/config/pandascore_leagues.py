
from __future__ import annotations

APPROVED_PANDASCORE_LEAGUE_SLUGS: frozenset[str] = frozenset(
    {
        "league-of-legends-lcs",
        "league-of-legends-lec",
        "league-of-legends-champions-korea",
        "league-of-legends-lpl-china",
        "league-of-legends-world-championship",
        "league-of-legends-mid-season-invitational",
        "league-of-legends-americas-cup",
        "league-of-legends-first-stand",
        "league-of-legends-lcp",
    }
)

APPROVED_PANDASCORE_LEAGUE_IDS: frozenset[int] = frozenset()

LEGACY_ACCEPTED_NAME_SUBSTRINGS: tuple[str, ...] = (
    "lec",
    "lcs",
    "americas cup",
    "lpl",
    "lck",
    "lcp",
    "ewc",
    "esports world cup",
    "cblol",
    "fst",
    "first stand",
    "msi",
    "worlds",
    "world championship",
    "mid-season invitational",
)

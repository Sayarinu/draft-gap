from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal


MarketType = Literal["match_winner", "map_handicap", "total_maps"]


@dataclass(frozen=True)
class MarketOffer:
    source_book: str
    market_type: MarketType
    selection_key: str
    line_value: float | None
    decimal_odds: float
    market_status: str = "available"
    source_market_name: str | None = None
    source_selection_name: str | None = None
    source_payload_json: dict[str, object] | None = None
    scraped_at: str | None = None


@dataclass(frozen=True)
class MatchMarketSet:
    team_a: str
    team_b: str
    offers: list[MarketOffer] = field(default_factory=list)
    matched: bool = True
    confidence: str = "exact"
    matched_row_team1: str | None = None
    matched_row_team2: str | None = None


@dataclass(frozen=True)
class BetCandidate:
    pandascore_match_id: int
    series_key: str
    team_a: str
    team_b: str
    market_type: MarketType
    selection_key: str
    line_value: float | None
    chosen_team: str | None
    chosen_model_prob: Decimal
    chosen_book_prob: Decimal
    chosen_book_odds: Decimal
    chosen_edge: Decimal
    ev: Decimal
    stake: Decimal
    expected_log_growth: Decimal
    confidence: Decimal
    number_of_games: int
    source_book: str = "thunderpick"
    source_market_name: str | None = None
    source_selection_name: str | None = None
    odds_source_status: str = "available"
    model_snapshot_json: dict[str, object] | None = None


@dataclass(frozen=True)
class DecisionResult:
    recommended: BetCandidate | None
    ranked_candidates: list[BetCandidate] = field(default_factory=list)
    rejected_candidates: list[dict[str, object]] = field(default_factory=list)

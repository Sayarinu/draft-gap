from __future__ import annotations

from dataclasses import dataclass
from math import comb, log


@dataclass(frozen=True)
class SeriesScoreProbability:
    score_a: int
    score_b: int
    probability: float


def games_to_win(number_of_games: int) -> int:
    if number_of_games <= 1:
        return 1
    return (number_of_games // 2) + 1


def series_win_probability_from_map_prob(map_win_prob_a: float, number_of_games: int) -> float:
    if number_of_games <= 1:
        return max(0.0, min(1.0, map_win_prob_a))

    wins_needed = games_to_win(number_of_games)
    p = max(0.0001, min(0.9999, map_win_prob_a))
    total = 0.0
    for losses in range(wins_needed):
        total += comb((wins_needed - 1) + losses, losses) * (p ** wins_needed) * ((1.0 - p) ** losses)
    return max(0.0, min(1.0, total))


def infer_map_win_probability(series_win_prob_a: float, number_of_games: int) -> float:
    target = max(0.0001, min(0.9999, series_win_prob_a))
    if number_of_games <= 1:
        return target

    low = 0.0001
    high = 0.9999
    for _ in range(60):
        mid = (low + high) / 2.0
        implied = series_win_probability_from_map_prob(mid, number_of_games)
        if implied < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def compute_exact_score_probabilities(map_win_prob_a: float, number_of_games: int) -> list[SeriesScoreProbability]:
    if number_of_games <= 1:
        p = max(0.0, min(1.0, map_win_prob_a))
        return [
            SeriesScoreProbability(score_a=1, score_b=0, probability=p),
            SeriesScoreProbability(score_a=0, score_b=1, probability=1.0 - p),
        ]

    wins_needed = games_to_win(number_of_games)
    p = max(0.0001, min(0.9999, map_win_prob_a))
    rows: list[SeriesScoreProbability] = []
    for losses in range(wins_needed):
        rows.append(
            SeriesScoreProbability(
                score_a=wins_needed,
                score_b=losses,
                probability=comb((wins_needed - 1) + losses, losses) * (p ** wins_needed) * ((1.0 - p) ** losses),
            )
        )
    for wins in range(wins_needed):
        rows.append(
            SeriesScoreProbability(
                score_a=wins,
                score_b=wins_needed,
                probability=comb((wins_needed - 1) + wins, wins) * ((1.0 - p) ** wins_needed) * (p ** wins),
            )
        )
    return rows


def normalize_score_probabilities(rows: list[SeriesScoreProbability]) -> list[SeriesScoreProbability]:
    total = sum(max(0.0, row.probability) for row in rows)
    if total <= 0:
        return rows
    return [
        SeriesScoreProbability(
            score_a=row.score_a,
            score_b=row.score_b,
            probability=row.probability / total,
        )
        for row in rows
    ]


def handicap_cover_probability(rows: list[SeriesScoreProbability], *, side: str, line_value: float) -> float:
    normalized = normalize_score_probabilities(rows)
    side_key = side.strip().lower()
    total = 0.0
    for row in normalized:
        score_for = row.score_a if side_key == "team_a" else row.score_b
        score_against = row.score_b if side_key == "team_a" else row.score_a
        if (score_for + line_value) > score_against:
            total += row.probability
    return max(0.0, min(1.0, total))


def total_maps_probability(rows: list[SeriesScoreProbability], *, bet: str, line_value: float) -> float:
    normalized = normalize_score_probabilities(rows)
    bet_key = bet.strip().lower()
    total = 0.0
    for row in normalized:
        maps_played = row.score_a + row.score_b
        if bet_key == "over" and maps_played > line_value:
            total += row.probability
        if bet_key == "under" and maps_played < line_value:
            total += row.probability
    return max(0.0, min(1.0, total))


def expected_log_growth(model_prob: float, decimal_odds: float, bankroll_fraction: float) -> float:
    p = max(0.0, min(1.0, model_prob))
    odds = max(1.0001, decimal_odds)
    f = max(0.0, bankroll_fraction)
    b = odds - 1.0
    if f <= 0.0:
        return 0.0
    win_term = 1.0 + (b * f)
    lose_term = 1.0 - f
    if win_term <= 0.0 or lose_term <= 0.0:
        return float("-inf")
    return (p * log(win_term)) + ((1.0 - p) * log(lose_term))

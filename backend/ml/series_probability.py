from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=512)
def series_win_probability(
    p: float,
    score_a: int,
    score_b: int,
    games_to_win: int,
) -> float:
    if score_a >= games_to_win:
        return 1.0
    if score_b >= games_to_win:
        return 0.0
    p = max(0.01, min(0.99, p))
    win_next = p * series_win_probability(p, score_a + 1, score_b, games_to_win)
    lose_next = (1 - p) * series_win_probability(p, score_a, score_b + 1, games_to_win)
    return win_next + lose_next


def format_to_games_to_win(series_format: str) -> int:
    fmt = series_format.upper().strip()
    if fmt == "BO5":
        return 3
    if fmt == "BO3":
        return 2
    return 1


def number_of_games_to_format(number_of_games: int) -> str:
    if number_of_games >= 5:
        return "BO5"
    if number_of_games >= 3:
        return "BO3"
    return "BO1"


def compute_live_series_odds(
    game_win_prob: float,
    score_a: int,
    score_b: int,
    number_of_games: int,
) -> tuple[float, float]:
    fmt = number_of_games_to_format(number_of_games)
    games_to_win = format_to_games_to_win(fmt)

    if games_to_win <= 1:
        return (game_win_prob, 1.0 - game_win_prob)

    prob_a = series_win_probability(game_win_prob, score_a, score_b, games_to_win)
    return (prob_a, 1.0 - prob_a)


def prob_to_decimal_odds(prob: float) -> float:
    prob = max(0.01, min(0.99, prob))
    return round(1.0 / prob, 2)

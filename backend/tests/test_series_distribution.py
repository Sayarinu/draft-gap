from ml.series_distribution import (
    compute_exact_score_probabilities,
    handicap_cover_probability,
    infer_map_win_probability,
    series_win_probability_from_map_prob,
    total_maps_probability,
)


def test_exact_score_probabilities_sum_to_one_for_bo3() -> None:
    rows = compute_exact_score_probabilities(0.57, 3)
    total = sum(row.probability for row in rows)
    assert len(rows) == 4
    assert abs(total - 1.0) < 1e-9


def test_inferred_map_probability_round_trips_series_probability() -> None:
    target_series_prob = 0.64
    map_prob = infer_map_win_probability(target_series_prob, 5)
    implied = series_win_probability_from_map_prob(map_prob, 5)
    assert abs(implied - target_series_prob) < 1e-4


def test_handicap_and_total_maps_are_derived_from_score_distribution() -> None:
    rows = compute_exact_score_probabilities(0.60, 3)
    cover_prob = handicap_cover_probability(rows, side="team_a", line_value=-1.5)
    over_prob = total_maps_probability(rows, bet="over", line_value=2.5)

    assert 0.0 <= cover_prob <= 1.0
    assert 0.0 <= over_prob <= 1.0
    assert cover_prob > 0.0
    assert over_prob > 0.0

from api.v1 import rankings as rankings_api
from tests.factories import create_api_snapshot


def test_power_rankings_response_is_trimmed_for_frontend(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "rankings",
            payload_json={
                "items": [
                    {
                        "rank": 1,
                        "team": "Alpha",
                        "league_slug": "lck",
                        "wins": 12,
                        "losses": 3,
                        "win_rate": 0.8,
                        "avg_game_duration_min": 31.2,
                        "avg_gold_diff_15": 845.0,
                        "first_blood_pct": 0.62,
                        "first_dragon_pct": 0.7,
                        "first_tower_pct": 0.66,
                        "games_played": 15,
                        "abbreviation": "ALP",
                        "league": "LCK",
                        "kda": 3.2,
                        "playoff_games": 3,
                        "playoff_wins": 2,
                        "playoff_losses": 1,
                        "split_titles": 1,
                        "strength_of_schedule": 0.58,
                        "region_weight": 1.18,
                        "composite_score": 88.4,
                    }
                ]
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/rankings/power")

    assert response.status_code == 200
    assert response.json() == [
        {
            "rank": 1,
            "team": "Alpha",
            "league_slug": "lck",
            "wins": 12,
            "losses": 3,
            "win_rate": 0.8,
            "avg_game_duration_min": 31.2,
            "avg_gold_diff_15": 845.0,
            "first_blood_pct": 0.62,
            "first_dragon_pct": 0.7,
            "first_tower_pct": 0.66,
            "games_played": 15,
        }
    ]


def test_power_rankings_fall_back_to_computed_rows_when_snapshot_missing(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        rankings_api,
        "compute_power_rankings",
        lambda league=None: [
            rankings_api.PowerRankingRow(
                rank=1,
                team="Fallback Alpha",
                league_slug="lck",
                wins=10,
                losses=2,
                win_rate=0.8333,
                avg_game_duration_min=32.1,
                avg_gold_diff_15=700.0,
                first_blood_pct=0.6,
                first_dragon_pct=0.7,
                first_tower_pct=0.65,
                games_played=12,
            )
        ],
    )

    response = client.get("/api/v1/rankings/power")

    assert response.status_code == 200
    assert response.json()[0]["team"] == "Fallback Alpha"


def test_power_rankings_filter_excludes_removed_pcs_region(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "rankings",
            payload_json={
                "items": [
                    {
                        "rank": 1,
                        "team": "Alpha",
                        "league_slug": "pcs",
                        "wins": 12,
                        "losses": 3,
                        "win_rate": 0.8,
                        "avg_game_duration_min": 31.2,
                        "avg_gold_diff_15": 845.0,
                        "first_blood_pct": 0.62,
                        "first_dragon_pct": 0.7,
                        "first_tower_pct": 0.66,
                        "games_played": 15,
                    }
                ]
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/rankings/power?league=pcs")

    assert response.status_code == 200
    assert response.json() == []

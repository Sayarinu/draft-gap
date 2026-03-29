from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from pytest import approx

from api.v1 import pandascore as pandascore_api
from ml import model_registry, predictor_v2
from models_ml import LiveWithOddsSnapshot
from services.pandascore import PandaScoreUpstreamError, is_degradable_upstream_error
from tasks import task_refresh_live_snapshot, task_refresh_odds_pipeline
from tests.factories import create_api_snapshot, create_bankroll, create_bet, create_model_run


def _sample_match() -> dict[str, object]:
    return {
        "id": 4001,
        "name": "Alpha vs Beta",
        "status": "not_started",
        "scheduled_at": "2026-03-22T18:00:00Z",
        "begin_at": None,
        "end_at": None,
        "original_scheduled_at": "2026-03-22T18:00:00Z",
        "modified_at": "2026-03-22T18:00:00Z",
        "league_id": 10,
        "league": {"id": 10, "name": "LCK", "slug": "lck", "image_url": None},
        "tournament": {
            "id": 11,
            "name": "Spring",
            "type": "league",
            "tier": "s",
            "region": "KR",
            "country": "KR",
            "begin_at": "2026-03-01T00:00:00Z",
            "end_at": None,
        },
        "opponents": [
            {
                "type": "Team",
                "opponent": {
                    "id": 1,
                    "name": "Alpha",
                    "location": None,
                    "slug": "alpha",
                    "acronym": "ALP",
                    "image_url": None,
                },
            },
            {
                "type": "Team",
                "opponent": {
                    "id": 2,
                    "name": "Beta",
                    "location": None,
                    "slug": "beta",
                    "acronym": "BET",
                    "image_url": None,
                },
            },
        ],
        "results": [],
        "number_of_games": 3,
        "match_type": "best_of",
        "streams_list": [],
        "forfeit": False,
        "draw": False,
        "winner_id": None,
        "winner": None,
    }


def test_public_odds_endpoint_does_not_require_admin_key(client) -> None:
    pandascore_api._odds_response_cache.clear()
    response = client.get("/api/v1/pandascore/odds-refresh-global-status")

    assert response.status_code == 200


def test_upcoming_with_odds_returns_enriched_payload_and_cache_control(
    client,
    db_session,
    monkeypatch,
) -> None:
    db_session.add(
        create_api_snapshot(
            "upcoming",
            payload_json={
                "items": [
                    {
                        "id": 4001,
                        "scheduled_at": "2026-03-22T18:00:00Z",
                        "league_name": "LCK",
                        "team1_name": "Alpha",
                        "team1_acronym": "ALP",
                        "team2_name": "Beta",
                        "team2_acronym": "BET",
                        "stream_url": None,
                        "bookie_odds_team1": 2.2,
                        "bookie_odds_team2": 1.7,
                        "model_odds_team1": 1.9,
                        "model_odds_team2": 2.05,
                        "series_format": "BO3",
                        "tournament_tier": "s",
                    },
                    {
                        "id": 4002,
                        "scheduled_at": "2026-03-22T20:00:00Z",
                        "league_name": "LEC",
                        "team1_name": "Delta",
                        "team1_acronym": "DLT",
                        "team2_name": "Echo",
                        "team2_acronym": "ECH",
                        "stream_url": None,
                        "bookie_odds_team1": 1.8,
                        "bookie_odds_team2": 2.1,
                        "model_odds_team1": 1.7,
                        "model_odds_team2": 2.2,
                        "series_format": "BO1",
                        "tournament_tier": "s",
                    },
                ]
            },
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/pandascore/lol/upcoming-with-odds?tier=s",
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=600, s-maxage=900"

    body = response.json()
    assert body["page"] == 1
    assert body["per_page"] == 10
    assert body["total_items"] == 2
    assert body["total_pages"] == 1
    assert body["available_leagues"] == ["LCK", "LEC"]
    assert len(body["items"]) == 2
    assert body["items"][0] == {
        "id": 4001,
        "scheduled_at": "2026-03-22T18:00:00Z",
        "league_name": "LCK",
        "team1_name": "Alpha",
        "team1_acronym": "ALP",
        "team2_name": "Beta",
        "team2_acronym": "BET",
        "stream_url": None,
        "bookie_odds_team1": 2.2,
        "bookie_odds_team2": 1.7,
        "model_odds_team1": 1.9,
        "model_odds_team2": 2.05,
        "series_format": "BO3",
    }

    filtered_response = client.get(
        "/api/v1/pandascore/lol/upcoming-with-odds?tier=s&league=LEC&search=echo",
    )
    assert filtered_response.status_code == 200
    filtered_body = filtered_response.json()
    assert filtered_body["total_items"] == 1
    assert filtered_body["items"][0]["league_name"] == "LEC"


def test_upcoming_serialization_prefers_safe_league_abbreviations() -> None:
    match = _sample_match()
    match["league"] = {"id": 12, "name": "North American Challengers League", "slug": "north-american-challengers-league"}

    serialized = pandascore_api._serialize_upcoming_row(match).model_dump()

    assert serialized["league_name"] == "NACL"


def test_paginate_upcoming_snapshot_items_excludes_hidden_feed_leagues() -> None:
    response = pandascore_api.paginate_upcoming_snapshot_items(
        [
            {
                "id": 4001,
                "scheduled_at": "2026-03-22T18:00:00Z",
                "league_name": "VCS",
                "team1_name": "Alpha",
                "team2_name": "Beta",
                "series_format": "BO3",
            },
            {
                "id": 4002,
                "scheduled_at": "2026-03-22T19:00:00Z",
                "league_name": "LJL",
                "team1_name": "Gamma",
                "team2_name": "Delta",
                "series_format": "BO3",
            },
            {
                "id": 4003,
                "scheduled_at": "2026-03-22T19:30:00Z",
                "league_name": "NACL",
                "team1_name": "Eta",
                "team2_name": "Theta",
                "series_format": "BO3",
            },
            {
                "id": 4004,
                "scheduled_at": "2026-03-22T20:00:00Z",
                "league_name": "LCK",
                "team1_name": "Delta",
                "team2_name": "Echo",
                "series_format": "BO1",
            },
        ],
        page=1,
        per_page=10,
    )

    assert response.available_leagues == ["LCK"]
    assert [item.league_name for item in response.items] == ["LCK"]


def test_upcoming_available_leagues_include_later_pages() -> None:
    response = pandascore_api.paginate_upcoming_snapshot_items(
        [
            {
                "id": 4001,
                "scheduled_at": "2026-03-22T18:00:00Z",
                "league_name": "LCK",
                "team1_name": "Alpha",
                "team2_name": "Beta",
                "series_format": "BO3",
            },
            {
                "id": 4002,
                "scheduled_at": "2026-03-22T20:00:00Z",
                "league_name": "LPL",
                "team1_name": "Delta",
                "team2_name": "Echo",
                "series_format": "BO1",
            },
        ],
        page=1,
        per_page=1,
    )

    assert response.total_pages == 2
    assert [item.league_name for item in response.items] == ["LCK"]
    assert response.available_leagues == ["LCK", "LPL"]


def test_homepage_bootstrap_returns_promoted_snapshot_payload(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "homepage",
            payload_json={
                "generated_at": "2026-03-22T17:45:00Z",
                "results_generated_at": "2026-03-22T17:45:00Z",
                "upcoming": {
                    "items": [
                        {
                            "id": 4001,
                            "scheduled_at": "2026-03-22T18:00:00Z",
                            "league_name": "LCK",
                            "team1_name": "Alpha",
                            "team1_acronym": "ALP",
                            "team2_name": "Beta",
                            "team2_acronym": "BET",
                            "stream_url": None,
                            "bookie_odds_team1": 2.2,
                            "bookie_odds_team2": 1.7,
                            "model_odds_team1": 1.9,
                            "model_odds_team2": 2.05,
                            "series_format": "BO3",
                            "tournament_tier": "s",
                        }
                    ],
                    "page": 1,
                    "per_page": 10,
                    "total_items": 1,
                    "total_pages": 1,
                },
                "live": {"items": [], "page": 1, "per_page": 20, "total_items": 0, "total_pages": 1},
                "bankroll": None,
                "active_bets": [],
                "power_rankings_preview": [],
                "refresh_status": {
                    "in_progress": False,
                    "progress": 0,
                    "stage": "",
                    "last_completed_at": None,
                    "next_scheduled_at": None,
                },
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    assert response.json()["upcoming"]["items"][0]["team1_name"] == "Alpha"
    assert response.json()["results_generated_at"] == "2026-03-22T17:45:00Z"
    assert "results" not in response.json()
    assert "sections" not in response.json()
    assert response.headers["x-snapshot-version"] == "homepage-test-version"


def test_homepage_bootstrap_filters_promoted_upcoming_manifest(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "homepage",
            payload_json={
                "generated_at": "2026-03-22T17:45:00Z",
                "upcoming": {
                    "items": [
                        {
                            "id": 4001,
                            "scheduled_at": "2026-03-22T18:00:00Z",
                            "league_name": "VCS",
                            "team1_name": "Hidden One",
                            "team1_acronym": "H1",
                            "team2_name": "Hidden Two",
                            "team2_acronym": "H2",
                            "stream_url": None,
                            "bookie_odds_team1": 2.2,
                            "bookie_odds_team2": 1.7,
                            "model_odds_team1": 1.9,
                            "model_odds_team2": 2.05,
                            "series_format": "BO3",
                            "tournament_tier": "s",
                        },
                        {
                            "id": 4002,
                            "scheduled_at": "2026-03-22T19:00:00Z",
                            "league_name": "LCK",
                            "team1_name": "Tier Skip",
                            "team1_acronym": "TS",
                            "team2_name": "Tier Skip 2",
                            "team2_acronym": "T2",
                            "stream_url": None,
                            "bookie_odds_team1": 2.0,
                            "bookie_odds_team2": 1.8,
                            "model_odds_team1": 1.9,
                            "model_odds_team2": 2.0,
                            "series_format": "BO3",
                            "tournament_tier": "b",
                        },
                        {
                            "id": 4003,
                            "scheduled_at": "2026-03-22T20:00:00Z",
                            "league_name": "LEC",
                            "team1_name": "Visible One",
                            "team1_acronym": "V1",
                            "team2_name": "Visible Two",
                            "team2_acronym": "V2",
                            "stream_url": None,
                            "bookie_odds_team1": 2.1,
                            "bookie_odds_team2": 1.9,
                            "model_odds_team1": 1.95,
                            "model_odds_team2": 1.98,
                            "series_format": "BO5",
                            "tournament_tier": "a",
                        },
                    ],
                    "page": 1,
                    "per_page": 10,
                    "total_items": 3,
                    "total_pages": 1,
                    "available_leagues": ["VCS", "LCK", "LEC"],
                },
                "live": {"items": [], "page": 1, "per_page": 20, "total_items": 0, "total_pages": 1},
                "bankroll": None,
                "active_bets": [],
                "power_rankings_preview": [],
                "refresh_status": {
                    "in_progress": False,
                    "progress": 0,
                    "stage": "",
                    "last_completed_at": None,
                    "next_scheduled_at": None,
                },
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()["upcoming"]
    assert [item["league_name"] for item in body["items"]] == ["LEC"]
    assert body["available_leagues"] == ["LEC"]
    assert body["total_items"] == 1


def test_homepage_bootstrap_includes_blocked_match_betting_statuses(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "bankroll",
            payload_json={
                "summary": {
                    "initial_balance": 1000.0,
                    "current_balance": 1000.0,
                    "win_rate_pct": 0.0,
                    "total_profit": 0.0,
                    "roi_pct": 0.0,
                },
                "active_bets": [],
                "match_betting_statuses": [
                    {
                        "pandascore_match_id": 4999,
                        "status": "blocked_missing_odds",
                        "reason_code": "missing_bookie_odds",
                        "short_detail": "NO THUNDERPICK MATCH",
                        "within_force_window": True,
                        "force_bet_after": "2026-03-22T16:00:00Z",
                    }
                ],
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["match_betting_statuses"][0]["status"] == "blocked_missing_odds"
    assert body["match_betting_statuses"][0]["reason_code"] == "missing_bookie_odds"
    assert body["match_betting_statuses"][0]["short_detail"] == "NO THUNDERPICK MATCH"
    assert body["match_betting_statuses"][0]["within_force_window"] is True


def test_homepage_bootstrap_prefers_current_match_betting_statuses_over_stale_manifest_values(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "bankroll",
            payload_json={
                "summary": {
                    "initial_balance": 1000.0,
                    "current_balance": 1000.0,
                    "win_rate_pct": 0.0,
                    "total_profit": 0.0,
                    "roi_pct": 0.0,
                },
                "active_bets": [],
                "match_betting_statuses": [
                    {
                        "pandascore_match_id": 5000,
                        "status": "blocked_prediction_unavailable",
                        "reason_code": "prediction_unavailable",
                        "within_force_window": True,
                        "force_bet_after": "2026-03-22T16:00:00Z",
                    }
                ],
            },
        )
    )
    db_session.add(
        create_api_snapshot(
            "homepage",
            payload_json={
                "generated_at": "2026-03-22T17:45:00Z",
                "upcoming": {"items": []},
                "live": {"items": []},
                "bankroll": {
                    "initial_balance": 1000.0,
                    "current_balance": 1000.0,
                    "win_rate_pct": 0.0,
                    "total_profit": 0.0,
                    "roi_pct": 0.0,
                },
                "active_bets": [],
                "match_betting_statuses": [],
                "power_rankings_preview": [],
                "refresh_status": {
                    "in_progress": False,
                    "progress": 0,
                    "stage": "",
                    "last_completed_at": None,
                    "next_scheduled_at": None,
                },
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert len(body["match_betting_statuses"]) == 1
    assert body["match_betting_statuses"][0]["status"] == "blocked_prediction_unavailable"
    assert body["match_betting_statuses"][0]["reason_code"] == "prediction_unavailable"


def test_homepage_bootstrap_prefers_current_active_bets_over_stale_manifest_values(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "bankroll",
            payload_json={
                "summary": {
                    "initial_balance": 1000.0,
                    "current_balance": 975.0,
                    "win_rate_pct": 0.0,
                    "total_profit": 0.0,
                    "roi_pct": 0.0,
                },
                "active_bets": [
                    {
                        "pandascore_match_id": 7001,
                        "bet_on": "Alpha",
                        "locked_odds": 2.2,
                        "stake": 25.0,
                    }
                ],
                "match_betting_statuses": [],
            },
        )
    )
    db_session.add(
        create_api_snapshot(
            "homepage",
            payload_json={
                "generated_at": "2026-03-22T17:45:00Z",
                "upcoming": {"items": []},
                "live": {"items": []},
                "bankroll": {
                    "initial_balance": 1000.0,
                    "current_balance": 975.0,
                    "win_rate_pct": 0.0,
                    "total_profit": 0.0,
                    "roi_pct": 0.0,
                },
                "active_bets": [
                    {
                        "pandascore_match_id": 9999,
                        "bet_on": "Stale",
                        "locked_odds": 9.9,
                        "stake": 99.0,
                    }
                ],
                "match_betting_statuses": [],
                "power_rankings_preview": [],
                "refresh_status": {
                    "in_progress": False,
                    "progress": 0,
                    "stage": "",
                    "last_completed_at": None,
                    "next_scheduled_at": None,
                },
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert len(body["active_bets"]) == 1
    assert body["active_bets"][0]["pandascore_match_id"] == 7001


def test_homepage_bootstrap_prefers_current_upcoming_snapshot_over_stale_manifest_upcoming(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "upcoming",
            payload_json={
                "items": [
                    {
                        "id": 4001,
                        "scheduled_at": "2026-03-29T10:00:00Z",
                        "league_name": "LPL",
                        "team1_name": "Team WE",
                        "team1_acronym": "WE",
                        "team2_name": "ThunderTalk Gaming",
                        "team2_acronym": "TT",
                        "stream_url": None,
                        "bookie_odds_team1": 1.38,
                        "bookie_odds_team2": 2.8,
                        "model_odds_team1": 1.29,
                        "model_odds_team2": 4.41,
                        "series_format": "BO3",
                        "tournament_tier": "s",
                    }
                ],
                "source_matches": [],
            },
        )
    )
    db_session.add(
        create_api_snapshot(
            "bankroll",
            payload_json={
                "summary": {
                    "initial_balance": 1000.0,
                    "current_balance": 1000.0,
                    "win_rate_pct": 0.0,
                    "total_profit": 0.0,
                    "roi_pct": 0.0,
                },
                "active_bets": [],
                "match_betting_statuses": [],
            },
        )
    )
    db_session.add(
        create_api_snapshot(
            "homepage",
            payload_json={
                "generated_at": "2026-03-28T22:00:00Z",
                "upcoming": {
                    "items": [
                        {
                            "id": 9999,
                            "scheduled_at": "2026-04-04T11:00:00Z",
                            "league_name": "LPL",
                            "team1_name": "Team WE",
                            "team2_name": "Ninjas in Pyjamas",
                            "series_format": "BO3",
                            "tournament_tier": "s",
                        }
                    ]
                },
                "live": {"items": []},
                "bankroll": {
                    "initial_balance": 1000.0,
                    "current_balance": 1000.0,
                    "win_rate_pct": 0.0,
                    "total_profit": 0.0,
                    "roi_pct": 0.0,
                },
                "active_bets": [],
                "match_betting_statuses": [],
                "power_rankings_preview": [],
                "refresh_status": {
                    "in_progress": False,
                    "progress": 0,
                    "stage": "",
                    "last_completed_at": None,
                    "next_scheduled_at": None,
                },
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert len(body["upcoming"]["items"]) == 1
    assert body["upcoming"]["items"][0]["id"] == 4001
    assert body["upcoming"]["items"][0]["team2_name"] == "ThunderTalk Gaming"


def test_homepage_bootstrap_includes_pending_match_betting_statuses(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "bankroll",
            payload_json={
                "summary": {
                    "initial_balance": 1000.0,
                    "current_balance": 1000.0,
                    "win_rate_pct": 0.0,
                    "total_profit": 0.0,
                    "roi_pct": 0.0,
                },
                "active_bets": [],
                "match_betting_statuses": [
                    {
                        "pandascore_match_id": 5001,
                        "status": "pending_force_bet",
                        "reason_code": "eligible_force_bet",
                        "within_force_window": True,
                        "force_bet_after": "2026-03-22T16:00:00Z",
                    }
                ],
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["match_betting_statuses"][0]["status"] == "pending_force_bet"
    assert body["match_betting_statuses"][0]["reason_code"] == "eligible_force_bet"


def test_homepage_bootstrap_falls_back_when_manifest_is_missing(
    client,
    db_session,
) -> None:
    from decimal import Decimal

    bankroll = create_bankroll(current_balance=Decimal("1060.00"))
    db_session.add(bankroll)
    db_session.flush()
    db_session.add(
        create_bet(
            bankroll.id,
            pandascore_match_id=5001,
            status="WON",
            actual_stake=Decimal("50.00"),
            profit_loss=Decimal("60.00"),
            placed_at=datetime.now(timezone.utc) - timedelta(hours=5),
            settled_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db_session.add(
        create_api_snapshot(
            "upcoming",
            payload_json={
                "items": [
                    {
                        "id": 4001,
                        "scheduled_at": "2026-03-22T18:00:00Z",
                        "league_name": "LCK",
                        "team1_name": "Alpha",
                        "team1_acronym": "ALP",
                        "team2_name": "Beta",
                        "team2_acronym": "BET",
                        "stream_url": None,
                        "bookie_odds_team1": 2.2,
                        "bookie_odds_team2": 1.7,
                        "model_odds_team1": 1.9,
                        "model_odds_team2": 2.05,
                        "series_format": "BO3",
                        "tournament_tier": "s",
                    }
                ]
            },
        )
    )
    db_session.add(create_api_snapshot("live", payload_json={"items": []}))
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert "results" not in body
    assert body["bankroll"]["current_balance"] == 1060.0
    assert body["section_status"]["homepage"]["source"] == "fallback_live"
    assert body["section_status"]["results"]["source"] == "fallback_live"


def test_homepage_bootstrap_prefers_current_bankroll_snapshot_over_stale_manifest_bankroll(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "bankroll",
            payload_json={
                "summary": {
                    "initial_balance": 1000.0,
                    "current_balance": 1060.0,
                    "win_rate_pct": 50.0,
                    "total_profit": 60.0,
                    "roi_pct": 20.0,
                },
                "active_bets": [],
                "match_betting_statuses": [],
            },
        )
    )
    db_session.add(
        create_api_snapshot(
            "homepage",
            payload_json={
                "generated_at": "2026-03-22T17:45:00Z",
                "bankroll": {
                    "initial_balance": 1000.0,
                    "current_balance": 900.0,
                    "win_rate_pct": 10.0,
                    "total_profit": -100.0,
                    "roi_pct": -10.0,
                },
                "upcoming": {"items": []},
                "live": {"items": []},
                "active_bets": [],
                "match_betting_statuses": [],
                "power_rankings_preview": [],
                "refresh_status": {
                    "in_progress": False,
                    "progress": 0,
                    "stage": "",
                    "last_completed_at": None,
                    "next_scheduled_at": None,
                },
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")
    bankroll_response = client.get("/api/v1/betting/bankroll")

    assert response.status_code == 200
    assert bankroll_response.status_code == 200
    assert response.json()["bankroll"]["current_balance"] == 1060.0
    assert response.json()["bankroll"] == bankroll_response.json()


def test_homepage_bootstrap_uses_existing_live_snapshot_when_upstream_is_degraded(
    client,
    db_session,
    monkeypatch,
) -> None:
    db_session.add(
        create_api_snapshot(
            "live",
            payload_json={
                "items": [
                    {
                        "id": 9001,
                        "scheduled_at": "2026-03-22T18:00:00Z",
                        "league_name": "LCK",
                        "team1_name": "Alpha",
                        "team2_name": "Beta",
                        "series_format": "BO3",
                        "series_score_team1": 1,
                        "series_score_team2": 0,
                        "match_status": "running",
                    }
                ]
            },
        )
    )
    db_session.commit()

    def _boom() -> dict[str, object]:
        raise PandaScoreUpstreamError(
            message="PandaScore upstream returned 500 for /lol/matches",
            path="/lol/matches",
            status_code=500,
            retryable=True,
        )

    monkeypatch.setattr("services.homepage_snapshots.build_live_snapshot_payload", _boom)

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["live"]["total_items"] == 1
    assert body["live"]["items"][0]["id"] == 9001
    assert body["section_status"]["live"]["source"] == "snapshot"


def test_homepage_bootstrap_live_ignores_stale_manifest_live_when_snapshot_exists(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "live",
            payload_json={
                "items": [
                    {
                        "id": 9001,
                        "scheduled_at": "2026-03-22T18:00:00Z",
                        "league_name": "LCK",
                        "team1_name": "Alpha",
                        "team2_name": "Beta",
                        "series_format": "BO3",
                        "series_score_team1": 1,
                        "series_score_team2": 0,
                    }
                ]
            },
        )
    )
    db_session.add(
        create_api_snapshot(
            "homepage",
            payload_json={
                "generated_at": "2026-03-22T18:05:00Z",
                "live": {
                    "items": [
                        {
                            "id": 1234,
                            "scheduled_at": "2026-03-22T17:00:00Z",
                            "league_name": "LEC",
                            "team1_name": "Old",
                            "team2_name": "Stale",
                            "series_format": "BO1",
                            "series_score_team1": 0,
                            "series_score_team2": 0,
                        }
                    ],
                    "page": 1,
                    "per_page": 20,
                    "total_items": 1,
                    "total_pages": 1,
                    "available_leagues": ["LEC"],
                },
            },
        )
    )
    db_session.commit()

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["live"]["total_items"] == 1
    assert body["live"]["items"][0]["id"] == 9001
    assert body["section_status"]["live"]["source"] == "snapshot"


def test_homepage_bootstrap_live_matches_live_endpoint_for_same_snapshot(
    client,
    db_session,
) -> None:
    db_session.add(
        create_api_snapshot(
            "live",
            payload_json={
                "items": [
                    {
                        "id": 9001,
                        "scheduled_at": "2026-03-22T18:00:00Z",
                        "league_name": "LCK",
                        "team1_name": "Alpha",
                        "team1_acronym": "ALP",
                        "team2_name": "Beta",
                        "team2_acronym": "BET",
                        "stream_url": None,
                        "bookie_odds_team1": 2.2,
                        "bookie_odds_team2": 1.7,
                        "model_odds_team1": 1.9,
                        "model_odds_team2": 2.05,
                        "series_format": "BO3",
                        "series_score_team1": 1,
                        "series_score_team2": 0,
                        "pre_match_odds_team1": 1.8,
                        "pre_match_odds_team2": 2.1,
                    }
                ]
            },
        )
    )
    db_session.add(
        create_api_snapshot(
            "homepage",
            payload_json={
                "generated_at": "2026-03-22T18:05:00Z",
                "live": {
                    "items": [],
                    "page": 1,
                    "per_page": 20,
                    "total_items": 0,
                    "total_pages": 1,
                    "available_leagues": [],
                },
            },
        )
    )
    db_session.commit()

    bootstrap_response = client.get("/api/v1/homepage/bootstrap")
    live_response = client.get("/api/v1/pandascore/lol/live-with-odds")

    assert bootstrap_response.status_code == 200
    assert live_response.status_code == 200
    assert bootstrap_response.json()["live"] == live_response.json()


def test_homepage_bootstrap_returns_empty_live_when_upstream_is_degraded_and_no_snapshot(
    client,
    monkeypatch,
) -> None:
    def _boom() -> dict[str, object]:
        raise PandaScoreUpstreamError(
            message="PandaScore upstream returned 500 for /lol/matches",
            path="/lol/matches",
            status_code=500,
            retryable=True,
        )

    monkeypatch.setattr("services.homepage_snapshots.build_live_snapshot_payload", _boom)

    response = client.get("/api/v1/homepage/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["live"]["total_items"] == 0
    assert body["section_status"]["live"]["source"] == "fallback_live"
    assert body["section_status"]["live"]["status"] == "missing"


def test_live_with_odds_returns_empty_payload_when_upstream_is_degraded(
    client,
    monkeypatch,
) -> None:
    def _boom() -> dict[str, object]:
        raise PandaScoreUpstreamError(
            message="PandaScore upstream returned 500 for /lol/matches",
            path="/lol/matches",
            status_code=500,
            retryable=True,
        )

    monkeypatch.setattr("services.homepage_snapshots.build_live_snapshot_payload", _boom)

    response = client.get("/api/v1/pandascore/lol/live-with-odds")

    assert response.status_code == 200
    assert response.json()["total_items"] == 0


def test_live_with_odds_still_raises_for_internal_errors(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "services.homepage_snapshots.build_live_snapshot_payload",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.get("/api/v1/pandascore/lol/live-with-odds")


def test_task_refresh_live_snapshot_returns_error_on_upstream_500(
    monkeypatch,
    db_session,
) -> None:
    def _boom() -> dict[str, object]:
        raise PandaScoreUpstreamError(
            message="PandaScore upstream returned 500 for /lol/matches",
            path="/lol/matches",
            status_code=500,
            retryable=True,
        )

    monkeypatch.setattr("tasks.build_live_snapshot_payload", _boom)

    result = task_refresh_live_snapshot.run()

    assert result["status"] == "error"
    assert "PandaScore upstream returned 500" in result["message"]
    snapshots = db_session.query(LiveWithOddsSnapshot).all()
    assert len(snapshots) == 1
    assert snapshots[0].status == "failed"
    assert snapshots[0].is_active is False


def test_is_degradable_upstream_error_only_matches_retryable_upstream_failures() -> None:
    assert is_degradable_upstream_error(
        PandaScoreUpstreamError(
            message="retryable",
            path="/lol/matches",
            status_code=500,
            retryable=True,
        )
    )
    assert not is_degradable_upstream_error(RuntimeError("boom"))
    assert not is_degradable_upstream_error(
        PandaScoreUpstreamError(
            message="non-retryable",
            path="/lol/matches",
            status_code=400,
            retryable=False,
        )
    )


def test_upcoming_with_odds_recomputes_when_active_model_changes(
    client,
    db_session,
) -> None:
    first_model = create_model_run(
        model_version="first",
        artifact_path="/tmp/first.xgb",
        is_active=True,
        created_at=datetime(2026, 3, 22, 17, 0, tzinfo=timezone.utc),
    )
    db_session.add(first_model)
    db_session.commit()

    db_session.add(
        create_api_snapshot(
            "upcoming",
            payload_json={
                "items": [
                    {
                        "id": 4001,
                        "scheduled_at": "2026-03-22T18:00:00Z",
                        "league_name": "LCK",
                        "team1_name": "Alpha",
                        "team1_acronym": "ALP",
                        "team2_name": "Beta",
                        "team2_acronym": "BET",
                        "stream_url": None,
                        "bookie_odds_team1": 2.2,
                        "bookie_odds_team2": 1.7,
                        "model_odds_team1": 1.1,
                        "model_odds_team2": 2.1,
                        "series_format": "BO3",
                        "tournament_tier": "s",
                    }
                ]
            },
            version="upcoming-first",
        )
    )
    db_session.commit()

    first_response = client.get(
        "/api/v1/pandascore/lol/upcoming-with-odds",
    )
    assert first_response.status_code == 200
    assert first_response.json()["items"][0]["model_odds_team1"] == approx(1.1, rel=1e-6)

    first_model.is_active = False
    second_model = create_model_run(
        model_version="second",
        artifact_path="/tmp/second.xgb",
        is_active=True,
        created_at=datetime(2026, 3, 22, 18, 0, tzinfo=timezone.utc),
    )
    db_session.add(second_model)
    db_session.add(
        create_api_snapshot(
            "upcoming",
            payload_json={
                "items": [
                    {
                        "id": 4001,
                        "scheduled_at": "2026-03-22T18:00:00Z",
                        "league_name": "LCK",
                        "team1_name": "Alpha",
                        "team1_acronym": "ALP",
                        "team2_name": "Beta",
                        "team2_acronym": "BET",
                        "stream_url": None,
                        "bookie_odds_team1": 2.2,
                        "bookie_odds_team2": 1.7,
                        "model_odds_team1": 1.2,
                        "model_odds_team2": 2.2,
                        "series_format": "BO3",
                        "tournament_tier": "s",
                    }
                ]
            },
            version="upcoming-second",
        )
    )
    db_session.commit()

    second_response = client.get(
        "/api/v1/pandascore/lol/upcoming-with-odds",
    )
    assert second_response.status_code == 200
    assert second_response.json()["items"][0]["model_odds_team1"] == approx(1.2, rel=1e-6)


def test_refresh_endpoints_report_locked_and_running_states(
    client,
    admin_headers,
    monkeypatch,
) -> None:
    locked_until = datetime.now(timezone.utc) + timedelta(minutes=2)
    monkeypatch.setattr(
        pandascore_api,
        "_get_manual_refresh_next_available",
        lambda: locked_until,
    )
    locked_response = client.get(
        "/api/v1/pandascore/odds-refresh-status",
    )
    assert locked_response.status_code == 403
    locked_response = client.get(
        "/api/v1/pandascore/odds-refresh-status",
        headers=admin_headers,
    )
    assert locked_response.status_code == 200
    assert locked_response.json() == {
        "allowed": False,
        "next_available_at": pandascore_api._datetime_to_iso(locked_until),
    }

    worker_module = types.ModuleType("worker")
    worker_module.celery_app = object()
    monkeypatch.setitem(sys.modules, "worker", worker_module)
    monkeypatch.setattr(pandascore_api, "get_current_task_id", lambda: "task-123")
    monkeypatch.setattr(pandascore_api, "get_last_completed_at", lambda: "2026-03-22T17:45:00Z")

    class DummyAsyncResult:
        def __init__(self, task_id: str, app: object) -> None:
            self.task_id = task_id
            self.app = app
            self.state = "PROGRESS"
            self.info = {"progress": 55, "stage": "refreshing_thunderpick"}

    monkeypatch.setattr(pandascore_api, "AsyncResult", DummyAsyncResult)

    global_response = client.get(
        "/api/v1/pandascore/odds-refresh-global-status",
    )
    assert global_response.status_code == 200
    assert global_response.json()["in_progress"] is True
    assert global_response.json()["progress"] == 55
    assert global_response.json()["stage"] == "refreshing_thunderpick"

    progress_response = client.get(
        "/api/v1/pandascore/refresh-odds-progress?task_id=task-123",
        headers=admin_headers,
    )
    assert progress_response.status_code == 200
    assert progress_response.json() == {
        "status": "running",
        "progress": 55,
        "stage": "refreshing_thunderpick",
        "done": False,
        "message": "",
    }


def test_refresh_odds_returns_accepted_when_pipeline_is_enqueued(
    client,
    admin_headers,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        pandascore_api,
        "_acquire_manual_refresh_slot",
        lambda: (True, datetime.now(timezone.utc)),
    )

    tasks_module = types.ModuleType("tasks")

    class DummyTask:
        @staticmethod
        def delay() -> types.SimpleNamespace:
            return types.SimpleNamespace(id="job-789")

    tasks_module.task_refresh_odds_pipeline = DummyTask()
    monkeypatch.setitem(sys.modules, "tasks", tasks_module)

    response = client.post("/api/v1/pandascore/refresh-odds", headers=admin_headers)

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "message": "Odds refresh pipeline started",
        "task_ids": ["job-789"],
    }


def test_task_refresh_odds_pipeline_refreshes_live_snapshot_before_homepage_manifest(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr("tasks._refresh_pipeline_acquire_slot", lambda task_id: True)
    monkeypatch.setattr("tasks.clear_current_task_id", lambda: None)
    monkeypatch.setattr("tasks.set_last_completed_at_now", lambda: None)
    monkeypatch.setattr("tasks.refresh_pandascore_upcoming", lambda: calls.append("pandascore") or {"status": "success"})
    monkeypatch.setattr("tasks.refresh_thunderpick_odds", lambda: calls.append("thunderpick") or {"status": "success"})
    monkeypatch.setattr("tasks.task_auto_place_bets", lambda: calls.append("auto_bets") or {"status": "success"})
    monkeypatch.setattr("tasks.task_refresh_upcoming_snapshot", lambda: calls.append("upcoming_snapshot") or {"status": "success"})
    monkeypatch.setattr(
        "tasks.task_refresh_results_and_bankroll_snapshot",
        lambda: calls.append("results_and_bankroll_snapshot") or {"status": "success"},
    )
    monkeypatch.setattr("tasks.task_refresh_live_snapshot", lambda: calls.append("live_snapshot") or {"status": "success"})
    monkeypatch.setattr("tasks.task_refresh_homepage_manifest", lambda: calls.append("homepage_manifest") or {"status": "success"})

    class DummyTaskSelf:
        request = types.SimpleNamespace(id="task-123")

        def update_state(self, *, state: str, meta: dict[str, object]) -> None:
            calls.append(f"state:{meta['stage']}")

    result = task_refresh_odds_pipeline.__wrapped__.__func__(DummyTaskSelf())

    assert result["status"] == "success"
    assert result["live_snapshot"] == {"status": "success"}
    assert calls.index("live_snapshot") < calls.index("homepage_manifest")


def test_task_settle_bets_refreshes_results_and_homepage_after_settlement(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "tasks.init_db",
        lambda: calls.append("init_db") or None,
    )

    class DummySession:
        def close(self) -> None:
            calls.append("session_close")

    monkeypatch.setattr("tasks.SessionLocal", lambda: DummySession())
    monkeypatch.setattr(
        "betting.bet_manager.settle_completed_bets",
        lambda session: calls.append("settle_completed_bets") or {"settled": 1, "won": 1, "lost": 0, "removed": 0, "profit": 12.5},
    )
    monkeypatch.setattr(
        "tasks.run_snapshot_refresh_after_settlement",
        lambda: calls.append("snapshot_refresh_after_settlement")
        or {
            "results_and_bankroll_snapshot": {"status": "success"},
            "homepage_manifest": {"status": "success"},
        },
    )
    monkeypatch.setattr(
        "tasks.task_verify_model_health",
        lambda: calls.append("model_health") or {"status": "success"},
    )

    from tasks import task_settle_bets

    result = task_settle_bets()

    assert result["status"] == "success"
    assert result["results_and_bankroll_snapshot"] == {"status": "success"}
    assert result["homepage_manifest"] == {"status": "success"}
    assert calls.index("settle_completed_bets") < calls.index("snapshot_refresh_after_settlement")
    assert calls.index("snapshot_refresh_after_settlement") < calls.index("model_health")


def test_run_snapshot_refresh_after_settlement_runs_snapshots_in_process(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "tasks.task_refresh_results_and_bankroll_snapshot",
        lambda: calls.append("results_bankroll") or {"status": "success", "rb": 1},
    )
    monkeypatch.setattr(
        "tasks.task_refresh_upcoming_snapshot",
        lambda: calls.append("upcoming") or {"status": "success"},
    )
    monkeypatch.setattr(
        "tasks.task_refresh_live_snapshot",
        lambda: calls.append("live") or {"status": "success"},
    )
    monkeypatch.setattr(
        "tasks.task_refresh_homepage_manifest",
        lambda: calls.append("homepage") or {"status": "success", "h": 1},
    )

    from tasks import run_snapshot_refresh_after_settlement

    out = run_snapshot_refresh_after_settlement()

    assert calls == ["results_bankroll", "upcoming", "live", "homepage"]
    assert out["results_and_bankroll_snapshot"] == {"status": "success", "rb": 1}
    assert out["homepage_manifest"] == {"status": "success", "h": 1}


def test_worker_schedule_runs_auto_place_and_settlement_every_two_minutes() -> None:
    from worker import celery_app

    auto_place_schedule = celery_app.conf.beat_schedule["auto-place-bets"]["schedule"]
    settle_schedule = celery_app.conf.beat_schedule["settle-bets"]["schedule"]
    repair_schedule = celery_app.conf.beat_schedule["repair-orphaned-bets"]["schedule"]

    assert str(auto_place_schedule) == "<crontab: */2 * * * * (m/h/dM/MY/d)>"
    assert str(settle_schedule) == "<crontab: */2 * * * * (m/h/dM/MY/d)>"
    assert str(repair_schedule) == "<crontab: */10 * * * * (m/h/dM/MY/d)>"


def test_task_repair_orphaned_bets_refreshes_snapshots_after_repair(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "tasks.init_db",
        lambda: calls.append("init_db") or None,
    )

    class DummySession:
        def close(self) -> None:
            calls.append("session_close")

    monkeypatch.setattr("tasks.SessionLocal", lambda: DummySession())
    monkeypatch.setattr(
        "betting.bet_manager.repair_orphaned_bets",
        lambda session: calls.append("repair_orphaned_bets") or {"repaired": 1, "voided": 0, "reconciled_balance_delta": 0.0},
    )
    monkeypatch.setattr(
        "tasks.task_refresh_results_and_bankroll_snapshot",
        lambda: calls.append("results_and_bankroll_snapshot") or {"status": "success"},
    )
    monkeypatch.setattr(
        "tasks.task_refresh_homepage_manifest",
        lambda: calls.append("homepage_manifest") or {"status": "success"},
    )

    from tasks import task_repair_orphaned_bets

    result = task_repair_orphaned_bets()

    assert result["status"] == "success"
    assert result["results"][0]["repaired"] == 1
    assert result["results_and_bankroll_snapshot"] == {"status": "success"}
    assert result["homepage_manifest"] == {"status": "success"}
    assert calls.index("repair_orphaned_bets") < calls.index("results_and_bankroll_snapshot")
    assert calls.index("results_and_bankroll_snapshot") < calls.index("homepage_manifest")


def test_load_active_model_falls_back_to_older_loadable_active_model(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    predictor_v2.clear_prediction_caches()
    broken = create_model_run(
        model_version="broken",
        artifact_path="/tmp/missing-model",
        is_active=True,
        created_at=datetime(2026, 3, 22, 18, 0, tzinfo=timezone.utc),
    )
    working_base = tmp_path / "xgboost_20260309_021820"
    working_base.with_suffix(".xgb").write_text("stub", encoding="utf-8")
    working_base.with_suffix(".meta").write_text("stub", encoding="utf-8")
    working = create_model_run(
        model_version="working",
        artifact_path=str(working_base),
        is_active=True,
        created_at=datetime(2026, 3, 22, 17, 0, tzinfo=timezone.utc),
    )
    db_session.add_all([broken, working])
    db_session.commit()

    def fake_load_xgboost(path):
        assert str(path) == str(working_base)
        return object(), ["feature_a"]

    monkeypatch.setattr(model_registry, "load_xgboost", fake_load_xgboost)

    loaded = predictor_v2._load_active_model(db_session)

    assert loaded is not None
    assert loaded["run_id"] == working.id
    assert loaded["artifact_path"] == str(working_base)


def test_persist_model_runs_deactivates_existing_active_models(db_session) -> None:
    existing = create_model_run(
        model_version="existing",
        artifact_path="/tmp/existing",
        is_active=True,
        created_at=datetime(2026, 3, 22, 16, 0, tzinfo=timezone.utc),
    )
    db_session.add(existing)
    db_session.commit()

    results = [
        {
            "model_type": "xgboost",
            "model_version": "new",
            "artifact_path": "/tmp/new",
            "is_active": True,
            "feature_names": ["feature_a"],
            "config": {"type": "xgboost"},
            "train_metrics": {"accuracy": 0.6, "log_loss": 0.5, "roc_auc": 0.7},
            "val_metrics": {"accuracy": 0.61, "log_loss": 0.49, "roc_auc": 0.71},
            "test_metrics": {"accuracy": 0.62, "log_loss": 0.48, "roc_auc": 0.72},
            "train_samples": 10,
            "val_samples": 5,
            "test_samples": 5,
        }
    ]

    run_ids = model_registry.persist_model_runs(db_session, results)

    active_ids = [
        run.id
        for run in db_session.query(pandascore_api.MLModelRun)
        .filter(pandascore_api.MLModelRun.is_active.is_(True))
        .order_by(pandascore_api.MLModelRun.id.asc())
        .all()
    ]

    assert run_ids
    assert active_ids == [run_ids[0]]


def test_persist_model_runs_retains_existing_active_model_when_candidate_underperforms(
    db_session,
) -> None:
    existing = create_model_run(
        model_version="existing",
        artifact_path="/tmp/existing",
        is_active=True,
        created_at=datetime(2026, 3, 22, 16, 0, tzinfo=timezone.utc),
    )
    existing.val_roc_auc = 0.76
    existing.val_log_loss = 0.42
    existing.test_accuracy = 0.68
    existing.test_roc_auc = 0.74
    existing.test_log_loss = 0.45
    db_session.add(existing)
    db_session.commit()

    results = [
        {
            "model_type": "xgboost",
            "model_version": "candidate",
            "artifact_path": "/tmp/candidate",
            "is_active": True,
            "feature_names": ["feature_a"],
            "config": {"type": "xgboost"},
            "train_metrics": {"accuracy": 0.61, "log_loss": 0.48, "roc_auc": 0.7},
            "val_metrics": {"accuracy": 0.62, "log_loss": 0.44, "roc_auc": 0.75},
            "test_metrics": {"accuracy": 0.66, "log_loss": 0.47, "roc_auc": 0.73},
            "train_samples": 10,
            "val_samples": 5,
            "test_samples": 5,
        }
    ]

    run_ids = model_registry.persist_model_runs(db_session, results)

    active_ids = [
        run.id
        for run in db_session.query(pandascore_api.MLModelRun)
        .filter(pandascore_api.MLModelRun.is_active.is_(True))
        .order_by(pandascore_api.MLModelRun.id.asc())
        .all()
    ]

    assert run_ids
    assert active_ids == [existing.id]

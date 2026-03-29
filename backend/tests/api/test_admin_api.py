from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.factories import create_api_snapshot, create_bankroll, create_bet


def test_runtime_status_reports_snapshot_and_model_mismatches(
    client,
    db_session,
    admin_headers,
    monkeypatch,
) -> None:
    from services import runtime_diagnostics

    bankroll = create_bankroll(current_balance=Decimal("925.00"))
    db_session.add(bankroll)
    db_session.flush()
    db_session.add(
        create_bet(
            bankroll.id,
            pandascore_match_id=111,
            status="WON",
            actual_stake=Decimal("75.00"),
            profit_loss=Decimal("-75.00"),
            placed_at=datetime.now(timezone.utc) - timedelta(hours=4),
            settled_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db_session.add(
        create_api_snapshot(
            "bankroll",
            payload_json={
                "summary": {
                    "initial_balance": 1000.0,
                    "current_balance": 925.0,
                    "win_rate_pct": 0.0,
                    "total_profit": -75.0,
                    "roi_pct": -100.0,
                },
                "active_bets": [],
            },
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        runtime_diagnostics,
        "get_prediction_runtime_status",
        lambda _session: {
            "active_model_id": None,
            "active_model_version": None,
            "active_model_path": None,
            "game_data_row_count": 1234,
        },
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "get_odds_attachment_status",
        lambda kind: {"kind": kind, "rows_with_model_odds": 0, "updated_at": "2026-03-22T17:45:00Z"},
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "read_thunderpick_scrape_status",
        lambda: {
            "dom_match_count": 0,
            "text_match_count": 20,
            "accepted_match_count": 19,
            "rejected_candidate_count": 3,
            "degraded_mode": True,
            "sample_matches": ["Team WE vs ThunderTalk Gaming"],
            "sample_rejections": [{"team1": "eam WE", "team2": "ThunderTalk Gaming", "reason": "midword_capture"}],
        },
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "get_upcoming_match_betting_statuses",
        lambda _session: [
            {
                "pandascore_match_id": 222,
                "status": "blocked_missing_odds",
                "reason_code": "missing_bookie_odds",
                "within_force_window": True,
            },
            {
                "pandascore_match_id": 223,
                "status": "waiting_for_better_odds",
                "reason_code": "below_edge_waiting",
                "within_force_window": True,
            },
        ],
    )

    response = client.get("/api/v1/admin/runtime-status", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["betting_state"]["settled_bets"] == 1
    assert body["snapshot_status"]["bankroll"]["snapshot_version"] == "bankroll-test-version"
    assert body["snapshot_status"]["results"]["snapshot_version"] is None
    assert body["odds_attachment_status"]["upcoming"]["rows_with_model_odds"] == 0
    assert body["thunderpick_scrape_status"]["degraded_mode"] is True
    assert body["force_window_blockers"]["blocked_matches"] == 1
    assert body["force_window_blockers"]["waiting_matches"] == 1
    assert body["force_window_blockers"]["blocked_by_reason"]["missing_bookie_odds"] == 1
    assert any("results snapshot is empty" in issue.lower() for issue in body["detected_issues"])
    assert any("no loadable active model" in issue.lower() for issue in body["detected_issues"])


def test_betting_diagnostics_endpoint_returns_summary_and_matches(
    client,
    admin_headers,
    monkeypatch,
) -> None:
    from api.v1 import admin as admin_api

    monkeypatch.setattr(
        admin_api,
        "get_match_betting_diagnostics",
        lambda session, **kwargs: {
            "summary": {
                "total_matches": 1,
                "by_status": {"waiting_for_better_odds": 1},
                "by_reason": {"below_edge_waiting": 1},
                "waiting_matches": 1,
                "blocked_matches": 0,
                "pending_matches": 0,
                "placed_matches": 0,
            },
            "matches": [
                {
                    "pandascore_match_id": 9301,
                    "scheduled_at": "2026-03-22T20:00:00Z",
                    "league": "LPL",
                    "team_a": "WE",
                    "team_b": "ThunderTalk",
                    "series_format": "BO3",
                    "status": "waiting_for_better_odds",
                    "reason_code": "below_edge_waiting",
                    "reason_detail": "Model edge is below the minimum threshold outside the force window.",
                    "short_detail": "EDGE 2.0% < 3.0%",
                    "within_force_window": False,
                    "force_bet_after": "2026-03-22T16:00:00Z",
                    "position_count": 0,
                    "diagnostics": {
                        "chosen_edge": 0.02,
                        "min_edge_threshold": 0.03,
                        "bookie_match_confidence": "exact",
                    },
                }
            ],
        },
    )

    response = client.get(
        "/api/v1/admin/betting/diagnostics?search=thundertalk",
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["waiting_matches"] == 1
    assert body["matches"][0]["team_a"] == "WE"
    assert body["matches"][0]["team_b"] == "ThunderTalk"
    assert body["matches"][0]["short_detail"] == "EDGE 2.0% < 3.0%"


def test_admin_debug_report_supports_json_and_text_output(
    client,
    admin_headers,
    monkeypatch,
) -> None:
    from api.v1 import admin as admin_api

    monkeypatch.setattr(
        admin_api,
        "build_operator_debug_payload",
        lambda session, **kwargs: {
            "generated_at": "2026-03-28T22:00:00Z",
            "runtime_status": {
                "detected_issues": ["No loadable active model is available in the API runtime."],
                "betting_state": {"total_bets": 12},
                "force_window_blockers": {"blocked_matches": 2},
            },
            "betting_diagnostics": {
                "summary": {"waiting_matches": 3, "pending_matches": 1},
                "matches": [
                    {
                        "pandascore_match_id": 9301,
                        "team_a": "WE",
                        "team_b": "ThunderTalk",
                        "status": "waiting_for_better_odds",
                        "short_detail": "EDGE 2.0% < 3.0%",
                        "diagnostics": {
                            "chosen_edge": 0.02,
                            "min_edge_threshold": 0.03,
                            "confidence": 0.53,
                            "ev": 0.0,
                            "bookie_match_confidence": "exact",
                        },
                    }
                ],
            },
            "component_checks": [
                {
                    "component": "model_runtime",
                    "status": "error",
                    "summary": "No model loaded in API runtime",
                }
            ],
            "recommendations": ["Promote or reload an active model before trusting any betting output."],
            "detected_issues": ["No loadable active model is available in the API runtime."],
        },
    )

    monkeypatch.setattr(
        admin_api,
        "render_operator_debug_report",
        lambda payload: "DRAFT GAP DEBUG REPORT\n- [ERROR] model_runtime: No model loaded in API runtime\n",
    )

    json_response = client.get("/api/v1/admin/debug-report", headers=admin_headers)

    assert json_response.status_code == 200
    json_body = json_response.json()
    assert json_body["component_checks"][0]["component"] == "model_runtime"
    assert json_body["betting_diagnostics"]["matches"][0]["team_a"] == "WE"

    text_response = client.get(
        "/api/v1/admin/debug-report?output=text",
        headers=admin_headers,
    )

    assert text_response.status_code == 200
    assert "text/plain" in text_response.headers["content-type"]
    assert "DRAFT GAP DEBUG REPORT" in text_response.text


def test_match_feed_compare_endpoint_returns_source_alignment_rows(
    client,
    admin_headers,
    monkeypatch,
) -> None:
    from api.v1 import admin as admin_api

    monkeypatch.setattr(
        admin_api,
        "build_match_feed_comparison_payload",
        lambda session, **kwargs: {
            "summary": {
                "homepage_visible_count": 1,
                "upcoming_snapshot_count": 1,
                "upcoming_source_match_count": 0,
                "betting_status_count": 0,
                "homepage_missing_betting_status_count": 1,
                "homepage_missing_source_match_count": 1,
                "rows_returned": 1,
                "mismatches_only": True,
            },
            "sources": {
                "homepage": {"generated_at": "2026-03-28T22:00:00Z", "visible_count": 1},
                "upcoming_snapshot": {"source": "snapshot", "item_count": 1},
                "upcoming_source_matches": {"source": "snapshot", "item_count": 0},
            },
            "matches": [
                {
                    "pandascore_match_id": 9301,
                    "scheduled_at": "2026-03-29T10:00:00Z",
                    "league": "LPL",
                    "team_a": "Team WE",
                    "team_b": "ThunderTalk Gaming",
                    "in_homepage_visible": True,
                    "in_upcoming_snapshot": True,
                    "in_upcoming_source_matches": False,
                    "in_betting_statuses": False,
                    "betting_status": None,
                    "reason_code": None,
                    "short_detail": None,
                    "discrepancy_codes": [
                        "homepage_missing_source_match",
                        "homepage_missing_betting_status",
                        "snapshot_missing_source_match",
                    ],
                }
            ],
        },
    )

    response = client.get(
        "/api/v1/admin/match-feed-compare?mismatches_only=true&search=thundertalk",
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["homepage_missing_betting_status_count"] == 1
    assert body["matches"][0]["team_b"] == "ThunderTalk Gaming"
    assert "homepage_missing_source_match" in body["matches"][0]["discrepancy_codes"]


def test_match_feed_compare_endpoint_uses_real_builder_without_500(
    client,
    admin_headers,
    monkeypatch,
) -> None:
    from services import runtime_diagnostics

    monkeypatch.setattr(
        runtime_diagnostics,
        "get_active_snapshot",
        lambda session, model: None,
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "build_homepage_bootstrap_payload",
        lambda session, homepage_snapshot=None: {
            "upcoming": {
                "items": [
                    {
                        "id": 1416688,
                        "scheduled_at": "2026-03-29T10:00:00Z",
                        "league_name": "Esports World Cup",
                        "team1_name": "Team WE",
                        "team2_name": "ThunderTalk Gaming",
                        "bookie_odds_team1": None,
                        "bookie_odds_team2": None,
                        "odds_source_kind": "missing",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "build_upcoming_items_with_fallback",
        lambda session, snapshot=None: (
            [
                {
                    "id": 1416688,
                    "scheduled_at": "2026-03-29T10:00:00Z",
                    "league_name": "Esports World Cup",
                    "team1_name": "Team WE",
                    "team2_name": "ThunderTalk Gaming",
                    "bookie_odds_team1": None,
                    "bookie_odds_team2": None,
                    "odds_source_kind": "missing",
                }
            ],
            {"source": "snapshot", "item_count": 1},
        ),
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "build_upcoming_matches_with_fallback",
        lambda session, snapshot=None: (
            [
                {
                    "id": 1416688,
                    "scheduled_at": "2026-03-29T10:00:00Z",
                    "league": {"name": "Esports World Cup"},
                    "opponents": [
                        {"opponent": {"name": "Team WE"}},
                        {"opponent": {"name": "ThunderTalk Gaming"}},
                    ],
                }
            ],
            {"source": "snapshot", "item_count": 1},
        ),
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "get_upcoming_match_betting_statuses",
        lambda session, matches=None: [],
    )
    monkeypatch.setattr(
        runtime_diagnostics,
        "classify_match_betting_eligibility",
        lambda match: {
            "is_bettable": True,
            "eligibility_reason": None,
            "normalized_identity": "esports world cup",
        },
    )

    response = client.get(
        "/api/v1/admin/match-feed-compare?mismatches_only=true&search=thundertalk",
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matches"][0]["team_b"] == "ThunderTalk Gaming"
    assert body["matches"][0]["is_bettable"] is True
    assert body["matches"][0]["odds_source_kind"] == "missing"
    assert "homepage_missing_betting_status" in body["matches"][0]["discrepancy_codes"]

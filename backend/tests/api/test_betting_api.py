from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from pytest import approx

from api.v1 import betting as betting_api
from betting import bet_manager
from entity_resolution.resolver import EntityResolver
from models_ml import Bet, BetEvent
from services.bookie import _build_market_catalog_from_page_text
from tests.factories import create_api_snapshot, create_bankroll, create_bet, create_model_run, create_snapshot


def test_betting_mutation_requires_admin_key(client) -> None:
    response = client.post("/api/v1/betting/settle")

    assert response.status_code == 403


def test_reset_trading_state_requires_admin_key(client) -> None:
    response = client.post("/api/v1/betting/trading-state/reset")
    assert response.status_code == 403


def test_reset_trading_state_clears_bets_events_and_resets_balance(
    client,
    db_session,
    admin_headers,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "tasks.run_snapshot_refresh_after_settlement",
        lambda: {},
    )
    bankroll = create_bankroll(current_balance=Decimal("500.00"))
    db_session.add(bankroll)
    db_session.flush()
    bet = create_bet(bankroll.id, pandascore_match_id=777001, status="WON")
    db_session.add(bet)
    db_session.flush()
    db_session.add(
        BetEvent(
            bankroll_id=bankroll.id,
            bet_id=bet.id,
            pandascore_match_id=777001,
            series_key=bet.series_key,
            event_type="settled",
        )
    )
    db_session.commit()

    response = client.post("/api/v1/betting/trading-state/reset", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["bets_deleted"] >= 1
    assert body["bet_events_deleted"] >= 1
    assert body["current_balance"] == float(bankroll.initial_balance)

    remaining_bets = db_session.query(Bet).filter(Bet.bankroll_id == bankroll.id).count()
    remaining_events = (
        db_session.query(BetEvent).filter(BetEvent.bankroll_id == bankroll.id).count()
    )
    assert remaining_bets == 0
    assert remaining_events == 0


def _finished_match_alpha_wins(match_id: int) -> dict:
    return {
        "id": match_id,
        "status": "finished",
        "winner": {"name": "Alpha", "id": 1},
        "opponents": [
            {"opponent": {"name": "Alpha", "id": 1}},
            {"opponent": {"name": "Beta", "id": 2}},
        ],
        "results": [
            {"team_id": 1, "score": 2},
            {"team_id": 2, "score": 1},
        ],
    }


def test_settle_completed_bets_settles_from_batch_without_past_feed(
    db_session,
    monkeypatch,
) -> None:
    from services import pandascore as pandascore_service

    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()
    mid = 884_001
    bet = create_bet(
        bankroll.id,
        pandascore_match_id=mid,
        status="PLACED",
        bet_on="Alpha",
        actual_stake=Decimal("50.00"),
        book_odds_locked=Decimal("2.0000"),
    )
    db_session.add(bet)
    db_session.commit()

    finished = _finished_match_alpha_wins(mid)

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_match_by_id", lambda m_id: finished if m_id == mid else None)
    monkeypatch.setattr(
        bet_manager,
        "fetch_lol_matches_by_ids_sync",
        lambda ids, **_: {mid: finished} if mid in ids else {},
    )

    def guard_no_past(path: str, params=None, token=None):
        if "past" in path:
            raise AssertionError("settlement must not depend on /past")
        return []

    monkeypatch.setattr(pandascore_service, "fetch_json_sync", guard_no_past)

    summary = bet_manager.settle_completed_bets(db_session)

    db_session.refresh(bet)
    db_session.refresh(bankroll)
    assert summary["settled"] == 1
    assert summary["won"] == 1
    assert bet.status == "WON"
    assert bankroll.current_balance > Decimal("950.00")


def test_settle_completed_bets_voids_canceled_match_without_forfeit(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()
    mid = 884_002
    bet = create_bet(
        bankroll.id,
        pandascore_match_id=mid,
        status="PLACED",
        actual_stake=Decimal("50.00"),
    )
    db_session.add(bet)
    db_session.commit()

    canceled = {
        "id": mid,
        "status": "canceled",
        "forfeit": False,
        "opponents": [
            {"opponent": {"name": "Alpha", "id": 1}},
            {"opponent": {"name": "Beta", "id": 2}},
        ],
        "results": [],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_match_by_id", lambda m_id: canceled if m_id == mid else None)
    monkeypatch.setattr(
        bet_manager,
        "fetch_lol_matches_by_ids_sync",
        lambda ids, **_: {mid: canceled} if mid in ids else {},
    )

    summary = bet_manager.settle_completed_bets(db_session)

    db_session.refresh(bet)
    db_session.refresh(bankroll)
    assert summary["voided"] >= 1
    assert bet.status == "VOID"
    assert bankroll.current_balance == Decimal("1000.00")


def test_settle_completed_bets_resolves_forfeit_winner_by_team_id(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()
    mid = 884_003
    bet = create_bet(
        bankroll.id,
        pandascore_match_id=mid,
        status="SETTLEMENT_PENDING",
        bet_on="Beta",
        actual_stake=Decimal("50.00"),
        book_odds_locked=Decimal("2.0000"),
        team_a="Alpha",
        team_b="Beta",
    )
    db_session.add(bet)
    db_session.commit()

    forfeit = {
        "id": mid,
        "status": "canceled",
        "forfeit": True,
        "winner": {"id": 2},
        "winner_id": 2,
        "opponents": [
            {"opponent": {"name": "Alpha", "id": 1}},
            {"opponent": {"name": "Beta", "id": 2}},
        ],
        "results": [
            {"team_id": 1, "score": 0},
            {"team_id": 2, "score": 1},
        ],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_match_by_id", lambda m_id: forfeit if m_id == mid else None)
    monkeypatch.setattr(
        bet_manager,
        "fetch_lol_matches_by_ids_sync",
        lambda ids, **_: {mid: forfeit} if mid in ids else {},
    )

    summary = bet_manager.settle_completed_bets(db_session)

    db_session.refresh(bet)
    assert summary["settled"] == 1
    assert summary["won"] == 1
    assert bet.status == "WON"


def test_settlement_preview_requires_admin_key(client) -> None:
    response = client.get("/api/v1/betting/settlement-preview")
    assert response.status_code == 403


def test_settlement_preview_returns_open_bets_and_matches(
    client,
    db_session,
    monkeypatch,
    admin_headers,
) -> None:
    bankroll = create_bankroll()
    db_session.add(bankroll)
    db_session.flush()
    mid = 884_004
    bet = create_bet(bankroll.id, pandascore_match_id=mid, status="PLACED")
    db_session.add(bet)
    db_session.commit()

    snap = _finished_match_alpha_wins(mid)
    monkeypatch.setattr(
        bet_manager,
        "fetch_lol_matches_by_ids_sync",
        lambda ids, **_: {mid: snap} if mid in ids else {},
    )

    response = client.get("/api/v1/betting/settlement-preview", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["open_bets"]) >= 1
    assert any(row["pandascore_match_id"] == mid for row in body["open_bets"])
    assert str(mid) in body["matches_by_id"]
    assert body["matches_by_id"][str(mid)]["status"] == "finished"


def test_betting_endpoints_return_expected_aggregates(
    client,
    db_session,
) -> None:
    now = datetime.now(timezone.utc)

    bankroll = create_bankroll(current_balance=Decimal("925.00"))
    db_session.add(bankroll)
    db_session.flush()

    db_session.add(
        create_snapshot(
            bankroll.id,
            balance=Decimal("925.00"),
            peak_balance=Decimal("1200.00"),
            total_bets=4,
            wins=1,
            losses=1,
        )
    )

    db_session.add_all(
        [
          create_bet(
              bankroll.id,
              pandascore_match_id=101,
              league="LCK",
              status="PLACED",
              actual_stake=Decimal("50.00"),
              edge=Decimal("0.12000"),
              placed_at=now - timedelta(hours=4),
          ),
          create_bet(
              bankroll.id,
              pandascore_match_id=102,
              league="Unknown Invitational",
              status="PLACED",
              actual_stake=Decimal("25.00"),
              edge=Decimal("0.08000"),
              placed_at=now - timedelta(hours=3),
          ),
          create_bet(
              bankroll.id,
              pandascore_match_id=103,
              league="LCK",
              status="WON",
              actual_stake=Decimal("100.00"),
              book_odds_locked=Decimal("2.0000"),
              edge=Decimal("0.20000"),
              profit_loss=Decimal("100.00"),
              placed_at=now - timedelta(hours=6),
              settled_at=now - timedelta(hours=2),
          ),
          create_bet(
              bankroll.id,
              pandascore_match_id=104,
              league="LEC",
              team_a="Delta",
              team_b="Echo",
              bet_on="Echo",
              status="LOST",
              actual_stake=Decimal("75.00"),
              book_odds_locked=Decimal("1.8000"),
              edge=Decimal("0.04000"),
              profit_loss=Decimal("-75.00"),
              placed_at=now - timedelta(hours=5),
              settled_at=now - timedelta(hours=1),
          ),
        ]
    )
    db_session.commit()

    bankroll_response_payload = {
        "summary": {
            "initial_balance": 1000.0,
            "current_balance": 925.0,
            "win_rate_pct": 50.0,
            "total_profit": 25.0,
            "roi_pct": 14.28571,
        },
        "active_bets": [
            {
                "pandascore_match_id": 101,
                "bet_on": "Alpha",
                "locked_odds": 2.2,
                "stake": 50.0,
            }
        ],
    }
    results_snapshot_payload = {
        "items": [
            {
                "id": "result-lost",
                "betDateTime": str(now - timedelta(hours=5)),
                "league": "LEC",
                "team1": "Delta",
                "team2": "Echo",
                "betOn": "Echo",
                "lockedOdds": 1.8,
                "stake": 75.0,
                "result": "LOST",
                "profit": -75.0,
            },
            {
                "id": "result-won",
                "betDateTime": str(now - timedelta(hours=6)),
                "league": "LCK",
                "team1": "Alpha",
                "team2": "Beta",
                "betOn": "Alpha",
                "lockedOdds": 2.0,
                "stake": 100.0,
                "result": "WON",
                "profit": 100.0,
            },
        ]
    }
    db_session.add(create_api_snapshot("bankroll", payload_json=bankroll_response_payload))
    db_session.add(create_api_snapshot("results", payload_json=results_snapshot_payload))
    db_session.commit()

    bankroll_response = client.get("/api/v1/betting/bankroll")
    assert bankroll_response.status_code == 200
    assert bankroll_response.json() == {
        "initial_balance": 1000.0,
        "current_balance": 925.0,
        "win_rate_pct": 50.0,
        "total_profit": 25.0,
        "roi_pct": approx(14.28571, rel=1e-5),
    }

    active_response = client.get("/api/v1/betting/bets/active")
    assert active_response.status_code == 200
    assert active_response.json() == [
        {
            "pandascore_match_id": 101,
            "bet_on": "Alpha",
            "locked_odds": 2.2,
            "stake": 50.0,
        }
    ]

    results_response = client.get("/api/v1/betting/results?per_page=10&page=1")
    assert results_response.status_code == 200
    results_body = results_response.json()
    assert results_body["total_items"] == 2
    assert results_body["available_leagues"] == ["LCK", "LEC"]
    assert results_body["items"][0]["team1"] == "Delta"
    assert results_body["items"][0]["result"] == "LOST"
    assert results_body["items"][0]["profit"] == -75.0
    assert results_body["items"][1]["team1"] == "Alpha"
    assert results_body["items"][1]["result"] == "WON"

    analytics_response = client.get("/api/v1/betting/results/analytics?league=LCK")
    assert analytics_response.status_code == 200
    analytics_body = analytics_response.json()
    assert analytics_body["summary"]["settled"] == 1
    assert analytics_body["summary"]["total_profit"] == 100.0
    assert analytics_body["available_leagues"] == ["LCK", "LEC"]

    summary_response = client.get("/api/v1/betting/summary")
    assert summary_response.status_code == 200
    summary_body = summary_response.json()
    assert summary_body["total_bets"] == 4
    assert summary_body["settled_bets"] == 2
    assert summary_body["wins"] == 1
    assert summary_body["losses"] == 1
    assert summary_body["total_profit"] == 25.0
    assert summary_body["avg_edge_pct"] == approx(11.0, rel=1e-6)
    assert summary_body["avg_odds"] == approx(2.05, rel=1e-6)


def test_missing_open_bets_are_marked_orphaned_without_refund(
    client,
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("900.00"))
    model_run = create_model_run()
    db_session.add(bankroll)
    db_session.add(model_run)
    db_session.flush()

    db_session.add_all(
        [
                create_bet(
                    bankroll.id,
                    pandascore_match_id=201,
                    status="PLACED",
                    model_run_id=model_run.id,
                ),
                create_bet(
                    bankroll.id,
                    pandascore_match_id=202,
                    status="PLACED",
                    team_a="Ghost",
                    team_b="Phantom",
                    model_run_id=model_run.id,
                    actual_stake=Decimal("40.00"),
                ),
                create_bet(
                    bankroll.id,
                    pandascore_match_id=301,
                    status="WON",
                    model_run_id=model_run.id,
                    actual_stake=Decimal("50.00"),
                    profit_loss=Decimal("60.00"),
                    closing_odds=Decimal("2.0000"),
                placed_at=datetime.now(timezone.utc) - timedelta(hours=5),
                settled_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
                create_bet(
                    bankroll.id,
                    pandascore_match_id=302,
                    status="LOST",
                    model_run_id=model_run.id,
                    actual_stake=Decimal("40.00"),
                    profit_loss=Decimal("-40.00"),
                    closing_odds=Decimal("2.5000"),
                placed_at=datetime.now(timezone.utc) - timedelta(hours=4),
                settled_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(
        bet_manager,
        "fetch_json_sync",
        lambda path, params=None: [] if path == "/lol/matches" else [],
    )
    monkeypatch.setattr(
        bet_manager,
        "read_upcoming_matches_from_file",
        lambda: [],
    )
    monkeypatch.setattr(
        bet_manager,
        "_fetch_match_by_id",
        lambda match_id: None if match_id == 202 else {"id": match_id, "status": "running"},
    )

    db_session.add(
        create_api_snapshot(
            "bankroll",
            payload_json={
                "summary": {
                    "initial_balance": 1000.0,
                    "current_balance": 900.0,
                    "win_rate_pct": 50.0,
                    "total_profit": 20.0,
                    "roi_pct": 22.22,
                },
                "active_bets": [],
            },
        )
    )
    db_session.commit()

    open_status_response = client.get("/api/v1/betting/bets/open-status")
    assert open_status_response.status_code == 200
    assert open_status_response.json() == []

    db_session.refresh(bankroll)
    assert bankroll.current_balance == Decimal("900.00")
    orphaned_bet = db_session.query(betting_api.Bet).filter_by(pandascore_match_id=202).one()
    assert orphaned_bet.status == "ORPHANED_FEED"
    tracked_bet = db_session.query(betting_api.Bet).filter_by(pandascore_match_id=201).one()
    assert tracked_bet.pandascore_match_id == 201

    evaluation_response = client.get("/api/v1/betting/models/evaluation")
    assert evaluation_response.status_code == 200
    body = evaluation_response.json()
    assert body[0]["model_run_id"] == model_run.id
    assert body[0]["settled_bets"] == 2
    assert body[0]["wins"] == 1
    assert body[0]["losses"] == 1
    assert body[0]["realized_roi_pct"] == approx(22.22222, rel=1e-5)
    assert body[0]["edge_calibration"]


def test_results_endpoint_falls_back_to_live_bets_when_snapshot_missing(
    client,
    db_session,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("1085.00"))
    db_session.add(bankroll)
    db_session.flush()
    db_session.add(
        create_bet(
            bankroll.id,
            pandascore_match_id=909,
            league="LCK",
            status="WON",
            actual_stake=Decimal("40.00"),
            profit_loss=Decimal("85.00"),
            placed_at=datetime.now(timezone.utc) - timedelta(hours=6),
            settled_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db_session.commit()

    response = client.get("/api/v1/betting/results?per_page=10&page=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["league"] == "LCK"
    assert body["items"][0]["result"] == "WON"
    assert body["items"][0]["profit"] == 85.0


def test_active_series_endpoint_groups_multiple_positions_for_same_match(
    client,
    db_session,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("900.00"))
    db_session.add(bankroll)
    db_session.flush()
    db_session.add_all(
        [
            create_bet(
                bankroll.id,
                pandascore_match_id=777,
                status="PLACED",
                actual_stake=Decimal("25.00"),
            ),
            create_bet(
                bankroll.id,
                pandascore_match_id=777,
                status="LIVE",
                actual_stake=Decimal("30.00"),
                recommended_stake=Decimal("30.00"),
                bet_on="Beta",
                book_odds_locked=Decimal("2.4000"),
                edge=Decimal("0.19000"),
                model_prob=Decimal("0.62000"),
                book_prob_adj=Decimal("0.43000"),
                ev=Decimal("6.0000"),
                placed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            ),
        ]
    )
    db_session.flush()
    latest = db_session.query(betting_api.Bet).filter_by(status="LIVE").one()
    latest.series_key = "ps:777"
    latest.bet_sequence = 2
    latest.entry_phase = "live_mid_series"
    latest.entry_score_team_a = 1
    latest.entry_score_team_b = 0
    first = db_session.query(betting_api.Bet).filter_by(status="PLACED").one()
    first.series_key = "ps:777"
    first.bet_sequence = 1
    db_session.commit()

    response = client.get("/api/v1/betting/bets/active-series")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["series_key"] == "ps:777"
    assert body[0]["position_count"] == 2
    assert body[0]["total_exposure"] == 55.0
    assert body[0]["latest_position"]["bet_sequence"] == 2


def test_repair_orphaned_endpoint_restores_open_bet_when_match_returns(
    client,
    db_session,
    admin_headers,
    monkeypatch,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()
    bet = create_bet(
        bankroll.id,
        pandascore_match_id=888,
        status="ORPHANED_FEED",
        actual_stake=Decimal("50.00"),
    )
    bet.feed_health_status = "missing"
    db_session.add(bet)
    db_session.commit()

    monkeypatch.setattr(
        bet_manager,
        "_fetch_match_by_id",
        lambda match_id: {"id": match_id, "status": "running", "results": [], "opponents": []},
    )

    response = client.post("/api/v1/betting/bets/repair-orphaned", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["repaired"] == 1
    db_session.refresh(bet)
    assert bet.status == "LIVE"


def test_refund_missing_open_bets_voids_prematch_bet_when_odds_disappear(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()

    bet = create_bet(
        bankroll.id,
        pandascore_match_id=9901,
        status="PLACED",
        actual_stake=Decimal("50.00"),
    )
    db_session.add(bet)
    db_session.commit()

    upcoming_match = {
        "id": 9901,
        "status": "not_started",
        "scheduled_at": "2026-03-29T20:00:00Z",
        "opponents": [
            {"opponent": {"name": "Alpha", "acronym": "ALP", "id": 1}},
            {"opponent": {"name": "Beta", "acronym": "BET", "id": 2}},
        ],
        "results": [],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [upcoming_match])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])
    monkeypatch.setattr(
        bet_manager,
        "read_market_catalog_from_file",
        lambda: {
            "version": 2,
            "source_book": "thunderpick",
            "scraped_at": "2026-03-29T19:00:00Z",
            "matches": [
                {
                    "team1": "Other Team",
                    "team2": "Another Team",
                    "offers": [
                        {
                            "source_book": "thunderpick",
                            "market_type": "match_winner",
                            "selection_key": "team1",
                            "line_value": None,
                            "decimal_odds": 1.9,
                            "market_status": "available",
                            "scraped_at": "2026-03-29T19:00:00Z",
                            "source_market_name": "Match Winner",
                            "source_selection_name": "Other Team",
                            "source_payload_json": None,
                        }
                    ],
                }
            ],
        },
    )

    summary = bet_manager.refund_and_delete_missing_open_bets(db_session)

    assert summary["voided"] == 1
    db_session.refresh(bankroll)
    db_session.refresh(bet)
    assert bankroll.current_balance == Decimal("1000.00")
    assert bet.status == "VOID"
    assert bet.feed_health_status == "cancelled"
    assert bet.odds_source_status == "missing"
    assert bet.profit_loss == Decimal("0.00")
    assert bet.settled_at is not None

    refund_event = (
        db_session.query(BetEvent)
        .filter(BetEvent.bet_id == bet.id, BetEvent.event_type == "wallet_void_refund")
        .one()
    )
    assert refund_event.payload_json == {"reason": "odds_removed_before_start"}


def test_refund_missing_open_bets_keeps_bet_with_live_history_when_odds_disappear(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()

    bet = create_bet(
        bankroll.id,
        pandascore_match_id=9902,
        status="ORPHANED_FEED",
        actual_stake=Decimal("50.00"),
    )
    db_session.add(bet)
    db_session.flush()
    db_session.add(
        BetEvent(
            bankroll_id=bankroll.id,
            bet_id=bet.id,
            pandascore_match_id=bet.pandascore_match_id,
            series_key=bet.series_key,
            event_type="live_started",
        )
    )
    db_session.commit()

    upcoming_match = {
        "id": 9902,
        "status": "not_started",
        "scheduled_at": "2026-03-29T20:00:00Z",
        "opponents": [
            {"opponent": {"name": "Alpha", "acronym": "ALP", "id": 1}},
            {"opponent": {"name": "Beta", "acronym": "BET", "id": 2}},
        ],
        "results": [],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [upcoming_match])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])
    monkeypatch.setattr(
        bet_manager,
        "read_market_catalog_from_file",
        lambda: {
            "version": 2,
            "source_book": "thunderpick",
            "scraped_at": "2026-03-29T19:00:00Z",
            "matches": [
                {
                    "team1": "Other Team",
                    "team2": "Another Team",
                    "offers": [
                        {
                            "source_book": "thunderpick",
                            "market_type": "match_winner",
                            "selection_key": "team1",
                            "line_value": None,
                            "decimal_odds": 1.9,
                            "market_status": "available",
                            "scraped_at": "2026-03-29T19:00:00Z",
                            "source_market_name": "Match Winner",
                            "source_selection_name": "Other Team",
                            "source_payload_json": None,
                        }
                    ],
                }
            ],
        },
    )

    summary = bet_manager.refund_and_delete_missing_open_bets(db_session)

    assert summary["voided"] == 0
    db_session.refresh(bankroll)
    db_session.refresh(bet)
    assert bankroll.current_balance == Decimal("950.00")
    assert bet.status == "PLACED"
    assert bet.feed_health_status == "tracked"


def test_refund_missing_open_bets_marks_settlement_pending_when_finished_still_in_upcoming_file(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()
    mid = 9905
    bet = create_bet(
        bankroll.id,
        pandascore_match_id=mid,
        status="LIVE",
        actual_stake=Decimal("50.00"),
    )
    db_session.add(bet)
    db_session.commit()

    stale_upcoming_row = _finished_match_alpha_wins(mid)

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [stale_upcoming_row])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])

    summary = bet_manager.refund_and_delete_missing_open_bets(db_session)

    db_session.refresh(bet)
    assert summary["pending"] == 1
    assert bet.status == "SETTLEMENT_PENDING"
    assert bet.feed_health_status == "tracked"


def test_settle_completed_bets_settles_when_match_status_is_completed(
    db_session,
    monkeypatch,
) -> None:
    from services import pandascore as pandascore_service

    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()
    mid = 884_010
    bet = create_bet(
        bankroll.id,
        pandascore_match_id=mid,
        status="PLACED",
        bet_on="Alpha",
        actual_stake=Decimal("50.00"),
        book_odds_locked=Decimal("2.0000"),
    )
    db_session.add(bet)
    db_session.commit()

    completed = {**_finished_match_alpha_wins(mid), "status": "completed"}

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_match_by_id", lambda m_id: completed if m_id == mid else None)
    monkeypatch.setattr(
        bet_manager,
        "fetch_lol_matches_by_ids_sync",
        lambda ids, **_: {mid: completed} if mid in ids else {},
    )

    def guard_no_past(path: str, params=None, token=None):
        if "past" in path:
            raise AssertionError("settlement must not depend on /past")
        return []

    monkeypatch.setattr(pandascore_service, "fetch_json_sync", guard_no_past)

    summary = bet_manager.settle_completed_bets(db_session)

    db_session.refresh(bet)
    assert summary["settled"] == 1
    assert summary["won"] == 1
    assert bet.status == "WON"


def test_settle_completed_bets_voids_cancelled_spelling_without_forfeit(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll(current_balance=Decimal("950.00"))
    db_session.add(bankroll)
    db_session.flush()
    mid = 884_011
    bet = create_bet(
        bankroll.id,
        pandascore_match_id=mid,
        status="PLACED",
        actual_stake=Decimal("50.00"),
    )
    db_session.add(bet)
    db_session.commit()

    cancelled = {
        "id": mid,
        "status": "cancelled",
        "forfeit": False,
        "opponents": [
            {"opponent": {"name": "Alpha", "id": 1}},
            {"opponent": {"name": "Beta", "id": 2}},
        ],
        "results": [],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_match_by_id", lambda m_id: cancelled if m_id == mid else None)
    monkeypatch.setattr(
        bet_manager,
        "fetch_lol_matches_by_ids_sync",
        lambda ids, **_: {mid: cancelled} if mid in ids else {},
    )

    summary = bet_manager.settle_completed_bets(db_session)

    db_session.refresh(bet)
    db_session.refresh(bankroll)
    assert summary["voided"] >= 1
    assert bet.status == "VOID"
    assert bankroll.current_balance == Decimal("1000.00")


def test_get_open_bet_schedule_statuses_returns_scheduled_upcoming_rows(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll()
    db_session.add(bankroll)
    db_session.flush()
    mid = 9910
    bet = create_bet(
        bankroll.id,
        pandascore_match_id=mid,
        status="PLACED",
        league="LCK",
    )
    db_session.add(bet)
    db_session.commit()

    upcoming_row = {
        "id": mid,
        "status": "not_started",
        "scheduled_at": "2026-03-29T20:00:00Z",
        "opponents": [
            {"opponent": {"name": "Alpha", "id": 1}},
            {"opponent": {"name": "Beta", "id": 2}},
        ],
        "results": [],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [upcoming_row])
    monkeypatch.setattr(bet_manager, "_fetch_running_matches", lambda: [])
    monkeypatch.setattr(bet_manager, "_fetch_match_by_id", lambda _mid: None)

    rows = bet_manager.get_open_bet_schedule_statuses(db_session)

    assert len(rows) == 1
    assert rows[0]["pandascore_match_id"] == mid
    assert rows[0]["schedule_status"] == "scheduled_upcoming"


def test_build_upcoming_snapshot_payload_excludes_finished_matches(monkeypatch) -> None:
    from api.v1 import pandascore as pandascore_api
    from services.homepage_snapshots import build_upcoming_snapshot_payload

    keep = {
        "id": 501,
        "status": "not_started",
        "scheduled_at": "2026-03-29T20:00:00Z",
        "league": {"name": "LCK", "slug": "lck"},
        "opponents": [
            {"opponent": {"name": "Alpha", "acronym": "ALP", "id": 1}},
            {"opponent": {"name": "Beta", "acronym": "BET", "id": 2}},
        ],
        "results": [],
    }
    drop = _finished_match_alpha_wins(502)

    monkeypatch.setattr(pandascore_api, "read_upcoming_matches_from_file", lambda: [keep, drop])
    captured: list[list[dict[str, object]]] = []

    def fake_build(matches: list[dict[str, object]]) -> list[dict[str, object]]:
        captured.append(list(matches))
        out: list[dict[str, object]] = []
        for m in matches:
            row = dict(m)
            row["series_format"] = "BO3"
            row["markets"] = []
            row["bookie_odds_team1"] = None
            row["bookie_odds_team2"] = None
            row["bookie_odds_status_team1"] = "missing"
            row["bookie_odds_status_team2"] = "missing"
            row["odds_source_kind"] = None
            row["odds_source_status"] = None
            row["model_odds_team1"] = None
            row["model_odds_team2"] = None
            row["recommended_bet"] = None
            row["streams_list"] = []
            out.append(row)
        return out

    monkeypatch.setattr(pandascore_api, "_build_upcoming_with_odds_from_matches", fake_build)

    payload = build_upcoming_snapshot_payload()

    assert len(captured) == 1
    assert len(captured[0]) == 1
    assert captured[0][0]["id"] == 501
    assert len(payload["source_matches"]) == 1
    assert payload["source_matches"][0]["id"] == 501
    assert len(payload["items"]) == 1


def test_get_upcoming_match_betting_statuses_marks_waiting_matches(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll()
    db_session.add(bankroll)
    db_session.commit()

    match = {
        "id": 9001,
        "scheduled_at": "2026-03-22T20:00:00Z",
        "league": {"name": "LCK", "slug": "lck"},
        "tournament": {"tier": "s"},
        "number_of_games": 3,
        "opponents": [
            {"opponent": {"name": "Alpha", "acronym": "ALP", "id": 1}},
            {"opponent": {"name": "Beta", "acronym": "BET", "id": 2}},
        ],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [match])
    monkeypatch.setattr("ml.predictor_v2.get_prediction_runtime_status", lambda session: {"active_model_id": 1})
    monkeypatch.setattr(
        bet_manager,
        "_evaluate_match_for_betting",
        lambda *args, **kwargs: {
            "pandascore_match_id": 9001,
            "team_a": "Alpha",
            "team_b": "Beta",
            "chosen_team": "Alpha",
            "chosen_model_prob": Decimal("0.52"),
            "chosen_book_prob": Decimal("0.50"),
            "chosen_book_odds": Decimal("2.2000"),
            "chosen_edge": Decimal("0.02000"),
            "stake": Decimal("25.00"),
            "ev": Decimal("1.0000"),
            "model_run_id": None,
            "number_of_games": 3,
            "force_bet_after": datetime.now(timezone.utc) + timedelta(hours=2),
            "within_force_window": False,
            "should_force_bet": False,
        },
    )

    statuses = bet_manager.get_upcoming_match_betting_statuses(db_session)

    assert len(statuses) == 1
    assert statuses[0]["pandascore_match_id"] == 9001
    assert statuses[0]["status"] == "waiting_for_better_odds"
    assert statuses[0]["reason_code"] == "below_edge_waiting"
    assert statuses[0]["short_detail"] == "EDGE 2.0% < 3.0%"
    assert statuses[0]["force_bet_after"] is not None


def test_get_upcoming_match_betting_statuses_marks_blocked_matches(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll()
    db_session.add(bankroll)
    db_session.commit()

    match = {
        "id": 9002,
        "scheduled_at": "2026-03-22T20:00:00Z",
        "league": {"name": "LCK", "slug": "lck"},
        "tournament": {"tier": "s"},
        "number_of_games": 3,
        "opponents": [
            {"opponent": {"name": "Alpha", "acronym": "ALP", "id": 1}},
            {"opponent": {"name": "Beta", "acronym": "BET", "id": 2}},
        ],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [match])
    monkeypatch.setattr("ml.predictor_v2.get_prediction_runtime_status", lambda session: {"active_model_id": 1})
    monkeypatch.setattr(
        bet_manager,
        "_evaluate_match_for_betting",
        lambda *args, **kwargs: {
            "pandascore_match_id": 9002,
            "status": "blocked_missing_odds",
            "reason_code": "missing_bookie_odds",
            "within_force_window": True,
            "force_bet_after": datetime.now(timezone.utc) - timedelta(minutes=15),
        },
    )

    statuses = bet_manager.get_upcoming_match_betting_statuses(db_session)

    assert len(statuses) == 1
    assert statuses[0]["status"] == "blocked_missing_odds"
    assert statuses[0]["reason_code"] == "missing_bookie_odds"
    assert statuses[0]["short_detail"] == "NO THUNDERPICK MATCH"
    assert statuses[0]["within_force_window"] is True


def test_get_upcoming_match_betting_statuses_marks_pending_matches(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll()
    db_session.add(bankroll)
    db_session.commit()

    match = {
        "id": 9003,
        "scheduled_at": "2026-03-22T20:00:00Z",
        "league": {"name": "LCK", "slug": "lck"},
        "tournament": {"tier": "s"},
        "number_of_games": 3,
        "opponents": [
            {"opponent": {"name": "Alpha", "acronym": "ALP", "id": 1}},
            {"opponent": {"name": "Beta", "acronym": "BET", "id": 2}},
        ],
    }

    monkeypatch.setattr(bet_manager, "read_upcoming_matches_from_file", lambda: [match, {**match, "id": 9004}])
    monkeypatch.setattr("ml.predictor_v2.get_prediction_runtime_status", lambda session: {"active_model_id": 1})

    def fake_evaluate(*args, **kwargs):
        current_match = args[3]
        if int(current_match["id"]) == 9003:
            return {
                "pandascore_match_id": 9003,
                "team_a": "Alpha",
                "team_b": "Beta",
                "chosen_team": "Alpha",
                "chosen_model_prob": Decimal("0.55"),
                "chosen_book_prob": Decimal("0.50"),
                "chosen_book_odds": Decimal("2.2000"),
                "chosen_edge": Decimal("0.05000"),
                "stake": Decimal("25.00"),
                "ev": Decimal("2.0000"),
                "model_run_id": None,
                "number_of_games": 3,
                "force_bet_after": datetime.now(timezone.utc) + timedelta(hours=2),
                "within_force_window": False,
                "should_force_bet": False,
            }
        return {
            "pandascore_match_id": 9004,
            "team_a": "Gamma",
            "team_b": "Delta",
            "chosen_team": "Gamma",
            "chosen_model_prob": Decimal("0.50"),
            "chosen_book_prob": Decimal("0.50"),
            "chosen_book_odds": Decimal("2.1000"),
            "chosen_edge": Decimal("0.00000"),
            "stake": Decimal("25.00"),
            "ev": Decimal("0.0000"),
            "model_run_id": None,
            "number_of_games": 3,
            "force_bet_after": datetime.now(timezone.utc) - timedelta(minutes=5),
            "within_force_window": True,
            "should_force_bet": True,
        }

    monkeypatch.setattr(bet_manager, "_evaluate_match_for_betting", fake_evaluate)

    statuses = bet_manager.get_upcoming_match_betting_statuses(db_session)

    assert len(statuses) == 2
    assert statuses[0]["status"] == "pending_auto_bet"
    assert statuses[0]["reason_code"] == "eligible_auto_bet"
    assert statuses[1]["status"] == "pending_force_bet"
    assert statuses[1]["reason_code"] == "eligible_force_bet"


def test_entity_resolver_supports_we_and_thundertalk_aliases(db_session) -> None:
    resolver = EntityResolver(db_session)

    team_we = resolver.resolve_team("WE", "pandascore")
    thunder_talk = resolver.resolve_team("TT", "pandascore")

    assert team_we is not None
    assert team_we.canonical_name == "Team WE"
    assert thunder_talk is not None
    assert thunder_talk.canonical_name == "ThunderTalk Gaming"


def test_evaluate_match_for_betting_surfaces_low_confidence_diagnostics(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll()
    db_session.add(bankroll)
    db_session.commit()

    match = {
        "id": 9301,
        "scheduled_at": "2026-03-22T20:00:00Z",
        "league": {"name": "LPL", "slug": "lpl"},
        "tournament": {"tier": "s"},
        "number_of_games": 3,
        "opponents": [
            {"opponent": {"name": "WE", "acronym": "WE", "id": 11}},
            {"opponent": {"name": "ThunderTalk", "acronym": "TT", "id": 22}},
        ],
    }
    offers = [
        {
            "source_book": "thunderpick",
            "market_type": "match_winner",
            "selection_key": "team_a",
            "line_value": None,
            "decimal_odds": 2.4,
            "market_status": "available",
            "scraped_at": None,
            "source_market_name": "Match Winner",
            "source_selection_name": "WE",
            "source_payload_json": None,
        },
        {
            "source_book": "thunderpick",
            "market_type": "match_winner",
            "selection_key": "team_b",
            "line_value": None,
            "decimal_odds": 1.55,
            "market_status": "available",
            "scraped_at": None,
            "source_market_name": "Match Winner",
            "source_selection_name": "ThunderTalk",
            "source_payload_json": None,
        },
    ]

    monkeypatch.setattr(
        bet_manager,
        "find_market_set_for_match",
        lambda *args, **kwargs: {
            "matched": True,
            "confidence": "exact",
            "matched_row_team1": "Team WE",
            "matched_row_team2": "ThunderTalk Gaming",
            "offers": offers,
        },
    )
    monkeypatch.setattr(bet_manager, "find_odds_for_match", lambda *args, **kwargs: (2.4, 1.55))
    monkeypatch.setattr(
        bet_manager,
        "predict_for_pandascore_match",
        lambda *args, **kwargs: (2.05, 1.82, None, None, 123),
    )
    monkeypatch.setattr(
        bet_manager,
        "predict_live_rebet_context",
        lambda *args, **kwargs: {
            "series_win_prob_a": 0.52,
            "series_win_prob_b": 0.48,
            "adjusted_game_win_prob_a": 0.51,
            "confidence": 0.53,
        },
    )

    fake_resolver = SimpleNamespace(
        resolve_team=lambda raw_name, *args, **kwargs: SimpleNamespace(id=11 if raw_name == "WE" else 22),
    )

    result = bet_manager._evaluate_match_for_betting(
        db_session,
        fake_resolver,
        bankroll,
        match,
        {"matches": []},
        now=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
        model_available=True,
    )

    assert result["status"] == "blocked_low_confidence"
    assert result["reason_code"] == "low_confidence"
    assert result["short_detail"] == "CONFIDENCE 0.53 < 0.54"
    assert result["bookie_match_confidence"] == "exact"
    assert result["matched_row_team1"] == "Team WE"
    assert result["matched_row_team2"] == "ThunderTalk Gaming"
    assert result["rejected_candidates"][0]["reason"] == "low_confidence"


def test_evaluate_match_for_betting_uses_real_thunderpick_card_catalog_for_we_vs_thundertalk(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll()
    db_session.add(bankroll)
    db_session.commit()

    match = {
        "id": 9302,
        "scheduled_at": "2026-03-29T10:00:00Z",
        "league": {"name": "Esports World Cup", "slug": "ewc"},
        "tournament": {"tier": "s"},
        "number_of_games": 3,
        "opponents": [
            {"opponent": {"name": "Team WE", "acronym": "WE", "id": 11}},
            {"opponent": {"name": "ThunderTalk Gaming", "acronym": "TT", "id": 22}},
        ],
    }
    thunderpick_text = "Team WE 1.45 vs 2.66 ThunderTalk Gaming"
    catalog = _build_market_catalog_from_page_text(thunderpick_text)

    monkeypatch.setattr(bet_manager, "read_odds_from_file", lambda: [])
    monkeypatch.setattr(
        bet_manager,
        "predict_for_pandascore_match",
        lambda *args, **kwargs: (1.29, 4.41, None, None, 123),
    )
    monkeypatch.setattr(
        bet_manager,
        "predict_live_rebet_context",
        lambda *args, **kwargs: {
            "series_win_prob_a": 0.69,
            "series_win_prob_b": 0.31,
            "adjusted_game_win_prob_a": 0.68,
            "confidence": 0.91,
        },
    )

    fake_resolver = SimpleNamespace(
        resolve_team=lambda raw_name, *args, **kwargs: SimpleNamespace(id=11 if "WE" in raw_name else 22),
    )

    result = bet_manager._evaluate_match_for_betting(
        db_session,
        fake_resolver,
        bankroll,
        match,
        catalog,
        now=datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc),
        model_available=True,
    )

    assert result.get("status") != "blocked_missing_odds"
    assert result["matched_row_team1"] == "Team WE"
    assert result["matched_row_team2"] == "ThunderTalk Gaming"
    assert result["odds_source_kind"] == "market_catalog_fallback"
    assert result["has_match_winner_offer"] is True
    assert result["market_offer_count"] >= 2


def test_auto_place_bets_waits_blocks_then_forces_within_four_hours(
    db_session,
    monkeypatch,
) -> None:
    bankroll = create_bankroll()
    db_session.add(bankroll)
    db_session.commit()

    base_match = {
        "scheduled_at": "2026-03-22T20:00:00Z",
        "league": {"name": "LCK", "slug": "lck"},
        "tournament": {"tier": "s"},
        "number_of_games": 3,
        "opponents": [
            {"opponent": {"name": "Alpha", "acronym": "ALP", "id": 1}},
            {"opponent": {"name": "Beta", "acronym": "BET", "id": 2}},
        ],
    }
    future_match = {**base_match, "id": 9101}
    force_match = {**base_match, "id": 9102}
    missing_match = {**base_match, "id": 9103}

    monkeypatch.setattr(
        bet_manager,
        "read_upcoming_matches_from_file",
        lambda: [future_match, force_match, missing_match, {**base_match, "id": 9104}],
    )
    monkeypatch.setattr("ml.predictor_v2.get_prediction_runtime_status", lambda session: {"active_model_id": 1})

    def fake_evaluate_candidate(session, resolver, bankroll_obj, match, bookie_odds, *, now, model_available):
        match_id = int(match["id"])
        if match_id == 9101:
            return {
                "pandascore_match_id": 9101,
                "team_a": "Alpha",
                "team_b": "Beta",
                "chosen_team": "Alpha",
                "chosen_model_prob": Decimal("0.52"),
                "chosen_book_prob": Decimal("0.50"),
                "chosen_book_odds": Decimal("2.2000"),
                "chosen_edge": Decimal("0.02000"),
                "stake": Decimal("25.00"),
                "ev": Decimal("1.0000"),
                "model_run_id": None,
                "number_of_games": 3,
                "force_bet_after": datetime.now(timezone.utc) + timedelta(minutes=30),
                "within_force_window": False,
                "should_force_bet": False,
            }
        if match_id == 9102:
            return {
                "pandascore_match_id": 9102,
                "team_a": "Gamma",
                "team_b": "Delta",
                "chosen_team": "Gamma",
                "chosen_model_prob": Decimal("0.50"),
                "chosen_book_prob": Decimal("0.50"),
                "chosen_book_odds": Decimal("2.3000"),
                "chosen_edge": Decimal("0.00000"),
                "stake": Decimal("25.00"),
                "ev": Decimal("0.0000"),
                "model_run_id": None,
                "number_of_games": 3,
                "force_bet_after": datetime.now(timezone.utc) - timedelta(minutes=5),
                "within_force_window": True,
                "should_force_bet": True,
            }
        if match_id == 9103:
            return {
                "pandascore_match_id": 9103,
                "status": "blocked_missing_odds",
                "reason_code": "missing_bookie_odds",
                "within_force_window": True,
                "force_bet_after": datetime.now(timezone.utc) - timedelta(minutes=10),
            }
        return {
            "pandascore_match_id": 9104,
            "status": "blocked_prediction_unavailable",
            "reason_code": "prediction_unavailable",
            "within_force_window": False,
            "force_bet_after": datetime.now(timezone.utc) + timedelta(minutes=45),
        }

    monkeypatch.setattr(bet_manager, "_evaluate_match_for_betting", fake_evaluate_candidate)

    summary = bet_manager.auto_place_bets(db_session)
    placed_bets = db_session.query(betting_api.Bet).all()

    assert summary["waiting_for_better_odds"] == 1
    assert summary["skipped_missing_inputs"] == 2
    assert summary["placed"] == 1
    assert summary["skipped_by_reason"]["below_edge_waiting"] == 1
    assert summary["skipped_by_reason"]["missing_bookie_odds"] == 1
    assert summary["skipped_by_reason"]["prediction_unavailable"] == 1
    assert len(placed_bets) == 1
    assert placed_bets[0].pandascore_match_id == 9102


def test_rebet_blocks_opposite_side_when_series_ev_does_not_improve() -> None:
    bankroll = create_bankroll()
    now = datetime.now(timezone.utc)
    existing_positions = [
        create_bet(
            bankroll.id,
            pandascore_match_id=9001,
            bet_on="Alpha",
            actual_stake=Decimal("50.00"),
            book_odds_locked=Decimal("2.20"),
            edge=Decimal("0.12000"),
            placed_at=now - timedelta(minutes=30),
        )
    ]
    candidate = {
        "pandascore_match_id": 9001,
        "series_key": "ps:9001",
        "team_a": "Alpha",
        "team_b": "Beta",
        "chosen_team": "Beta",
        "chosen_model_prob": Decimal("0.46"),
        "chosen_book_prob": Decimal("0.45"),
        "chosen_book_odds": Decimal("2.05"),
        "chosen_edge": Decimal("0.01000"),
        "stake": Decimal("25.00"),
        "ev": Decimal("-1.42"),
        "entry_phase": "live_mid_series",
        "team_a_model_prob": Decimal("0.54"),
        "team_b_model_prob": Decimal("0.46"),
    }

    can_place, skip_reason, context = bet_manager._can_place_rebet(
        existing_positions,
        candidate,
        bankroll=bankroll,
        now=now,
    )

    assert can_place is False
    assert skip_reason in {"hedge_not_improving", "series_net_ev_negative"}
    assert context["has_conflicting_positions"] is False


def test_rebet_allows_opposite_side_when_series_ev_improves() -> None:
    bankroll = create_bankroll()
    now = datetime.now(timezone.utc)
    existing_positions = [
        create_bet(
            bankroll.id,
            pandascore_match_id=9002,
            bet_on="Alpha",
            actual_stake=Decimal("50.00"),
            book_odds_locked=Decimal("2.20"),
            edge=Decimal("0.12000"),
            placed_at=now - timedelta(minutes=45),
        )
    ]
    candidate = {
        "pandascore_match_id": 9002,
        "series_key": "ps:9002",
        "team_a": "Alpha",
        "team_b": "Beta",
        "chosen_team": "Beta",
        "chosen_model_prob": Decimal("0.48"),
        "chosen_book_prob": Decimal("0.42"),
        "chosen_book_odds": Decimal("2.80"),
        "chosen_edge": Decimal("0.06000"),
        "stake": Decimal("25.00"),
        "ev": Decimal("8.60"),
        "entry_phase": "live_mid_series",
        "team_a_model_prob": Decimal("0.52"),
        "team_b_model_prob": Decimal("0.48"),
    }

    can_place, skip_reason, context = bet_manager._can_place_rebet(
        existing_positions,
        candidate,
        bankroll=bankroll,
        now=now,
    )

    assert can_place is True
    assert skip_reason is None
    assert context["series_ev_after"] > context["series_ev_before"]

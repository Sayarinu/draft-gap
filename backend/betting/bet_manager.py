from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TypedDict

from sqlalchemy.orm import Session

from betting.odds_engine import compute_edge, compute_ev, implied_prob, kelly_stake, remove_vig, roi_pct
from entity_resolution.canonical_store import normalize_team_for_settlement
from entity_resolution.resolver import EntityResolver
from ml.predictor_v2 import predict_for_pandascore_match
from models_ml import Bankroll, BankrollSnapshot, Bet
from services.bookie import find_odds_for_match, read_odds_from_file
from services.pandascore import fetch_json_sync, match_allowed_tier, read_upcoming_matches_from_file


class PlacementSummary(TypedDict):
    placed: int
    skipped_existing: int
    skipped_missing_inputs: int
    total_staked: float


class SettlementSummary(TypedDict):
    settled: int
    won: int
    lost: int
    void: int
    pnl: float


def _to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _team_names(match: dict[str, object]) -> tuple[str, str]:
    opponents = match.get("opponents") or []
    team_a = ((opponents[0].get("opponent") or {}).get("name") if len(opponents) > 0 else None) or "TBD"
    team_b = ((opponents[1].get("opponent") or {}).get("name") if len(opponents) > 1 else None) or "TBD"
    return (str(team_a), str(team_b))


def _team_acronyms(match: dict[str, object]) -> tuple[str | None, str | None]:
    opponents = match.get("opponents") or []
    team_a = ((opponents[0].get("opponent") or {}).get("acronym") if len(opponents) > 0 else None) or None
    team_b = ((opponents[1].get("opponent") or {}).get("acronym") if len(opponents) > 1 else None) or None
    return (str(team_a) if team_a else None, str(team_b) if team_b else None)


def get_or_create_agent_bankroll(session: Session) -> Bankroll:
    bankroll = session.query(Bankroll).filter(Bankroll.name == "DraftGap Agent").first()
    if bankroll is not None:
        return bankroll
    bankroll = Bankroll(
        name="DraftGap Agent",
        currency="USD",
        initial_balance=Decimal("1000.00"),
        current_balance=Decimal("1000.00"),
        staking_model="kelly_quarter",
        kelly_fraction=Decimal("0.250"),
        max_bet_pct=Decimal("0.0500"),
        min_edge_threshold=Decimal("0.0300"),
    )
    session.add(bankroll)
    session.commit()
    session.refresh(bankroll)
    return bankroll


def auto_place_bets(session: Session) -> PlacementSummary:
    bankroll = get_or_create_agent_bankroll(session)
    matches = read_upcoming_matches_from_file() or []
    bookie_odds = read_odds_from_file()
    resolver = EntityResolver(session)
    summary: PlacementSummary = {
        "placed": 0,
        "skipped_existing": 0,
        "skipped_missing_inputs": 0,
        "total_staked": 0.0,
    }
    for match in matches:
        match_id = int(match.get("id") or 0)
        if match_id <= 0:
            summary["skipped_missing_inputs"] += 1
            continue

        if not match_allowed_tier(match):
            summary["skipped_missing_inputs"] += 1
            continue

        exists = session.query(Bet).filter(Bet.pandascore_match_id == match_id).first()
        if exists is not None:
            summary["skipped_existing"] += 1
            continue

        team_a, team_b = _team_names(match)
        if team_a == "TBD" or team_b == "TBD":
            summary["skipped_missing_inputs"] += 1
            continue
        acr_a, acr_b = _team_acronyms(match)
        odds_a, odds_b = find_odds_for_match(team_a, team_b, bookie_odds, acronym1=acr_a, acronym2=acr_b)
        if odds_a is None or odds_b is None:
            summary["skipped_missing_inputs"] += 1
            continue

        opponents = match.get("opponents") or []
        ps_id_a = ((opponents[0].get("opponent") or {}).get("id") if len(opponents) > 0 else None) or None
        ps_id_b = ((opponents[1].get("opponent") or {}).get("id") if len(opponents) > 1 else None) or None
        team_model_a = resolver.resolve_team(team_a, "pandascore", pandascore_id=ps_id_a, abbreviation=acr_a)
        team_model_b = resolver.resolve_team(team_b, "pandascore", pandascore_id=ps_id_b, abbreviation=acr_b)
        if team_model_a is None or team_model_b is None:
            summary["skipped_missing_inputs"] += 1
            continue

        number_of_games = int(match.get("number_of_games") or 1)
        league_slug = str(((match.get("league") or {}).get("slug") or ""))
        model_odds_a, model_odds_b, _, _ = predict_for_pandascore_match(
            session,
            team_model_a.id,
            team_model_b.id,
            number_of_games=number_of_games,
            score_a=0,
            score_b=0,
            league_slug=league_slug,
        )
        if model_odds_a is None or model_odds_b is None:
            summary["skipped_missing_inputs"] += 1
            continue

        model_prob_a = implied_prob(_to_decimal(model_odds_a))
        model_prob_b = implied_prob(_to_decimal(model_odds_b))
        true_prob_a, true_prob_b = remove_vig(_to_decimal(odds_a), _to_decimal(odds_b))
        edge_a = compute_edge(model_prob_a, true_prob_a)
        edge_b = compute_edge(model_prob_b, true_prob_b)

        if edge_a >= edge_b:
            chosen_team = team_a
            chosen_model_prob = model_prob_a
            chosen_book_prob = true_prob_a
            chosen_book_odds = _to_decimal(odds_a)
            chosen_edge = edge_a
        else:
            chosen_team = team_b
            chosen_model_prob = model_prob_b
            chosen_book_prob = true_prob_b
            chosen_book_odds = _to_decimal(odds_b)
            chosen_edge = edge_b

        stake = kelly_stake(
            chosen_model_prob,
            chosen_book_odds,
            bankroll.current_balance,
            fraction=bankroll.kelly_fraction,
            max_pct=bankroll.max_bet_pct,
            min_stake=Decimal("25.00"),
        )
        if stake <= Decimal("0"):
            summary["skipped_missing_inputs"] += 1
            continue

        ev = compute_ev(chosen_model_prob, chosen_book_odds, stake)
        now = datetime.now(timezone.utc)
        bet = Bet(
            bankroll_id=bankroll.id,
            pandascore_match_id=match_id,
            model_run_id=None,
            team_a=team_a,
            team_b=team_b,
            league=((match.get("league") or {}).get("name") or None),
            series_format="BO5" if number_of_games >= 5 else ("BO3" if number_of_games >= 3 else "BO1"),
            bet_on=chosen_team,
            model_prob=chosen_model_prob,
            book_odds_locked=chosen_book_odds,
            book_prob_adj=chosen_book_prob,
            edge=chosen_edge,
            ev=ev,
            recommended_stake=stake,
            actual_stake=stake,
            status="PLACED",
            placed_at=now,
        )
        session.add(bet)
        bankroll.current_balance = max(Decimal("0"), bankroll.current_balance - stake)
        summary["total_staked"] += float(stake)
        summary["placed"] += 1

    session.commit()
    return summary


def settle_completed_bets(session: Session) -> SettlementSummary:
    results = fetch_json_sync(
        "/lol/matches/past",
        params={"per_page": 200, "sort": "-scheduled_at"},
    )
    past_matches = results if isinstance(results, list) else []
    winners_by_match: dict[int, str] = {}
    for match in past_matches:
        mid = int(match.get("id") or 0)
        if mid <= 0:
            continue
        winner = match.get("winner") or {}
        winner_name = str(winner.get("name") or "").strip()
        if winner_name:
            winners_by_match[mid] = winner_name

    open_bets = session.query(Bet).filter(Bet.status == "PLACED").all()
    summary: SettlementSummary = {
        "settled": 0,
        "won": 0,
        "lost": 0,
        "void": 0,
        "pnl": 0.0,
    }
    if not open_bets:
        return summary

    bankroll_map: dict[str, Bankroll] = {}
    bookie_odds = read_odds_from_file()
    now = datetime.now(timezone.utc)

    for bet in open_bets:
        winner_name = winners_by_match.get(bet.pandascore_match_id)
        if not winner_name:
            continue
        bankroll = bankroll_map.get(str(bet.bankroll_id))
        if bankroll is None:
            bankroll = session.query(Bankroll).get(bet.bankroll_id)
            if bankroll is None:
                continue
            bankroll_map[str(bet.bankroll_id)] = bankroll

        bet_won = normalize_team_for_settlement(session, winner_name) == normalize_team_for_settlement(session, bet.bet_on)
        stake = _to_decimal(bet.actual_stake)
        odds = _to_decimal(bet.book_odds_locked)
        if bet_won:
            gross_return = stake * odds
            profit_loss = stake * (odds - Decimal("1"))
            bankroll.current_balance = bankroll.current_balance + gross_return
            bet.status = "WON"
            summary["won"] += 1
        else:
            profit_loss = Decimal("0") - stake
            bet.status = "LOST"
            summary["lost"] += 1
        bet.profit_loss = profit_loss
        bet.settled_at = now
        summary["settled"] += 1
        summary["pnl"] += float(profit_loss)

        close_a, close_b = find_odds_for_match(bet.team_a, bet.team_b, bookie_odds)
        if close_a is not None and close_b is not None:
            if bet.bet_on.strip().lower() == bet.team_a.strip().lower():
                bet.closing_odds = _to_decimal(close_a)
            elif bet.bet_on.strip().lower() == bet.team_b.strip().lower():
                bet.closing_odds = _to_decimal(close_b)

    if summary["settled"] > 0:
        for bankroll in bankroll_map.values():
            settled_bets = session.query(Bet).filter(
                Bet.bankroll_id == bankroll.id,
                Bet.status.in_(["WON", "LOST", "VOID"]),
            ).all()
            wins = sum(1 for b in settled_bets if b.status == "WON")
            losses = sum(1 for b in settled_bets if b.status == "LOST")
            total_staked = sum(_to_decimal(b.actual_stake) for b in settled_bets)
            total_profit = sum(_to_decimal(b.profit_loss) for b in settled_bets if b.profit_loss is not None)

            latest_snapshot = (
                session.query(BankrollSnapshot)
                .filter(BankrollSnapshot.bankroll_id == bankroll.id)
                .order_by(BankrollSnapshot.snapshot_at.desc())
                .first()
            )
            peak_balance = bankroll.current_balance
            if latest_snapshot is not None:
                peak_balance = max(peak_balance, latest_snapshot.peak_balance)

            snapshot = BankrollSnapshot(
                bankroll_id=bankroll.id,
                snapshot_at=now,
                balance=bankroll.current_balance,
                total_bets=len(settled_bets),
                wins=wins,
                losses=losses,
                roi_pct=roi_pct(total_profit, total_staked),
                peak_balance=peak_balance,
            )
            session.add(snapshot)
        session.commit()

    return summary

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

from fastapi import APIRouter
from pydantic import BaseModel

from betting.bet_manager import get_or_create_agent_bankroll, settle_completed_bets
from betting.odds_engine import roi_pct
from database import SessionLocal, init_db
from models_ml import Bankroll, BankrollSnapshot, Bet
from services.pandascore import league_name_or_slug_allowed

router = APIRouter(prefix="/betting", tags=["betting"])


def _to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


class BankrollResponse(BaseModel):
    bankroll_id: str
    name: str
    currency: str
    initial_balance: float
    current_balance: float
    active_bets: int
    settled_bets: int
    wins: int
    losses: int
    win_rate_pct: float
    total_staked: float
    total_profit_loss: float
    roi_pct: float
    peak_balance: float
    drawdown_pct: float


class BetItemResponse(BaseModel):
    id: str
    pandascore_match_id: int
    team_a: str
    team_b: str
    league: str | None = None
    series_format: str | None = None
    bet_on: str
    book_odds_locked: float
    model_prob: float
    book_prob_adj: float
    edge: float
    ev: float
    actual_stake: float
    status: str
    profit_loss: float | None = None
    placed_at: str
    settled_at: str | None = None


class ResultsItemResponse(BaseModel):
    id: str
    betDateTime: str
    league: str
    team1: str
    team2: str
    betOn: str
    lockedOdds: float
    stake: float
    result: str
    profitLoss: float


class BettingSummaryResponse(BaseModel):
    total_bets: int
    active_bets: int
    settled_bets: int
    wins: int
    losses: int
    win_rate_pct: float
    total_staked: float
    total_profit_loss: float
    roi_pct: float
    avg_edge_pct: float
    avg_odds: float


class ResetBankrollResponse(BaseModel):
    status: str
    bankroll_id: str
    current_balance: float


class ActiveBetBadgeResponse(TypedDict):
    pandascore_match_id: int
    bet_on: str
    locked_odds: float
    stake: float


def _build_bankroll_response() -> BankrollResponse:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        session.refresh(bankroll)
        active_all = session.query(Bet).filter(Bet.bankroll_id == bankroll.id, Bet.status == "PLACED").all()
        active = [b for b in active_all if league_name_or_slug_allowed(b.league)]
        settled = session.query(Bet).filter(Bet.bankroll_id == bankroll.id, Bet.status.in_(["WON", "LOST"])).all()
        wins = sum(1 for bet in settled if bet.status == "WON")
        losses = sum(1 for bet in settled if bet.status == "LOST")
        total_staked = sum(_to_decimal(bet.actual_stake) for bet in settled)
        total_profit = sum(_to_decimal(bet.profit_loss) for bet in settled if bet.profit_loss is not None)
        win_rate = (wins / len(settled) * 100.0) if settled else 0.0
        peak = (
            session.query(BankrollSnapshot)
            .filter(BankrollSnapshot.bankroll_id == bankroll.id)
            .order_by(BankrollSnapshot.snapshot_at.desc())
            .first()
        )
        peak_balance = _to_decimal(peak.peak_balance) if peak is not None else _to_decimal(bankroll.initial_balance)
        drawdown = 0.0
        if peak_balance > Decimal("0"):
            drawdown = float(((peak_balance - _to_decimal(bankroll.current_balance)) / peak_balance) * Decimal("100"))

        return BankrollResponse(
            bankroll_id=str(bankroll.id),
            name=bankroll.name,
            currency=bankroll.currency,
            initial_balance=float(bankroll.initial_balance),
            current_balance=float(bankroll.current_balance),
            active_bets=len(active),
            settled_bets=len(settled),
            wins=wins,
            losses=losses,
            win_rate_pct=win_rate,
            total_staked=float(total_staked),
            total_profit_loss=float(total_profit),
            roi_pct=float(roi_pct(total_profit, total_staked)),
            peak_balance=float(peak_balance),
            drawdown_pct=drawdown,
        )
    finally:
        session.close()


@router.get("/bankroll", response_model=BankrollResponse)
def get_bankroll() -> BankrollResponse:
    return _build_bankroll_response()


class SettledBetBreakdownItem(BaseModel):
    pandascore_match_id: int
    result: str
    stake: float
    profit_loss: float


class BankrollBreakdownResponse(BaseModel):
    initial_balance: float
    current_balance: float
    active_stake_total: float
    active_stake_allowed: float
    active_stake_filtered: float
    settled_pnl: float
    settled_bets: list[SettledBetBreakdownItem]


@router.get("/bankroll/breakdown", response_model=BankrollBreakdownResponse)
def get_bankroll_breakdown() -> BankrollBreakdownResponse:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        session.refresh(bankroll)
        active = (
            session.query(Bet)
            .filter(Bet.bankroll_id == bankroll.id, Bet.status == "PLACED")
            .all()
        )
        settled = (
            session.query(Bet)
            .filter(
                Bet.bankroll_id == bankroll.id,
                Bet.status.in_(["WON", "LOST", "VOID"]),
            )
            .order_by(Bet.settled_at.desc(), Bet.placed_at.desc())
            .all()
        )
        active_stake_total = sum(_to_decimal(b.actual_stake) for b in active)
        active_stake_allowed = sum(
            _to_decimal(b.actual_stake) for b in active if league_name_or_slug_allowed(b.league)
        )
        active_stake_filtered = active_stake_total - active_stake_allowed
        settled_pnl = sum(
            _to_decimal(b.profit_loss) for b in settled if b.profit_loss is not None
        )
        return BankrollBreakdownResponse(
            initial_balance=float(bankroll.initial_balance),
            current_balance=float(bankroll.current_balance),
            active_stake_total=float(active_stake_total),
            active_stake_allowed=float(active_stake_allowed),
            active_stake_filtered=float(active_stake_filtered),
            settled_pnl=float(settled_pnl),
            settled_bets=[
                SettledBetBreakdownItem(
                    pandascore_match_id=b.pandascore_match_id,
                    result=b.status,
                    stake=float(b.actual_stake),
                    profit_loss=float(b.profit_loss or 0),
                )
                for b in settled
            ],
        )
    finally:
        session.close()


@router.get("/bets", response_model=list[BetItemResponse])
def get_bets(status: str | None = None, limit: int = 50) -> list[BetItemResponse]:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        query = session.query(Bet).filter(Bet.bankroll_id == bankroll.id)
        if status:
            statuses = [part.strip().upper() for part in status.split(",") if part.strip()]
            if statuses:
                query = query.filter(Bet.status.in_(statuses))
        rows = query.order_by(Bet.placed_at.desc()).limit(min(max(limit, 1), 500)).all()
        return [
            BetItemResponse(
                id=str(row.id),
                pandascore_match_id=row.pandascore_match_id,
                team_a=row.team_a,
                team_b=row.team_b,
                league=row.league,
                series_format=row.series_format,
                bet_on=row.bet_on,
                book_odds_locked=float(row.book_odds_locked),
                model_prob=float(row.model_prob),
                book_prob_adj=float(row.book_prob_adj),
                edge=float(row.edge),
                ev=float(row.ev),
                actual_stake=float(row.actual_stake),
                status=row.status,
                profit_loss=float(row.profit_loss) if row.profit_loss is not None else None,
                placed_at=str(row.placed_at),
                settled_at=str(row.settled_at) if row.settled_at is not None else None,
            )
            for row in rows
        ]
    finally:
        session.close()


@router.get("/bets/active", response_model=list[dict[str, object]])
def get_active_bets() -> list[dict[str, object]]:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        rows = (
            session.query(Bet)
            .filter(Bet.bankroll_id == bankroll.id, Bet.status == "PLACED")
            .order_by(Bet.placed_at.desc())
            .all()
        )
        return [
            {
                "id": str(row.id),
                "pandascore_match_id": row.pandascore_match_id,
                "bet_on": row.bet_on,
                "locked_odds": float(row.book_odds_locked),
                "stake": float(row.actual_stake),
            }
            for row in rows
            if league_name_or_slug_allowed(row.league)
        ]
    finally:
        session.close()


@router.get("/results", response_model=list[ResultsItemResponse])
def get_results(limit: int = 50) -> list[ResultsItemResponse]:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        rows = (
            session.query(Bet)
            .filter(
                Bet.bankroll_id == bankroll.id,
                Bet.status.in_(["WON", "LOST", "VOID"]),
            )
            .order_by(Bet.settled_at.desc(), Bet.placed_at.desc())
            .limit(min(max(limit, 1), 500))
            .all()
        )
        return [
            ResultsItemResponse(
                id=str(row.id),
                betDateTime=str(row.placed_at),
                league=row.league or "UNKNOWN",
                team1=row.team_a,
                team2=row.team_b,
                betOn=row.bet_on,
                lockedOdds=float(row.book_odds_locked),
                stake=float(row.actual_stake),
                result=row.status,
                profitLoss=float(row.profit_loss or 0),
            )
            for row in rows
        ]
    finally:
        session.close()


@router.get("/summary", response_model=BettingSummaryResponse)
def get_summary() -> BettingSummaryResponse:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        all_bets = session.query(Bet).filter(Bet.bankroll_id == bankroll.id).all()
        active = [bet for bet in all_bets if bet.status == "PLACED" and league_name_or_slug_allowed(bet.league)]
        settled = [bet for bet in all_bets if bet.status in {"WON", "LOST"}]
        wins = sum(1 for bet in settled if bet.status == "WON")
        losses = sum(1 for bet in settled if bet.status == "LOST")
        total_staked = sum(_to_decimal(bet.actual_stake) for bet in settled)
        total_profit = sum(_to_decimal(bet.profit_loss) for bet in settled if bet.profit_loss is not None)
        avg_edge = 0.0
        avg_odds = 0.0
        if all_bets:
            avg_edge = float(sum(_to_decimal(bet.edge) for bet in all_bets) / Decimal(len(all_bets))) * 100.0
            avg_odds = float(sum(_to_decimal(bet.book_odds_locked) for bet in all_bets) / Decimal(len(all_bets)))
        return BettingSummaryResponse(
            total_bets=len(all_bets),
            active_bets=len(active),
            settled_bets=len(settled),
            wins=wins,
            losses=losses,
            win_rate_pct=(wins / len(settled) * 100.0) if settled else 0.0,
            total_staked=float(total_staked),
            total_profit_loss=float(total_profit),
            roi_pct=float(roi_pct(total_profit, total_staked)),
            avg_edge_pct=avg_edge,
            avg_odds=avg_odds,
        )
    finally:
        session.close()


@router.post("/bankroll/reset", response_model=ResetBankrollResponse)
def reset_bankroll() -> ResetBankrollResponse:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        session.query(Bet).filter(Bet.bankroll_id == bankroll.id).delete()
        session.query(BankrollSnapshot).filter(BankrollSnapshot.bankroll_id == bankroll.id).delete()
        bankroll.current_balance = bankroll.initial_balance
        session.commit()
        return ResetBankrollResponse(
            status="success",
            bankroll_id=str(bankroll.id),
            current_balance=float(bankroll.current_balance),
        )
    finally:
        session.close()


class VoidBetsRequest(BaseModel):
    match_ids: list[int]


class VoidBetsResponse(BaseModel):
    voided: int
    match_ids: list[int]
    current_balance: float


@router.post("/bets/void", response_model=VoidBetsResponse)
def void_bets(request: VoidBetsRequest) -> VoidBetsResponse:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        session.refresh(bankroll)
        bets = (
            session.query(Bet)
            .filter(
                Bet.bankroll_id == bankroll.id,
                Bet.status == "PLACED",
                Bet.pandascore_match_id.in_(request.match_ids),
            )
            .all()
        )
        voided_ids: list[int] = []
        for bet in bets:
            bankroll.current_balance = bankroll.current_balance + _to_decimal(bet.actual_stake)
            bet.status = "VOID"
            bet.profit_loss = Decimal("0")
            voided_ids.append(bet.pandascore_match_id)
        session.commit()
        return VoidBetsResponse(
            voided=len(voided_ids),
            match_ids=voided_ids,
            current_balance=float(bankroll.current_balance),
        )
    finally:
        session.close()


class VoidUnsupportedResponse(BaseModel):
    voided: int
    match_ids: list[int]
    refunded: float
    current_balance: float


@router.post("/bets/void-unsupported", response_model=VoidUnsupportedResponse)
def void_unsupported_league_bets() -> VoidUnsupportedResponse:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        session.refresh(bankroll)
        active = (
            session.query(Bet)
            .filter(Bet.bankroll_id == bankroll.id, Bet.status == "PLACED")
            .all()
        )
        to_void = [b for b in active if not league_name_or_slug_allowed(b.league)]
        refunded = Decimal("0")
        voided_ids: list[int] = []
        for bet in to_void:
            refunded += _to_decimal(bet.actual_stake)
            bankroll.current_balance = bankroll.current_balance + _to_decimal(bet.actual_stake)
            bet.status = "VOID"
            bet.profit_loss = Decimal("0")
            voided_ids.append(bet.pandascore_match_id)
        session.commit()
        return VoidUnsupportedResponse(
            voided=len(voided_ids),
            match_ids=voided_ids,
            refunded=float(refunded),
            current_balance=float(bankroll.current_balance),
        )
    finally:
        session.close()


class ReconcileResponse(BaseModel):
    previous_balance: float
    computed_balance: float
    current_balance: float
    adjusted: bool


@router.post("/bankroll/reconcile", response_model=ReconcileResponse)
def reconcile_bankroll() -> ReconcileResponse:
    init_db()
    session = SessionLocal()
    try:
        bankroll = get_or_create_agent_bankroll(session)
        session.refresh(bankroll)
        previous = float(bankroll.current_balance)
        initial = _to_decimal(bankroll.initial_balance)
        all_bets = session.query(Bet).filter(Bet.bankroll_id == bankroll.id).all()
        active_stake_total = sum(
            _to_decimal(b.actual_stake) for b in all_bets if b.status == "PLACED"
        )
        settled_pnl = sum(
            _to_decimal(b.profit_loss) for b in all_bets if b.status in {"WON", "LOST", "VOID"}
        )
        computed = initial - active_stake_total + settled_pnl
        adjusted = abs(computed - _to_decimal(bankroll.current_balance)) > Decimal("0.001")
        if adjusted:
            bankroll.current_balance = computed
            session.commit()
            session.refresh(bankroll)
        return ReconcileResponse(
            previous_balance=previous,
            computed_balance=float(computed),
            current_balance=float(bankroll.current_balance),
            adjusted=adjusted,
        )
    finally:
        session.close()


class SettleResponse(BaseModel):
    settled: int
    won: int
    lost: int
    void: int
    pnl: float


@router.post("/settle", response_model=SettleResponse)
def manual_settle() -> SettleResponse:
    init_db()
    session = SessionLocal()
    try:
        summary = settle_completed_bets(session)
        return SettleResponse(
            settled=summary["settled"],
            won=summary["won"],
            lost=summary["lost"],
            void=summary["void"],
            pnl=summary["pnl"],
        )
    finally:
        session.close()

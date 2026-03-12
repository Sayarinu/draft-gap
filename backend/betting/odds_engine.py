from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


def _quantize(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def implied_prob(decimal_odds: Decimal) -> Decimal:
    if decimal_odds <= _ZERO:
        return _ZERO
    return _quantize(_ONE / decimal_odds, "0.00001")


def remove_vig(odds_a: Decimal, odds_b: Decimal) -> tuple[Decimal, Decimal]:
    implied_a = implied_prob(odds_a)
    implied_b = implied_prob(odds_b)
    total = implied_a + implied_b
    if total <= _ZERO:
        return (_ZERO, _ZERO)
    true_a = implied_a / total
    true_b = implied_b / total
    return (_quantize(true_a, "0.00001"), _quantize(true_b, "0.00001"))


def compute_edge(model_prob: Decimal, book_prob_adj: Decimal) -> Decimal:
    return _quantize(model_prob - book_prob_adj, "0.00001")


def compute_ev(model_prob: Decimal, decimal_odds: Decimal, stake: Decimal) -> Decimal:
    profit_if_win = stake * (decimal_odds - _ONE)
    loss_if_lose = stake
    model_loss_prob = _ONE - model_prob
    ev = (model_prob * profit_if_win) - (model_loss_prob * loss_if_lose)
    return _quantize(ev, "0.0001")


def kelly_stake(
    model_prob: Decimal,
    decimal_odds: Decimal,
    bankroll_balance: Decimal,
    *,
    fraction: Decimal = Decimal("0.25"),
    max_pct: Decimal = Decimal("0.05"),
    min_stake: Decimal = Decimal("25.00"),
) -> Decimal:
    if bankroll_balance <= _ZERO:
        return _ZERO
    b = decimal_odds - _ONE
    if b <= _ZERO:
        return _ZERO

    p = max(_ZERO, min(_ONE, model_prob))
    q = _ONE - p
    raw_fraction = ((b * p) - q) / b
    adjusted_fraction = raw_fraction * max(_ZERO, fraction)
    capped_fraction = min(max(adjusted_fraction, _ZERO), max(_ZERO, max_pct))

    stake = bankroll_balance * capped_fraction
    if stake < min_stake:
        stake = min_stake if bankroll_balance >= min_stake else bankroll_balance
    if stake > bankroll_balance:
        stake = bankroll_balance
    return _quantize(stake, "0.01")


def roi_pct(total_profit_loss: Decimal, total_staked: Decimal) -> Decimal:
    if total_staked <= _ZERO:
        return _ZERO
    return _quantize((total_profit_loss / total_staked) * _HUNDRED, "0.00001")

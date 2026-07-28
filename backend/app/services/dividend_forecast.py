"""
Project future dividend payments from a security's own payment history.

Nothing forward-looking is cached anywhere — no announced dividends, no calendar
(the fundamentals/earnings tables carry no dividend fields) — so a forecast is
necessarily inferred: the payout cadence comes from the spacing of past payments,
the amount from the trailing payments scaled to the current holding. Pure
functions, no DB and no network, so the inference rules are pinned by fast unit
tests and can never violate the no-Yahoo-at-request-time rule.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import List, Optional

# Cadence is inferred from the median gap between recent payments. Anything
# slower than ~13 months is not a cadence, and anything faster than ~3 weeks is
# noise (monthly is the fastest real payout schedule), so both refuse to forecast.
MAX_GAP_DAYS = 400
MIN_GAP_DAYS = 20

# Only the most recent payments describe the current schedule; a decade of
# history would let long-dead behaviour outvote a recent dividend change.
CADENCE_SAMPLE = 8

# A payer that has skipped ~2.5 expected payouts before the horizon even starts
# has stopped, not paused — projecting a resumption would be invention.
STOPPED_AFTER_GAPS = 2.5


@dataclass(frozen=True)
class HistPayment:
    """One historical payment: when, how much (net EUR), and the shares that earned it.

    ``shares_held`` is None/0 when unknown (IBKR rows store a 0 sentinel and the
    holding at the pay date may not be derivable) — the amount is then used
    unscaled instead of being scaled to the current position size.
    """
    on_date: date
    net_eur: Decimal
    shares_held: Optional[Decimal] = None


@dataclass(frozen=True)
class ForecastPayment:
    on_date: date
    net_eur: Decimal


def infer_gap_days(dates: List[date]) -> Optional[int]:
    """Median gap between the most recent payments, or None when no cadence exists."""
    uniq = sorted(set(dates))[-CADENCE_SAMPLE:]
    if len(uniq) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(uniq, uniq[1:])]
    gap = int(median(gaps))
    if gap < MIN_GAP_DAYS or gap > MAX_GAP_DAYS:
        return None
    return gap


def _trailing_amount(history: List[HistPayment], current_shares: Decimal) -> Optional[Decimal]:
    """
    Median of the recent payments, each scaled to the current holding where the
    earning share count is known. The median (not mean) keeps a one-off special
    dividend from inflating every projected payment.
    """
    recent = sorted(history, key=lambda p: p.on_date)[-CADENCE_SAMPLE:]
    scaled: List[Decimal] = []
    for p in recent:
        if p.net_eur is None or p.net_eur <= 0:
            continue
        if p.shares_held and p.shares_held > 0 and current_shares > 0:
            scaled.append(p.net_eur * current_shares / p.shares_held)
        else:
            scaled.append(p.net_eur)
    if not scaled:
        return None
    amount = median(scaled)
    return amount if amount > 0 else None


def project_dividends(
    history: List[HistPayment],
    current_shares: Decimal,
    horizon_start: date,
    horizon_end: date,
) -> List[ForecastPayment]:
    """
    Future payments for one security inside [horizon_start, horizon_end].

    Returns [] whenever an honest projection isn't possible: nothing is held,
    fewer than two past payments, no inferable cadence, the payer looks stopped,
    or the horizon is empty.
    """
    if current_shares <= 0 or horizon_start > horizon_end or not history:
        return []

    paid = [p for p in history if p.net_eur and p.net_eur > 0]
    gap = infer_gap_days([p.on_date for p in paid])
    if gap is None:
        return []

    last_paid = max(p.on_date for p in paid)
    if (horizon_start - last_paid).days > STOPPED_AFTER_GAPS * gap:
        return []

    amount = _trailing_amount(paid, current_shares)
    if amount is None:
        return []

    out: List[ForecastPayment] = []
    nxt = last_paid + timedelta(days=gap)
    while nxt <= horizon_end:
        if nxt >= horizon_start:
            out.append(ForecastPayment(on_date=nxt, net_eur=amount))
        nxt += timedelta(days=gap)
    return out

"""
Project future dividend payments from a security's own payment history.

Nothing forward-looking is cached anywhere — no announced dividends, no calendar
(the fundamentals/earnings tables carry no dividend fields) — so a forecast is
necessarily inferred: the payout cadence comes from the spacing of past
ex-dates, the size from the recent dividend **per share** scaled to the holding
we have now. Pure functions, no DB and no network, so the inference rules are
pinned by fast unit tests and can never violate the no-Yahoo-at-request-time
rule.

Working per share rather than per payment received is what lets a security
bought last month be forecast at all: the payout schedule is a property of the
company, not of how long we have owned it. Keying on realized income instead
left TSMC, Samsung, SK Hynix, HPE and the SOXQ ETF — every one a real payer —
projecting nothing.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import List, Optional

# Cadence is inferred from the median gap between recent ex-dates. Anything
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
    """
    One historical dividend: when it went ex, and how much per share in EUR.

    ``per_share_eur`` is None when the amount can't be established (an IBKR row
    with no per-share figure and no usable share count). Such a payment still
    counts towards the cadence — the date is evidence of the schedule — it just
    can't contribute to the size.
    """
    on_date: date
    per_share_eur: Optional[Decimal] = None


@dataclass(frozen=True)
class ForecastPayment:
    on_date: date
    net_eur: Decimal


def infer_gap_days(dates: List[date]) -> Optional[int]:
    """Median gap between the most recent ex-dates, or None when no cadence exists."""
    uniq = sorted(set(dates))[-CADENCE_SAMPLE:]
    if len(uniq) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(uniq, uniq[1:])]
    gap = int(median(gaps))
    if gap < MIN_GAP_DAYS or gap > MAX_GAP_DAYS:
        return None
    return gap


def _per_share(history: List[HistPayment]) -> Optional[Decimal]:
    """
    Median dividend per share over the recent payments.

    The median (not the mean) keeps a one-off special dividend from inflating
    every projected payment.
    """
    recent = sorted(history, key=lambda p: p.on_date)[-CADENCE_SAMPLE:]
    amounts = [p.per_share_eur for p in recent
               if p.per_share_eur is not None and p.per_share_eur > 0]
    if not amounts:
        return None
    value = median(amounts)
    return value if value > 0 else None


def project_dividends(
    history: List[HistPayment],
    current_shares: Decimal,
    horizon_start: date,
    horizon_end: date,
    as_of: Optional[date] = None,
) -> List[ForecastPayment]:
    """
    Future payments for one security inside [horizon_start, horizon_end].

    ``as_of`` is *now* — the point from which staleness is judged. It is separate
    from ``horizon_start`` because asking about next year must not make every
    payer look stopped: the distance to a future horizon is a property of the
    question, not of the company.

    Returns [] whenever an honest projection isn't possible: nothing is held,
    fewer than two past ex-dates, no inferable cadence, no usable per-share
    amount, the payer looks stopped, or the horizon is empty.
    """
    if current_shares <= 0 or horizon_start > horizon_end or not history:
        return []

    gap = infer_gap_days([p.on_date for p in history])
    if gap is None:
        return []

    last_seen = max(p.on_date for p in history)
    if ((as_of or horizon_start) - last_seen).days > STOPPED_AFTER_GAPS * gap:
        return []

    per_share = _per_share(history)
    if per_share is None:
        return []

    amount = per_share * current_shares
    out: List[ForecastPayment] = []
    nxt = last_seen + timedelta(days=gap)
    while nxt <= horizon_end:
        if nxt >= horizon_start:
            out.append(ForecastPayment(on_date=nxt, net_eur=amount))
        nxt += timedelta(days=gap)
    return out

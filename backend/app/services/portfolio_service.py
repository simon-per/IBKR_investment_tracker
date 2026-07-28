"""
Portfolio Service
Calculates cost basis and market value for the portfolio over time.
"""
import bisect
import calendar
from collections import defaultdict
from typing import List, Dict, Optional, Tuple
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.taxlot import TaxLot
from app.models.security import Security
from app.models.trade import Trade
from app.services.market_data_service import MarketDataService
from app.services.currency_service import CurrencyService
from app.repositories.app_settings_repository import AppSettingsRepository
from app.repositories.cash_flow_repository import CashFlowRepository

logger = logging.getLogger(__name__)

# Average calendar month, used only to express an elapsed span in months so a
# part-month of history isn't rounded away.
_DAYS_PER_MONTH = 365.25 / 12


def _shift_months(from_date: date, months: int) -> date:
    """
    The same day-of-month ``months`` before ``from_date``, clamped to the length
    of the target month (31 May - 3 months -> 28/29 Feb).
    """
    total = from_date.year * 12 + (from_date.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(from_date.day, calendar.monthrange(year, month)[1]))


class BaseFx:
    """
    Converts EUR-denominated amounts into the selected base (display) currency
    at a given date. The whole portfolio pipeline computes values in EUR; this
    applies a single EUR->base factor as a read-time projection.

    - Cost basis is converted at each lot's open_date (so the cost-basis line
      only moves on buys/sells, never with day-to-day FX).
    - Market value is converted at the valuation date.

    When base_currency == 'EUR' this is a no-op (rate 1.0).
    """

    def __init__(self, base_currency: str, rate_cache: Dict[date, Decimal]):
        self.base_currency = base_currency
        self.rate_cache = rate_cache  # {date: EUR->base rate}
        self._sorted_dates = sorted(rate_cache.keys())

    def _rate_on(self, on_date: date) -> Optional[Decimal]:
        rate = self.rate_cache.get(on_date)
        if rate is not None:
            return rate
        if not self._sorted_dates:
            return None
        # Carry-forward: most recent rate on/before on_date
        idx = bisect.bisect_right(self._sorted_dates, on_date)
        if idx > 0:
            return self.rate_cache[self._sorted_dates[idx - 1]]
        # on_date precedes all cached rates: carry the earliest back
        return self.rate_cache[self._sorted_dates[0]]

    def convert(self, amount_eur: Decimal, on_date: date) -> Decimal:
        if self.base_currency == "EUR" or not amount_eur:
            return amount_eur
        rate = self._rate_on(on_date)
        if rate is None:
            # No rate available anywhere: fall back to EUR value rather than zero.
            return amount_eur
        return amount_eur * rate


class PortfolioService:
    """
    Service for portfolio analytics and calculations.

    Calculates:
    - Cost basis: Total amount invested (in EUR)
    - Market value: Current worth of holdings (in EUR)
    - Unrealized gain/loss
    - Portfolio composition by security
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.market_data_service = MarketDataService(db)
        self.currency_service = CurrencyService(db)

    async def get_base_currency(self) -> str:
        """Return the configured base (display) currency."""
        return await AppSettingsRepository(self.db).get_base_currency()

    async def _load_base_fx(self) -> BaseFx:
        """
        Build a BaseFx for the configured base currency, loading EUR->base daily
        rates over the full portfolio history (earliest lot open_date .. today).

        Reads cached ExchangeRate rows; if none exist yet (base just switched and
        backfill was skipped), fetches the whole range once from Frankfurter.
        """
        base_currency = await self.get_base_currency()
        if base_currency == "EUR":
            return BaseFx("EUR", {})

        from app.models.exchange_rate import ExchangeRate

        today = date.today()
        min_open = (await self.db.execute(select(func.min(TaxLot.open_date)))).scalar()
        start = min_open or (today - timedelta(days=365))

        async def load_cache() -> Dict[date, Decimal]:
            rows = (await self.db.execute(
                select(ExchangeRate).where(
                    ExchangeRate.from_currency == "EUR",
                    ExchangeRate.to_currency == base_currency,
                    ExchangeRate.date >= start,
                    ExchangeRate.date <= today,
                )
            )).scalars().all()
            return {r.date: r.rate for r in rows}

        cache = await load_cache()
        if not cache:
            # Safety net: populate EUR->base history once, then reload.
            try:
                await self.currency_service._batch_fetch_rates(
                    from_currency="EUR",
                    target_date=today,
                    to_currency=base_currency,
                    days_back=max((today - start).days, 30),
                )
                cache = await load_cache()
            except Exception as e:
                logger.warning(f"Could not backfill EUR->{base_currency} rates: {e}")

        return BaseFx(base_currency, cache)

    async def get_portfolio_value_over_time(
        self,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """
        Calculate portfolio value (cost basis and market value) for each day in range.
        Uses optimized caching for fast performance.
        Includes both open AND closed tax lots for correct historical values.
        """
        # Get ALL taxlots (open + closed) for historical accuracy
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .order_by(TaxLot.open_date.asc())
        )
        taxlots_with_securities = result.all()

        if not taxlots_with_securities:
            return []

        # Pre-load all data once
        unique_securities = {security for _, security in taxlots_with_securities}
        price_cache, price_currency_cache = await self._preload_market_prices(unique_securities, start_date, end_date)
        exchange_rate_cache = await self._preload_exchange_rates(unique_securities, start_date, end_date, price_currency_cache=price_currency_cache)
        base_fx = await self._load_base_fx()

        # Calculate portfolio value for each business day
        portfolio_timeline = []
        current_date = start_date

        while current_date <= end_date:
            # Skip weekends
            if current_date.weekday() < 5:
                daily_value = self._calculate_daily_value(
                    current_date, taxlots_with_securities, price_cache, exchange_rate_cache,
                    price_currency_cache=price_currency_cache, base_fx=base_fx
                )
                daily_value["base_currency"] = base_fx.base_currency
                portfolio_timeline.append(daily_value)

            current_date += timedelta(days=1)

        return portfolio_timeline

    async def get_current_portfolio_summary(self) -> Dict:
        """
        Get current portfolio summary with latest values.
        """
        today = date.today()

        base_fx = await self._load_base_fx()

        # Get all open taxlots with securities
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .where(TaxLot.is_open == True)
        )
        taxlots_with_securities = result.all()

        if not taxlots_with_securities:
            realized = await self.get_realized_totals(base_fx=base_fx)
            return {
                "total_cost_basis_eur": 0.0,
                "total_market_value_eur": 0.0,
                "total_gain_loss_eur": 0.0,
                "total_gain_loss_percent": 0.0,
                "num_positions": 0,
                "base_currency": base_fx.base_currency,
                **realized,
            }

        # Use optimized method
        unique_securities = {security for _, security in taxlots_with_securities}
        price_cache, price_currency_cache = await self._preload_market_prices(unique_securities, today, today)
        exchange_rate_cache = await self._preload_exchange_rates(unique_securities, today, today, price_currency_cache=price_currency_cache)

        daily_value = self._calculate_daily_value(
            today, taxlots_with_securities, price_cache, exchange_rate_cache,
            price_currency_cache=price_currency_cache, base_fx=base_fx
        )

        realized = await self.get_realized_totals(base_fx=base_fx)

        return {
            "total_cost_basis_eur": daily_value["cost_basis_eur"],
            "total_market_value_eur": daily_value["market_value_eur"],
            "total_gain_loss_eur": daily_value["gain_loss_eur"],
            "total_gain_loss_percent": daily_value["gain_loss_percent"],
            "num_positions": len(set(security.id for _, security in taxlots_with_securities)),
            "date": daily_value["date"],
            "base_currency": base_fx.base_currency,
            **realized,
        }

    async def get_contributions(self, as_of: Optional[date] = None) -> Dict:
        """
        How much money went in per month, over several trailing windows.

        **``money_in_eur`` is the answer**, and it is spliced across two eras because
        no single source is authoritative for the whole history:

        - Before ``coverage_from``, from **lot cost basis**. That reaches back through
          the pre-IBKR years because the 2026 transfer from the previous brokers
          carried every lot across with its original open_date *and* original cost
          basis (verified: securities have as many distinct costBasisPrice values as
          they have lots, so nothing was re-based to the transfer date).
        - From ``coverage_from`` onward, from **real deposits**.

        ``coverage_from`` is what the statements claim to cover, clamped forward to the
        first row the ledger actually holds — the account is routinely younger than the
        statement period that reports it.

        The split exists because lot cost basis cannot survive a rotation: selling one
        ETF to buy another closes lots and opens new ones, so the same money is
        deployed twice. A deposit has a single leg and cannot be inflated that way, so
        the moment a real ledger exists it takes over. This matters concretely — the
        Ireland-domiciled sleeve is being switched to US-domiciled ETFs for tax
        reasons, which is one large rotation. Averaging deployment through that would
        report savings that never happened.

        Each euro is counted once: the boundary is a single date, lots are summed
        strictly before it and deposits strictly from it, so a purchase funded by a
        deposit in the same month contributes only the deposit.

        ``deployed_eur`` is kept alongside as the secondary figure. Once the rotation
        starts it will exceed ``money_in_eur``, and that divergence is exactly the
        useful signal: it is capital churn, not saving.

        ``net_eur`` (deployed minus the cost basis of lots closed in the window) is
        kept only for the tooltip and because it is what makes the cost-basis identity
        check work. Nothing averages it — doing so lets a sale retroactively erase a
        purchase that really happened.

        ``as_of`` defaults to today and exists so tests can pin the windows.
        """
        as_of = as_of or date.today()
        base_fx = await self._load_base_fx()

        rows = (await self.db.execute(
            select(TaxLot.open_date, TaxLot.close_date, TaxLot.cost_basis_eur)
        )).all()

        # Each lot contributes one positive leg on its open_date (the deployment)
        # and, once sold, a negative leg on its close_date (capital coming back).
        # Project into the base currency at the date the leg sits on, then
        # everything downstream is plain date arithmetic.
        legs: List[Tuple[date, Decimal]] = []
        first_open: Optional[date] = None

        for open_date, close_date, cost_basis_eur in rows:
            cost = cost_basis_eur or Decimal("0")
            if open_date:
                legs.append((open_date, base_fx.convert(cost, open_date)))
                if first_open is None or open_date < first_open:
                    first_open = open_date
            if close_date:
                legs.append((close_date, -base_fx.convert(cost, close_date)))

        # External cash, if the Flex Query has been set to deliver it. Deposits only:
        # get_deposits() excludes TRANSFER rows, so capital that arrived by broker
        # transfer is never read as a contribution.
        flow_repo = CashFlowRepository(self.db)
        deposits_from = await flow_repo.earliest_deposit_date()
        transfer_in_date = await flow_repo.earliest_transfer_in_date()
        deposit_legs: List[Tuple[date, Decimal]] = [
            (f.flow_date, base_fx.convert(f.amount_eur or Decimal("0"), f.flow_date))
            for f in await flow_repo.get_deposits()
        ]

        # The splice point: where the deposit ledger becomes complete. Recorded from the
        # statement period start, so a covered week with no deposits still counts as
        # covered. Falls back to the first deposit for ledgers ingested before the
        # setting existed, and is None when no deposits exist at all.
        coverage_from = await AppSettingsRepository(self.db).get_cash_flows_covered_from()
        if coverage_from is None:
            coverage_from = deposits_from

        # ...but never before the ledger's first row of any kind. A YTD statement in the
        # account's first year starts on 1 January while the account was funded weeks
        # later, and in that gap an empty deposit list means the money went to another
        # broker — not that none was added. Taking the statement's word for it drops
        # those purchases from both sides: past the lot cutoff, with no deposit to
        # replace them. Clamping forward hands the gap back to lot cost basis, which is
        # the correct source for any era the ledger does not reach.
        ledger_starts_at = await flow_repo.earliest_flow_date()
        if coverage_from and ledger_starts_at and ledger_starts_at > coverage_from:
            coverage_from = ledger_starts_at

        if first_open is None:
            return {
                "windows": [],
                "monthly": [],
                "first_contribution_date": None,
                "deposits_from": deposits_from.isoformat() if deposits_from else None,
                "coverage_from": coverage_from.isoformat() if coverage_from else None,
                "transfer_in_date": transfer_in_date.isoformat() if transfer_in_date else None,
                "base_currency": base_fx.base_currency,
            }

        monthly_net: Dict[str, Decimal] = defaultdict(Decimal)
        monthly_gross: Dict[str, Decimal] = defaultdict(Decimal)
        for on_date, amount in legs:
            month = on_date.strftime("%Y-%m")
            monthly_net[month] += amount
            if amount > 0:
                monthly_gross[month] += amount

        monthly = [
            {
                "month": month,
                "net_eur": round(float(monthly_net[month]), 2),
                "deployed_eur": round(float(monthly_gross[month]), 2),
            }
            for month in sorted(monthly_net)
        ]

        # Elapsed history caps every window's divisor: a four-month-old portfolio
        # must not report a 12-month average divided by 12. Floored at one day so
        # a portfolio opened today can't divide by zero.
        history_months = max((as_of - first_open).days, 1) / _DAYS_PER_MONTH

        windows = []
        for label, span in (("all", None), ("12m", 12), ("6m", 6), ("3m", 3)):
            if span is None:
                start, months, partial = first_open, history_months, False
            else:
                partial = history_months < span
                months = min(float(span), history_months)
                start = max(_shift_months(as_of, span), first_open)

            net = sum((a for d, a in legs if start <= d <= as_of), Decimal("0"))
            deployed = sum(
                (a for d, a in legs if start <= d <= as_of and a > 0), Decimal("0")
            )

            # Splice at the coverage boundary: lots strictly before it, deposits from it
            # onward. The two ranges don't overlap, so nothing is counted twice, and
            # together they cover the whole window — no clamped divisor needed.
            if coverage_from is None:
                method = "deployed"
                deposits = Decimal("0")
                money_in = deployed
            elif start >= coverage_from:
                method = "deposits"
                deposits = sum(
                    (a for d, a in deposit_legs if start <= d <= as_of), Decimal("0")
                )
                money_in = deposits
            else:
                method = "spliced"
                deposits = sum(
                    (a for d, a in deposit_legs if coverage_from <= d <= as_of),
                    Decimal("0"),
                )
                pre = sum(
                    (a for d, a in legs if start <= d < coverage_from and a > 0),
                    Decimal("0"),
                )
                money_in = pre + deposits

            windows.append({
                "label": label,
                "months": round(months, 2),
                "partial": partial,
                # The answer: era-correct money in, immune to rotation wherever a
                # deposit ledger exists.
                "money_in_eur": round(float(money_in), 2),
                "avg_money_in_per_month_eur": (
                    round(float(money_in) / months, 2) if months > 0 else 0.0
                ),
                "money_in_method": method,
                "deposits_eur": round(float(deposits), 2),
                # Secondary: capital put to work. Exceeds money_in once positions are
                # rotated, and that gap is the point of showing it.
                "deployed_eur": round(float(deployed), 2),
                "avg_deployed_per_month_eur": (
                    round(float(deployed) / months, 2) if months > 0 else 0.0
                ),
                "net_eur": round(float(net), 2),
            })

        return {
            "windows": windows,
            "monthly": monthly,
            "first_contribution_date": first_open.isoformat(),
            "deposits_from": deposits_from.isoformat() if deposits_from else None,
            "coverage_from": coverage_from.isoformat() if coverage_from else None,
            "transfer_in_date": transfer_in_date.isoformat() if transfer_in_date else None,
            "base_currency": base_fx.base_currency,
        }

    async def _realized_from_trades(self, base_fx: BaseFx) -> Optional[Dict]:
        """
        Compute realized totals from authoritative IBKR SELL trades, or return
        None if no trades have been ingested yet (caller then falls back to the
        market-price approximation over closed lots).

        Each SELL trade already carries IBKR's own FIFO realized P&L
        (fifoPnlRealized) and proceeds in the trade currency; we convert both to
        EUR at the trade date, then project into the base currency.
        """
        trades = (await self.db.execute(select(Trade))).scalars().all()
        if not trades:
            return None

        total_proceeds_eur = Decimal("0")
        total_gain_eur = Decimal("0")
        closed_security_ids: set = set()

        for t in trades:
            if (t.buy_sell or "").upper() != "SELL":
                continue
            currency = t.currency or "EUR"
            proceeds = t.proceeds if t.proceeds is not None else Decimal("0")
            gain = t.realized_pnl if t.realized_pnl is not None else Decimal("0")

            try:
                if currency == "EUR":
                    proceeds_eur = proceeds
                    gain_eur = gain
                else:
                    proceeds_eur = await self.currency_service.convert_to_eur(
                        amount=proceeds, from_currency=currency, target_date=t.trade_date
                    )
                    gain_eur = await self.currency_service.convert_to_eur(
                        amount=gain, from_currency=currency, target_date=t.trade_date
                    )
            except ValueError:
                logger.warning(
                    f"Realized: skipping trade {t.ib_key} — no FX for {currency} near {t.trade_date}"
                )
                continue

            total_proceeds_eur += base_fx.convert(proceeds_eur, t.trade_date)
            total_gain_eur += base_fx.convert(gain_eur, t.trade_date)
            if t.security_id is not None:
                closed_security_ids.add(t.security_id)

        return {
            "total_realized_gain_loss_eur": float(total_gain_eur),
            "total_realized_proceeds_eur": float(total_proceeds_eur),
            "total_realized_cost_basis_eur": float(total_proceeds_eur - total_gain_eur),
            "num_closed_positions": len(closed_security_ids),
        }

    async def get_realized_totals(self, base_fx: Optional[BaseFx] = None) -> Dict:
        """
        Aggregate realized gain/loss from closed tax lots.

        Proceeds are approximated as quantity × market_price × fx_rate on close_date
        (we don't persist actual sale proceeds from IBKR <Trades> yet). Lots that can't
        be priced within the 14-day fallback window are skipped and not counted.

        Values are returned in the base currency (proceeds converted at close_date,
        cost basis at open_date). Output keys keep the *_eur suffix.

        When authoritative IBKR <Trades> have been ingested, realized P&L is taken
        straight from each SELL trade's fifoPnlRealized/proceeds (exact, IBKR's own
        FIFO) instead of the market-price approximation below.
        """
        if base_fx is None:
            base_fx = await self._load_base_fx()

        trade_based = await self._realized_from_trades(base_fx)
        if trade_based is not None:
            return trade_based

        rows = await self.realized_rows_from_closed_lots(base_fx)
        total_proceeds_eur = sum((row["proceeds"] for row in rows), Decimal("0"))
        total_cost_basis_eur = sum((row["cost_basis"] for row in rows), Decimal("0"))

        return {
            "total_realized_gain_loss_eur": float(total_proceeds_eur - total_cost_basis_eur),
            "total_realized_proceeds_eur": float(total_proceeds_eur),
            "total_realized_cost_basis_eur": float(total_cost_basis_eur),
            "num_closed_positions": len({row["security_id"] for row in rows}),
        }

    async def holdings_snapshot_as_of(self, base_fx: BaseFx, on_date: date) -> List[Dict]:
        """
        Per-security holdings as they stood on ``on_date``, valued at that date's prices.

        The Swiss wealth-tax base (Steuerwert) is the **31 December** value, so the tax
        report cannot just use today's positions for a past year. Lot selection uses the
        same window as _calculate_daily_value (opened on or before the date, not closed
        before it) so the tax snapshot and the portfolio timeline agree.

        Securities whose price can't be resolved near ``on_date`` are skipped rather than
        counted at zero — a thin price history degrades the total instead of lying.
        """
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .where(
                and_(
                    TaxLot.open_date <= on_date,
                    or_(TaxLot.close_date.is_(None), TaxLot.close_date >= on_date),
                )
            )
            .order_by(Security.symbol.asc())
        )
        lots = result.all()
        if not lots:
            return []

        securities = {security for _, security in lots}
        price_cache, price_currency_cache = await self._preload_market_prices(
            securities, on_date, on_date
        )
        exchange_rate_cache = await self._preload_exchange_rates(
            securities, on_date, on_date, price_currency_cache=price_currency_cache
        )

        by_security: Dict[int, Dict] = {}
        for lot, security in lots:
            price = self._get_market_price_with_fallback(security.id, on_date, price_cache)
            if price is None:
                logger.warning(
                    f"Holdings snapshot {on_date}: no price for {security.symbol}, skipping lot {lot.id}"
                )
                continue

            price_currency = price_currency_cache.get(security.id, security.currency)
            if price_currency == "EUR":
                fx_rate = Decimal("1")
            else:
                fx_rate = self._get_exchange_rate_with_fallback(
                    price_currency, on_date, exchange_rate_cache
                )
                if fx_rate is None:
                    logger.warning(
                        f"Holdings snapshot {on_date}: no FX for {price_currency}, skipping lot {lot.id}"
                    )
                    continue

            row = by_security.setdefault(security.id, {
                "symbol": security.symbol,
                "quantity": Decimal("0"),
                "market_value": Decimal("0"),
                "cost_basis": Decimal("0"),
            })
            row["quantity"] += lot.quantity
            row["market_value"] += base_fx.convert(lot.quantity * price * fx_rate, on_date)
            row["cost_basis"] += base_fx.convert(lot.cost_basis_eur, lot.open_date)

        return list(by_security.values())

    async def realized_rows_from_closed_lots(
        self,
        base_fx: BaseFx,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> List[Dict]:
        """
        Per-closed-lot realized figures using the market-price approximation
        described in get_realized_totals, optionally restricted to lots closed
        within [start, end].

        Shared by the portfolio realized totals and the tax report's fallback so
        the two views can never disagree about the same closed lots. Lots that
        can't be priced (or converted) are skipped, exactly as before.
        """
        conditions = [TaxLot.is_open == False, TaxLot.close_date.isnot(None)]
        if start is not None:
            conditions.append(TaxLot.close_date >= start)
        if end is not None:
            conditions.append(TaxLot.close_date <= end)

        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .where(and_(*conditions))
            .order_by(TaxLot.close_date.asc())
        )
        closed_lots = result.all()
        if not closed_lots:
            return []

        close_dates = [lot.close_date for lot, _ in closed_lots]
        unique_securities = {security for _, security in closed_lots}
        price_cache, price_currency_cache = await self._preload_market_prices(
            unique_securities, min(close_dates), max(close_dates)
        )
        exchange_rate_cache = await self._preload_exchange_rates(
            unique_securities, min(close_dates), max(close_dates),
            price_currency_cache=price_currency_cache,
        )

        rows: List[Dict] = []
        for lot, security in closed_lots:
            price = self._get_market_price_with_fallback(
                security.id, lot.close_date, price_cache
            )
            if price is None:
                logger.warning(
                    f"Skipping realized calc for closed lot {lot.id} "
                    f"({security.symbol}): no price near {lot.close_date}"
                )
                continue

            price_currency = price_currency_cache.get(security.id, security.currency)
            if price_currency == "EUR":
                fx_rate = Decimal("1")
            else:
                fx_rate = self._get_exchange_rate_with_fallback(
                    price_currency, lot.close_date, exchange_rate_cache
                )
                if fx_rate is None:
                    logger.warning(
                        f"Skipping realized calc for closed lot {lot.id} "
                        f"({security.symbol}): no FX rate for {price_currency} near {lot.close_date}"
                    )
                    continue

            proceeds_eur = lot.quantity * price * fx_rate
            rows.append({
                "security_id": security.id,
                "symbol": security.symbol,
                "close_date": lot.close_date,
                "quantity": lot.quantity,
                "proceeds": base_fx.convert(proceeds_eur, lot.close_date),
                "cost_basis": base_fx.convert(lot.cost_basis_eur, lot.open_date),
            })
        return rows

    async def get_positions_breakdown(self) -> List[Dict]:
        """
        Get breakdown of all current positions by security.
        """
        today = date.today()

        # Get all open taxlots grouped by security
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .where(TaxLot.is_open == True)
            .order_by(Security.symbol.asc())
        )
        taxlots_with_securities = result.all()

        # Pre-load all market prices and exchange rates
        unique_securities = {security for _, security in taxlots_with_securities}
        price_cache, price_currency_cache = await self._preload_market_prices(unique_securities, today, today)
        exchange_rate_cache = await self._preload_exchange_rates(unique_securities, today, today, price_currency_cache=price_currency_cache)
        base_fx = await self._load_base_fx()

        # Pre-load analyst ratings
        from app.repositories.analyst_rating_repository import AnalystRatingRepository
        rating_repo = AnalystRatingRepository(self.db)
        all_ratings = await rating_repo.get_all()
        ratings_by_security = {rating.security_id: rating for rating in all_ratings}

        # Group by security
        positions = {}
        securities_by_id = {}

        for taxlot, security in taxlots_with_securities:
            if security.id not in positions:
                positions[security.id] = {
                    "security_id": security.id,
                    "symbol": security.symbol,
                    "description": security.description,
                    "isin": security.isin,
                    "currency": security.currency,
                    "exchange": security.exchange,
                    "quantity": Decimal("0.0"),
                    "cost_basis_eur": Decimal("0.0"),
                    "taxlots": []
                }
                securities_by_id[security.id] = security

            lot_cost_base = base_fx.convert(taxlot.cost_basis_eur, taxlot.open_date)
            positions[security.id]["quantity"] += taxlot.quantity
            positions[security.id]["cost_basis_eur"] += lot_cost_base
            positions[security.id]["taxlots"].append({
                "open_date": taxlot.open_date.isoformat(),
                "quantity": float(taxlot.quantity),
                "cost_basis": float(taxlot.cost_basis),
                "cost_basis_eur": float(lot_cost_base)
            })

        # Calculate market values using cached data with fallback
        positions_list = []
        for security_id, position in positions.items():
            security = securities_by_id[security_id]

            # Get latest market price with forward-fill fallback
            market_price = self._get_market_price_with_fallback(
                security.id, today, price_cache
            )

            if market_price:
                market_value = position["quantity"] * market_price

                # Use actual price currency if available
                price_currency = price_currency_cache.get(security_id, security.currency)

                # Convert to EUR with forward-fill fallback
                if price_currency != "EUR":
                    rate = self._get_exchange_rate_with_fallback(
                        price_currency, today, exchange_rate_cache
                    )
                    if rate:
                        market_value_eur = market_value * rate
                    else:
                        logger.warning(
                            f"No exchange rate for {price_currency} on {today}, "
                            f"cannot calculate market value for {security.symbol}"
                        )
                        market_value_eur = Decimal("0.0")
                else:
                    market_value_eur = market_value

                position["market_value_eur"] = float(base_fx.convert(market_value_eur, today))
                position["market_price"] = float(market_price)
            else:
                logger.warning(
                    f"No market price for {security.symbol} on {today}, "
                    f"setting market value to 0"
                )
                position["market_value_eur"] = 0.0
                position["market_price"] = None

            # Calculate gains
            cost_basis = position["cost_basis_eur"]
            market_value = Decimal(str(position["market_value_eur"]))
            gain_loss = market_value - cost_basis

            position["gain_loss_eur"] = float(gain_loss)
            position["gain_loss_percent"] = float(
                (gain_loss / cost_basis * 100) if cost_basis > 0 else 0
            )

            # Convert Decimal to float for JSON serialization
            position["quantity"] = float(position["quantity"])
            position["cost_basis_eur"] = float(position["cost_basis_eur"])

            # Add analyst rating if available
            rating = ratings_by_security.get(security_id)
            if rating:
                position["analyst_rating"] = {
                    "strong_buy": rating.strong_buy,
                    "buy": rating.buy,
                    "hold": rating.hold,
                    "sell": rating.sell,
                    "strong_sell": rating.strong_sell,
                    "total_ratings": rating.total_ratings,
                    "consensus": rating.consensus,
                    "last_updated": rating.last_updated.isoformat()
                }
            else:
                position["analyst_rating"] = None

            positions_list.append(position)

        # Sort by market value (largest first)
        positions_list.sort(key=lambda x: x["market_value_eur"], reverse=True)

        return positions_list

    async def calculate_xirr(
        self,
        start_date: date,
        end_date: date
    ) -> Tuple[Optional[float], int, date, date]:
        """
        Calculate XIRR (money-weighted annualized return) for the portfolio.

        Cash flows:
        - Negative: portfolio market value on start_date (money already invested)
        - Negative: each tax lot opened in (start_date, end_date] at its cost_basis_eur
        - Positive: portfolio market value on end_date (terminal value)

        Returns: (annualized_return_pct or None, num_cash_flows)
        """
        import pyxirr

        # Get ALL taxlots (open + closed) for correct historical XIRR
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .order_by(TaxLot.open_date.asc())
        )
        taxlots_with_securities = result.all()

        if not taxlots_with_securities:
            return None, 0, start_date, end_date

        # Pre-load caches for start and end dates
        unique_securities = {security for _, security in taxlots_with_securities}
        price_cache, price_currency_cache = await self._preload_market_prices(unique_securities, start_date, end_date)
        exchange_rate_cache = await self._preload_exchange_rates(unique_securities, start_date, end_date, price_currency_cache=price_currency_cache)
        base_fx = await self._load_base_fx()

        # Find the effective end date: latest date with actual market prices
        # This handles stale price data (e.g., prices only go up to Feb 2 but end_date is Feb 27)
        effective_end_date = self._find_latest_price_date(end_date, price_cache)
        if effective_end_date is None or effective_end_date <= start_date:
            logger.warning(f"No usable price data found near {end_date}")
            return None, 0, start_date, end_date

        # Similarly find effective start date
        effective_start_date = self._find_latest_price_date(start_date, price_cache)
        if effective_start_date is None:
            effective_start_date = start_date

        # Get portfolio market values on effective start and end dates
        start_value = self._calculate_daily_value(
            effective_start_date, taxlots_with_securities, price_cache, exchange_rate_cache,
            price_currency_cache=price_currency_cache, base_fx=base_fx
        )
        end_value = self._calculate_daily_value(
            effective_end_date, taxlots_with_securities, price_cache, exchange_rate_cache,
            price_currency_cache=price_currency_cache, base_fx=base_fx
        )

        start_mv = start_value["market_value_eur"]
        end_mv = end_value["market_value_eur"]

        # Build cash flows
        dates = []
        amounts = []

        # Initial outflow: portfolio value at effective start date
        if start_mv > 0:
            dates.append(effective_start_date)
            amounts.append(-start_mv)

        # Intermediate outflows: tax lots opened during (start_date, effective_end_date]
        for taxlot, security in taxlots_with_securities:
            if effective_start_date < taxlot.open_date <= effective_end_date:
                dates.append(taxlot.open_date)
                amounts.append(-float(base_fx.convert(taxlot.cost_basis_eur, taxlot.open_date)))

        # Terminal inflow: portfolio value at effective end date
        if end_mv > 0:
            dates.append(effective_end_date)
            amounts.append(end_mv)

        num_cash_flows = len(dates)

        # Need at least 2 cash flows (one negative, one positive)
        if num_cash_flows < 2 or start_mv <= 0 or end_mv <= 0:
            return None, num_cash_flows, effective_start_date, effective_end_date

        # For very short periods (< 30 days), return simple period return
        days_diff = (effective_end_date - effective_start_date).days
        if days_diff < 30:
            total_invested = -sum(a for a in amounts if a < 0)
            if total_invested > 0:
                simple_return = (end_mv / total_invested - 1) * 100
                return simple_return, num_cash_flows, effective_start_date, effective_end_date
            return None, num_cash_flows, effective_start_date, effective_end_date

        try:
            xirr_result = pyxirr.xirr(dates, amounts)
            if xirr_result is None:
                logger.warning("XIRR calculation did not converge")
                return None, num_cash_flows, effective_start_date, effective_end_date
            return xirr_result * 100, num_cash_flows, effective_start_date, effective_end_date
        except Exception as e:
            logger.warning(f"XIRR calculation failed: {e}")
            return None, num_cash_flows, effective_start_date, effective_end_date

    async def get_performance_attribution(
        self,
        start_date: date,
        end_date: date
    ) -> Dict:
        """
        Calculate per-security P&L attribution over a time period.

        For each security, computes:
        - Market value at start and end dates
        - New investment during the period (tax lots opened)
        - Pure P&L contribution = value_change - new_investment
        - Contribution % of total portfolio P&L
        """
        # Get ALL taxlots (open + closed) for correct historical attribution
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .order_by(TaxLot.open_date.asc())
        )
        taxlots_with_securities = result.all()

        if not taxlots_with_securities:
            return {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_pnl_eur": 0.0,
                "attributions": []
            }

        # Pre-load caches
        unique_securities = {security for _, security in taxlots_with_securities}
        price_cache, price_currency_cache = await self._preload_market_prices(unique_securities, start_date, end_date)
        exchange_rate_cache = await self._preload_exchange_rates(unique_securities, start_date, end_date, price_currency_cache=price_currency_cache)
        base_fx = await self._load_base_fx()

        # Find effective dates with actual price data
        effective_end = self._find_latest_price_date(end_date, price_cache)
        if effective_end is None or effective_end <= start_date:
            return {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_pnl_eur": 0.0,
                "attributions": []
            }

        effective_start = self._find_latest_price_date(start_date, price_cache)
        if effective_start is None:
            effective_start = start_date

        # Group tax lots by security
        security_map: Dict[int, Dict] = {}
        securities_by_id: Dict[int, Security] = {}

        for taxlot, security in taxlots_with_securities:
            if security.id not in security_map:
                security_map[security.id] = {
                    "start_market_value": Decimal("0.0"),
                    "end_market_value": Decimal("0.0"),
                    "new_investment": Decimal("0.0"),
                }
                securities_by_id[security.id] = security

            sid = security.id
            entry = security_map[sid]

            # Get FX rate helper — uses actual price currency, not security currency
            def get_eur_value(qty, price, sec, target_date):
                if price is None:
                    return Decimal("0.0")
                val = qty * price
                price_currency = price_currency_cache.get(sec.id, sec.currency)
                if price_currency != "EUR":
                    rate = self._get_exchange_rate_with_fallback(
                        price_currency, target_date, exchange_rate_cache
                    )
                    return val * rate if rate else Decimal("0.0")
                return val

            # Tax lot contributes to start value if opened on or before effective_start
            # AND not already closed by effective_start
            if taxlot.open_date <= effective_start:
                if not (taxlot.close_date and taxlot.close_date < effective_start):
                    price = self._get_market_price_with_fallback(sid, effective_start, price_cache)
                    entry["start_market_value"] += get_eur_value(taxlot.quantity, price, security, effective_start)

            # Tax lot contributes to end value if opened on or before effective_end
            # AND not already closed by effective_end
            if taxlot.open_date <= effective_end:
                if not (taxlot.close_date and taxlot.close_date < effective_end):
                    price = self._get_market_price_with_fallback(sid, effective_end, price_cache)
                    entry["end_market_value"] += get_eur_value(taxlot.quantity, price, security, effective_end)

            # New investment: opened during (effective_start, effective_end] (base, at open_date)
            if effective_start < taxlot.open_date <= effective_end:
                entry["new_investment"] += base_fx.convert(taxlot.cost_basis_eur, taxlot.open_date)

        # Calculate totals — market values converted to base at their effective date
        total_end_mv = sum(
            float(base_fx.convert(v["end_market_value"], effective_end))
            for v in security_map.values()
        )
        attributions = []

        for sid, entry in security_map.items():
            sec = securities_by_id[sid]
            start_mv = float(base_fx.convert(entry["start_market_value"], effective_start))
            end_mv = float(base_fx.convert(entry["end_market_value"], effective_end))
            new_inv = float(entry["new_investment"])
            value_change = end_mv - start_mv
            pnl = value_change - new_inv
            weight = (end_mv / total_end_mv * 100) if total_end_mv > 0 else 0.0

            attributions.append({
                "security_id": sid,
                "symbol": sec.symbol,
                "description": sec.description or sec.symbol,
                "start_market_value_eur": round(start_mv, 2),
                "end_market_value_eur": round(end_mv, 2),
                "new_investment_eur": round(new_inv, 2),
                "value_change_eur": round(value_change, 2),
                "pnl_contribution_eur": round(pnl, 2),
                "contribution_percent": 0.0,  # set below
                "weight_percent": round(weight, 2),
            })

        total_pnl = sum(a["pnl_contribution_eur"] for a in attributions)

        # Set contribution percentages
        for a in attributions:
            a["contribution_percent"] = round(
                (a["pnl_contribution_eur"] / total_pnl * 100) if total_pnl != 0 else 0.0, 2
            )

        # Sort by absolute P&L contribution descending
        attributions.sort(key=lambda a: abs(a["pnl_contribution_eur"]), reverse=True)

        return {
            "start_date": effective_start.isoformat(),
            "end_date": effective_end.isoformat(),
            "total_pnl_eur": round(total_pnl, 2),
            "attributions": attributions
        }

    def _find_latest_price_date(
        self,
        target_date: date,
        price_cache: Dict,
        max_lookback_days: int = 30
    ) -> Optional[date]:
        """
        Find the latest date on or before target_date that has price data
        for at least one security in the cache.
        """
        for days_back in range(0, max_lookback_days + 1):
            check_date = target_date - timedelta(days=days_back)
            for security_id, dates_dict in price_cache.items():
                if check_date in dates_dict:
                    return check_date
        return None

    async def _preload_market_prices(
        self,
        securities: set,
        start_date: date,
        end_date: date,
        lookback_days: int = 14
    ) -> Tuple[Dict, Dict]:
        """
        Pre-load all market prices for securities in date range.

        Extends the date range backwards by lookback_days to support
        forward-fill fallback logic when prices are missing.

        Returns: (
            {security_id: {date: price}},
            {security_id: currency}  -- actual price currency from DB
        )
        """
        from app.models.market_price import MarketPrice

        security_ids = [s.id for s in securities]

        # Extend start_date backwards to support forward-fill
        extended_start_date = start_date - timedelta(days=lookback_days)

        result = await self.db.execute(
            select(MarketPrice)
            .where(
                and_(
                    MarketPrice.security_id.in_(security_ids),
                    MarketPrice.date >= extended_start_date,
                    MarketPrice.date <= end_date
                )
            )
        )

        all_prices = result.scalars().all()

        # Build nested dict: {security_id: {date: price}}
        price_cache = {}
        price_currency_cache = {}
        for price in all_prices:
            if price.security_id not in price_cache:
                price_cache[price.security_id] = {}
            price_cache[price.security_id][price.date] = price.close_price
            # Track actual price currency per security
            price_currency_cache[price.security_id] = price.currency

        return price_cache, price_currency_cache

    async def _preload_exchange_rates(
        self,
        securities: set,
        start_date: date,
        end_date: date,
        lookback_days: int = 14,
        price_currency_cache: Optional[Dict] = None
    ) -> Dict:
        """
        Pre-load all exchange rates for currencies in date range.

        Extends the date range backwards by lookback_days to support
        forward-fill fallback logic when rates are missing.

        Args:
            price_currency_cache: Optional {security_id: currency} from _preload_market_prices.
                If provided, also loads FX rates for price currencies (which may differ
                from security.currency for cross-listed securities).

        Returns: {(from_currency, date): rate}
        """
        from app.models.exchange_rate import ExchangeRate

        currencies = {s.currency for s in securities if s.currency != 'EUR'}

        # Also include actual price currencies (may differ from security.currency)
        if price_currency_cache:
            for sec_id, price_curr in price_currency_cache.items():
                if price_curr != 'EUR':
                    currencies.add(price_curr)

        if not currencies:
            return {}

        # Extend start_date backwards to support forward-fill
        extended_start_date = start_date - timedelta(days=lookback_days)

        result = await self.db.execute(
            select(ExchangeRate)
            .where(
                and_(
                    ExchangeRate.from_currency.in_(currencies),
                    ExchangeRate.to_currency == 'EUR',
                    ExchangeRate.date >= extended_start_date,
                    ExchangeRate.date <= end_date
                )
            )
        )

        all_rates = result.scalars().all()

        # Build dict: {(from_currency, date): rate}
        rate_cache = {}
        for rate in all_rates:
            rate_cache[(rate.from_currency, rate.date)] = rate.rate

        return rate_cache

    def _get_market_price_with_fallback(
        self,
        security_id: int,
        target_date: date,
        price_cache: Dict,
        max_lookback_days: int = 14
    ) -> Optional[Decimal]:
        """
        Get market price for a date with forward-fill fallback.

        If price is missing for target_date, looks back up to max_lookback_days
        to find the most recent available price (carry-forward strategy).

        Args:
            security_id: ID of the security
            target_date: Date to get price for
            price_cache: Pre-loaded price cache {security_id: {date: price}}
            max_lookback_days: Maximum days to look back (default: 7)

        Returns:
            Price as Decimal, or None if no price found within lookback window
        """
        # Try exact date first
        market_price = price_cache.get(security_id, {}).get(target_date)
        if market_price:
            return market_price

        # Try previous days (up to max_lookback_days)
        for days_back in range(1, max_lookback_days + 1):
            fallback_date = target_date - timedelta(days=days_back)
            market_price = price_cache.get(security_id, {}).get(fallback_date)
            if market_price:
                logger.debug(
                    f"Using {days_back}-day-old price for security {security_id} "
                    f"on {target_date}: €{market_price} (from {fallback_date})"
                )
                return market_price

        # No price found within lookback window
        logger.warning(
            f"No price found for security {security_id} on {target_date} "
            f"(checked {max_lookback_days} days back)"
        )
        return None

    def _get_exchange_rate_with_fallback(
        self,
        from_currency: str,
        target_date: date,
        exchange_rate_cache: Dict,
        max_lookback_days: int = 14
    ) -> Optional[Decimal]:
        """
        Get exchange rate for a date with forward-fill fallback.

        If rate is missing for target_date, looks back up to max_lookback_days
        to find the most recent available rate (carry-forward strategy).

        Args:
            from_currency: Currency to convert from (e.g., 'USD')
            target_date: Date to get rate for
            exchange_rate_cache: Pre-loaded rate cache {(currency, date): rate}
            max_lookback_days: Maximum days to look back (default: 7)

        Returns:
            Exchange rate as Decimal, or None if no rate found within lookback window
        """
        # Try exact date first
        rate = exchange_rate_cache.get((from_currency, target_date))
        if rate:
            return rate

        # Try previous days (up to max_lookback_days)
        for days_back in range(1, max_lookback_days + 1):
            fallback_date = target_date - timedelta(days=days_back)
            rate = exchange_rate_cache.get((from_currency, fallback_date))
            if rate:
                logger.debug(
                    f"Using {days_back}-day-old exchange rate for {from_currency} "
                    f"on {target_date}: {rate} (from {fallback_date})"
                )
                return rate

        # No rate found within lookback window
        logger.warning(
            f"No exchange rate found for {from_currency} on {target_date} "
            f"(checked {max_lookback_days} days back)"
        )
        return None

    def _calculate_daily_value(
        self,
        target_date: date,
        taxlots_with_securities: List,
        price_cache: Dict,
        exchange_rate_cache: Dict,
        price_currency_cache: Optional[Dict] = None,
        base_fx: Optional[BaseFx] = None,
    ) -> Dict:
        """
        Calculate portfolio value for a specific date using cached data.
        Includes both open and closed lots — filters by open_date/close_date window.

        Values are returned in the base (display) currency: cost basis is converted
        at each lot's open_date, market value at target_date. When base is EUR this
        is a pass-through. Output keys keep the historical *_eur suffix.
        """
        base_fx = base_fx or BaseFx("EUR", {})
        total_cost_basis = Decimal("0.0")      # in base currency
        total_market_value_eur = Decimal("0.0")  # in EUR, converted once at the end

        for taxlot, security in taxlots_with_securities:
            # Only include taxlots opened on or before this date
            if taxlot.open_date > target_date:
                continue

            # Exclude taxlots that were closed before this date (lot is still active on its close date)
            if taxlot.close_date and taxlot.close_date < target_date:
                continue

            # Cost basis converts at the lot's open_date (stable, FX-independent line)
            total_cost_basis += base_fx.convert(taxlot.cost_basis_eur, taxlot.open_date)

            # Get market price with forward-fill fallback
            market_price = self._get_market_price_with_fallback(
                security.id, target_date, price_cache
            )

            if market_price:
                position_value = taxlot.quantity * market_price

                # Use actual price currency if available, fall back to security currency
                price_currency = price_currency_cache.get(security.id, security.currency) if price_currency_cache else security.currency

                # Convert to EUR with forward-fill fallback
                if price_currency != "EUR":
                    rate = self._get_exchange_rate_with_fallback(
                        price_currency, target_date, exchange_rate_cache
                    )
                    if rate:
                        total_market_value_eur += position_value * rate
                    else:
                        # Log but skip this position if no exchange rate available
                        logger.warning(
                            f"Skipping position for security {security.id} on {target_date}: "
                            f"no exchange rate for {price_currency}"
                        )
                else:
                    total_market_value_eur += position_value
            else:
                # Log but skip this position if no market price available
                logger.warning(
                    f"Skipping position for security {security.id} ({security.symbol}) on {target_date}: "
                    f"no market price available"
                )

        # Market value converts at the valuation date
        total_market_value = base_fx.convert(total_market_value_eur, target_date)
        gain_loss = total_market_value - total_cost_basis

        return {
            "date": target_date.isoformat(),
            "cost_basis_eur": float(total_cost_basis),
            "market_value_eur": float(total_market_value),
            "gain_loss_eur": float(gain_loss),
            "gain_loss_percent": float((gain_loss / total_cost_basis * 100) if total_cost_basis > 0 else 0)
        }

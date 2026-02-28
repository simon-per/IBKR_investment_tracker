"""
Benchmark Service
Simulates "what if I bought S&P 500 / NASDAQ instead?" using actual tax lot dates and amounts.
"""
import asyncio
import random
import logging
from typing import List, Dict, Optional, Tuple
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

import yfinance as yf

from app.models.taxlot import TaxLot
from app.models.security import Security
from app.models.benchmark_price import BenchmarkPrice
from app.models.exchange_rate import ExchangeRate

logger = logging.getLogger(__name__)


BENCHMARKS = {
    "sp500": {"ticker": "^GSPC", "currency": "USD", "name": "S&P 500"},
    "nasdaq": {"ticker": "^IXIC", "currency": "USD", "name": "NASDAQ Composite"},
}


class BenchmarkService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Price fetching / caching ───────────────────────────────────────

    async def _ensure_prices_available(
        self, ticker: str, start_date: date, end_date: date
    ) -> int:
        """Lazy-sync: fetch missing benchmark prices from Yahoo Finance."""
        # Check what we already have
        result = await self.db.execute(
            select(BenchmarkPrice.date)
            .where(
                and_(
                    BenchmarkPrice.ticker == ticker,
                    BenchmarkPrice.date >= start_date,
                    BenchmarkPrice.date <= end_date,
                )
            )
        )
        existing_dates = {row[0] for row in result.all()}

        # Build set of expected business days
        expected_dates = set()
        d = start_date
        while d <= end_date:
            if d.weekday() < 5:
                expected_dates.add(d)
            d += timedelta(days=1)

        missing = expected_dates - existing_dates
        if not missing:
            return 0

        # Fetch from Yahoo Finance (entire range; yfinance returns only trading days)
        logger.info(f"Fetching benchmark {ticker} prices: {len(missing)} dates missing")
        fetch_start = min(missing) - timedelta(days=5)  # small buffer
        fetch_end = max(missing) + timedelta(days=1)

        await asyncio.sleep(random.uniform(1.0, 2.0))  # rate-limit

        try:
            yf_ticker = yf.Ticker(ticker)
            hist = yf_ticker.history(
                start=fetch_start.isoformat(),
                end=fetch_end.isoformat(),
                auto_adjust=True,
            )

            if hist.empty:
                logger.warning(f"No data returned from Yahoo for {ticker}")
                return 0

            new_count = 0
            for idx, row in hist.iterrows():
                price_date = idx.date()
                if price_date in existing_dates:
                    continue

                self.db.add(BenchmarkPrice(
                    ticker=ticker,
                    date=price_date,
                    close_price=Decimal(str(round(row["Close"], 6))),
                    currency="USD",
                    source="yahoo_finance",
                ))
                existing_dates.add(price_date)
                new_count += 1

            await self.db.flush()
            logger.info(f"Cached {new_count} new {ticker} prices")
            return new_count

        except Exception as e:
            logger.error(f"Failed to fetch benchmark {ticker}: {e}")
            return 0

    async def _preload_benchmark_prices(
        self, ticker: str, start_date: date, end_date: date, lookback_days: int = 14
    ) -> Dict[date, Decimal]:
        """Load benchmark prices into {date: price} dict."""
        extended_start = start_date - timedelta(days=lookback_days)
        result = await self.db.execute(
            select(BenchmarkPrice)
            .where(
                and_(
                    BenchmarkPrice.ticker == ticker,
                    BenchmarkPrice.date >= extended_start,
                    BenchmarkPrice.date <= end_date,
                )
            )
        )
        return {bp.date: bp.close_price for bp in result.scalars().all()}

    async def _preload_usd_eur_rates(
        self, start_date: date, end_date: date, lookback_days: int = 14
    ) -> Dict[date, Decimal]:
        """Load USD→EUR exchange rates into {date: rate} dict."""
        extended_start = start_date - timedelta(days=lookback_days)
        result = await self.db.execute(
            select(ExchangeRate)
            .where(
                and_(
                    ExchangeRate.from_currency == "USD",
                    ExchangeRate.to_currency == "EUR",
                    ExchangeRate.date >= extended_start,
                    ExchangeRate.date <= end_date,
                )
            )
        )
        return {er.date: er.rate for er in result.scalars().all()}

    @staticmethod
    def _get_with_fallback(
        cache: Dict[date, Decimal], target_date: date, max_lookback: int = 14
    ) -> Optional[Decimal]:
        """Forward-fill: try exact date, then look back."""
        for days_back in range(0, max_lookback + 1):
            val = cache.get(target_date - timedelta(days=days_back))
            if val is not None:
                return val
        return None

    # ── Core benchmark calculation ─────────────────────────────────────

    async def calculate_benchmark_value_over_time(
        self,
        start_date: date,
        end_date: date,
        benchmark_key: str = "sp500",
    ) -> List[Dict]:
        """
        Simulate investing every tax lot into the benchmark index instead.

        For each tax lot:
          1. Convert cost_basis_eur → USD on the lot's open_date
          2. Divide by index price on that date → hypothetical_shares
        Then for each business day:
          benchmark_value_eur = sum(shares_i * index_price) * usd_to_eur_rate
        """
        bench = BENCHMARKS.get(benchmark_key)
        if not bench:
            return []

        ticker = bench["ticker"]

        # 1. Load all open tax lots
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .where(TaxLot.is_open == True)
            .order_by(TaxLot.open_date.asc())
        )
        taxlots_with_securities = result.all()
        if not taxlots_with_securities:
            return []

        # Earliest tax lot date determines how far back we need benchmark prices
        earliest_lot_date = min(tl.open_date for tl, _ in taxlots_with_securities)
        price_start = min(earliest_lot_date, start_date)

        # 2. Ensure benchmark prices are cached
        await self._ensure_prices_available(ticker, price_start, end_date)

        # 3. Pre-load caches
        bench_prices = await self._preload_benchmark_prices(ticker, price_start, end_date)
        usd_eur_rates = await self._preload_usd_eur_rates(price_start, end_date)

        # 4. Compute hypothetical shares for each tax lot
        #    shares_i = cost_basis_eur / usd_to_eur_rate / index_price
        #    i.e. EUR → USD → index units
        lot_shares: List[Tuple[date, Decimal]] = []  # (open_date, shares)

        for taxlot, _security in taxlots_with_securities:
            lot_date = taxlot.open_date
            index_price = self._get_with_fallback(bench_prices, lot_date)
            usd_eur = self._get_with_fallback(usd_eur_rates, lot_date)

            if not index_price or not usd_eur or usd_eur == 0:
                logger.warning(
                    f"Cannot compute benchmark shares for lot on {lot_date}: "
                    f"index={index_price}, usd_eur={usd_eur}"
                )
                continue

            # EUR → USD: divide by usd_to_eur rate
            cost_usd = taxlot.cost_basis_eur / usd_eur
            shares = cost_usd / index_price
            lot_shares.append((lot_date, shares))

        if not lot_shares:
            return []

        # 5. Walk business days and compute daily benchmark value
        timeline: List[Dict] = []
        current_date = start_date
        running_cost_basis = Decimal("0.0")

        # Pre-compute cumulative cost basis per date for efficiency
        lot_idx = 0
        # Sort lot_shares by date (should already be sorted)
        lot_shares.sort(key=lambda x: x[0])

        # Also keep original tax lots for cost basis tracking
        sorted_lots = sorted(
            [(tl.open_date, tl.cost_basis_eur) for tl, _ in taxlots_with_securities],
            key=lambda x: x[0],
        )
        lot_cost_idx = 0

        while current_date <= end_date:
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            # Accumulate cost basis for lots opened on or before this date
            while lot_cost_idx < len(sorted_lots) and sorted_lots[lot_cost_idx][0] <= current_date:
                running_cost_basis += sorted_lots[lot_cost_idx][1]
                lot_cost_idx += 1

            # Sum hypothetical shares for lots opened on or before this date
            total_shares = Decimal("0.0")
            for lot_date, shares in lot_shares:
                if lot_date <= current_date:
                    total_shares += shares

            if total_shares > 0:
                index_price = self._get_with_fallback(bench_prices, current_date)
                usd_eur = self._get_with_fallback(usd_eur_rates, current_date)

                if index_price and usd_eur:
                    bench_value_usd = total_shares * index_price
                    bench_value_eur = bench_value_usd * usd_eur
                    gain_loss = bench_value_eur - running_cost_basis

                    timeline.append({
                        "date": current_date.isoformat(),
                        "benchmark_value_eur": float(round(bench_value_eur, 2)),
                        "cost_basis_eur": float(round(running_cost_basis, 2)),
                        "gain_loss_eur": float(round(gain_loss, 2)),
                        "gain_loss_percent": float(
                            round((gain_loss / running_cost_basis * 100), 2)
                            if running_cost_basis > 0 else 0
                        ),
                    })
                else:
                    # Skip day if no data
                    pass
            else:
                # No lots opened yet → benchmark value is 0
                timeline.append({
                    "date": current_date.isoformat(),
                    "benchmark_value_eur": 0.0,
                    "cost_basis_eur": float(round(running_cost_basis, 2)),
                    "gain_loss_eur": 0.0,
                    "gain_loss_percent": 0.0,
                })

            current_date += timedelta(days=1)

        return timeline

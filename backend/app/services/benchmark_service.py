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
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

import yfinance as yf

from app.models.taxlot import TaxLot
from app.models.security import Security
from app.models.benchmark_price import BenchmarkPrice
from app.models.exchange_rate import ExchangeRate
from app.models.benchmark_timeline_cache import BenchmarkTimelineCache

logger = logging.getLogger(__name__)


BENCHMARKS = {
    "sp500": {"ticker": "^GSPC", "currency": "USD", "name": "S&P 500"},
    "nasdaq": {"ticker": "^IXIC", "currency": "USD", "name": "NASDAQ Composite"},
    "msci_world": {"ticker": "URTH", "currency": "USD", "name": "MSCI World"},
    "dax": {"ticker": "^GDAXI", "currency": "EUR", "name": "DAX"},
    "euro_stoxx_50": {"ticker": "^STOXX50E", "currency": "EUR", "name": "Euro Stoxx 50"},
    "ftse100": {"ticker": "^FTSE", "currency": "GBP", "name": "FTSE 100"},
    "nikkei225": {"ticker": "^N225", "currency": "JPY", "name": "Nikkei 225"},
    "cac40": {"ticker": "^FCHI", "currency": "EUR", "name": "CAC 40"},
}


class BenchmarkService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Price fetching / caching ───────────────────────────────────────

    async def _ensure_prices_available(
        self, ticker: str, start_date: date, end_date: date, currency: str = "USD"
    ) -> int:
        """Lazy-sync: fetch missing benchmark prices from Yahoo Finance."""
        # Check what we already have (include buffer zone to avoid duplicate inserts)
        buffer_start = start_date - timedelta(days=10)
        result = await self.db.execute(
            select(BenchmarkPrice.date)
            .where(
                and_(
                    BenchmarkPrice.ticker == ticker,
                    BenchmarkPrice.date >= buffer_start,
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
                    currency=currency,
                    source="yahoo_finance",
                ))
                existing_dates.add(price_date)
                new_count += 1

            await self.db.flush()
            logger.info(f"Cached {new_count} new {ticker} prices")
            return new_count

        except Exception as e:
            logger.error(f"Failed to fetch benchmark {ticker}: {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass
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

    async def _preload_fx_rates(
        self, from_currency: str, start_date: date, end_date: date, lookback_days: int = 14
    ) -> Dict[date, Decimal]:
        """Load from_currency→EUR exchange rates into {date: rate} dict."""
        extended_start = start_date - timedelta(days=lookback_days)
        result = await self.db.execute(
            select(ExchangeRate)
            .where(
                and_(
                    ExchangeRate.from_currency == from_currency,
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

    # ── Cache management ───────────────────────────────────────────────

    async def _read_cache(
        self, benchmark_key: str, start_date: date, end_date: date
    ) -> Dict[date, Dict]:
        """Read cached benchmark timeline data for the given range."""
        result = await self.db.execute(
            select(BenchmarkTimelineCache)
            .where(
                and_(
                    BenchmarkTimelineCache.benchmark_key == benchmark_key,
                    BenchmarkTimelineCache.date >= start_date,
                    BenchmarkTimelineCache.date <= end_date,
                )
            )
        )
        cached = {}
        for row in result.scalars().all():
            cached[row.date] = {
                "date": row.date.isoformat(),
                "benchmark_value_eur": float(row.benchmark_value_eur),
                "cost_basis_eur": float(row.cost_basis_eur),
                "gain_loss_eur": float(row.gain_loss_eur),
                "gain_loss_percent": float(row.gain_loss_percent),
            }
        return cached

    async def _write_cache(
        self, benchmark_key: str, points: List[Dict]
    ) -> None:
        """Write computed benchmark timeline points to cache."""
        for point in points:
            point_date = date.fromisoformat(point["date"])
            self.db.add(BenchmarkTimelineCache(
                benchmark_key=benchmark_key,
                date=point_date,
                benchmark_value_eur=Decimal(str(point["benchmark_value_eur"])),
                cost_basis_eur=Decimal(str(point["cost_basis_eur"])),
                gain_loss_eur=Decimal(str(point["gain_loss_eur"])),
                gain_loss_percent=Decimal(str(point["gain_loss_percent"])),
            ))
        await self.db.flush()

    async def clear_cache(self, benchmark_key: Optional[str] = None) -> int:
        """Clear cached benchmark timeline data. If benchmark_key is None, clear all."""
        if benchmark_key:
            result = await self.db.execute(
                delete(BenchmarkTimelineCache)
                .where(BenchmarkTimelineCache.benchmark_key == benchmark_key)
            )
        else:
            result = await self.db.execute(
                delete(BenchmarkTimelineCache)
            )
        await self.db.flush()
        return result.rowcount

    async def clear_cache_recent_days(self, days: int = 7) -> int:
        """Clear cache entries for the last N days (prices may have been updated)."""
        cutoff = date.today() - timedelta(days=days)
        result = await self.db.execute(
            delete(BenchmarkTimelineCache)
            .where(BenchmarkTimelineCache.date >= cutoff)
        )
        await self.db.flush()
        return result.rowcount

    # ── Core benchmark calculation ─────────────────────────────────────

    async def _ensure_fx_rates_available(
        self, currency: str, start_date: date, end_date: date
    ) -> None:
        """Lazy-fetch missing FX rates for currency→EUR via CurrencyService."""
        if currency == "EUR":
            return

        from app.services.currency_service import CurrencyService

        currency_service = CurrencyService(self.db)
        # Batch fetch rates in 30-day chunks covering the full range
        current = start_date
        while current <= end_date:
            try:
                await currency_service._batch_fetch_rates(
                    from_currency=currency,
                    target_date=current,
                    to_currency="EUR",
                    days_back=30,
                )
            except Exception as e:
                logger.error(f"Failed to fetch FX rates {currency}→EUR for {current}: {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    pass
            current += timedelta(days=30)

    async def calculate_benchmark_value_over_time(
        self,
        start_date: date,
        end_date: date,
        benchmark_key: str = "sp500",
    ) -> List[Dict]:
        """
        Simulate investing every tax lot into the benchmark index instead.

        Uses a persistent cache: historical values never change, so we compute
        once and only recompute missing/recent days.

        For each tax lot:
          1. Convert cost_basis_eur → benchmark currency on the lot's open_date
          2. Divide by index price on that date → hypothetical_shares
        Then for each business day:
          benchmark_value_eur = sum(shares_i * index_price) * fx_to_eur_rate
        """
        bench = BENCHMARKS.get(benchmark_key)
        if not bench:
            return []

        ticker = bench["ticker"]
        currency = bench["currency"]
        is_eur_benchmark = currency == "EUR"

        # ── Step 0: Check cache ──────────────────────────────────────
        cached_data = await self._read_cache(benchmark_key, start_date, end_date)

        # Build the set of expected business days in [start_date, end_date]
        expected_dates = set()
        d = start_date
        while d <= end_date:
            if d.weekday() < 5:
                expected_dates.add(d)
            d += timedelta(days=1)

        missing_dates = expected_dates - set(cached_data.keys())

        if not missing_dates:
            # Full cache hit — return cached data sorted by date
            logger.info(f"Benchmark {benchmark_key}: full cache hit ({len(cached_data)} points)")
            return sorted(cached_data.values(), key=lambda x: x["date"])

        logger.info(
            f"Benchmark {benchmark_key}: {len(cached_data)} cached, "
            f"{len(missing_dates)} to compute"
        )

        # ── Step 1: Load all open tax lots ───────────────────────────
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

        # ── Step 2: Ensure benchmark prices are cached ───────────────
        try:
            await self._ensure_prices_available(ticker, price_start, end_date, currency=currency)
        except Exception as e:
            logger.warning(f"Could not fetch new benchmark prices for {ticker}, using cached: {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass

        # ── Step 3: Ensure FX rates are available ────────────────────
        if not is_eur_benchmark:
            await self._ensure_fx_rates_available(currency, price_start, end_date)

        # ── Step 4: Pre-load caches ──────────────────────────────────
        bench_prices = await self._preload_benchmark_prices(ticker, price_start, end_date)
        fx_rates: Dict[date, Decimal] = {}
        if not is_eur_benchmark:
            fx_rates = await self._preload_fx_rates(currency, price_start, end_date)

        # ── Step 5: Compute hypothetical shares for each tax lot ─────
        lot_shares: List[Tuple[date, Decimal]] = []

        for taxlot, _security in taxlots_with_securities:
            lot_date = taxlot.open_date
            index_price = self._get_with_fallback(bench_prices, lot_date)

            if not index_price:
                logger.warning(f"No benchmark price for {lot_date}, skipping lot")
                continue

            if is_eur_benchmark:
                shares = taxlot.cost_basis_eur / index_price
            else:
                fx_rate = self._get_with_fallback(fx_rates, lot_date)
                if not fx_rate or fx_rate == 0:
                    logger.warning(
                        f"Cannot compute benchmark shares for lot on {lot_date}: "
                        f"fx_rate={fx_rate}"
                    )
                    continue
                cost_foreign = taxlot.cost_basis_eur / fx_rate
                shares = cost_foreign / index_price

            lot_shares.append((lot_date, shares))

        if not lot_shares:
            return []

        # Sort lot_shares by date
        lot_shares.sort(key=lambda x: x[0])

        # Also keep original tax lots for cost basis tracking
        sorted_lots = sorted(
            [(tl.open_date, tl.cost_basis_eur) for tl, _ in taxlots_with_securities],
            key=lambda x: x[0],
        )

        # ── Step 6: Walk only MISSING business days ──────────────────
        # We need cumulative state, so walk ALL days from start_date but
        # only record points for missing dates.
        new_points: List[Dict] = []
        current_date = start_date
        running_cost_basis = Decimal("0.0")
        lot_cost_idx = 0
        lot_shares_idx = 0  # cumulative pointer for shares (O(n) instead of O(n²))
        running_shares = Decimal("0.0")

        while current_date <= end_date:
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            # Accumulate cost basis for lots opened on or before this date
            while lot_cost_idx < len(sorted_lots) and sorted_lots[lot_cost_idx][0] <= current_date:
                running_cost_basis += sorted_lots[lot_cost_idx][1]
                lot_cost_idx += 1

            # Accumulate shares for lots opened on or before this date (O(n) fix)
            while lot_shares_idx < len(lot_shares) and lot_shares[lot_shares_idx][0] <= current_date:
                running_shares += lot_shares[lot_shares_idx][1]
                lot_shares_idx += 1

            # Only compute for missing dates
            if current_date in missing_dates:
                if running_shares > 0:
                    index_price = self._get_with_fallback(bench_prices, current_date)

                    if is_eur_benchmark:
                        if index_price:
                            bench_value_eur = running_shares * index_price
                            gain_loss = bench_value_eur - running_cost_basis

                            new_points.append({
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
                        fx_rate = self._get_with_fallback(fx_rates, current_date)
                        if index_price and fx_rate:
                            bench_value_foreign = running_shares * index_price
                            bench_value_eur = bench_value_foreign * fx_rate
                            gain_loss = bench_value_eur - running_cost_basis

                            new_points.append({
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
                    new_points.append({
                        "date": current_date.isoformat(),
                        "benchmark_value_eur": 0.0,
                        "cost_basis_eur": float(round(running_cost_basis, 2)),
                        "gain_loss_eur": 0.0,
                        "gain_loss_percent": 0.0,
                    })

            current_date += timedelta(days=1)

        # ── Step 7: Store new points in cache ────────────────────────
        if new_points:
            try:
                await self._write_cache(benchmark_key, new_points)
                logger.info(f"Cached {len(new_points)} new benchmark timeline points for {benchmark_key}")
            except Exception as e:
                logger.warning(f"Failed to write benchmark cache: {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    pass

        # ── Step 8: Merge cached + new and return ────────────────────
        # Add new points to cached_data dict
        for point in new_points:
            cached_data[date.fromisoformat(point["date"])] = point

        return sorted(cached_data.values(), key=lambda x: x["date"])

"""
Scheduler Service
Handles automated daily synchronization of IBKR data and market prices.
"""
import logging
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import date, timedelta

from app.config import settings
from app.database import AsyncSessionLocal
from app.single_flight import SYNC_PIPELINE, SyncBusy, single_flight
from app.services.ibkr_service import IBKRService, FLEX_RETRY_DELAYS_PATIENT
from app.services.market_data_service import MarketDataService
from app.services.currency_service import CurrencyService
from app.services.sync_helper import ingest_flex_statement
from app.repositories.security_repository import SecurityRepository
from app.repositories.sync_run_repository import SyncRunRepository, utc_iso
from app.services.benchmark_service import BenchmarkService, BENCHMARKS
from app.models.benchmark_price import BenchmarkPrice
from app.models.dividend_payment import DividendPayment
from app.models.market_price import MarketPrice
from app.models.security import Security
from app.models.taxlot import TaxLot
from app.models.ticker_mapping import TickerMapping
from sqlalchemy import select, distinct, func, and_

logger = logging.getLogger(__name__)

# How old the newest cached price for a held security may be before we say so.
# Generous enough to absorb a weekend plus a public holiday, and the 13:00 job running
# before the US open, so a warning means something is actually wrong rather than "the
# market was shut". Five days is roughly one trading week of silence.
STALE_PRICE_DAYS = 5

# How late a missed run may still be honoured.
#
# APScheduler runs in-process with the app, so a `docker compose down` that overlaps a
# Berlin slot loses that slot outright — which is what happened to the 2026-07-30 08:00
# full_sync, and why CLAUDE.md tells humans not to push near a slot. With a persistent
# job store the missed run time survives the restart, and this is the window in which
# it is still worth running.
#
# Thirty minutes is chosen from both ends. A `build --no-cache` rebuild takes a couple
# of minutes, so it comfortably covers a deploy. And it is short enough that a genuinely
# long outage does *not* dump four missed slots onto a cold container: anything older is
# dropped, so only the slot the outage actually straddled is recovered. `coalesce` then
# collapses repeats of the same job into one.
MISFIRE_GRACE_SECONDS = 30 * 60


def _collect_warnings(job_result: dict, *step_results) -> None:
    """
    Hoist the steps' warnings to the top of a job's result dict.

    `_record_run` reads `result["warnings"]`, and a job's own dict never had that key —
    so anything a step reported was buried inside `details` and never rendered as a
    warning. The steps that produce them (`ingest_flex_statement`'s skipped currencies
    and split purges, `sync_market_data`'s stale prices) are exactly the events that
    should be visible without opening the JSON.
    """
    warnings = []
    for step in step_results:
        warnings.extend((step or {}).get("warnings") or [])
    if warnings:
        job_result["warnings"] = warnings


class SchedulerService:
    """
    Service for scheduling automated data synchronization tasks.

    Runs 3 times daily (Europe/Berlin):
    - 08:00: Full sync (IBKR + 730 days market data) — fills historical gaps gradually
    - 15:00: Market data only (7 days) — picks up EU closing prices
    - 22:00: Market data only (7 days) — picks up US closing prices
    """

    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.last_sync_result: Optional[dict] = None

    async def sync_ibkr_data(self) -> dict:
        """
        Sync securities and tax lots from IBKR Flex Query.

        Returns:
            Summary of synced data
        """
        logger.info("Starting scheduled IBKR data sync...")

        async with AsyncSessionLocal() as db:
            try:
                # Initialize services and repositories
                # Step 1: Fetch data from IBKR. Nobody is waiting on a scheduled run,
                # so wait longer between attempts rather than risking IBKR's rate cap.
                logger.info("Fetching data from IBKR Flex Query...")
                flex_data = await IBKRService().fetch_flex_data(
                    retry_delays=FLEX_RETRY_DELAYS_PATIENT
                )

                # Steps 2-6, shared with POST /api/sync/ibkr and the offline XML ingest so
                # every path reconciles in exactly the same order.
                ingested = await ingest_flex_statement(db, flex_data)

                # Commit transaction
                await db.commit()

                # Same warnings as the manual endpoint: unsupported currencies plus any
                # Flex XML schema drift the sanitizer worked around, so a scheduled sync
                # surfaces it in /api/scheduler/status instead of only in the logs.
                warnings = ingested.pop("warnings", [])
                result = {
                    "status": "success",
                    "message": "Successfully synced data from IBKR",
                    **ingested,
                    "timestamp": utc_iso(datetime.now()),
                }
                if warnings:
                    result["warnings"] = warnings

                logger.info(
                    f"IBKR sync completed: {ingested['securities_synced']} securities, "
                    f"{ingested['taxlots_synced']} taxlots"
                )
                return result

            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to sync IBKR data: {str(e)}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Failed to sync IBKR data: {str(e)}",
                    "timestamp": utc_iso(datetime.now())
                }

    async def sync_market_data(self, days_back: int = 730) -> dict:
        """
        Sync market prices from Yahoo Finance for all securities.
        Only fetches missing dates (incremental sync).

        Args:
            days_back: Number of days to look back (default 730 = 2 years)

        Returns:
            Summary of synced data
        """
        logger.info("Starting scheduled market data sync...")

        async with AsyncSessionLocal() as db:
            try:
                market_data_service = MarketDataService(db)
                security_repo = SecurityRepository(db)

                # Get all securities
                securities = await security_repo.get_all(limit=1000)

                if not securities:
                    logger.info("No securities found to sync")
                    return {
                        "status": "success",
                        "message": "No securities found to sync",
                        "securities_processed": 0,
                        "prices_fetched": 0,
                        "timestamp": utc_iso(datetime.now())
                    }

                total_prices = 0
                errors = []

                logger.info(f"Syncing market data for {len(securities)} securities...")

                for security in securities:
                    try:
                        logger.info(f"Fetching prices for {security.symbol} ({security.exchange})...")

                        # Fetch historical data
                        # The service will only fetch missing dates
                        prices_count = await market_data_service.sync_security_prices(
                            security,
                            days_back=days_back
                        )

                        total_prices += prices_count
                        logger.info(f"Fetched {prices_count} price points for {security.symbol}")

                    except Exception as e:
                        error_msg = f"Failed to fetch prices for {security.symbol}: {str(e)}"
                        logger.error(error_msg)
                        errors.append(error_msg)

                # Commit all price data
                await db.commit()

                result = {
                    "status": "success" if not errors else "partial_success",
                    "message": f"Synced market data for {len(securities)} securities",
                    "securities_processed": len(securities),
                    "prices_fetched": total_prices,
                    "timestamp": utc_iso(datetime.now())
                }

                if errors:
                    result["errors"] = errors
                    result["errors_count"] = len(errors)

                # A fetch that returned nothing is not an error anywhere: the position
                # simply gets no price, and _calculate_daily_value / the positions
                # endpoint value it at 0.00 and move on. SBI@TSE lost 446.93 CHF off the
                # portfolio total that way with nothing, anywhere, saying so.
                #
                # Guarded on its own: this is a diagnostic, and it must never be the
                # reason a sync that actually fetched prices reports failure.
                diagnostics = []
                try:
                    diagnostics += await self.find_stale_priced_securities(db)
                except Exception as e:
                    logger.warning(f"Could not check for stale prices: {e}")
                # Same shape, same reasoning, for the dividend side: an estimate row
                # older than its mapping came from a different ticker and silently
                # keeps driving the forecast. Separately guarded so one diagnostic
                # failing cannot hide the other.
                try:
                    diagnostics += await self.find_dividends_predating_their_mapping(db)
                except Exception as e:
                    logger.warning(f"Could not check dividend provenance: {e}")
                if diagnostics:
                    result["warnings"] = diagnostics

                logger.info(f"Market data sync completed: {total_prices} prices fetched")
                return result

            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to sync market data: {str(e)}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Failed to sync market data: {str(e)}",
                    "timestamp": utc_iso(datetime.now())
                }

    async def find_stale_priced_securities(
        self, db: AsyncSession, as_of: Optional[date] = None
    ) -> list:
        """
        Held securities whose newest cached price is missing or too old.

        Restricted to securities with open tax lots, because those are the only ones
        whose price actually moves a number the user sees — a fully-sold security going
        quiet is expected, not a fault.

        Returns human-readable strings, ready for `warnings[]`, so the dashboard and
        `/api/scheduler/history` surface them without needing to know the shape.
        """
        as_of = as_of or date.today()
        cutoff = as_of - timedelta(days=STALE_PRICE_DAYS)

        # Deliberately two queries rather than one join. Joining taxlots to
        # market_prices multiplies them — a security with 100 open lots and 730 cached
        # closes is 73,000 rows to aggregate, and the portfolio holds 972 lots against
        # 21,000 prices. Two indexed scans and a dict lookup cost nothing by comparison.
        held = await db.execute(
            select(Security.id, Security.symbol, Security.exchange)
            .join(TaxLot, TaxLot.security_id == Security.id)
            .where(TaxLot.is_open == True)  # noqa: E712 — SQLAlchemy needs the operator
            .group_by(Security.id)
        )
        held_rows = held.all()
        if not held_rows:
            return []

        newest = await db.execute(
            select(MarketPrice.security_id, func.max(MarketPrice.date))
            .where(MarketPrice.security_id.in_([row[0] for row in held_rows]))
            .group_by(MarketPrice.security_id)
        )
        newest_by_security = dict(newest.all())

        warnings = []
        for security_id, symbol, exchange in held_rows:
            name = f"{symbol}@{exchange}" if exchange else str(symbol)
            latest = newest_by_security.get(security_id)
            if latest is None:
                warnings.append(
                    f"{name}: no cached price at all — the position is being "
                    f"valued at 0.00. Check the ticker_mappings row and the Yahoo symbol"
                )
            elif latest < cutoff:
                warnings.append(
                    f"{name}: newest price is {latest} "
                    f"({(as_of - latest).days} days old) — the price feed looks broken"
                )

        if warnings:
            logger.warning(f"{len(warnings)} security(ies) with missing or stale prices")
        return warnings

    async def find_dividends_predating_their_mapping(self, db: AsyncSession) -> list:
        """
        Held securities whose dividend estimates were fetched under an older ticker.

        The price side of this class has been watched since
        `find_stale_priced_securities` — a missing price now warns. Nothing watched
        the dividend side, which is why SBI's two rows survived the mapping's
        correction to SBI.TO, the price purge, and a month of syncs: estimates are
        keyed to whatever Yahoo ticker resolved when they were written, and
        `_forecast_inputs()` then let them alone define a gold miner's payout
        schedule while the real IBKR payment was skipped.

        The signal is specific rather than a staleness guess: a row computed before
        its mapping's `updated_at` came from a *different* ticker. A genuine
        non-payer has no estimate rows at all, so it cannot trip this; a payer that
        simply hasn't declared lately has rows newer than the mapping.

        Returns `warnings[]`-ready strings, like its price-side counterpart.
        """
        held = await db.execute(
            select(Security.id, Security.symbol, Security.exchange)
            .join(TaxLot, TaxLot.security_id == Security.id)
            .where(TaxLot.is_open == True)  # noqa: E712 — SQLAlchemy needs the operator
            .group_by(Security.id)
        )
        held_rows = held.all()
        if not held_rows:
            return []

        # Same two-queries-not-a-join reasoning as above: joining lots to dividend
        # rows multiplies them for no benefit.
        newest = await db.execute(
            select(DividendPayment.security_id, func.max(DividendPayment.last_computed))
            .where(
                and_(
                    DividendPayment.security_id.in_([row[0] for row in held_rows]),
                    DividendPayment.source == "yfinance_estimate",
                )
            )
            .group_by(DividendPayment.security_id)
        )
        newest_by_security = dict(newest.all())

        mappings = await db.execute(
            select(TickerMapping.ibkr_symbol, TickerMapping.ibkr_exchange,
                   TickerMapping.yahoo_ticker, TickerMapping.updated_at)
            .where(TickerMapping.is_active == True)  # noqa: E712
        )
        mapping_by_key = {
            (sym, exch): (ticker, updated) for sym, exch, ticker, updated in mappings.all()
        }

        warnings = []
        for security_id, symbol, exchange in held_rows:
            newest_row = newest_by_security.get(security_id)
            if newest_row is None:
                continue  # no estimates: a non-payer, or IBKR-only. Nothing to suspect.
            mapping = mapping_by_key.get((symbol, exchange))
            if not mapping:
                continue  # resolved by suffix or bare symbol; no mapping row to compare
            ticker, updated_at = mapping
            if updated_at is None or newest_row >= updated_at:
                continue

            name = f"{symbol}@{exchange}" if exchange else str(symbol)
            warnings.append(
                f"{name}: dividend estimates were last computed "
                f"{newest_row:%Y-%m-%d} but the mapping to {ticker} changed "
                f"{updated_at:%Y-%m-%d} — those rows came from a different ticker and "
                f"still drive the forecast. Clear them with "
                f"`python -m app.cli.purge_dividend_estimates {symbol} {exchange}`"
            )

        if warnings:
            logger.warning(
                f"{len(warnings)} security(ies) hold dividend estimates older than "
                f"their ticker mapping"
            )
        return warnings

    async def sync_exchange_rates(self, days_back: int = 30) -> dict:
        """
        Sync exchange rates from Frankfurter API for all non-EUR currencies
        used by securities in the portfolio.

        Args:
            days_back: Number of days to fetch rates for

        Returns:
            Summary of synced rates
        """
        logger.info("Starting exchange rate sync...")

        async with AsyncSessionLocal() as db:
            try:
                security_repo = SecurityRepository(db)
                currency_service = CurrencyService(db)

                # Currencies actually held, plus the ones we keep warm on spec.
                securities = await security_repo.get_all(limit=1000)
                held = {
                    sec.currency for sec in securities
                    if sec.currency and sec.currency != "EUR"
                }

                # WARM_CURRENCIES are the ones the fallback provider has to serve, and it
                # is latest-only: their history exists only because this job records a
                # rate every day. Warming them costs one extra request for the whole set,
                # and it is what lets a position in a new currency be valued from the day
                # its statement lands rather than from the day we happen to notice.
                currencies = held | currency_service.WARM_CURRENCIES

                logger.info(f"Syncing exchange rates for currencies: {sorted(currencies)}")

                today = date.today()

                warmed = await currency_service.warm_rates(
                    currencies, target_date=today, days_back=days_back
                )
                total_rates = warmed["frankfurter"] + warmed["fallback"]

                # Also keep EUR->base rates fresh for the selectable base currencies
                # (CHF/USD) so switching the display currency is instant.
                for base in ("CHF", "USD"):
                    try:
                        await currency_service._batch_fetch_rates(
                            from_currency="EUR",
                            target_date=today,
                            to_currency=base,
                            days_back=days_back
                        )
                        logger.info(f"Fetched EUR->{base} exchange rates")
                        total_rates += 1
                    except Exception as e:
                        logger.error(f"Failed to fetch EUR->{base} rates: {e}")

                await db.commit()

                result = {
                    "status": "success",
                    "currencies_synced": total_rates,
                    "currencies": sorted(currencies),
                    "held_currencies": sorted(held),
                    "timestamp": utc_iso(datetime.now())
                }
                logger.info(f"Exchange rate sync completed: {total_rates} currencies updated")
                return result

            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to sync exchange rates: {str(e)}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Failed to sync exchange rates: {str(e)}",
                    "timestamp": utc_iso(datetime.now())
                }

    async def sync_benchmark_prices(self) -> dict:
        """
        Sync last 7 days of benchmark prices for benchmarks already in the DB.
        Only syncs benchmarks the user has previously selected (i.e., have cached prices).
        """
        logger.info("Starting benchmark price sync...")

        async with AsyncSessionLocal() as db:
            try:
                # Find which benchmark tickers already have data in the DB
                result = await db.execute(
                    select(distinct(BenchmarkPrice.ticker))
                )
                existing_tickers = {row[0] for row in result.all()}

                if not existing_tickers:
                    logger.info("No benchmarks in DB to refresh")
                    return {"status": "success", "benchmarks_synced": 0}

                # Map tickers back to benchmark info for currency
                ticker_to_benchmark = {
                    info["ticker"]: info for info in BENCHMARKS.values()
                }

                bench_service = BenchmarkService(db)
                today = date.today()
                start = today - timedelta(days=7)
                synced = 0

                for ticker in existing_tickers:
                    bench_info = ticker_to_benchmark.get(ticker)
                    currency = bench_info["currency"] if bench_info else "USD"
                    try:
                        count = await bench_service._ensure_prices_available(
                            ticker, start, today, currency=currency
                        )
                        if count > 0:
                            logger.info(f"Synced {count} benchmark prices for {ticker}")
                        synced += 1
                    except Exception as e:
                        logger.error(f"Failed to sync benchmark {ticker}: {e}")

                await db.commit()
                logger.info(f"Benchmark price sync completed: {synced} benchmarks refreshed")
                return {"status": "success", "benchmarks_synced": synced}

            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to sync benchmark prices: {e}", exc_info=True)
                return {"status": "error", "message": str(e)}

    async def sync_dividends(self) -> dict:
        """
        Sync dividend ex-dates from Yahoo Finance and compute EUR income.

        Independent of IBKR (yfinance-based); computes against existing tax lots.
        Cheap to run daily: DividendService applies a 7-day per-security staleness
        guard that skips already-fetched securities before any network call.

        Returns:
            Summary of the dividend sync + compute steps
        """
        logger.info("Starting scheduled dividend sync...")

        async with AsyncSessionLocal() as db:
            try:
                # Imported here to avoid any import cycle at module load
                from app.services.dividend_service import DividendService

                service = DividendService(db)
                sync_res = await service.sync_dividend_data()
                compute_res = await service.compute_dividend_income()

                logger.info(f"Dividend sync completed: {sync_res}; compute: {compute_res}")
                return {
                    "status": "success",
                    "sync": sync_res,
                    "compute": compute_res,
                    "timestamp": utc_iso(datetime.now())
                }

            except Exception as e:
                logger.error(f"Failed to sync dividends: {str(e)}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Failed to sync dividends: {str(e)}",
                    "timestamp": utc_iso(datetime.now())
                }

    async def _gated_job(self, job_type: str, run) -> Optional[dict]:
        """
        Run one pipeline job under the shared sync-pipeline gate.

        A collision (e.g. a manual trigger already in flight at a scheduled slot)
        records itself as 'skipped' instead of running concurrently — two
        pipelines would race the Flex budget toward a Code=1025 lockout and
        double-hit Yahoo. The next scheduled slot recovers the freshness.
        """
        try:
            with single_flight(SYNC_PIPELINE):
                return await run()
        except SyncBusy as e:
            logger.warning(f"{job_type} skipped: {e}")
            skipped = {
                "type": job_type,
                "status": "skipped",
                "message": str(e),
                "timestamp": utc_iso(datetime.now()),
            }
            await self._record_run(skipped, datetime.now())
            return skipped

    async def full_sync_job(self) -> Optional[dict]:
        """
        Full sync job that runs once daily at 08:00 Europe/Berlin.

        Executes in sequence:
        1. IBKR data sync (securities and tax lots)
        2. Market data sync (prices for all securities)
        3. Dividend sync (Yahoo Finance ex-dates + EUR income)
        """
        return await self._gated_job("full_sync", self._full_sync_job_locked)

    async def _full_sync_job_locked(self) -> dict:
        logger.info("=" * 80)
        logger.info("STARTING FULL SYNC JOB (IBKR + MARKET DATA)")
        logger.info("=" * 80)

        started_at = datetime.now()
        market_result = None

        # Step 1: Sync IBKR data
        ibkr_result = await self.sync_ibkr_data()
        logger.info(f"IBKR Sync Result: {ibkr_result}")

        # Step 2: Sync exchange rates (always, even if IBKR sync fails)
        logger.info("Syncing exchange rates...")
        fx_result = await self.sync_exchange_rates(days_back=30)
        logger.info(f"Exchange Rate Sync Result: {fx_result}")

        # Step 3: Sync market data (only if IBKR sync was successful)
        if ibkr_result.get("status") == "success":
            logger.info("IBKR sync successful, proceeding to market data sync (730 days)...")
            market_result = await self.sync_market_data(days_back=730)
            logger.info(f"Market Data Sync Result: {market_result}")
        else:
            logger.error("IBKR sync failed, skipping market data sync")

        # Step 4: Sync dividends (always — yfinance-based, computes against existing tax lots)
        logger.info("Syncing dividends...")
        div_result = await self.sync_dividends()
        logger.info(f"Dividend Sync Result: {div_result}")

        # Track result
        self.last_sync_result = {
            "type": "full_sync",
            "timestamp": utc_iso(datetime.now()),
            "ibkr_result": ibkr_result,
            "fx_result": fx_result,
            "market_result": market_result,
            "dividend_result": div_result,
            "status": ibkr_result.get("status", "error"),
        }
        _collect_warnings(self.last_sync_result, ibkr_result, market_result)
        await self._record_run(self.last_sync_result, started_at)

        logger.info("=" * 80)
        logger.info("FULL SYNC JOB COMPLETED")
        logger.info("=" * 80)
        return self.last_sync_result

    async def market_data_only_sync_job(self) -> Optional[dict]:
        """
        Market-data-only sync job that runs at 15:00 and 22:00 Europe/Berlin.
        Only checks last 7 days — very lightweight, just picks up recent closing prices.
        Also syncs exchange rates to keep FX data current.
        """
        return await self._gated_job("market_data_only", self._market_data_only_locked)

    async def _market_data_only_locked(self) -> dict:
        logger.info("=" * 80)
        logger.info("STARTING MARKET DATA + EXCHANGE RATE SYNC (7 days)")
        logger.info("=" * 80)

        started_at = datetime.now()

        # Sync exchange rates first (needed for portfolio value calculation)
        fx_result = await self.sync_exchange_rates(days_back=7)
        logger.info(f"Exchange Rate Sync Result: {fx_result}")

        market_result = await self.sync_market_data(days_back=7)
        logger.info(f"Market Data Sync Result: {market_result}")

        # Sync benchmark prices (only previously used benchmarks)
        bench_result = await self.sync_benchmark_prices()
        logger.info(f"Benchmark Price Sync Result: {bench_result}")

        # Invalidate recent benchmark timeline cache (prices updated for last 7 days)
        async with AsyncSessionLocal() as db:
            try:
                bench_service = BenchmarkService(db)
                cleared = await bench_service.clear_cache_recent_days(days=7)
                await db.commit()
                logger.info(f"Cleared {cleared} recent benchmark timeline cache entries")
            except Exception as e:
                logger.error(f"Failed to clear benchmark timeline cache: {e}")

        # Track result
        self.last_sync_result = {
            "type": "market_data_only",
            "timestamp": utc_iso(datetime.now()),
            "fx_result": fx_result,
            "market_result": market_result,
            "benchmark_result": bench_result,
            "status": market_result.get("status", "error"),
        }
        _collect_warnings(self.last_sync_result, market_result)
        await self._record_run(self.last_sync_result, started_at)

        logger.info("=" * 80)
        logger.info("MARKET DATA ONLY SYNC COMPLETED")
        logger.info("=" * 80)
        return self.last_sync_result

    async def _record_run(self, result: dict, started_at: datetime) -> None:
        """
        Persist a job's outcome to sync_runs.

        last_sync_result alone is in-memory, so it disappears on every container
        restart — and auto-deploy restarts on each push, which would leave the daily
        validator blind.

        Best-effort end to end: the session itself may fail to open, so the whole thing
        is guarded. Bookkeeping must never be the reason a sync reports failure.
        """
        try:
            async with AsyncSessionLocal() as db:
                await SyncRunRepository(db).record(
                    sync_type=result.get("type", "unknown"),
                    status=result.get("status", "error"),
                    message=result.get("message") or (result.get("ibkr_result") or {}).get("message"),
                    details={k: v for k, v in result.items() if k not in ("warnings",)},
                    warnings=result.get("warnings"),
                    started_at=started_at,
                )
        except Exception as e:
            logger.warning(f"Could not persist sync run: {e}")

    async def ibkr_only_sync_job(self) -> Optional[dict]:
        return await self._gated_job("ibkr_sync", self._ibkr_only_sync_locked)

    async def _ibkr_only_sync_locked(self) -> dict:
        """
        IBKR-only sync, at 13:00 and 20:00 Europe/Berlin.

        Exists because the 08:00 full sync is the *only* job that talks to IBKR, so a
        transient `Code=1001` ("statement could not be generated") used to cost a whole
        day of freshness — and that got likelier once the Flex Query grew to Year-to-Date
        with Trades/CorporateActions/CashTransactions, since IBKR takes longer to build it.

        Deliberately does NOT call sync_market_data() or sync_dividends(): both hit Yahoo
        Finance, which is rate-limited and, per CLAUDE.md, must never be called without
        explicit user permission. Re-running just the IBKR half is safe and cheap —
        ingestion is idempotent (upserts keyed on ib_key) — and it also picks up intraday
        trades. Exchange rates come from Frankfurter (free, unmetered), so they ride along.
        """
        logger.info("=" * 80)
        logger.info("STARTING IBKR-ONLY SYNC (no market data)")
        logger.info("=" * 80)

        started_at = datetime.now()
        ibkr_result = await self.sync_ibkr_data()
        logger.info(f"IBKR Sync Result: {ibkr_result}")

        fx_result = await self.sync_exchange_rates(days_back=7)
        logger.info(f"Exchange Rate Sync Result: {fx_result}")

        self.last_sync_result = {
            "type": "ibkr_sync",
            "timestamp": utc_iso(datetime.now()),
            "ibkr_result": ibkr_result,
            "fx_result": fx_result,
            "status": ibkr_result.get("status", "error"),
        }
        _collect_warnings(self.last_sync_result, ibkr_result)
        await self._record_run(self.last_sync_result, started_at)

        logger.info("=" * 80)
        logger.info("IBKR-ONLY SYNC COMPLETED")
        logger.info("=" * 80)
        return self.last_sync_result

    def _add_or_keep(self, job_id: str, func, trigger: CronTrigger, name: str) -> None:
        """
        Register a job, **preserving a stored run time when the schedule is unchanged**.

        `add_job(..., replace_existing=True)` looks like the obvious call and is the
        wrong one here: replacing a job recomputes `next_run_time` from now, so the
        missed run time a restart was supposed to recover is overwritten on the way in
        and the persistent store buys nothing. Leaving an identically-triggered job
        alone keeps that timestamp, which is what lets APScheduler notice the misfire.

        Comparing `str(trigger)` is how a schedule *change* still lands: CronTrigger's
        repr is its full field set, so editing an hour replaces the job (and its stale
        run time) while a restart with the same schedule does not.
        """
        existing = self.scheduler.get_job(job_id)
        if existing is not None and str(existing.trigger) == str(trigger):
            logger.info(f"  {name} — kept, next run: {existing.next_run_time}")
            return

        if existing is not None:
            logger.info(f"  {name} — schedule changed, rescheduling")

        self.scheduler.add_job(
            func, trigger=trigger, id=job_id, name=name, replace_existing=True
        )

    def start(self):
        """
        Start the scheduler with 5 daily syncs (Europe/Berlin):
        - 08:00: Full sync (IBKR + 730 days market data) — fills historical gaps
        - 13:00: IBKR only — second chance if the morning statement wasn't ready
        - 15:00: Market data only (7 days) — after European market close
        - 20:00: IBKR only — last chance to land the day's trades
        - 22:00: Market data only (7 days) — after US market close

        Jobs are persisted to `settings.scheduler_jobstore_url` so a restart that
        overlaps a slot recovers it instead of losing it — see MISFIRE_GRACE_SECONDS.
        """
        if self.scheduler is not None:
            logger.warning("Scheduler is already running")
            return

        logger.info("Starting scheduler service...")

        jobstores = {}
        if settings.scheduler_jobstore_url:
            # A persistent store serializes each job, so the target must be importable
            # by name. That is why the five entry points below are module-level
            # functions rather than the bound methods they used to be: a bound method
            # of this instance would drag the live AsyncIOScheduler into the pickle.
            jobstores['default'] = SQLAlchemyJobStore(url=settings.scheduler_jobstore_url)

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            job_defaults={
                # One catch-up run, not one per slot the outage covered.
                'coalesce': True,
                'misfire_grace_time': MISFIRE_GRACE_SECONDS,
                # Belt and braces beside single_flight, which is the real guard.
                'max_instances': 1,
            },
        )

        # Paused, so the job store is live for the get_job() lookups in _add_or_keep
        # (before start() those would only see APScheduler's pending-jobs list) while
        # nothing can fire mid-registration.
        self.scheduler.start(paused=True)

        self._add_or_keep(
            'full_sync_job', full_sync_job_entry,
            CronTrigger(hour=8, minute=0, timezone='Europe/Berlin'),
            'Full IBKR + Market Data Sync (08:00 Europe/Berlin)',
        )
        # 13:00 and 20:00 are IBKR-only second chances: a transient Code=1001 at 08:00
        # used to cost a full day of freshness.
        self._add_or_keep(
            'ibkr_sync_midday', ibkr_only_sync_job_entry,
            CronTrigger(hour=13, minute=0, timezone='Europe/Berlin'),
            'IBKR-only Sync (13:00 Europe/Berlin)',
        )
        self._add_or_keep(
            'ibkr_sync_evening', ibkr_only_sync_job_entry,
            CronTrigger(hour=20, minute=0, timezone='Europe/Berlin'),
            'IBKR-only Sync (20:00 Europe/Berlin)',
        )
        self._add_or_keep(
            'market_sync_eu_close', market_data_only_sync_job_entry,
            CronTrigger(hour=15, minute=0, timezone='Europe/Berlin'),
            'Market Data Sync after EU Close (15:00 Europe/Berlin)',
        )
        self._add_or_keep(
            'market_sync_us_close', market_data_only_sync_job_entry,
            CronTrigger(hour=22, minute=0, timezone='Europe/Berlin'),
            'Market Data Sync after US Close (22:00 Europe/Berlin)',
        )

        self.scheduler.resume()

        logger.info("Scheduler started successfully")
        for job in self.scheduler.get_jobs():
            logger.info(f"  {job.name} — next run: {job.next_run_time}")

    def shutdown(self):
        """
        Shutdown the scheduler gracefully.
        """
        if self.scheduler is None:
            logger.warning("Scheduler is not running")
            return

        logger.info("Shutting down scheduler service...")
        self.scheduler.shutdown(wait=True)
        self.scheduler = None
        logger.info("Scheduler shut down successfully")

    async def trigger_sync_now(self) -> dict:
        """
        Manually trigger the sync job immediately (for testing).

        Raises SyncBusy (a 429 at the router) when the pipeline is already
        running, instead of pretending a skipped run completed.
        """
        logger.info("Manually triggering full sync job...")
        result = await self.full_sync_job()
        if result and result.get("status") == "skipped":
            raise SyncBusy(result.get("message") or "sync pipeline is busy")
        # last_sync_result is already set by full_sync_job
        return {"status": "completed", "message": "Manual sync triggered successfully"}


# Global scheduler instance
_scheduler_service: Optional[SchedulerService] = None


def get_scheduler() -> SchedulerService:
    """
    Get the global scheduler service instance.

    Returns:
        SchedulerService instance
    """
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService()
    return _scheduler_service


# ── Job entry points ──────────────────────────────────────────────────────────
#
# The scheduled jobs used to be registered as bound methods (`self.full_sync_job`),
# which an in-memory job store is happy to hold onto. A persistent store serializes
# each job instead, and a bound method would drag the whole SchedulerService — the live
# AsyncIOScheduler included — into the pickle.
#
# Module-level functions serialize as `module:name` references, so these thin wrappers
# resolve the singleton at fire time. They are also the reason the scheduler survives a
# code change: a stored reference is re-imported, not un-pickled from old bytes.


async def full_sync_job_entry() -> dict:
    return await get_scheduler().full_sync_job()


async def ibkr_only_sync_job_entry() -> dict:
    return await get_scheduler().ibkr_only_sync_job()


async def market_data_only_sync_job_entry() -> dict:
    return await get_scheduler().market_data_only_sync_job()

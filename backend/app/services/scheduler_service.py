"""
Scheduler Service
Handles automated daily synchronization of IBKR data and market prices.
"""
import logging
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import date, timedelta

from app.database import AsyncSessionLocal
from app.services.ibkr_service import IBKRService, FLEX_RETRY_DELAYS_PATIENT
from app.services.market_data_service import MarketDataService
from app.services.currency_service import CurrencyService
from app.services.sync_helper import ingest_flex_statement
from app.repositories.security_repository import SecurityRepository
from app.repositories.sync_run_repository import SyncRunRepository, utc_iso
from app.services.benchmark_service import BenchmarkService, BENCHMARKS
from app.models.benchmark_price import BenchmarkPrice
from sqlalchemy import select, distinct

logger = logging.getLogger(__name__)


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

                # Get all unique non-EUR currencies from securities
                securities = await security_repo.get_all(limit=1000)
                currencies = set()
                for sec in securities:
                    if sec.currency and sec.currency != "EUR":
                        currencies.add(sec.currency)

                if not currencies:
                    logger.info("No non-EUR currencies found")
                    return {
                        "status": "success",
                        "currencies_synced": 0,
                        "timestamp": utc_iso(datetime.now())
                    }

                logger.info(f"Syncing exchange rates for currencies: {currencies}")

                today = date.today()
                total_rates = 0

                for currency in currencies:
                    try:
                        # Use the currency service's batch fetch to get rates
                        target_date = today
                        await currency_service._batch_fetch_rates(
                            from_currency=currency,
                            target_date=target_date,
                            to_currency="EUR",
                            days_back=days_back
                        )
                        logger.info(f"Fetched exchange rates for {currency}")
                        total_rates += 1
                    except Exception as e:
                        logger.error(f"Failed to fetch rates for {currency}: {e}")

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
                    "currencies": list(currencies),
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

    async def full_sync_job(self):
        """
        Full sync job that runs once daily at 08:00 Europe/Berlin.

        Executes in sequence:
        1. IBKR data sync (securities and tax lots)
        2. Market data sync (prices for all securities)
        3. Dividend sync (Yahoo Finance ex-dates + EUR income)
        """
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
        await self._record_run(self.last_sync_result, started_at)

        logger.info("=" * 80)
        logger.info("FULL SYNC JOB COMPLETED")
        logger.info("=" * 80)

    async def market_data_only_sync_job(self):
        """
        Market-data-only sync job that runs at 15:00 and 22:00 Europe/Berlin.
        Only checks last 7 days — very lightweight, just picks up recent closing prices.
        Also syncs exchange rates to keep FX data current.
        """
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
        await self._record_run(self.last_sync_result, started_at)

        logger.info("=" * 80)
        logger.info("MARKET DATA ONLY SYNC COMPLETED")
        logger.info("=" * 80)

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

    async def ibkr_only_sync_job(self):
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
        await self._record_run(self.last_sync_result, started_at)

        logger.info("=" * 80)
        logger.info("IBKR-ONLY SYNC COMPLETED")
        logger.info("=" * 80)

    def start(self):
        """
        Start the scheduler with 5 daily syncs (Europe/Berlin):
        - 08:00: Full sync (IBKR + 730 days market data) — fills historical gaps
        - 13:00: IBKR only — second chance if the morning statement wasn't ready
        - 15:00: Market data only (7 days) — after European market close
        - 20:00: IBKR only — last chance to land the day's trades
        - 22:00: Market data only (7 days) — after US market close
        """
        if self.scheduler is not None:
            logger.warning("Scheduler is already running")
            return

        logger.info("Starting scheduler service...")

        self.scheduler = AsyncIOScheduler()

        # 08:00 Europe/Berlin — full sync (IBKR + market data)
        self.scheduler.add_job(
            self.full_sync_job,
            trigger=CronTrigger(hour=8, minute=0, timezone='Europe/Berlin'),
            id='full_sync_job',
            name='Full IBKR + Market Data Sync (08:00 Europe/Berlin)',
            replace_existing=True
        )

        # 13:00 Europe/Berlin — IBKR only (second chance if 08:00's statement wasn't ready)
        self.scheduler.add_job(
            self.ibkr_only_sync_job,
            trigger=CronTrigger(hour=13, minute=0, timezone='Europe/Berlin'),
            id='ibkr_sync_midday',
            name='IBKR-only Sync (13:00 Europe/Berlin)',
            replace_existing=True
        )

        # 20:00 Europe/Berlin — IBKR only (last chance to land the day's trades)
        self.scheduler.add_job(
            self.ibkr_only_sync_job,
            trigger=CronTrigger(hour=20, minute=0, timezone='Europe/Berlin'),
            id='ibkr_sync_evening',
            name='IBKR-only Sync (20:00 Europe/Berlin)',
            replace_existing=True
        )

        # 15:00 Europe/Berlin — market data only (after EU close)
        self.scheduler.add_job(
            self.market_data_only_sync_job,
            trigger=CronTrigger(hour=15, minute=0, timezone='Europe/Berlin'),
            id='market_sync_eu_close',
            name='Market Data Sync after EU Close (15:00 Europe/Berlin)',
            replace_existing=True
        )

        # 22:00 Europe/Berlin — market data only (after US close)
        self.scheduler.add_job(
            self.market_data_only_sync_job,
            trigger=CronTrigger(hour=22, minute=0, timezone='Europe/Berlin'),
            id='market_sync_us_close',
            name='Market Data Sync after US Close (22:00 Europe/Berlin)',
            replace_existing=True
        )

        self.scheduler.start()

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

        Returns:
            Combined results from both sync operations
        """
        logger.info("Manually triggering full sync job...")
        await self.full_sync_job()
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

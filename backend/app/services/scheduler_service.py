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

from app.database import AsyncSessionLocal
from app.services.ibkr_service import IBKRService
from app.services.market_data_service import MarketDataService
from app.services.currency_service import CurrencyService
from app.repositories.security_repository import SecurityRepository
from app.repositories.taxlot_repository import TaxLotRepository
from app.repositories.market_price_repository import MarketPriceRepository
from decimal import Decimal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Service for scheduling automated data synchronization tasks.

    Runs 3 times daily:
    - 08:00 UTC: Full sync (IBKR + 730 days market data) — fills historical gaps gradually
    - 15:00 UTC: Market data only (7 days) — picks up EU closing prices
    - 22:00 UTC: Market data only (7 days) — picks up US closing prices
    """

    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None

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
                ibkr_service = IBKRService()
                currency_service = CurrencyService(db)
                security_repo = SecurityRepository(db)
                taxlot_repo = TaxLotRepository(db)

                # Step 1: Fetch data from IBKR
                logger.info("Fetching data from IBKR Flex Query...")
                flex_data = await ibkr_service.fetch_flex_data()

                # Step 2: Extract securities
                logger.info("Extracting securities from Flex Query response...")
                securities_data = await ibkr_service.extract_securities(flex_data)

                # Step 3: Upsert securities to database
                securities_count = 0
                conid_to_security_id = {}

                for sec_data in securities_data:
                    security = await security_repo.upsert(sec_data)
                    conid_to_security_id[sec_data['conid']] = security.id
                    securities_count += 1

                logger.info(f"Synced {securities_count} securities")

                # Step 4: Extract tax lots
                logger.info("Extracting tax lots from Flex Query response...")
                taxlots_data = await ibkr_service.extract_taxlots(flex_data)

                # Step 5: Process and store tax lots
                taxlots_count = 0
                taxlots_skipped = 0
                skipped_currencies = set()
                total_cost_basis_eur = Decimal('0')

                # Delete existing taxlots before syncing fresh data
                logger.info("Deleting existing taxlots before sync...")
                for conid, security_id in conid_to_security_id.items():
                    await taxlot_repo.delete_by_security_id(security_id)

                for lot_data in taxlots_data:
                    conid = lot_data['conid']

                    # Get the security ID from our database
                    security_id = conid_to_security_id.get(conid)
                    if not security_id:
                        logger.warning(f"Security with conid {conid} not found, skipping taxlot")
                        taxlots_skipped += 1
                        continue

                    # Convert cost basis to EUR
                    try:
                        cost_basis_eur = await currency_service.convert_to_eur(
                            amount=lot_data['cost_basis'],
                            from_currency=lot_data['currency'],
                            target_date=lot_data['open_date']
                        )
                    except ValueError as e:
                        logger.warning(f"Skipping taxlot with unsupported currency {lot_data['currency']}: {str(e)}")
                        skipped_currencies.add(lot_data['currency'])
                        taxlots_skipped += 1
                        continue

                    # Create new taxlot
                    taxlot_data = {
                        'security_id': security_id,
                        'open_date': lot_data['open_date'],
                        'quantity': lot_data['quantity'],
                        'cost_basis': lot_data['cost_basis'],
                        'price_per_unit': lot_data['price_per_unit'],
                        'currency': lot_data['currency'],
                        'cost_basis_eur': cost_basis_eur,
                        'is_open': lot_data['is_open'],
                    }

                    await taxlot_repo.create(taxlot_data)
                    taxlots_count += 1
                    total_cost_basis_eur += cost_basis_eur

                # Commit transaction
                await db.commit()

                result = {
                    "status": "success",
                    "message": "Successfully synced data from IBKR",
                    "securities_synced": securities_count,
                    "taxlots_synced": taxlots_count,
                    "taxlots_skipped": taxlots_skipped,
                    "total_cost_basis_eur": float(total_cost_basis_eur),
                    "timestamp": datetime.now().isoformat()
                }

                if skipped_currencies:
                    result["warnings"] = [
                        f"Skipped {taxlots_skipped} taxlot(s) with unsupported currencies: {', '.join(sorted(skipped_currencies))}"
                    ]

                logger.info(f"IBKR sync completed: {securities_count} securities, {taxlots_count} taxlots")
                return result

            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to sync IBKR data: {str(e)}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Failed to sync IBKR data: {str(e)}",
                    "timestamp": datetime.now().isoformat()
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
                        "timestamp": datetime.now().isoformat()
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
                    "timestamp": datetime.now().isoformat()
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
                    "timestamp": datetime.now().isoformat()
                }

    async def full_sync_job(self):
        """
        Full sync job that runs once daily at 8 AM UTC.

        Executes in sequence:
        1. IBKR data sync (securities and tax lots)
        2. Market data sync (prices for all securities)
        """
        logger.info("=" * 80)
        logger.info("STARTING FULL SYNC JOB (IBKR + MARKET DATA)")
        logger.info("=" * 80)

        # Step 1: Sync IBKR data
        ibkr_result = await self.sync_ibkr_data()
        logger.info(f"IBKR Sync Result: {ibkr_result}")

        # Step 2: Sync market data (only if IBKR sync was successful)
        if ibkr_result.get("status") == "success":
            logger.info("IBKR sync successful, proceeding to market data sync (730 days)...")
            market_result = await self.sync_market_data(days_back=730)
            logger.info(f"Market Data Sync Result: {market_result}")
        else:
            logger.error("IBKR sync failed, skipping market data sync")

        logger.info("=" * 80)
        logger.info("FULL SYNC JOB COMPLETED")
        logger.info("=" * 80)

    async def market_data_only_sync_job(self):
        """
        Market-data-only sync job that runs at 15:00 and 22:00 UTC.
        Only checks last 7 days — very lightweight, just picks up recent closing prices.
        """
        logger.info("=" * 80)
        logger.info("STARTING MARKET DATA ONLY SYNC (7 days)")
        logger.info("=" * 80)

        market_result = await self.sync_market_data(days_back=7)
        logger.info(f"Market Data Sync Result: {market_result}")

        logger.info("=" * 80)
        logger.info("MARKET DATA ONLY SYNC COMPLETED")
        logger.info("=" * 80)

    def start(self):
        """
        Start the scheduler with 3 daily syncs:
        - 08:00 UTC: Full sync (IBKR + 730 days market data) — fills historical gaps
        - 15:00 UTC: Market data only (7 days) — after European market close
        - 22:00 UTC: Market data only (7 days) — after US market close
        """
        if self.scheduler is not None:
            logger.warning("Scheduler is already running")
            return

        logger.info("Starting scheduler service...")

        self.scheduler = AsyncIOScheduler()

        # 08:00 UTC — full sync (IBKR + market data)
        self.scheduler.add_job(
            self.full_sync_job,
            trigger=CronTrigger(hour=8, minute=0),
            id='full_sync_job',
            name='Full IBKR + Market Data Sync (08:00 UTC)',
            replace_existing=True
        )

        # 15:00 UTC — market data only (after EU close)
        self.scheduler.add_job(
            self.market_data_only_sync_job,
            trigger=CronTrigger(hour=15, minute=0),
            id='market_sync_eu_close',
            name='Market Data Sync after EU Close (15:00 UTC)',
            replace_existing=True
        )

        # 22:00 UTC — market data only (after US close)
        self.scheduler.add_job(
            self.market_data_only_sync_job,
            trigger=CronTrigger(hour=22, minute=0),
            id='market_sync_us_close',
            name='Market Data Sync after US Close (22:00 UTC)',
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

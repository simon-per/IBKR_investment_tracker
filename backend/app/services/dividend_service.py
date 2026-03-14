"""
Dividend Service
Fetches dividend ex-dates from yfinance, computes income from tax lots,
converts to EUR, and provides monthly summary data.
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta, date
from decimal import Decimal
from collections import defaultdict
import logging
import random
import asyncio
import yfinance as yf

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import Security
from app.models.taxlot import TaxLot
from app.repositories.dividend_repository import DividendRepository
from app.services.currency_service import CurrencyService

logger = logging.getLogger(__name__)


class DividendService:
    """Service for fetching and computing dividend income."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DividendRepository(db)
        self.currency_service = CurrencyService(db)

    async def _get_yahoo_ticker(self, security: Security) -> str:
        """Resolve Yahoo ticker for a security (reuses MarketDataService logic)."""
        from app.services.market_data_service import MarketDataService
        market_service = MarketDataService(self.db)
        return await market_service._get_yahoo_ticker(security)

    async def sync_dividend_data(self) -> Dict:
        """Fetch dividend ex-dates from yfinance for all securities."""
        result = await self.db.execute(select(Security))
        securities = list(result.scalars().all())

        if not securities:
            return {'securities_processed': 0, 'dividends_added': 0, 'errors': 0,
                    'message': 'No securities found'}

        logger.info(f"Syncing dividends for {len(securities)} securities")

        dividends_added = 0
        errors = 0
        skipped = 0

        for i, security in enumerate(securities, 1):
            try:
                # Staleness check: skip if we fetched dividends < 7 days ago
                last_fetch = await self.repo.get_last_fetch_time(security.id)
                if last_fetch and (datetime.now() - last_fetch) < timedelta(days=7):
                    skipped += 1
                    continue

                yahoo_ticker = await self._get_yahoo_ticker(security)
                logger.info(f"[{i}/{len(securities)}] Fetching dividends for {security.symbol} ({yahoo_ticker})")

                # Rate limit before API call
                await asyncio.sleep(random.uniform(1.0, 2.0))

                # Fetch dividends in a thread
                def _fetch(ticker=yahoo_ticker):
                    return yf.Ticker(ticker).dividends

                dividends_series = await asyncio.to_thread(_fetch)

                if dividends_series is None or dividends_series.empty:
                    logger.info(f"No dividends found for {security.symbol}")
                    continue

                for dt_index, amount in dividends_series.items():
                    ex_date = dt_index.date() if hasattr(dt_index, 'date') else dt_index
                    await self.repo.upsert_payment({
                        'security_id': security.id,
                        'ex_date': ex_date,
                        'amount_per_share': Decimal(str(amount)),
                        'currency': security.currency,
                    })
                    dividends_added += 1

                await self.db.commit()

            except Exception as e:
                logger.error(f"Error fetching dividends for {security.symbol}: {e}")
                errors += 1
                await self.db.rollback()
                continue

        logger.info(f"Dividend sync complete: added={dividends_added}, skipped={skipped}, errors={errors}")
        return {
            'securities_processed': len(securities) - skipped,
            'dividends_added': dividends_added,
            'skipped': skipped,
            'errors': errors,
            'message': f'Synced dividends: {dividends_added} records from {len(securities) - skipped} securities',
        }

    async def compute_dividend_income(self) -> Dict:
        """Compute shares held and EUR amounts for all uncomputed dividend payments."""
        uncomputed = await self.repo.get_uncomputed()
        if not uncomputed:
            return {'computed': 0, 'message': 'All dividends already computed'}

        logger.info(f"Computing income for {len(uncomputed)} dividend payments")

        # Pre-load all tax lots
        taxlot_result = await self.db.execute(select(TaxLot))
        all_taxlots = list(taxlot_result.scalars().all())

        # Group tax lots by security_id
        taxlots_by_security: Dict[int, List[TaxLot]] = defaultdict(list)
        for tl in all_taxlots:
            taxlots_by_security[tl.security_id].append(tl)

        computed = 0
        errors = 0

        for dp in uncomputed:
            try:
                # Sum shares held on ex_date: open_date <= ex_date AND (close_date IS NULL OR close_date > ex_date)
                lots = taxlots_by_security.get(dp.security_id, [])
                shares = Decimal("0")
                for lot in lots:
                    if lot.open_date > dp.ex_date:
                        continue
                    if lot.close_date and lot.close_date <= dp.ex_date:
                        continue
                    shares += lot.quantity

                if shares <= 0:
                    # No shares held on ex-date — set to 0 so it's not re-processed
                    dp.shares_held = Decimal("0")
                    dp.gross_amount_eur = Decimal("0")
                    dp.last_computed = datetime.now()
                    computed += 1
                    continue

                gross_amount = dp.amount_per_share * shares

                # Convert to EUR
                currency = dp.currency or "USD"
                if currency == "EUR":
                    gross_eur = gross_amount
                else:
                    try:
                        fx_rate = await self.currency_service.get_exchange_rate(
                            currency, dp.ex_date
                        )
                        gross_eur = gross_amount * fx_rate
                    except Exception as e:
                        logger.warning(f"FX conversion failed for {currency} on {dp.ex_date}: {e}")
                        gross_eur = gross_amount  # fallback: store unconverted

                dp.shares_held = shares
                dp.gross_amount_eur = gross_eur
                dp.last_computed = datetime.now()
                computed += 1

            except Exception as e:
                logger.error(f"Error computing dividend for security_id={dp.security_id}, ex_date={dp.ex_date}: {e}")
                errors += 1
                continue

        await self.db.commit()
        logger.info(f"Dividend computation complete: computed={computed}, errors={errors}")
        return {'computed': computed, 'errors': errors, 'message': f'Computed {computed} dividend payments'}

    async def get_dividend_summary(self) -> Dict:
        """Aggregate computed dividends into a monthly summary."""
        payments = await self.repo.get_computed_dividends()

        monthly: Dict[str, Decimal] = defaultdict(Decimal)
        total_eur = Decimal("0")

        now = datetime.now()
        ytd_eur = Decimal("0")

        for p in payments:
            month_key = p.ex_date.strftime("%Y-%m")
            amount = p.gross_amount_eur or Decimal("0")
            monthly[month_key] += amount
            total_eur += amount

            if p.ex_date.year == now.year:
                ytd_eur += amount

        # Sort by month
        monthly_list = [
            {"month": k, "amount_eur": round(float(v), 2)}
            for k, v in sorted(monthly.items())
        ]

        # Find last_updated
        last_updated = None
        if payments:
            latest = max((p.last_computed for p in payments if p.last_computed), default=None)
            if latest:
                last_updated = latest.isoformat()

        return {
            "monthly": monthly_list,
            "ytd_eur": round(float(ytd_eur), 2),
            "total_eur": round(float(total_eur), 2),
            "last_updated": last_updated,
        }

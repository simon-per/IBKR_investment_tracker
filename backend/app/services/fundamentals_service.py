from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging
import yfinance as yf
import random
import asyncio
import math
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.repositories.fundamentals_repository import FundamentalsRepository
from app.models.security import Security
from app.models.fundamental_metrics import FundamentalMetrics
from app.models.earnings_event import EarningsEvent

logger = logging.getLogger(__name__)


class FundamentalsService:
    """Service for fetching and caching fundamental metrics and earnings data."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = FundamentalsRepository(db)

    async def _get_yahoo_ticker(self, security: Security, market_service=None) -> str:
        if market_service is None:
            from app.services.market_data_service import MarketDataService
            market_service = MarketDataService(self.db)
        return await market_service._get_yahoo_ticker(security)

    def _safe_float(self, value) -> Optional[float]:
        """Safely convert a value to float, returning None for NaN/Inf/None."""
        if value is None:
            return None
        try:
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value) -> Optional[int]:
        """Safely convert a value to int, returning None for invalid values."""
        if value is None:
            return None
        try:
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return None
            return int(f)
        except (ValueError, TypeError):
            return None

    async def _fetch_yahoo_data(self, yahoo_ticker: str) -> tuple:
        """Fetch .info, .earnings_dates, .quarterly_financials, .growth_estimates, and .revenue_estimate in a thread."""
        def _fetch():
            ticker = yf.Ticker(yahoo_ticker)
            info = ticker.info
            try:
                earnings = ticker.earnings_dates
            except Exception:
                earnings = None
            try:
                quarterly_financials = ticker.quarterly_financials
            except Exception:
                quarterly_financials = None
            try:
                growth_estimates = ticker.growth_estimates
            except Exception:
                growth_estimates = None
            try:
                revenue_estimate = ticker.revenue_estimate
            except Exception:
                revenue_estimate = None
            return info, earnings, quarterly_financials, growth_estimates, revenue_estimate

        return await asyncio.to_thread(_fetch)

    def _ttm_growth_from_quarterly(self, quarterly_financials, row_candidates: list) -> Optional[float]:
        """TTM YoY growth: sum of 4 most recent quarters vs prior 4 quarters."""
        if quarterly_financials is None or quarterly_financials.empty or quarterly_financials.shape[1] < 8:
            return None
        for row_name in row_candidates:
            if row_name in quarterly_financials.index:
                row = quarterly_financials.loc[row_name].dropna()
                if len(row) >= 8:
                    current_ttm = float(row.iloc[:4].sum())
                    prior_ttm = float(row.iloc[4:8].sum())
                    if prior_ttm != 0:
                        return round((current_ttm - prior_ttm) / abs(prior_ttm), 4)
        return None

    def _extract_metrics(self, security: Security, info: Dict, quarterly_financials=None,
                         growth_estimates=None, revenue_estimate=None) -> Optional[Dict]:
        """Extract fundamental metrics from a Yahoo Finance info dict."""
        if not info:
            logger.info(f"No fundamental data available for {security.symbol}")
            return None

        # TTM growth from quarterly financials (always current, no lag)
        ttm_rev = self._ttm_growth_from_quarterly(quarterly_financials, ['Total Revenue'])
        ttm_eps = self._ttm_growth_from_quarterly(quarterly_financials, ['Diluted EPS', 'Basic EPS', 'Net Income'])

        # Forward estimates from analyst consensus
        fwd_rev = None
        try:
            if revenue_estimate is not None and '+1y' in revenue_estimate.index:
                fwd_rev = self._safe_float(revenue_estimate.loc['+1y', 'growth'])
        except Exception:
            pass

        fwd_eps = None
        try:
            if growth_estimates is not None and '+1y' in growth_estimates.index:
                fwd_eps = self._safe_float(growth_estimates.loc['+1y', 'stockTrend'])
        except Exception:
            pass

        metrics_data = {
            'security_id': security.id,
            'trailing_pe': self._safe_float(info.get('trailingPE')),
            'forward_pe': self._safe_float(info.get('forwardPE')),
            'peg_ratio': self._safe_float(info.get('pegRatio')),
            'price_to_sales': self._safe_float(info.get('priceToSalesTrailing12Months')),
            'price_to_book': self._safe_float(info.get('priceToBook')),
            'revenue_growth': ttm_rev if ttm_rev is not None else self._safe_float(info.get('revenueGrowth')),
            'earnings_growth': ttm_eps if ttm_eps is not None else self._safe_float(info.get('earningsGrowth')),
            'fwd_revenue_growth': fwd_rev,
            'fwd_eps_growth': fwd_eps,
            'profit_margins': self._safe_float(info.get('profitMargins')),
            'gross_margins': self._safe_float(info.get('grossMargins')),
            'operating_margins': self._safe_float(info.get('operatingMargins')),
            'market_cap': self._safe_int(info.get('marketCap')),
            'number_of_analysts': self._safe_int(info.get('numberOfAnalystOpinions')),
            'target_mean_price': self._safe_float(info.get('targetMeanPrice')),
            'target_high_price': self._safe_float(info.get('targetHighPrice')),
            'target_low_price': self._safe_float(info.get('targetLowPrice')),
            'quote_type': info.get('quoteType', 'EQUITY'),
            'data_currency': info.get('currency'),
        }

        # Fallback: compute PEG from trailing PE / 5-year EPS growth (analyst long-term estimate)
        # Uses longTermGrowth (5-yr CAGR) which matches Yahoo Finance's PEG methodology.
        # Only falls back to trailing quarterly growth if longTermGrowth is unavailable.
        if metrics_data.get('peg_ratio') is None and metrics_data.get('trailing_pe'):
            lt_growth = self._safe_float(info.get('longTermGrowth') or info.get('longTermEpsGrowth'))
            if lt_growth and lt_growth > 0:
                lt_pct = lt_growth * 100 if lt_growth < 1 else lt_growth  # normalise if already a %
                metrics_data['peg_ratio'] = round(metrics_data['trailing_pe'] / lt_pct, 4)

        logger.info(f"Got fundamentals for {security.symbol} (type={metrics_data['quote_type']})")
        return metrics_data

    def _extract_earnings(self, security: Security, earnings_dates) -> List[Dict]:
        """Extract earnings events from a Yahoo Finance earnings_dates DataFrame."""
        if earnings_dates is None or (hasattr(earnings_dates, 'empty') and earnings_dates.empty):
            logger.info(f"No earnings dates for {security.symbol}")
            return []

        now = datetime.now()
        events = []

        for date_idx, row in earnings_dates.iterrows():
            try:
                if hasattr(date_idx, 'to_pydatetime'):
                    earnings_dt = date_idx.to_pydatetime()
                else:
                    earnings_dt = datetime.fromisoformat(str(date_idx))

                if earnings_dt.tzinfo is not None:
                    earnings_dt = earnings_dt.replace(tzinfo=None)

                eps_estimate = self._safe_float(row.get('EPS Estimate'))
                reported_eps = self._safe_float(row.get('Reported EPS'))
                surprise_pct = self._safe_float(row.get('Surprise(%)'))

                is_upcoming = earnings_dt > now and reported_eps is None

                events.append({
                    'security_id': security.id,
                    'earnings_date': earnings_dt,
                    'eps_estimate': eps_estimate,
                    'reported_eps': reported_eps,
                    'surprise_percent': surprise_pct,
                    'is_upcoming': is_upcoming,
                })
            except Exception as e:
                logger.warning(f"Skipping earnings row for {security.symbol}: {e}")
                continue

        logger.info(f"Got {len(events)} earnings events for {security.symbol}")
        return events

    async def sync_fundamentals_data(self, force_refresh: bool = False) -> Dict:
        """Sync fundamental metrics and earnings for all securities."""
        result = await self.db.execute(select(Security))
        securities = list(result.scalars().all())

        if not securities:
            return {
                'securities_processed': 0,
                'metrics_updated': 0,
                'earnings_updated': 0,
                'errors': 0,
                'message': 'No securities found',
            }

        logger.info(f"Syncing fundamentals for {len(securities)} securities")

        metrics_updated = 0
        earnings_updated = 0
        errors = 0

        # Determine which securities need updating
        if not force_refresh:
            stale_metrics = await self.repo.get_stale_metrics(days_old=1)
            stale_ids = {m.security_id for m in stale_metrics}
            all_metrics = await self.repo.get_all_metrics()
            existing_ids = {m.security_id for m in all_metrics}
            needs_update = [
                s for s in securities
                if s.id not in existing_ids or s.id in stale_ids
            ]
            if not needs_update:
                logger.info("All fundamentals are fresh (< 1 day old)")
                return {
                    'securities_processed': 0,
                    'metrics_updated': 0,
                    'earnings_updated': 0,
                    'errors': 0,
                    'message': 'All fundamentals are up to date',
                }
        else:
            needs_update = securities

        # Create MarketDataService once for ticker resolution
        from app.services.market_data_service import MarketDataService
        market_service = MarketDataService(self.db)

        for i, security in enumerate(needs_update, 1):
            logger.info(f"[{i}/{len(needs_update)}] Processing {security.symbol}")

            try:
                # Resolve ticker once
                yahoo_ticker = await self._get_yahoo_ticker(security, market_service)
                logger.info(f"Fetching data for {security.symbol} ({yahoo_ticker})...")

                # Rate limit before API call
                await asyncio.sleep(random.uniform(1.0, 3.0))

                # Single consolidated fetch in a thread (non-blocking)
                info, earnings_df, quarterly_financials, growth_estimates, revenue_estimate = await self._fetch_yahoo_data(yahoo_ticker)

                # Extract and save fundamentals (TTM growth from quarterly financials)
                metrics_data = self._extract_metrics(security, info, quarterly_financials, growth_estimates, revenue_estimate)
                if metrics_data:
                    await self.repo.upsert_metrics(metrics_data)
                    metrics_updated += 1

                # Extract and save earnings
                earnings_data = self._extract_earnings(security, earnings_df)
                for event_data in earnings_data:
                    await self.repo.upsert_earnings_event(event_data)
                    earnings_updated += 1

                await self.db.commit()

                # Rate limit between securities
                if i < len(needs_update):
                    delay = random.uniform(2.0, 4.0)
                    logger.debug(f"Waiting {delay:.1f}s before next security...")
                    await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Error processing {security.symbol}: {e}")
                errors += 1
                await self.db.rollback()
                continue

        logger.info(
            f"Fundamentals Sync Complete: "
            f"processed={len(needs_update)}, metrics={metrics_updated}, "
            f"earnings={earnings_updated}, errors={errors}"
        )

        return {
            'securities_processed': len(needs_update),
            'metrics_updated': metrics_updated,
            'earnings_updated': earnings_updated,
            'errors': errors,
            'message': f'Synced {metrics_updated}/{len(needs_update)} fundamentals, {earnings_updated} earnings events',
        }

    async def sync_stale_fundamentals(self) -> Dict:
        """Sync only fundamentals that are stale (> 1 day old)."""
        stale = await self.repo.get_stale_metrics(days_old=1)
        if not stale:
            return {
                'securities_processed': 0,
                'metrics_updated': 0,
                'earnings_updated': 0,
                'errors': 0,
                'message': 'No stale fundamentals to update',
            }
        return await self.sync_fundamentals_data(force_refresh=False)

    async def get_fundamentals_for_portfolio(self) -> List[Dict]:
        """Return fundamental metrics joined with security info for all securities."""
        result = await self.db.execute(select(Security))
        securities = list(result.scalars().all())

        all_metrics = await self.repo.get_all_metrics()
        metrics_map = {m.security_id: m for m in all_metrics}

        portfolio_data = []
        for sec in securities:
            m = metrics_map.get(sec.id)
            entry = {
                'security_id': sec.id,
                'symbol': sec.symbol,
                'description': sec.description,
                'exchange': sec.exchange,
                'currency': sec.currency,
            }
            if m:
                entry.update({
                    'quote_type': m.quote_type,
                    'trailing_pe': m.trailing_pe,
                    'forward_pe': m.forward_pe,
                    'peg_ratio': m.peg_ratio,
                    'price_to_sales': m.price_to_sales,
                    'price_to_book': m.price_to_book,
                    'revenue_growth': m.revenue_growth,
                    'earnings_growth': m.earnings_growth,
                    'fwd_revenue_growth': m.fwd_revenue_growth,
                    'fwd_eps_growth': m.fwd_eps_growth,
                    'profit_margins': m.profit_margins,
                    'gross_margins': m.gross_margins,
                    'operating_margins': m.operating_margins,
                    'market_cap': m.market_cap,
                    'number_of_analysts': m.number_of_analysts,
                    'target_mean_price': m.target_mean_price,
                    'target_high_price': m.target_high_price,
                    'target_low_price': m.target_low_price,
                    'data_currency': m.data_currency,
                    'last_updated': m.last_updated.isoformat() if m.last_updated else None,
                })
            else:
                entry.update({
                    'quote_type': None,
                    'trailing_pe': None,
                    'forward_pe': None,
                    'peg_ratio': None,
                    'price_to_sales': None,
                    'price_to_book': None,
                    'revenue_growth': None,
                    'earnings_growth': None,
                    'fwd_revenue_growth': None,
                    'fwd_eps_growth': None,
                    'profit_margins': None,
                    'gross_margins': None,
                    'operating_margins': None,
                    'market_cap': None,
                    'number_of_analysts': None,
                    'target_mean_price': None,
                    'target_high_price': None,
                    'target_low_price': None,
                    'data_currency': None,
                    'last_updated': None,
                })

            portfolio_data.append(entry)

        return portfolio_data

    async def get_earnings_calendar(self, days_ahead: int = 90) -> List[Dict]:
        """Return upcoming earnings events with security info (eagerly loaded)."""
        events = await self.repo.get_upcoming_earnings(days_ahead)
        result = []
        for ev in events:
            result.append({
                'security_id': ev.security_id,
                'symbol': ev.security.symbol,
                'description': ev.security.description,
                'earnings_date': ev.earnings_date.isoformat(),
                'eps_estimate': ev.eps_estimate,
            })
        return result

    async def get_earnings_history(self, days_back: int = 365) -> List[Dict]:
        """Return past earnings events with surprise data (eagerly loaded)."""
        events = await self.repo.get_recent_earnings(days_back)
        result = []
        for ev in events:
            result.append({
                'security_id': ev.security_id,
                'symbol': ev.security.symbol,
                'description': ev.security.description,
                'earnings_date': ev.earnings_date.isoformat(),
                'eps_estimate': ev.eps_estimate,
                'reported_eps': ev.reported_eps,
                'surprise_percent': ev.surprise_percent,
                'beat_or_miss': ev.beat_or_miss,
            })
        return result

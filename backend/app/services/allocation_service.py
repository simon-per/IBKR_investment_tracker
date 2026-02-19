"""
Allocation service for fetching and caching sector/geographic data for securities.
"""
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import yfinance as yf

from app.models.security import Security
from app.repositories.ticker_mapping_repository import TickerMappingRepository
from app.etf_mappings import get_etf_allocation, is_known_etf


class AllocationService:
    """Service for managing allocation data (sector, country, etc.)"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ticker_repo = TickerMappingRepository(db)

    async def _get_yahoo_ticker(self, security: Security) -> Optional[str]:
        """Get the appropriate Yahoo Finance ticker for a security"""
        # Check ticker mappings first
        mapping = await self.ticker_repo.get_mapping(security.symbol, security.exchange or "")
        if mapping:
            return mapping.yahoo_ticker

        # For US exchanges, use symbol as-is
        if security.exchange in ['NASDAQ', 'NYSE', 'AMEX']:
            return security.symbol

        # For other exchanges, we'd need proper ticker mapping
        # This should already be set up from market data sync
        return None

    async def fetch_allocation_for_security(self, security: Security) -> Dict:
        """
        Fetch allocation data for a single security.
        Uses ETF mappings for known ETFs, yfinance for stocks.
        """
        print(f"[OK] Fetching allocation for {security.symbol}...")

        # Check if it's a known ETF
        if is_known_etf(security.symbol):
            etf_data = get_etf_allocation(security.symbol)
            print(f"  Using ETF mapping for {security.symbol}")
            return {
                'success': True,
                'asset_type': 'ETF',
                'sector': None,  # ETFs have multiple sectors
                'industry': None,
                'country': None,  # ETFs have multiple countries
                'etf_data': etf_data,
            }

        # Get Yahoo ticker
        yahoo_ticker = await self._get_yahoo_ticker(security)
        if not yahoo_ticker:
            print(f"  [WARN] No Yahoo ticker mapping for {security.symbol}")
            return {'success': False, 'error': 'No ticker mapping'}

        # Rate limiting: 1-3 second delay
        await asyncio.sleep(random.uniform(1.0, 3.0))

        try:
            # Fetch data from yfinance
            ticker = yf.Ticker(yahoo_ticker)
            info = ticker.info

            if not info:
                print(f"  [WARN] No info data for {yahoo_ticker}")
                return {'success': False, 'error': 'No data'}

            sector = info.get('sector')
            industry = info.get('industry')
            country = info.get('country')

            # Determine asset type
            quote_type = info.get('quoteType', '')
            if quote_type == 'ETF':
                asset_type = 'ETF'
            else:
                asset_type = 'Stock'

            print(f"  [OK] {yahoo_ticker}: {sector}, {country}")

            return {
                'success': True,
                'asset_type': asset_type,
                'sector': sector,
                'industry': industry,
                'country': country,
            }

        except Exception as e:
            print(f"  [ERROR] Failed to fetch {yahoo_ticker}: {str(e)}")
            return {'success': False, 'error': str(e)}

    async def sync_allocation_data(self, force_refresh: bool = False) -> Dict:
        """
        Sync allocation data for all securities.
        Only fetches data that's older than 7 days unless force_refresh=True.
        """
        print("\n" + "=" * 60)
        print("Syncing allocation data for securities")
        print("=" * 60 + "\n")

        # Get all securities
        result = await self.db.execute(select(Security))
        securities = list(result.scalars().all())

        # Filter securities that need updates
        cutoff_date = datetime.now() - timedelta(days=7)
        securities_to_update = []

        for security in securities:
            if force_refresh:
                securities_to_update.append(security)
            elif security.allocation_last_updated is None:
                securities_to_update.append(security)
            elif security.allocation_last_updated < cutoff_date:
                securities_to_update.append(security)

        if not securities_to_update:
            print("All securities have fresh allocation data")
            return {
                'securities_processed': 0,
                'securities_updated': 0,
                'errors': 0,
                'message': 'All allocation data is up to date'
            }

        print(f"Updating {len(securities_to_update)} securities...\n")

        updated_count = 0
        error_count = 0

        for i, security in enumerate(securities_to_update, 1):
            print(f"[{i}/{len(securities_to_update)}] Processing {security.symbol}...")

            result = await self.fetch_allocation_for_security(security)

            if result['success']:
                # Update security with allocation data
                security.asset_type = result['asset_type']
                security.sector = result.get('sector')
                security.industry = result.get('industry')
                security.country = result.get('country')
                security.allocation_last_updated = datetime.now()
                updated_count += 1
            else:
                error_count += 1

            # Security delay between different securities (2-4 seconds)
            if i < len(securities_to_update):
                await asyncio.sleep(random.uniform(2.0, 4.0))

        # Commit changes
        await self.db.commit()

        print(f"\n[OK] Allocation sync complete: {updated_count} updated, {error_count} errors")

        return {
            'securities_processed': len(securities_to_update),
            'securities_updated': updated_count,
            'errors': error_count,
            'message': f'Updated {updated_count} securities'
        }

    async def get_portfolio_allocation(self) -> Dict:
        """
        Get current portfolio allocation breakdown by sector and geography.
        Calculates weighted percentages based on current market values.
        """
        from app.services.portfolio_service import PortfolioService

        portfolio_service = PortfolioService(self.db)
        positions = await portfolio_service.get_positions_breakdown()

        if not positions:
            return {
                'sector_allocation': {},
                'geographic_allocation': {},
                'asset_type_allocation': {},
            }

        # Calculate total portfolio value
        total_value = sum(pos['market_value_eur'] for pos in positions)

        # Get all securities with allocation data
        result = await self.db.execute(select(Security))
        securities = {sec.id: sec for sec in result.scalars().all()}

        # Aggregate allocations
        sector_allocation = {}
        geographic_allocation = {}
        asset_type_allocation = {}

        for position in positions:
            security_id = position['security_id']
            security = securities.get(security_id)
            if not security:
                continue

            position_value = position['market_value_eur']
            position_weight = position_value / total_value if total_value > 0 else 0

            # Asset type
            asset_type = security.asset_type or 'Unknown'
            asset_type_allocation[asset_type] = asset_type_allocation.get(asset_type, 0) + position_weight

            # For known ETFs, distribute according to ETF allocation
            if is_known_etf(security.symbol):
                etf_data = get_etf_allocation(security.symbol)

                # Distribute sector allocation
                for sector, pct in etf_data['sector'].items():
                    weighted_pct = position_weight * (pct / 100)
                    sector_allocation[sector] = sector_allocation.get(sector, 0) + weighted_pct

                # Distribute geographic allocation
                for region, pct in etf_data['geographic'].items():
                    weighted_pct = position_weight * (pct / 100)
                    geographic_allocation[region] = geographic_allocation.get(region, 0) + weighted_pct

            # For individual stocks, use direct sector/country
            else:
                if security.sector:
                    sector_allocation[security.sector] = sector_allocation.get(security.sector, 0) + position_weight

                if security.country:
                    geographic_allocation[security.country] = geographic_allocation.get(security.country, 0) + position_weight

        # Convert to percentages
        sector_allocation = {k: v * 100 for k, v in sector_allocation.items()}
        geographic_allocation = {k: v * 100 for k, v in geographic_allocation.items()}
        asset_type_allocation = {k: v * 100 for k, v in asset_type_allocation.items()}

        # Sort by percentage descending
        sector_allocation = dict(sorted(sector_allocation.items(), key=lambda x: x[1], reverse=True))
        geographic_allocation = dict(sorted(geographic_allocation.items(), key=lambda x: x[1], reverse=True))
        asset_type_allocation = dict(sorted(asset_type_allocation.items(), key=lambda x: x[1], reverse=True))

        return {
            'sector_allocation': sector_allocation,
            'geographic_allocation': geographic_allocation,
            'asset_type_allocation': asset_type_allocation,
        }

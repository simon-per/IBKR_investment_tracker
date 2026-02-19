"""
Market Data Service
Fetches historical price data using Yahoo Finance (primary) and Alpha Vantage (fallback).
Handles exchange-specific ticker symbols for international stocks.
"""
from typing import List, Dict, Optional, Tuple
from datetime import date, datetime, timedelta
from decimal import Decimal
import httpx
import yfinance as yf
import requests
import time
import random
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.market_price_repository import MarketPriceRepository
from app.models.security import Security


class MarketDataService:
    """
    Service for fetching and caching market price data.

    Primary source: Yahoo Finance (yfinance) - Free, excellent international coverage
    Fallback: Alpha Vantage API - Requires API key, primarily US stocks

    Handles exchange-specific ticker formatting:
    - US stocks: "AMZN" (no suffix)
    - German stocks (XETRA): "AMZ.DE"
    - UK stocks: "HSBA.L"
    - etc.
    """

    # Mapping of IBKR exchange codes to Yahoo Finance suffixes
    EXCHANGE_SUFFIXES = {
        # US Exchanges
        'NASDAQ': '',
        'NYSE': '',
        'ARCA': '',
        'AMEX': '',
        'BATS': '',

        # European Exchanges
        'XETRA': '.DE',      # Germany (Frankfurt Electronic)
        'FWB': '.F',         # Frankfurt
        'SWB': '.STU',       # Stuttgart
        'IBIS': '.DE',       # Germany
        'IBIS2': '.DE',      # Germany (IBIS2)
        'LSE': '.L',         # London
        'LSEETF': '.L',      # London Stock Exchange ETF
        'LSEIOB1': '.L',     # London IOB
        'EURONEXT': '.PA',   # Paris (default)
        'AEB': '.AS',        # Amsterdam
        'BM': '.MC',         # Madrid
        'SBF': '.PA',        # Paris
        'EBS': '.SW',        # Swiss

        # Asian Exchanges
        'SEHK': '.HK',       # Hong Kong
        'TSE': '.T',         # Tokyo
        'KRX': '.KS',        # Korea

        # Other
        'TSX': '.TO',        # Toronto
        'ASX': '.AX',        # Australia
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.market_price_repo = MarketPriceRepository(db)
        from app.repositories.ticker_mapping_repository import TickerMappingRepository
        self.ticker_mapping_repo = TickerMappingRepository(db)

        # yfinance 1.1.0+ handles sessions and User-Agent headers internally
        # No need to create a custom session

    async def _get_yahoo_ticker(self, security: Security) -> str:
        """
        Convert IBKR security info to Yahoo Finance ticker format.
        Checks custom ticker mappings first, then falls back to exchange suffix logic.

        Args:
            security: Security object with symbol and exchange

        Returns:
            Yahoo Finance ticker (e.g., "AMZN", "AMZ.DE", "HSBA.L", "XNAS.DE")
        """
        symbol = security.symbol
        exchange = security.exchange

        if not exchange:
            # No exchange info, try symbol as-is
            return symbol

        # First, check for custom ticker mapping in database
        mapping = await self.ticker_mapping_repo.get_mapping(symbol, exchange)
        if mapping:
            print(f"DEBUG: Using custom ticker mapping: {symbol}@{exchange} -> {mapping.yahoo_ticker}")
            return mapping.yahoo_ticker

        # Fall back to exchange suffix logic
        suffix = self.EXCHANGE_SUFFIXES.get(exchange, '')
        ticker = f"{symbol}{suffix}"

        return ticker

    def _get_yahoo_ticker_variations(self, security: Security) -> list[str]:
        """
        Get multiple ticker variations to try if the primary ticker fails.
        Useful for securities that might have different tickers on Yahoo.

        Args:
            security: Security object

        Returns:
            List of ticker variations to try
        """
        symbol = security.symbol
        exchange = security.exchange
        variations = []

        # Primary ticker (using suffix logic)
        suffix = self.EXCHANGE_SUFFIXES.get(exchange, '')
        primary = f"{symbol}{suffix}"
        variations.append(primary)

        # For German exchanges, try both .DE and .F suffixes
        if exchange in ['XETRA', 'IBIS', 'IBIS2', 'FWB']:
            if '.DE' not in primary:
                variations.append(f"{symbol}.DE")
            if '.F' not in primary:
                variations.append(f"{symbol}.F")

        # Try symbol without suffix (works for some securities)
        if suffix and symbol not in variations:
            variations.append(symbol)

        return variations

    async def fetch_prices_from_yahoo(
        self,
        security: Security,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """
        Fetch historical prices from Yahoo Finance with smart retry logic.

        Args:
            security: Security object
            start_date: Start date
            end_date: End date

        Returns:
            List of dicts with date, close_price, currency
        """
        # Get primary ticker (checks custom mappings first)
        ticker = await self._get_yahoo_ticker(security)

        # Try primary ticker first
        prices, rate_limited = await self._try_fetch_yahoo(ticker, security, start_date, end_date)

        # If we hit rate limit, stop immediately - don't try variations
        if rate_limited:
            print(f"[RATE LIMIT] Rate limit hit on {ticker}, stopping variations to avoid further blocking")
            return []

        # If primary fails (but not rate limited), try variations
        if not prices:
            print(f"Primary ticker {ticker} failed, trying variations...")
            variations = self._get_yahoo_ticker_variations(security)

            for alt_ticker in variations:
                if alt_ticker == ticker:
                    continue  # Already tried this one

                print(f"Trying alternative ticker: {alt_ticker}")
                prices, rate_limited = await self._try_fetch_yahoo(alt_ticker, security, start_date, end_date)

                # If we hit rate limit during variations, stop immediately
                if rate_limited:
                    print(f"[RATE LIMIT] Rate limit hit on variation {alt_ticker}, stopping")
                    return []

                if prices:
                    # Success! Save this mapping for future use
                    print(f"Success with {alt_ticker}, saving mapping")
                    await self.ticker_mapping_repo.upsert_mapping(
                        ibkr_symbol=security.symbol,
                        ibkr_exchange=security.exchange,
                        yahoo_ticker=alt_ticker,
                        source="auto",
                        notes=f"Auto-discovered from {ticker}"
                    )
                    break

        return prices

    def _get_currency_from_ticker(self, ticker: str, security: Security) -> str:
        """
        Determine the currency for a Yahoo Finance ticker.
        Uses exchange suffix to infer currency, falls back to security currency.
        """
        # Map of Yahoo Finance suffixes to currencies
        suffix_currency_map = {
            '.DE': 'EUR',  # Germany (Xetra)
            '.F': 'EUR',   # Frankfurt
            '.STU': 'EUR', # Stuttgart
            '.L': 'GBP',   # London
            '.AS': 'EUR',  # Amsterdam
            '.PA': 'EUR',  # Paris
            '.MC': 'EUR',  # Madrid
            '.MI': 'EUR',  # Milan
            '.SW': 'CHF',  # Swiss
            '.HK': 'HKD',  # Hong Kong
            '.T': 'JPY',   # Tokyo
            '.TO': 'CAD',  # Toronto
            '.AX': 'AUD',  # Australia
        }

        # Check if ticker has a known suffix
        for suffix, currency in suffix_currency_map.items():
            if ticker.endswith(suffix):
                return currency

        # No suffix or unknown suffix - use security currency
        return security.currency

    async def _try_fetch_yahoo(
        self,
        ticker: str,
        security: Security,
        start_date: date,
        end_date: date
    ) -> Tuple[List[Dict], bool]:
        """
        Attempt to fetch prices from Yahoo Finance with a specific ticker.

        Returns:
            Tuple of (prices_list, rate_limited)
            - prices_list: List of price dicts, empty if ticker doesn't work
            - rate_limited: True if we hit a rate limit (stop trying variations)
        """
        try:
            # Random delay between 2-5 seconds to look more human
            delay = random.uniform(2.0, 5.0)
            time.sleep(delay)

            # Download data from Yahoo Finance
            # Note: yfinance 1.1.0+ handles sessions and User-Agent internally
            yf_ticker = yf.Ticker(ticker)
            hist = yf_ticker.history(
                start=start_date,
                end=end_date + timedelta(days=1),  # yfinance end is exclusive
                auto_adjust=False  # Get actual close prices, not adjusted
            )

            if hist.empty:
                return [], False  # No data, but not rate limited

            # Determine the correct currency for this ticker
            price_currency = self._get_currency_from_ticker(ticker, security)

            prices = []
            for date_index, row in hist.iterrows():
                price_date = date_index.date()
                close_price = row['Close']

                if close_price and not (close_price != close_price):  # Check for NaN
                    prices.append({
                        'date': price_date,
                        'close_price': Decimal(str(close_price)),
                        'currency': price_currency
                    })

            return prices, False

        except Exception as e:
            error_msg = str(e).lower()

            # Detect rate limiting errors
            # Yahoo returns various errors when rate limited: 404, 429, connection errors
            if any(keyword in error_msg for keyword in ['429', 'too many requests', 'rate limit', 'blocked']):
                print(f"[WARNING] Rate limit detected for {ticker}: {error_msg}")
                return [], True  # Rate limited - stop trying variations

            # For other errors (invalid ticker, etc.), continue trying variations
            return [], False

    async def fetch_prices_from_alpha_vantage(
        self,
        security: Security,
        outputsize: str = "full"
    ) -> List[Dict]:
        """
        Fetch prices from Alpha Vantage API (fallback).
        Note: Free tier primarily supports US stocks.

        Args:
            security: Security object
            outputsize: "compact" or "full"

        Returns:
            List of dicts with date, close_price, currency
        """
        if not settings.alpha_vantage_api_key or settings.alpha_vantage_api_key == "your_api_key_here":
            return []  # Skip if no API key

        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": security.symbol,  # Alpha Vantage uses US symbols primarily
            "outputsize": outputsize,
            "apikey": settings.alpha_vantage_api_key
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://www.alphavantage.co/query",
                    params=params
                )
                response.raise_for_status()
                data = response.json()

                if "Error Message" in data:
                    print(f"Alpha Vantage error: {data['Error Message']}")
                    return []

                if "Note" in data:
                    print(f"Alpha Vantage rate limit: {data['Note']}")
                    return []

                if "Time Series (Daily)" not in data:
                    return []

                time_series = data["Time Series (Daily)"]
                prices = []

                for date_str, price_data in time_series.items():
                    price_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    close_price = price_data["4. close"]

                    prices.append({
                        'date': price_date,
                        'close_price': Decimal(str(close_price)),
                        'currency': security.currency
                    })

                return prices

        except Exception as e:
            print(f"Error fetching Alpha Vantage data: {str(e)}")
            return []

    async def fetch_and_cache_prices(
        self,
        security: Security,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> int:
        """
        Fetch price data and cache in database.
        Only fetches missing dates to minimize API calls.

        Uses Yahoo Finance as primary source (free, good international coverage).
        Falls back to Alpha Vantage if Yahoo Finance fails (US stocks only).

        Includes polite delays between securities to avoid rate limiting.

        Args:
            security: Security object with symbol, exchange, and currency
            start_date: Start date (defaults to 1 year ago)
            end_date: End date (defaults to today)

        Returns:
            Number of new prices cached
        """
        if not end_date:
            end_date = date.today()

        if not start_date:
            start_date = end_date - timedelta(days=365)

        # Check what dates we already have
        missing_dates = await self.market_price_repo.get_missing_dates(
            security.id, start_date, end_date
        )

        if not missing_dates:
            print(f"All prices already cached for {security.symbol} ({start_date} to {end_date})")
            # Add delay even when skipping to maintain consistent pacing
            await asyncio.sleep(random.uniform(2.0, 4.0))
            return 0

        print(f"Fetching {len(missing_dates)} missing prices for {security.symbol} on {security.exchange}")

        # Try Yahoo Finance first (primary source)
        prices_data = await self.fetch_prices_from_yahoo(
            security, start_date, end_date
        )

        # If Yahoo Finance fails or returns nothing, try Alpha Vantage (US stocks only)
        if not prices_data and security.exchange in ['NASDAQ', 'NYSE', 'ARCA', 'AMEX']:
            print(f"Yahoo Finance failed for {security.symbol}, trying Alpha Vantage...")
            prices_data = await self.fetch_prices_from_alpha_vantage(security)

        if not prices_data:
            print(f"Warning: Could not fetch any price data for {security.symbol}")
            # Add delay before moving to next security
            await asyncio.sleep(random.uniform(3.0, 6.0))
            return 0

        # Filter to only missing dates and prepare for caching
        missing_dates_set = set(missing_dates)
        prices_to_cache = []

        for price_info in prices_data:
            if price_info['date'] in missing_dates_set:
                prices_to_cache.append({
                    'security_id': security.id,
                    'date': price_info['date'],
                    'close_price': price_info['close_price'],
                    'currency': security.currency,
                    'source': 'yahoo_finance'  # or 'alpha_vantage' if from fallback
                })

        # Bulk insert
        if prices_to_cache:
            count = await self.market_price_repo.bulk_create(prices_to_cache)
            await self.db.commit()
            print(f"Cached {count} new prices for {security.symbol}")

            # Add delay between securities to be polite to Yahoo Finance
            # 3-6 seconds feels human and keeps us well under rate limits
            delay = random.uniform(3.0, 6.0)
            print(f"Waiting {delay:.1f}s before next security...")
            await asyncio.sleep(delay)

            return count

        return 0

    async def get_price_for_date(
        self,
        security: Security,
        target_date: date
    ) -> Optional[Decimal]:
        """
        Get the closing price for a security on a specific date.
        Fetches from cache if available, otherwise fetches from API.

        For weekends/holidays, returns the most recent available price.

        Args:
            security: Security object
            target_date: Target date

        Returns:
            Close price as Decimal, or None if not available
        """
        # Try to get from cache first
        cached_price = await self.market_price_repo.get_by_security_and_date(
            security.id, target_date
        )

        if cached_price:
            return cached_price.close_price

        # Not in cache - fetch from API
        # Fetch a small range around the target date
        start_date = target_date - timedelta(days=7)
        end_date = target_date

        await self.fetch_and_cache_prices(security, start_date, end_date)

        # Try again from cache
        cached_price = await self.market_price_repo.get_by_security_and_date(
            security.id, target_date
        )

        if cached_price:
            return cached_price.close_price

        # If still not found (weekend/holiday), get the most recent price before target_date
        prices = await self.market_price_repo.get_price_range(
            security.id, start_date, target_date
        )

        if prices:
            return prices[-1].close_price

        return None

    async def get_price_range(
        self,
        security: Security,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """
        Get all prices for a security within a date range.
        Fetches missing dates from API if needed.

        Args:
            security: Security object
            start_date: Start date
            end_date: End date

        Returns:
            List of dicts with date and close_price
        """
        # Ensure we have all data cached
        await self.fetch_and_cache_prices(security, start_date, end_date)

        # Get from cache
        prices = await self.market_price_repo.get_price_range(
            security.id, start_date, end_date
        )

        return [
            {
                "date": price.date,
                "close_price": price.close_price,
                "currency": price.currency
            }
            for price in prices
        ]

    async def sync_security_prices(
        self,
        security: Security,
        days_back: int = 730
    ) -> int:
        """
        Sync historical prices for a security (fetch missing dates).

        Args:
            security: Security to sync prices for
            days_back: How many days back to fetch (default: 730 = 2 years)

        Returns:
            Number of new price records fetched
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        # Fetch and cache all prices in range
        await self.fetch_and_cache_prices(security, start_date, end_date)

        # Count how many prices we have for this security
        prices = await self.market_price_repo.get_price_range(
            security.id, start_date, end_date
        )

        return len(prices)

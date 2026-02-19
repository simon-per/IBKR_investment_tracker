"""
Currency Service
Handles currency conversion to EUR using Frankfurter API.
Caches exchange rates in the database to minimize API calls.
"""
from typing import Dict, Optional
from datetime import date
from decimal import Decimal
import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exchange_rate import ExchangeRate


class CurrencyService:
    """Service for currency conversion and exchange rate caching"""

    FRANKFURTER_API_URL = "https://api.frankfurter.app"
    BASE_CURRENCY = "EUR"

    # Currencies supported by Frankfurter API (as of 2024)
    # Source: https://www.frankfurter.app/docs/
    # Currencies supported by Frankfurter API
    # Note: RUB (Russian Ruble), QAR (Qatari Riyal), SAR (Saudi Riyal) are NOT supported
    # Positions in these currencies will be skipped during sync
    SUPPORTED_CURRENCIES = {
        'AUD', 'BGN', 'BRL', 'CAD', 'CHF', 'CNY', 'CZK', 'DKK',
        'EUR', 'GBP', 'HKD', 'HUF', 'IDR', 'ILS', 'INR', 'ISK',
        'JPY', 'KRW', 'MXN', 'MYR', 'NOK', 'NZD', 'PHP', 'PLN',
        'RON', 'SEK', 'SGD', 'THB', 'TRY', 'USD', 'ZAR'
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_exchange_rate(
        self,
        from_currency: str,
        target_date: date,
        to_currency: str = "EUR"
    ) -> Decimal:
        """
        Get exchange rate for a specific date.
        Checks cache first, then fetches from API if needed.
        For weekends/holidays without data, uses the most recent available rate (carry forward).

        Args:
            from_currency: Source currency code (e.g., 'USD')
            target_date: Date for the exchange rate
            to_currency: Target currency (always EUR for this app)

        Returns:
            Exchange rate as Decimal

        Raises:
            ValueError: If currency is not supported by Frankfurter API
        """
        # If currencies are the same, return 1.0
        if from_currency == to_currency:
            return Decimal("1.0")

        # Check if currency is supported
        if from_currency not in self.SUPPORTED_CURRENCIES:
            raise ValueError(f"Currency {from_currency} is not supported by Frankfurter API")

        # Check database cache first
        cached_rate = await self._get_cached_rate(from_currency, target_date, to_currency)
        if cached_rate:
            return cached_rate

        # If not in cache, try to fetch a range of recent rates (batch fetch)
        # This is more efficient than fetching one date at a time
        await self._batch_fetch_rates(from_currency, target_date, to_currency)

        # Check cache again after batch fetch
        cached_rate = await self._get_cached_rate(from_currency, target_date, to_currency)
        if cached_rate:
            return cached_rate

        # If still not found (weekend/holiday), use carry-forward strategy
        # Get the most recent rate before this date
        rate = await self._get_most_recent_rate(from_currency, target_date, to_currency)
        if rate:
            # Cache this carried-forward rate for the requested date
            await self._cache_rate(from_currency, to_currency, target_date, rate)
            return rate

        raise ValueError(f"No exchange rate available for {from_currency} on or before {target_date}")

    async def _get_cached_rate(
        self,
        from_currency: str,
        target_date: date,
        to_currency: str
    ) -> Optional[Decimal]:
        """Get exchange rate from database cache"""
        result = await self.session.execute(
            select(ExchangeRate).where(
                ExchangeRate.date == target_date,
                ExchangeRate.from_currency == from_currency,
                ExchangeRate.to_currency == to_currency
            )
        )
        exchange_rate = result.scalar_one_or_none()
        return exchange_rate.rate if exchange_rate else None

    async def _get_most_recent_rate(
        self,
        from_currency: str,
        target_date: date,
        to_currency: str
    ) -> Optional[Decimal]:
        """
        Get the most recent exchange rate on or before the target date.
        Used for weekends/holidays when specific date isn't available.
        """
        result = await self.session.execute(
            select(ExchangeRate)
            .where(
                ExchangeRate.date <= target_date,
                ExchangeRate.from_currency == from_currency,
                ExchangeRate.to_currency == to_currency
            )
            .order_by(ExchangeRate.date.desc())
            .limit(1)
        )
        exchange_rate = result.scalar_one_or_none()
        return exchange_rate.rate if exchange_rate else None

    async def _batch_fetch_rates(
        self,
        from_currency: str,
        target_date: date,
        to_currency: str,
        days_back: int = 30
    ) -> None:
        """
        Batch fetch exchange rates for a date range.
        Uses Frankfurter's range endpoint: /start_date..end_date

        Args:
            from_currency: Source currency
            target_date: Target date (end of range)
            to_currency: Target currency (EUR)
            days_back: How many days before target_date to fetch (default: 30)
        """
        from datetime import timedelta

        start_date = target_date - timedelta(days=days_back)
        end_date = target_date

        # Use Frankfurter's date range endpoint
        url = f"{self.FRANKFURTER_API_URL}/{start_date.isoformat()}..{end_date.isoformat()}"
        params = {
            "from": from_currency,
            "to": to_currency
        }

        async with httpx.AsyncClient() as client:
            try:
                print(f"DEBUG CurrencyService: Batch fetching {url} with params {params}")
                response = await client.get(url, params=params, timeout=10.0)
                print(f"DEBUG CurrencyService: Batch response status: {response.status_code}")

                if response.status_code >= 400:
                    print(f"DEBUG CurrencyService: Batch fetch failed, will try individual dates")
                    return

                data = response.json()

                # Response format: {"amount": 1, "base": "USD", "start_date": "...", "end_date": "...", "rates": {"2024-01-01": {"EUR": 0.9}, ...}}
                rates_by_date = data.get('rates', {})
                print(f"DEBUG CurrencyService: Received {len(rates_by_date)} rates")

                # Cache all rates
                for date_str, rate_data in rates_by_date.items():
                    rate_value = rate_data.get(to_currency)
                    if rate_value:
                        rate_date = date.fromisoformat(date_str)
                        rate_decimal = Decimal(str(rate_value))

                        # Check if already cached
                        existing = await self._get_cached_rate(from_currency, rate_date, to_currency)
                        if not existing:
                            await self._cache_rate(from_currency, to_currency, rate_date, rate_decimal)

                print(f"DEBUG CurrencyService: Cached {len(rates_by_date)} rates")

            except Exception as e:
                print(f"DEBUG CurrencyService: Batch fetch error: {str(e)}")
                # Don't raise - we'll fall back to individual fetches if needed

    async def _fetch_from_api(
        self,
        from_currency: str,
        target_date: date,
        to_currency: str
    ) -> Decimal:
        """
        Fetch exchange rate from Frankfurter API.

        API docs: https://www.frankfurter.app/docs/

        Raises:
            ValueError: If currency is not supported by Frankfurter API
        """
        url = f"{self.FRANKFURTER_API_URL}/{target_date.isoformat()}"
        params = {
            "from": from_currency,
            "to": to_currency
        }

        async with httpx.AsyncClient() as client:
            try:
                print(f"DEBUG CurrencyService: Fetching {url} with params {params}")
                response = await client.get(url, params=params, timeout=10.0)
                print(f"DEBUG CurrencyService: Response status: {response.status_code}")

                # If 404, the date might not be available yet (too recent or weekend)
                # Fall back to latest available rate
                if response.status_code == 404:
                    print(f"DEBUG CurrencyService: Date {target_date} not available, using latest rate")
                    url_latest = f"{self.FRANKFURTER_API_URL}/latest"
                    response = await client.get(url_latest, params=params, timeout=10.0)
                    print(f"DEBUG CurrencyService: Latest rate response status: {response.status_code}")

                # Check for unsupported currency error (400 status)
                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        error_msg = str(error_data)
                    except:
                        error_msg = response.text

                    # Check if it's a currency support issue
                    if 'Unknown currency' in error_msg or 'not supported' in error_msg.lower():
                        raise ValueError(f"Currency {from_currency} is not supported by Frankfurter API")

                response.raise_for_status()
                data = response.json()

                # Extract rate from response
                rate = data.get('rates', {}).get(to_currency)
                if rate is None:
                    raise ValueError(f"No exchange rate found for {from_currency}/{to_currency} on {target_date}")

                return Decimal(str(rate))

            except httpx.HTTPStatusError as e:
                # Handle HTTP errors (400, 404 indicate unsupported currency)
                if e.response.status_code in (400, 404):
                    raise ValueError(f"Currency {from_currency} is not supported by Frankfurter API")
                raise ValueError(f"Failed to fetch exchange rate: {str(e)}")
            except httpx.RequestError as e:
                raise ValueError(f"Network error while fetching exchange rate: {str(e)}")

    async def _cache_rate(
        self,
        from_currency: str,
        to_currency: str,
        target_date: date,
        rate: Decimal
    ) -> None:
        """Cache exchange rate in database"""
        exchange_rate = ExchangeRate(
            date=target_date,
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            source="frankfurter"
        )
        self.session.add(exchange_rate)
        await self.session.flush()

    async def convert_to_eur(
        self,
        amount: Decimal,
        from_currency: str,
        target_date: date
    ) -> Decimal:
        """
        Convert an amount to EUR.

        Args:
            amount: Amount to convert
            from_currency: Source currency
            target_date: Date for exchange rate

        Returns:
            Amount in EUR
        """
        if from_currency == self.BASE_CURRENCY:
            return amount

        rate = await self.get_exchange_rate(from_currency, target_date)
        return amount * rate

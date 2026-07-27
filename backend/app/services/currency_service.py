"""
Currency Service
Handles currency conversion to EUR using Frankfurter API.
Caches exchange rates in the database to minimize API calls.
"""
from typing import Dict, Optional, Tuple
from datetime import date
from decimal import Decimal
import httpx
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exchange_rate import ExchangeRate

logger = logging.getLogger(__name__)


class CurrencyService:
    """Service for currency conversion and exchange rate caching"""

    FRANKFURTER_API_URL = "https://api.frankfurter.dev/v1"
    BASE_CURRENCY = "EUR"

    # Currencies Frankfurter serves. It republishes the ECB reference rates, so the
    # list is exactly the ECB's 30 + EUR and does not grow — anything outside it
    # (TWD, RUB, QAR, SAR, ...) has to come from FALLBACK_API_URL below.
    SUPPORTED_CURRENCIES = {
        'AUD', 'BGN', 'BRL', 'CAD', 'CHF', 'CNY', 'CZK', 'DKK',
        'EUR', 'GBP', 'HKD', 'HUF', 'IDR', 'ILS', 'INR', 'ISK',
        'JPY', 'KRW', 'MXN', 'MYR', 'NOK', 'NZD', 'PHP', 'PLN',
        'RON', 'SEK', 'SGD', 'THB', 'TRY', 'USD', 'ZAR'
    }

    # Secondary provider, consulted *only* for currencies Frankfurter doesn't carry.
    # Before this existed a TWD position (TSMC on TWSE) could not be converted at all,
    # so reconcile_taxlots() skipped the lot and the holding silently vanished from the
    # portfolio and the tax report.
    #
    # The free tier serves the *latest* rates only — there is no historical endpoint
    # without a paid key. So this can never reconstruct an old rate, and we refuse to
    # pretend otherwise: it is used only for dates within FALLBACK_MAX_AGE_DAYS of
    # today, and the row is tagged `er-api-latest` so a today's-rate-applied-to-a-recent-
    # date approximation is never mistaken for a real historical quote. Older dates keep
    # raising, which preserves the existing skip-with-warning behaviour.
    #
    # In practice the window is enough: rates are cached per date as syncs run, so
    # history accumulates forward from the first day a currency appears.
    FALLBACK_API_URL = "https://open.er-api.com/v6/latest/EUR"
    FALLBACK_SOURCE = "er-api-latest"
    FALLBACK_MAX_AGE_DAYS = 7

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
            ValueError: If no rate can be obtained for the currency on that date
        """
        # If currencies are the same, return 1.0
        if from_currency == to_currency:
            return Decimal("1.0")

        # Check database cache first. This runs before the provider split so a rate
        # already cached from either provider is reused without another request.
        cached_rate = await self._get_cached_rate(from_currency, target_date, to_currency)
        if cached_rate:
            return cached_rate

        if from_currency in self.SUPPORTED_CURRENCIES:
            # If not in cache, try to fetch a range of recent rates (batch fetch)
            # This is more efficient than fetching one date at a time
            await self._batch_fetch_rates(from_currency, target_date, to_currency)
        else:
            await self._fetch_fallback_rate(from_currency, target_date, to_currency)

        # Check cache again after fetching
        cached_rate = await self._get_cached_rate(from_currency, target_date, to_currency)
        if cached_rate:
            return cached_rate

        # If still not found (weekend/holiday), use carry-forward strategy
        # Get the most recent rate before this date
        recent = await self._get_most_recent_rate(from_currency, target_date, to_currency)
        if recent:
            rate, source = recent
            # Cache this carried-forward rate for the requested date, keeping the
            # provider tag of the row it came from so the audit trail survives.
            await self._cache_rate(from_currency, to_currency, target_date, rate, source=source)
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
    ) -> Optional[Tuple[Decimal, str]]:
        """
        Get the most recent exchange rate on or before the target date, with the
        provider that produced it. Used for weekends/holidays when the specific
        date isn't available.

        The `date <= target_date` bound is what stops a currency we only learned
        about recently from being projected backwards onto older lots: a rate first
        cached today is invisible to a request for last year, which still raises and
        so keeps the caller's skip-with-warning path.
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
        return (exchange_rate.rate, exchange_rate.source) if exchange_rate else None

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
                logger.debug(f"Batch fetching {url} with params {params}")
                response = await client.get(url, params=params, timeout=10.0)
                logger.debug(f"Batch response status: {response.status_code}")

                if response.status_code >= 400:
                    logger.warning(f"Batch fetch failed (status {response.status_code}), will try individual dates")
                    return

                data = response.json()

                # Response format: {"amount": 1, "base": "USD", "start_date": "...", "end_date": "...", "rates": {"2024-01-01": {"EUR": 0.9}, ...}}
                rates_by_date = data.get('rates', {})
                logger.debug(f"Received {len(rates_by_date)} rates")

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

                logger.debug(f"Cached {len(rates_by_date)} rates")

            except Exception as e:
                logger.error(f"Batch fetch error: {e}")
                # Don't raise - we'll fall back to individual fetches if needed

    async def _fetch_fallback_rate(
        self,
        from_currency: str,
        target_date: date,
        to_currency: str
    ) -> None:
        """
        Fetch a rate for a currency Frankfurter doesn't carry, and cache it.

        Only called for currencies outside SUPPORTED_CURRENCIES. The provider is
        EUR-based and latest-only, so:

        - the rate for an arbitrary pair is derived as rates[to] / rates[from],
          with EUR itself implied at 1;
        - a target date older than FALLBACK_MAX_AGE_DAYS is refused outright rather
          than answered with today's rate. Silently backdating would put an invented
          historical rate on an old tax lot, which the tax report would then present
          as fact. Leaving it unfetched keeps the caller's existing behaviour of
          skipping the lot and reporting it in `warnings[]`.

        Never raises: like _batch_fetch_rates it simply leaves the cache unpopulated,
        and get_exchange_rate() decides what that means.
        """
        age = abs((date.today() - target_date).days)
        if age > self.FALLBACK_MAX_AGE_DAYS:
            logger.warning(
                f"No historical rate available for {from_currency} on {target_date}: "
                f"Frankfurter does not carry it and the fallback provider serves only "
                f"current rates ({age} days old > {self.FALLBACK_MAX_AGE_DAYS})"
            )
            return

        async with httpx.AsyncClient() as client:
            try:
                logger.debug(f"Fetching fallback rate for {from_currency} from {self.FALLBACK_API_URL}")
                response = await client.get(self.FALLBACK_API_URL, timeout=10.0)

                if response.status_code >= 400:
                    logger.warning(
                        f"Fallback FX provider returned {response.status_code} for {from_currency}"
                    )
                    return

                data = response.json()
                if data.get("result") != "success":
                    logger.warning(f"Fallback FX provider reported failure: {data.get('result')}")
                    return

                rates = data.get("rates") or {}
                rates.setdefault(self.BASE_CURRENCY, 1)

                from_rate = rates.get(from_currency)
                to_rate = rates.get(to_currency)
                if not from_rate or to_rate is None:
                    logger.warning(
                        f"Fallback FX provider has no rate for {from_currency}/{to_currency}"
                    )
                    return

                # Provider is EUR-based: rates[X] is "X per 1 EUR".
                rate = Decimal(str(to_rate)) / Decimal(str(from_rate))

                existing = await self._get_cached_rate(from_currency, target_date, to_currency)
                if not existing:
                    await self._cache_rate(
                        from_currency, to_currency, target_date, rate,
                        source=self.FALLBACK_SOURCE
                    )
                logger.info(
                    f"Cached fallback rate {from_currency}/{to_currency}={rate} for {target_date}"
                )

            except Exception as e:
                logger.error(f"Fallback FX fetch error for {from_currency}: {e}")

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
                logger.debug(f"Fetching {url} with params {params}")
                response = await client.get(url, params=params, timeout=10.0)
                logger.debug(f"Response status: {response.status_code}")

                # If 404, the date might not be available yet (too recent or weekend)
                # Fall back to latest available rate
                if response.status_code == 404:
                    logger.debug(f"Date {target_date} not available, using latest rate")
                    url_latest = f"{self.FRANKFURTER_API_URL}/latest"
                    response = await client.get(url_latest, params=params, timeout=10.0)
                    logger.debug(f"Latest rate response status: {response.status_code}")

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
        rate: Decimal,
        source: str = "frankfurter"
    ) -> None:
        """Cache exchange rate in database"""
        exchange_rate = ExchangeRate(
            date=target_date,
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            source=source
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

    async def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        target_date: date,
    ) -> Decimal:
        """
        Convert an amount between arbitrary supported currencies on a given date.

        Frankfurter is EUR-based but supports arbitrary from/to pairs, and the
        exchange-rate cache is keyed by (from, to), so this works for e.g.
        EUR->CHF, EUR->USD as well as the usual X->EUR.
        """
        if from_currency == to_currency:
            return amount

        rate = await self.get_exchange_rate(from_currency, target_date, to_currency)
        return amount * rate

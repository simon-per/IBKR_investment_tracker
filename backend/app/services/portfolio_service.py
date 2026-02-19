"""
Portfolio Service
Calculates cost basis and market value for the portfolio over time.
"""
from typing import List, Dict, Optional
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.models.taxlot import TaxLot
from app.models.security import Security
from app.services.market_data_service import MarketDataService
from app.services.currency_service import CurrencyService

logger = logging.getLogger(__name__)


class PortfolioService:
    """
    Service for portfolio analytics and calculations.

    Calculates:
    - Cost basis: Total amount invested (in EUR)
    - Market value: Current worth of holdings (in EUR)
    - Unrealized gain/loss
    - Portfolio composition by security
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.market_data_service = MarketDataService(db)
        self.currency_service = CurrencyService(db)

    async def get_portfolio_value_over_time(
        self,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """
        Calculate portfolio value (cost basis and market value) for each day in range.
        Uses optimized caching for fast performance.
        """
        # Get all open taxlots
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .where(TaxLot.is_open == True)
            .order_by(TaxLot.open_date.asc())
        )
        taxlots_with_securities = result.all()

        if not taxlots_with_securities:
            return []

        # Pre-load all data once
        unique_securities = {security for _, security in taxlots_with_securities}
        price_cache = await self._preload_market_prices(unique_securities, start_date, end_date)
        exchange_rate_cache = await self._preload_exchange_rates(unique_securities, start_date, end_date)

        # Calculate portfolio value for each business day
        portfolio_timeline = []
        current_date = start_date

        while current_date <= end_date:
            # Skip weekends
            if current_date.weekday() < 5:
                daily_value = self._calculate_daily_value(
                    current_date, taxlots_with_securities, price_cache, exchange_rate_cache
                )
                portfolio_timeline.append(daily_value)

            current_date += timedelta(days=1)

        return portfolio_timeline

    async def get_current_portfolio_summary(self) -> Dict:
        """
        Get current portfolio summary with latest values.
        """
        today = date.today()

        # Get all open taxlots with securities
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .where(TaxLot.is_open == True)
        )
        taxlots_with_securities = result.all()

        if not taxlots_with_securities:
            return {
                "total_cost_basis_eur": 0.0,
                "total_market_value_eur": 0.0,
                "total_gain_loss_eur": 0.0,
                "total_gain_loss_percent": 0.0,
                "num_positions": 0
            }

        # Use optimized method
        unique_securities = {security for _, security in taxlots_with_securities}
        price_cache = await self._preload_market_prices(unique_securities, today, today)
        exchange_rate_cache = await self._preload_exchange_rates(unique_securities, today, today)

        daily_value = self._calculate_daily_value(
            today, taxlots_with_securities, price_cache, exchange_rate_cache
        )

        return {
            "total_cost_basis_eur": daily_value["cost_basis_eur"],
            "total_market_value_eur": daily_value["market_value_eur"],
            "total_gain_loss_eur": daily_value["gain_loss_eur"],
            "total_gain_loss_percent": daily_value["gain_loss_percent"],
            "num_positions": len(set(security.id for _, security in taxlots_with_securities)),
            "date": daily_value["date"]
        }

    async def get_positions_breakdown(self) -> List[Dict]:
        """
        Get breakdown of all current positions by security.
        """
        today = date.today()

        # Get all open taxlots grouped by security
        result = await self.db.execute(
            select(TaxLot, Security)
            .join(Security, TaxLot.security_id == Security.id)
            .where(TaxLot.is_open == True)
            .order_by(Security.symbol.asc())
        )
        taxlots_with_securities = result.all()

        # Pre-load all market prices and exchange rates
        unique_securities = {security for _, security in taxlots_with_securities}
        price_cache = await self._preload_market_prices(unique_securities, today, today)
        exchange_rate_cache = await self._preload_exchange_rates(unique_securities, today, today)

        # Pre-load analyst ratings
        from app.repositories.analyst_rating_repository import AnalystRatingRepository
        rating_repo = AnalystRatingRepository(self.db)
        all_ratings = await rating_repo.get_all()
        ratings_by_security = {rating.security_id: rating for rating in all_ratings}

        # Group by security
        positions = {}
        securities_by_id = {}

        for taxlot, security in taxlots_with_securities:
            if security.id not in positions:
                positions[security.id] = {
                    "security_id": security.id,
                    "symbol": security.symbol,
                    "description": security.description,
                    "isin": security.isin,
                    "currency": security.currency,
                    "exchange": security.exchange,
                    "quantity": Decimal("0.0"),
                    "cost_basis_eur": Decimal("0.0"),
                    "taxlots": []
                }
                securities_by_id[security.id] = security

            positions[security.id]["quantity"] += taxlot.quantity
            positions[security.id]["cost_basis_eur"] += taxlot.cost_basis_eur
            positions[security.id]["taxlots"].append({
                "open_date": taxlot.open_date.isoformat(),
                "quantity": float(taxlot.quantity),
                "cost_basis": float(taxlot.cost_basis),
                "cost_basis_eur": float(taxlot.cost_basis_eur)
            })

        # Calculate market values using cached data with fallback
        positions_list = []
        for security_id, position in positions.items():
            security = securities_by_id[security_id]

            # Get latest market price with forward-fill fallback
            market_price = self._get_market_price_with_fallback(
                security.id, today, price_cache
            )

            if market_price:
                market_value = position["quantity"] * market_price

                # Convert to EUR with forward-fill fallback
                if security.currency != "EUR":
                    rate = self._get_exchange_rate_with_fallback(
                        security.currency, today, exchange_rate_cache
                    )
                    if rate:
                        market_value_eur = market_value * rate
                    else:
                        logger.warning(
                            f"No exchange rate for {security.currency} on {today}, "
                            f"cannot calculate market value for {security.symbol}"
                        )
                        market_value_eur = Decimal("0.0")
                else:
                    market_value_eur = market_value

                position["market_value_eur"] = float(market_value_eur)
                position["market_price"] = float(market_price)
            else:
                logger.warning(
                    f"No market price for {security.symbol} on {today}, "
                    f"setting market value to 0"
                )
                position["market_value_eur"] = 0.0
                position["market_price"] = None

            # Calculate gains
            cost_basis = position["cost_basis_eur"]
            market_value = Decimal(str(position["market_value_eur"]))
            gain_loss = market_value - cost_basis

            position["gain_loss_eur"] = float(gain_loss)
            position["gain_loss_percent"] = float(
                (gain_loss / cost_basis * 100) if cost_basis > 0 else 0
            )

            # Convert Decimal to float for JSON serialization
            position["quantity"] = float(position["quantity"])
            position["cost_basis_eur"] = float(position["cost_basis_eur"])

            # Add analyst rating if available
            rating = ratings_by_security.get(security_id)
            if rating:
                position["analyst_rating"] = {
                    "strong_buy": rating.strong_buy,
                    "buy": rating.buy,
                    "hold": rating.hold,
                    "sell": rating.sell,
                    "strong_sell": rating.strong_sell,
                    "total_ratings": rating.total_ratings,
                    "consensus": rating.consensus,
                    "last_updated": rating.last_updated.isoformat()
                }
            else:
                position["analyst_rating"] = None

            positions_list.append(position)

        # Sort by market value (largest first)
        positions_list.sort(key=lambda x: x["market_value_eur"], reverse=True)

        return positions_list

    async def _preload_market_prices(
        self,
        securities: set,
        start_date: date,
        end_date: date,
        lookback_days: int = 14
    ) -> Dict:
        """
        Pre-load all market prices for securities in date range.

        Extends the date range backwards by lookback_days to support
        forward-fill fallback logic when prices are missing.

        Returns: {security_id: {date: price}}
        """
        from app.models.market_price import MarketPrice

        security_ids = [s.id for s in securities]

        # Extend start_date backwards to support forward-fill
        extended_start_date = start_date - timedelta(days=lookback_days)

        result = await self.db.execute(
            select(MarketPrice)
            .where(
                and_(
                    MarketPrice.security_id.in_(security_ids),
                    MarketPrice.date >= extended_start_date,
                    MarketPrice.date <= end_date
                )
            )
        )

        all_prices = result.scalars().all()

        # Build nested dict: {security_id: {date: price}}
        price_cache = {}
        for price in all_prices:
            if price.security_id not in price_cache:
                price_cache[price.security_id] = {}
            price_cache[price.security_id][price.date] = price.close_price

        return price_cache

    async def _preload_exchange_rates(
        self,
        securities: set,
        start_date: date,
        end_date: date,
        lookback_days: int = 14
    ) -> Dict:
        """
        Pre-load all exchange rates for currencies in date range.

        Extends the date range backwards by lookback_days to support
        forward-fill fallback logic when rates are missing.

        Returns: {(from_currency, date): rate}
        """
        from app.models.exchange_rate import ExchangeRate

        currencies = {s.currency for s in securities if s.currency != 'EUR'}

        if not currencies:
            return {}

        # Extend start_date backwards to support forward-fill
        extended_start_date = start_date - timedelta(days=lookback_days)

        result = await self.db.execute(
            select(ExchangeRate)
            .where(
                and_(
                    ExchangeRate.from_currency.in_(currencies),
                    ExchangeRate.to_currency == 'EUR',
                    ExchangeRate.date >= extended_start_date,
                    ExchangeRate.date <= end_date
                )
            )
        )

        all_rates = result.scalars().all()

        # Build dict: {(from_currency, date): rate}
        rate_cache = {}
        for rate in all_rates:
            rate_cache[(rate.from_currency, rate.date)] = rate.rate

        return rate_cache

    def _get_market_price_with_fallback(
        self,
        security_id: int,
        target_date: date,
        price_cache: Dict,
        max_lookback_days: int = 14
    ) -> Optional[Decimal]:
        """
        Get market price for a date with forward-fill fallback.

        If price is missing for target_date, looks back up to max_lookback_days
        to find the most recent available price (carry-forward strategy).

        Args:
            security_id: ID of the security
            target_date: Date to get price for
            price_cache: Pre-loaded price cache {security_id: {date: price}}
            max_lookback_days: Maximum days to look back (default: 7)

        Returns:
            Price as Decimal, or None if no price found within lookback window
        """
        # Try exact date first
        market_price = price_cache.get(security_id, {}).get(target_date)
        if market_price:
            return market_price

        # Try previous days (up to max_lookback_days)
        for days_back in range(1, max_lookback_days + 1):
            fallback_date = target_date - timedelta(days=days_back)
            market_price = price_cache.get(security_id, {}).get(fallback_date)
            if market_price:
                logger.debug(
                    f"Using {days_back}-day-old price for security {security_id} "
                    f"on {target_date}: €{market_price} (from {fallback_date})"
                )
                return market_price

        # No price found within lookback window
        logger.warning(
            f"No price found for security {security_id} on {target_date} "
            f"(checked {max_lookback_days} days back)"
        )
        return None

    def _get_exchange_rate_with_fallback(
        self,
        from_currency: str,
        target_date: date,
        exchange_rate_cache: Dict,
        max_lookback_days: int = 14
    ) -> Optional[Decimal]:
        """
        Get exchange rate for a date with forward-fill fallback.

        If rate is missing for target_date, looks back up to max_lookback_days
        to find the most recent available rate (carry-forward strategy).

        Args:
            from_currency: Currency to convert from (e.g., 'USD')
            target_date: Date to get rate for
            exchange_rate_cache: Pre-loaded rate cache {(currency, date): rate}
            max_lookback_days: Maximum days to look back (default: 7)

        Returns:
            Exchange rate as Decimal, or None if no rate found within lookback window
        """
        # Try exact date first
        rate = exchange_rate_cache.get((from_currency, target_date))
        if rate:
            return rate

        # Try previous days (up to max_lookback_days)
        for days_back in range(1, max_lookback_days + 1):
            fallback_date = target_date - timedelta(days=days_back)
            rate = exchange_rate_cache.get((from_currency, fallback_date))
            if rate:
                logger.debug(
                    f"Using {days_back}-day-old exchange rate for {from_currency} "
                    f"on {target_date}: {rate} (from {fallback_date})"
                )
                return rate

        # No rate found within lookback window
        logger.warning(
            f"No exchange rate found for {from_currency} on {target_date} "
            f"(checked {max_lookback_days} days back)"
        )
        return None

    def _calculate_daily_value(
        self,
        target_date: date,
        taxlots_with_securities: List,
        price_cache: Dict,
        exchange_rate_cache: Dict
    ) -> Dict:
        """
        Calculate portfolio value for a specific date using cached data.
        Simple and fast.
        """
        total_cost_basis = Decimal("0.0")
        total_market_value = Decimal("0.0")

        for taxlot, security in taxlots_with_securities:
            # Only include taxlots opened on or before this date
            if taxlot.open_date > target_date:
                continue

            total_cost_basis += taxlot.cost_basis_eur

            # Get market price with forward-fill fallback
            market_price = self._get_market_price_with_fallback(
                security.id, target_date, price_cache
            )

            if market_price:
                position_value = taxlot.quantity * market_price

                # Convert to EUR with forward-fill fallback
                if security.currency != "EUR":
                    rate = self._get_exchange_rate_with_fallback(
                        security.currency, target_date, exchange_rate_cache
                    )
                    if rate:
                        position_value_eur = position_value * rate
                        total_market_value += position_value_eur
                    else:
                        # Log but skip this position if no exchange rate available
                        logger.warning(
                            f"Skipping position for security {security.id} on {target_date}: "
                            f"no exchange rate for {security.currency}"
                        )
                else:
                    position_value_eur = position_value
                    total_market_value += position_value_eur
            else:
                # Log but skip this position if no market price available
                logger.warning(
                    f"Skipping position for security {security.id} ({security.symbol}) on {target_date}: "
                    f"no market price available"
                )

        gain_loss = total_market_value - total_cost_basis

        return {
            "date": target_date.isoformat(),
            "cost_basis_eur": float(total_cost_basis),
            "market_value_eur": float(total_market_value),
            "gain_loss_eur": float(gain_loss),
            "gain_loss_percent": float((gain_loss / total_cost_basis * 100) if total_cost_basis > 0 else 0)
        }

"""
Database models for the IBKR Portfolio Analyzer.
All models are imported here to ensure they're discovered by Alembic for migrations.
"""

from app.models.security import Security
from app.models.taxlot import TaxLot
from app.models.exchange_rate import ExchangeRate
from app.models.market_price import MarketPrice
from app.models.analyst_rating import AnalystRating
from app.models.benchmark_price import BenchmarkPrice
from app.models.fundamental_metrics import FundamentalMetrics
from app.models.earnings_event import EarningsEvent
from app.models.watchlist_item import WatchlistItem
from app.models.dividend_payment import DividendPayment

__all__ = [
    "Security",
    "TaxLot",
    "ExchangeRate",
    "MarketPrice",
    "AnalystRating",
    "BenchmarkPrice",
    "FundamentalMetrics",
    "EarningsEvent",
    "WatchlistItem",
    "DividendPayment",
]

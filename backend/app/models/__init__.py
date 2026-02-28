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

__all__ = [
    "Security",
    "TaxLot",
    "ExchangeRate",
    "MarketPrice",
    "AnalystRating",
    "BenchmarkPrice",
]

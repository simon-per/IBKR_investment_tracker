from sqlalchemy import String, Numeric, Date, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime, date
from decimal import Decimal

from app.database import Base


class BenchmarkPrice(Base):
    """
    Stores historical daily closing prices for benchmark indices (S&P 500, NASDAQ).
    Used for "what if I bought the index instead?" comparisons.
    """
    __tablename__ = "benchmark_prices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # ^GSPC, ^IXIC
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    source: Mapped[str] = mapped_column(String(50), default="yahoo_finance", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('ticker', 'date', name='uix_benchmark_ticker_date'),
        Index('ix_benchmark_ticker_date', 'ticker', 'date'),
    )

    def __repr__(self) -> str:
        return (
            f"<BenchmarkPrice(ticker={self.ticker}, date={self.date}, "
            f"close_price={self.close_price} {self.currency})>"
        )

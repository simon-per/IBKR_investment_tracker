from sqlalchemy import String, Numeric, Date, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime, date
from decimal import Decimal

from app.database import Base


class ExchangeRate(Base):
    """
    Stores historical currency exchange rates for conversion to EUR.
    Caches rates to minimize API calls to Frankfurter.
    """
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    from_currency: Mapped[str] = mapped_column(String(3), nullable=False)  # USD, GBP, etc.
    to_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")  # Always EUR
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)  # Exchange rate with high precision
    source: Mapped[str] = mapped_column(String(50), default="frankfurter", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    # Unique constraint to prevent duplicate rates for same date and currency pair
    # and index for fast lookups
    __table_args__ = (
        UniqueConstraint('date', 'from_currency', 'to_currency', name='uix_date_currencies'),
        Index('ix_date_from_currency', 'date', 'from_currency'),
    )

    def __repr__(self) -> str:
        return (
            f"<ExchangeRate(date={self.date}, {self.from_currency}/{self.to_currency}={self.rate})>"
        )

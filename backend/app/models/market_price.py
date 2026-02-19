from sqlalchemy import String, Integer, ForeignKey, Numeric, Date, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime, date
from decimal import Decimal

from app.database import Base


class MarketPrice(Base):
    """
    Stores historical daily closing prices for securities.
    Caches market data from Alpha Vantage to reduce API costs.
    Supports incremental fetching of missing date ranges.
    """
    __tablename__ = "market_prices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)  # Daily closing price
    currency: Mapped[str] = mapped_column(String(3), nullable=False)  # Price currency
    source: Mapped[str] = mapped_column(String(50), default="alpha_vantage", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    # Relationships
    security: Mapped["Security"] = relationship(back_populates="market_prices")

    # Unique constraint to prevent duplicate prices for same security and date
    # and indexes for fast range queries
    __table_args__ = (
        UniqueConstraint('security_id', 'date', name='uix_security_date'),
        Index('ix_date_security', 'date', 'security_id'),
    )

    def __repr__(self) -> str:
        return (
            f"<MarketPrice(security_id={self.security_id}, date={self.date}, "
            f"close_price={self.close_price} {self.currency})>"
        )

from sqlalchemy import String, Integer, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import List, Optional

from app.database import Base


class Security(Base):
    """
    Represents a security (stock, ETF, etc.) from Interactive Brokers.
    Uses ISIN + exchange as composite unique identifier to handle same security
    traded on different exchanges (e.g., Amazon on NASDAQ vs XETRA).
    """
    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    isin: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)  # USD, EUR, etc.
    conid: Mapped[int] = mapped_column(nullable=False, unique=True, index=True)  # IBKR unique ID
    asset_category: Mapped[str] = mapped_column(String(20), nullable=True)  # STK, OPT, FUT, etc.
    exchange: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Allocation data
    sector: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    asset_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="Stock")  # Stock, ETF, etc.
    allocation_last_updated: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationships
    taxlots: Mapped[List["TaxLot"]] = relationship(
        back_populates="security",
        cascade="all, delete-orphan"
    )
    market_prices: Mapped[List["MarketPrice"]] = relationship(
        back_populates="security",
        cascade="all, delete-orphan"
    )
    analyst_rating: Mapped[Optional["AnalystRating"]] = relationship(
        back_populates="security",
        cascade="all, delete-orphan",
        uselist=False  # One-to-one relationship
    )

    # Composite unique constraint for ISIN + exchange
    # and additional indexes for performance
    __table_args__ = (
        UniqueConstraint('isin', 'exchange', name='uix_isin_exchange'),
        Index('ix_symbol_currency', 'symbol', 'currency'),
    )

    def __repr__(self) -> str:
        return f"<Security(id={self.id}, symbol={self.symbol}, isin={self.isin}, exchange={self.exchange})>"

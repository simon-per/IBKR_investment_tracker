from sqlalchemy import Integer, Float, String, ForeignKey, DateTime, Index, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional

from app.database import Base


class FundamentalMetrics(Base):
    """
    Stores fundamental growth metrics for securities from Yahoo Finance.
    One-to-one with Security. Cached and refreshed weekly.
    """
    __tablename__ = "fundamental_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )

    # Valuation ratios
    trailing_pe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    forward_pe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    peg_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_to_sales: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_to_book: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Growth rates
    revenue_growth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    earnings_growth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fwd_revenue_growth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fwd_eps_growth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Margins
    profit_margins: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gross_margins: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    operating_margins: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Size & analyst targets
    market_cap: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    number_of_analysts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_mean_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_high_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_low_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Classification
    quote_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # ETF, EQUITY
    data_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Timestamps
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    # Relationships
    security: Mapped["Security"] = relationship(back_populates="fundamental_metrics")

    __table_args__ = (
        Index('ix_fundamental_metrics_security_id', 'security_id', unique=True),
    )

    @property
    def is_etf(self) -> bool:
        return self.quote_type == 'ETF'

    def __repr__(self) -> str:
        return (
            f"<FundamentalMetrics(security_id={self.security_id}, "
            f"pe={self.trailing_pe}, peg={self.peg_ratio})>"
        )

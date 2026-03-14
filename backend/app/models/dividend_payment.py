from sqlalchemy import Integer, Numeric, String, Date, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional
from decimal import Decimal

from app.database import Base


class DividendPayment(Base):
    """
    Caches yfinance dividend data (ex-date + per-share amount) and computed
    income based on shares held from tax lots. All amounts converted to EUR.
    """
    __tablename__ = "dividend_payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_per_share: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    shares_held: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    gross_amount_eur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    last_computed: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    # Relationships
    security: Mapped["Security"] = relationship(back_populates="dividend_payments")

    __table_args__ = (
        UniqueConstraint('security_id', 'ex_date', name='uix_dividend_security_exdate'),
        Index('ix_dividend_payments_security_id', 'security_id'),
        Index('ix_dividend_payments_ex_date', 'ex_date'),
    )

    def __repr__(self) -> str:
        return (
            f"<DividendPayment(security_id={self.security_id}, "
            f"ex_date={self.ex_date}, amount={self.amount_per_share})>"
        )

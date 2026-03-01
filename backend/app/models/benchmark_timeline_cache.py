from sqlalchemy import String, Numeric, Date, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime, date
from decimal import Decimal

from app.database import Base


class BenchmarkTimelineCache(Base):
    """
    Caches computed daily benchmark comparison values.
    Historical values never change (prices and FX rates are fixed),
    so we compute once and only recompute recent days when new prices arrive.
    """
    __tablename__ = "benchmark_timeline_cache"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    benchmark_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    benchmark_value_eur: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cost_basis_eur: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gain_loss_eur: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gain_loss_percent: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('benchmark_key', 'date', name='uix_benchmark_cache_key_date'),
        Index('ix_benchmark_cache_key_date', 'benchmark_key', 'date'),
    )

    def __repr__(self) -> str:
        return (
            f"<BenchmarkTimelineCache(key={self.benchmark_key}, date={self.date}, "
            f"value={self.benchmark_value_eur})>"
        )

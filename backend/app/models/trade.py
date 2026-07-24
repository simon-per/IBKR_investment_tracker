from sqlalchemy import String, Integer, ForeignKey, Numeric, Date, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from app.database import Base


class Trade(Base):
    """
    A single executed IBKR trade (BUY/SELL), parsed from the Flex Query <Trades>
    section. This is the authoritative source of realized P&L and true sale
    dates/proceeds, replacing the market-price approximation used when only
    <OpenPositions> is available.

    Idempotent on ``ib_key`` (IBKR transactionID, falling back to tradeID). The
    ``conid`` is the durable link to a security (``security_id`` is resolved when
    the security exists locally, but a fully-sold security may be absent).
    """
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ib_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    conid: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    security_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("securities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    symbol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    buy_sell: Mapped[str] = mapped_column(String(16), nullable=False)  # BUY / SELL / CANCELBUY / CANCELSELL
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)  # signed: buys +, sells -
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)  # tradePrice
    proceeds: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    commission: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)  # ibCommission
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    realized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)  # fifoPnlRealized
    asset_category: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_trades_conid_date", "conid", "trade_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<Trade(ib_key={self.ib_key}, conid={self.conid}, "
            f"{self.buy_sell} {self.quantity} @ {self.price} on {self.trade_date})>"
        )

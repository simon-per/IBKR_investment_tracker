"""
Ticker Mapping Model
Maps IBKR securities to Yahoo Finance ticker symbols.
Useful for German ETFs and stocks that have different tickers on Yahoo Finance.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class TickerMapping(Base):
    """
    Custom ticker mappings for securities that need special handling.

    Examples:
    - IBKR: symbol="XNAS", exchange="IBIS2" → Yahoo: "XNAS.DE"
    - IBKR: symbol="XAIX", exchange="XETRA" → Yahoo: "XAIX.DE"
    - IBKR: symbol="VUSA", exchange="LSE" → Yahoo: "VUSA.L"
    """
    __tablename__ = "ticker_mappings"

    id = Column(Integer, primary_key=True, index=True)

    # IBKR identifiers
    ibkr_symbol = Column(String(20), nullable=False)
    ibkr_exchange = Column(String(20), nullable=False)
    ibkr_conid = Column(Integer, nullable=True)  # Optional - for extra precision

    # Yahoo Finance ticker
    yahoo_ticker = Column(String(20), nullable=False)

    # Metadata
    source = Column(String(50), default="manual")  # "manual", "auto", "builtin"
    is_active = Column(Boolean, default=True)
    notes = Column(String(200), nullable=True)

    # When this row was set, and when its ticker last changed. Without these,
    # "did this cached price or dividend come from the mapping in force today?"
    # is unanswerable — which is why a wrong SBI mapping poisoned derived data
    # for months unnoticed. `updated_at` is what the dividend-provenance check
    # compares each estimate row's last_computed against, so it must be touched
    # on every edit, not just on insert.
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(),
                        nullable=True)

    # Unique constraint: one mapping per IBKR symbol+exchange
    __table_args__ = (
        UniqueConstraint('ibkr_symbol', 'ibkr_exchange', name='uq_ibkr_symbol_exchange'),
    )

    def __repr__(self):
        return f"<TickerMapping {self.ibkr_symbol}@{self.ibkr_exchange} → {self.yahoo_ticker}>"

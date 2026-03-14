"""
Portfolio Schemas
Pydantic models for portfolio API responses.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date


class TaxLotInfo(BaseModel):
    """Individual taxlot information within a position"""
    open_date: str
    quantity: float
    cost_basis: float
    cost_basis_eur: float

    class Config:
        from_attributes = True


class AnalystRatingInfo(BaseModel):
    """Analyst rating information for a security"""
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int
    total_ratings: int
    consensus: str
    last_updated: str

    class Config:
        from_attributes = True


class PositionResponse(BaseModel):
    """Response model for individual security position"""
    security_id: int
    symbol: str
    description: str
    isin: str
    currency: str
    exchange: Optional[str]
    quantity: float
    cost_basis_eur: float
    market_value_eur: float
    market_price: Optional[float]
    gain_loss_eur: float
    gain_loss_percent: float
    taxlots: List[TaxLotInfo]
    analyst_rating: Optional[AnalystRatingInfo] = None

    class Config:
        from_attributes = True


class PortfolioValuePoint(BaseModel):
    """Single data point for portfolio value over time"""
    date: str = Field(..., description="Date in ISO format (YYYY-MM-DD)")
    cost_basis_eur: float = Field(..., description="Total amount invested up to this date")
    market_value_eur: float = Field(..., description="Current market value on this date")
    gain_loss_eur: float = Field(..., description="Unrealized gain/loss")
    gain_loss_percent: float = Field(..., description="Percentage gain/loss")

    class Config:
        from_attributes = True


class AnnualizedReturnResponse(BaseModel):
    """Response for XIRR annualized return calculation"""
    method: str = Field(..., description="Calculation method used (xirr)")
    annualized_return_pct: Optional[float] = Field(None, description="Annualized return percentage")
    start_date: str = Field(..., description="Start date of the calculation period")
    end_date: str = Field(..., description="End date of the calculation period")
    num_cash_flows: int = Field(..., description="Number of cash flows used in calculation")

    class Config:
        from_attributes = True


class BenchmarkValuePoint(BaseModel):
    """Single data point for benchmark comparison"""
    date: str
    benchmark_value_eur: float
    cost_basis_eur: float
    gain_loss_eur: float
    gain_loss_percent: float


class BenchmarkResponse(BaseModel):
    """Response for benchmark comparison endpoint"""
    benchmark_name: str
    benchmark_ticker: str
    data: List[BenchmarkValuePoint]


class BenchmarkInfo(BaseModel):
    """Available benchmark index info"""
    key: str
    name: str
    ticker: str
    currency: str


class SecurityAttribution(BaseModel):
    """P&L attribution for a single security over a time period"""
    security_id: int
    symbol: str
    description: str
    start_market_value_eur: float
    end_market_value_eur: float
    new_investment_eur: float
    value_change_eur: float
    pnl_contribution_eur: float
    contribution_percent: float
    weight_percent: float

    class Config:
        from_attributes = True


class PerformanceAttributionResponse(BaseModel):
    """Response for performance attribution endpoint"""
    start_date: str
    end_date: str
    total_pnl_eur: float
    attributions: List[SecurityAttribution]

    class Config:
        from_attributes = True


class PortfolioSummary(BaseModel):
    """Current portfolio summary"""
    total_cost_basis_eur: float = Field(..., description="Total amount invested")
    total_market_value_eur: float = Field(..., description="Current total value")
    total_gain_loss_eur: float = Field(..., description="Total unrealized gain/loss")
    total_gain_loss_percent: float = Field(..., description="Total percentage gain/loss")
    num_positions: int = Field(..., description="Number of unique securities held")
    date: Optional[str] = Field(None, description="Date of the summary")

    class Config:
        from_attributes = True


class FundamentalMetricsResponse(BaseModel):
    """Fundamental metrics for a single security"""
    security_id: int
    symbol: str
    description: str
    exchange: Optional[str] = None
    currency: str
    quote_type: Optional[str] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_sales: Optional[float] = None
    price_to_book: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    fwd_revenue_growth: Optional[float] = None
    fwd_eps_growth: Optional[float] = None
    profit_margins: Optional[float] = None
    gross_margins: Optional[float] = None
    operating_margins: Optional[float] = None
    market_cap: Optional[int] = None
    number_of_analysts: Optional[int] = None
    target_mean_price: Optional[float] = None
    target_high_price: Optional[float] = None
    target_low_price: Optional[float] = None
    data_currency: Optional[str] = None
    last_updated: Optional[str] = None

    class Config:
        from_attributes = True


class EarningsCalendarItem(BaseModel):
    """Upcoming earnings event"""
    security_id: int
    symbol: str
    description: str
    earnings_date: str
    eps_estimate: Optional[float] = None

    class Config:
        from_attributes = True


class EarningsHistoryItem(BaseModel):
    """Past earnings event with surprise data"""
    security_id: int
    symbol: str
    description: str
    earnings_date: str
    eps_estimate: Optional[float] = None
    reported_eps: Optional[float] = None
    surprise_percent: Optional[float] = None
    beat_or_miss: Optional[str] = None

    class Config:
        from_attributes = True


class WatchlistItemResponse(BaseModel):
    """Watchlist item with cached fundamentals and technical indicators"""
    id: int
    yahoo_ticker: str
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    notes: Optional[str] = None
    target_price: Optional[float] = None
    current_price: Optional[float] = None
    currency: Optional[str] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    fwd_revenue_growth: Optional[float] = None
    fwd_eps_growth: Optional[float] = None
    profit_margins: Optional[float] = None
    market_cap: Optional[int] = None
    analyst_target: Optional[float] = None
    analyst_rating: Optional[str] = None
    analyst_count: Optional[int] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    pct_from_52w_high: Optional[float] = None
    ma200: Optional[float] = None
    ma50: Optional[float] = None
    pct_from_ma200: Optional[float] = None
    rsi14: Optional[float] = None
    buy_score: Optional[float] = None
    data_currency: Optional[str] = None
    last_synced: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class AddWatchlistItemRequest(BaseModel):
    """Request to add a stock to the watchlist"""
    yahoo_ticker: str
    notes: Optional[str] = None
    target_price: Optional[float] = None


class UpdateWatchlistItemRequest(BaseModel):
    """Request to update a watchlist item"""
    notes: Optional[str] = None
    target_price: Optional[float] = None


class DividendMonthlyItem(BaseModel):
    month: str  # "YYYY-MM"
    amount_eur: float

class DividendSummaryResponse(BaseModel):
    monthly: List[DividendMonthlyItem]
    ytd_eur: float
    total_eur: float
    last_updated: Optional[str] = None
    sync_in_progress: bool = False


class FundamentalsStatus(BaseModel):
    """Status of fundamentals data cache"""
    total_securities: int
    securities_with_data: int
    securities_without_data: int
    stale_metrics: int
    total_earnings_events: int
    oldest_update: Optional[str] = None
    newest_update: Optional[str] = None

    class Config:
        from_attributes = True

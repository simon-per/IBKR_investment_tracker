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

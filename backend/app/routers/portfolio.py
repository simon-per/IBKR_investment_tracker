"""
Portfolio Router
API endpoints for portfolio value and positions.
"""
from typing import List
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.portfolio_service import PortfolioService
from app.schemas.portfolio import (
    PortfolioValuePoint,
    PortfolioSummary,
    PositionResponse
)


router = APIRouter()


@router.get("/value-over-time", response_model=List[PortfolioValuePoint])
async def get_portfolio_value_over_time(
    response: Response,
    start_date: date = Query(
        default=None,
        description="Start date for the chart (defaults to 1 year ago)"
    ),
    end_date: date = Query(
        default=None,
        description="End date for the chart (defaults to today)"
    ),
    db: AsyncSession = Depends(get_db)
):
    """
    Get portfolio value (cost basis and market value) over time.

    This endpoint provides the data for the dual-line chart showing:
    - Cost basis: Total amount invested over time
    - Market value: Current worth of holdings over time

    Returns data points for each business day in the range.
    """
    if not end_date:
        end_date = date.today()

    if not start_date:
        # Default to 1 year ago
        start_date = end_date - timedelta(days=365)

    # Validate date range
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be before or equal to end_date"
        )

    # Limit to reasonable range (max 5 years to prevent huge queries)
    max_days = 365 * 5
    if (end_date - start_date).days > max_days:
        raise HTTPException(
            status_code=400,
            detail=f"Date range too large. Maximum allowed is {max_days} days (5 years)"
        )

    portfolio_service = PortfolioService(db)

    print(f"API CALL: start_date={start_date}, end_date={end_date}")
    timeline = await portfolio_service.get_portfolio_value_over_time(start_date, end_date)
    print(f"API RESULT: {len(timeline)} data points")
    if timeline:
        print(f"First point: {timeline[0]}")
        print(f"Last point: {timeline[-1]}")

    # Disable caching
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return timeline


@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(db: AsyncSession = Depends(get_db)):
    """
    Get current portfolio summary with total values.

    Returns:
    - total_cost_basis_eur: Total amount invested
    - total_market_value_eur: Current worth
    - total_gain_loss_eur: Unrealized gain/loss
    - total_gain_loss_percent: Percentage gain/loss
    - num_positions: Number of unique securities held
    """
    portfolio_service = PortfolioService(db)
    summary = await portfolio_service.get_current_portfolio_summary()

    return summary


@router.get("/positions", response_model=List[PositionResponse])
async def get_positions_breakdown(db: AsyncSession = Depends(get_db)):
    """
    Get breakdown of all current positions by security.

    Returns list of positions with:
    - Security information (symbol, description, ISIN)
    - Quantity held
    - Cost basis (total invested)
    - Current market value
    - Unrealized gain/loss
    - Individual taxlots that make up the position

    Positions are sorted by market value (largest first).
    """
    portfolio_service = PortfolioService(db)
    positions = await portfolio_service.get_positions_breakdown()

    return positions

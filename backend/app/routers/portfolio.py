"""
Portfolio Router
API endpoints for portfolio value and positions.
"""
from typing import List
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.portfolio_service import PortfolioService
from app.services.benchmark_service import BenchmarkService, BENCHMARKS
from app.schemas.portfolio import (
    PortfolioValuePoint,
    PortfolioSummary,
    PositionResponse,
    AnnualizedReturnResponse,
    BenchmarkResponse,
    BenchmarkInfo,
)


router = APIRouter()


@router.get("/value-over-time", response_model=List[PortfolioValuePoint])
async def get_portfolio_value_over_time(
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


@router.get("/annualized-return", response_model=AnnualizedReturnResponse)
async def get_annualized_return(
    start_date: date = Query(..., description="Start date for the calculation"),
    end_date: date = Query(..., description="End date for the calculation"),
    db: AsyncSession = Depends(get_db)
):
    """
    Calculate XIRR (money-weighted annualized return) for the portfolio.

    Treats each tax lot purchase as a dated cash flow and finds the annualized
    rate that makes the NPV of all cash flows equal zero.
    """
    if start_date >= end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be before end_date"
        )

    portfolio_service = PortfolioService(db)
    xirr_pct, num_cash_flows, eff_start, eff_end = await portfolio_service.calculate_xirr(start_date, end_date)

    return AnnualizedReturnResponse(
        method="xirr",
        annualized_return_pct=round(xirr_pct, 2) if xirr_pct is not None else None,
        start_date=eff_start.isoformat(),
        end_date=eff_end.isoformat(),
        num_cash_flows=num_cash_flows
    )


@router.get("/benchmarks", response_model=List[BenchmarkInfo])
async def get_available_benchmarks():
    """Return list of available benchmark indices for comparison."""
    return [
        BenchmarkInfo(key=key, name=info["name"], ticker=info["ticker"], currency=info["currency"])
        for key, info in BENCHMARKS.items()
    ]


@router.get("/benchmark", response_model=BenchmarkResponse)
async def get_benchmark_comparison(
    start_date: date = Query(default=None, description="Start date (defaults to 1 year ago)"),
    end_date: date = Query(default=None, description="End date (defaults to today)"),
    benchmark: str = Query(default="sp500", description="Benchmark: sp500 or nasdaq"),
    db: AsyncSession = Depends(get_db),
):
    """
    Compare portfolio against a benchmark index.

    Simulates investing every tax lot into S&P 500 or NASDAQ instead,
    using the same dates and EUR amounts.
    """
    if benchmark not in BENCHMARKS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown benchmark '{benchmark}'. Choose from: {', '.join(BENCHMARKS.keys())}",
        )

    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=365)

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be before or equal to end_date")

    max_days = 365 * 5
    if (end_date - start_date).days > max_days:
        raise HTTPException(status_code=400, detail=f"Date range too large. Maximum {max_days} days.")

    bench_info = BENCHMARKS[benchmark]
    service = BenchmarkService(db)
    data = await service.calculate_benchmark_value_over_time(start_date, end_date, benchmark)

    return BenchmarkResponse(
        benchmark_name=bench_info["name"],
        benchmark_ticker=bench_info["ticker"],
        data=data,
    )


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

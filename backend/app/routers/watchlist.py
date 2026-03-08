from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.watchlist_service import WatchlistService
from app.repositories.watchlist_repository import WatchlistRepository
from app.schemas.portfolio import (
    WatchlistItemResponse,
    AddWatchlistItemRequest,
    UpdateWatchlistItemRequest,
)

router = APIRouter()


@router.get("", response_model=list[WatchlistItemResponse])
async def get_watchlist(db: AsyncSession = Depends(get_db)):
    """Get all watchlist items."""
    service = WatchlistService(db)
    items = await service.get_all_items()
    return [_item_to_response(item) for item in items]


@router.post("", response_model=WatchlistItemResponse, status_code=201)
async def add_to_watchlist(
    request: AddWatchlistItemRequest,
    db: AsyncSession = Depends(get_db),
):
    """Add a stock to the watchlist by Yahoo Finance ticker."""
    repo = WatchlistRepository(db)

    existing = await repo.get_by_ticker(request.yahoo_ticker.upper())
    if existing:
        raise HTTPException(status_code=409, detail=f"{request.yahoo_ticker} is already on the watchlist")

    item = await repo.add(
        yahoo_ticker=request.yahoo_ticker.upper(),
        notes=request.notes,
        target_price=request.target_price,
    )
    await db.commit()

    # Immediately sync data
    service = WatchlistService(db)
    await service.sync_item(item.yahoo_ticker, force=True)

    # Re-fetch with cached data
    item = await repo.get_by_id(item.id)
    return _item_to_response(item)


@router.patch("/{item_id}", response_model=WatchlistItemResponse)
async def update_watchlist_item(
    item_id: int,
    request: UpdateWatchlistItemRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update notes and/or target price for a watchlist item."""
    repo = WatchlistRepository(db)
    item = await repo.get_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    update_kwargs = {}
    if request.notes is not None:
        update_kwargs["notes"] = request.notes
    if request.target_price is not None:
        update_kwargs["target_price"] = request.target_price

    if update_kwargs:
        # Direct attribute update for simplicity
        if "notes" in update_kwargs:
            item.notes = update_kwargs["notes"]
        if "target_price" in update_kwargs:
            item.target_price = update_kwargs["target_price"]
        await db.flush()
        await db.refresh(item)

    return _item_to_response(item)


@router.delete("/{item_id}")
async def remove_from_watchlist(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Remove a stock from the watchlist."""
    repo = WatchlistRepository(db)
    removed = await repo.remove(item_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return {"message": "Removed from watchlist"}


@router.post("/sync")
async def sync_watchlist(
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Force refresh all watchlist items."""
    service = WatchlistService(db)
    result = await service.sync_all(force=force)
    return result


def _item_to_response(item) -> WatchlistItemResponse:
    return WatchlistItemResponse(
        id=item.id,
        yahoo_ticker=item.yahoo_ticker,
        symbol=item.symbol,
        company_name=item.company_name,
        notes=item.notes,
        target_price=item.target_price,
        current_price=item.current_price,
        currency=item.currency,
        trailing_pe=item.trailing_pe,
        revenue_growth=item.revenue_growth,
        earnings_growth=item.earnings_growth,
        fwd_revenue_growth=item.fwd_revenue_growth,
        fwd_eps_growth=item.fwd_eps_growth,
        profit_margins=item.profit_margins,
        market_cap=item.market_cap,
        week52_high=item.week52_high,
        week52_low=item.week52_low,
        pct_from_52w_high=item.pct_from_52w_high,
        ma200=item.ma200,
        ma50=item.ma50,
        pct_from_ma200=item.pct_from_ma200,
        rsi14=item.rsi14,
        data_currency=item.data_currency,
        forward_pe=item.forward_pe,
        peg_ratio=item.peg_ratio,
        ev_to_ebitda=item.ev_to_ebitda,
        analyst_target=item.analyst_target,
        analyst_rating=item.analyst_rating,
        analyst_count=item.analyst_count,
        buy_score=item.buy_score,
        last_synced=item.last_synced.isoformat() if item.last_synced else None,
        created_at=item.created_at.isoformat() if item.created_at else None,
    )

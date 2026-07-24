"""
Settings Router
Read/update application-level settings, notably the portfolio's base (display) currency.
"""
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.taxlot import TaxLot
from app.repositories.app_settings_repository import (
    AppSettingsRepository,
    SUPPORTED_BASE_CURRENCIES,
)
from app.services.currency_service import CurrencyService

logger = logging.getLogger(__name__)

router = APIRouter()


class SettingsResponse(BaseModel):
    base_currency: str
    supported_currencies: list[str]


class UpdateBaseCurrencyRequest(BaseModel):
    base_currency: str


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    repo = AppSettingsRepository(db)
    base_currency = await repo.get_base_currency()
    return SettingsResponse(
        base_currency=base_currency,
        supported_currencies=SUPPORTED_BASE_CURRENCIES,
    )


@router.put("/base-currency", response_model=SettingsResponse)
async def update_base_currency(
    payload: UpdateBaseCurrencyRequest,
    db: AsyncSession = Depends(get_db),
):
    repo = AppSettingsRepository(db)
    try:
        base_currency = await repo.set_base_currency(payload.base_currency)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Backfill EUR -> base daily rates over the full portfolio history so read
    # endpoints can convert without hitting the network. One Frankfurter range call.
    if base_currency != "EUR":
        try:
            min_open = (await db.execute(select(func.min(TaxLot.open_date)))).scalar()
            today = date.today()
            start = min_open or (today - timedelta(days=365))
            currency_service = CurrencyService(db)
            await currency_service._batch_fetch_rates(
                from_currency="EUR",
                target_date=today,
                to_currency=base_currency,
                days_back=max((today - start).days, 30),
            )
        except Exception as e:  # non-fatal: the read path has its own safety net
            logger.warning(f"EUR->{base_currency} backfill failed: {e}")

    return SettingsResponse(
        base_currency=base_currency,
        supported_currencies=SUPPORTED_BASE_CURRENCIES,
    )

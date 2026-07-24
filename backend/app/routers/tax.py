"""
Tax Router
Per-year tax report (dividend income + withholding, realized gains, holdings)
with JSON and CSV output. Swiss-focused framing; see TaxService.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.tax_service import TaxService

router = APIRouter()

_MIN_YEAR = 2000
_MAX_YEAR = date.today().year


@router.get("/report")
async def get_tax_report(
    year: int = Query(default=_MAX_YEAR, ge=_MIN_YEAR, le=_MAX_YEAR),
    db: AsyncSession = Depends(get_db),
):
    """Return the tax report for a calendar year in the configured base currency."""
    return await TaxService(db).get_tax_report(year)


@router.get("/report.csv", response_class=PlainTextResponse)
async def get_tax_report_csv(
    year: int = Query(default=_MAX_YEAR, ge=_MIN_YEAR, le=_MAX_YEAR),
    db: AsyncSession = Depends(get_db),
):
    """Return the tax report as a downloadable CSV."""
    service = TaxService(db)
    report = await service.get_tax_report(year)
    csv_text = service.to_csv(report)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="tax_report_{year}.csv"'},
    )

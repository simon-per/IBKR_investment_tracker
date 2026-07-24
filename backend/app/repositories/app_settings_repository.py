"""
App Settings Repository
Key/value persistence for application-level settings.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import AppSetting

# The base (display) currency the whole portfolio is reported in.
BASE_CURRENCY_KEY = "base_currency"
DEFAULT_BASE_CURRENCY = "EUR"
SUPPORTED_BASE_CURRENCIES = ["EUR", "CHF", "USD"]


class AppSettingsRepository:
    """Repository for the app_settings key/value table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        result = await self.session.execute(
            select(AppSetting).where(AppSetting.key == key)
        )
        row = result.scalar_one_or_none()
        return row.value if row else default

    async def set(self, key: str, value: str) -> AppSetting:
        result = await self.session.execute(
            select(AppSetting).where(AppSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            row = AppSetting(key=key, value=value)
            self.session.add(row)
        await self.session.flush()
        return row

    async def get_base_currency(self) -> str:
        return await self.get(BASE_CURRENCY_KEY, DEFAULT_BASE_CURRENCY)

    async def set_base_currency(self, currency: str) -> str:
        currency = (currency or "").upper()
        if currency not in SUPPORTED_BASE_CURRENCIES:
            raise ValueError(
                f"Unsupported base currency '{currency}'. "
                f"Choose from: {', '.join(SUPPORTED_BASE_CURRENCIES)}"
            )
        await self.set(BASE_CURRENCY_KEY, currency)
        return currency

    async def ensure_default_base_currency(self) -> bool:
        """Seed the default base currency if not present. Returns True if seeded."""
        existing = await self.get(BASE_CURRENCY_KEY)
        if existing is None:
            await self.set(BASE_CURRENCY_KEY, DEFAULT_BASE_CURRENCY)
            return True
        return False

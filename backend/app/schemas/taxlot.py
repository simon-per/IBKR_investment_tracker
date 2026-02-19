"""
Pydantic schemas for TaxLot model
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime, date
from decimal import Decimal

from app.schemas.security import SecurityResponse


class TaxLotBase(BaseModel):
    """Base tax lot schema with common fields"""
    security_id: int
    open_date: date
    quantity: Decimal
    cost_basis: Decimal
    price_per_unit: Decimal
    currency: str
    cost_basis_eur: Decimal
    is_open: bool = True
    close_date: Optional[date] = None


class TaxLotCreate(TaxLotBase):
    """Schema for creating a new tax lot"""
    pass


class TaxLotUpdate(BaseModel):
    """Schema for updating a tax lot"""
    quantity: Optional[Decimal] = None
    cost_basis: Optional[Decimal] = None
    price_per_unit: Optional[Decimal] = None
    cost_basis_eur: Optional[Decimal] = None
    is_open: Optional[bool] = None
    close_date: Optional[date] = None


class TaxLotResponse(TaxLotBase):
    """Schema for tax lot response"""
    id: int
    created_at: datetime
    updated_at: datetime
    security: Optional[SecurityResponse] = None

    model_config = ConfigDict(from_attributes=True)

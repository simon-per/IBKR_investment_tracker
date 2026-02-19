"""
Pydantic schemas for Security model
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class SecurityBase(BaseModel):
    """Base security schema with common fields"""
    isin: str
    symbol: str
    description: str
    currency: str
    conid: int
    asset_category: Optional[str] = "STK"
    exchange: Optional[str] = None


class SecurityCreate(SecurityBase):
    """Schema for creating a new security"""
    pass


class SecurityUpdate(BaseModel):
    """Schema for updating a security"""
    isin: Optional[str] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    currency: Optional[str] = None
    asset_category: Optional[str] = None
    exchange: Optional[str] = None


class SecurityResponse(SecurityBase):
    """Schema for security response"""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

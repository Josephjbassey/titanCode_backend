"""
TitanCode Technologies — Pydantic Schemas: Revenue
====================================================
This module defines the data structures for revenue reporting from
external products.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal

# ═══════════════════════════════════════════════════════════════════════
# REVENUE SCHAMAS
# ═══════════════════════════════════════════════════════════════════════

class RevenueBase(BaseModel):
    """
    Core fields for a single revenue record.
    """
    amount: Decimal = Field(..., decimal_places=2, example="99.99")
    source: Optional[str] = Field(None, example="Stripe Checkout")

class RevenueCreate(RevenueBase):
    """Internal use: schema for creating a revenue record in the DB."""
    product_id: int

class RevenueReport(BaseModel):
    """
    EXTERNAL API SCHEMA: Used by products to report their earnings.
    Authentication metadata (api key, signature, timestamp, nonce)
    is supplied via HTTP headers.
    """
    amount: Decimal = Field(..., ge=0, description="The revenue amount to report")
    source: Optional[str] = Field(None, description="Where this revenue came from (e.g. 'Paypal')")

class Revenue(RevenueBase):
    """Final schema for a revenue record returned to the user."""
    id: int
    product_id: int
    created_at: datetime

    model_config = {"from_attributes": True}

class RevenueStats(BaseModel):
    """
    Summary statistics for the revenue dashboard.
    """
    total_revenue: Decimal
    product_count: int
    last_report_at: Optional[datetime] = None

class RevenueListResponse(BaseModel):
    """Paginated response for revenue history endpoints."""
    items: List[Revenue]
    total: int
    limit: int
    offset: int
    next_offset: Optional[int] = None


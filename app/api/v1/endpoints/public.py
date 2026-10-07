from typing import Any, List
from fastapi import APIRouter
from pydantic import BaseModel
from app.api.v1.endpoints.financials import _get_active_settings

router = APIRouter()


class PublicPricingTier(BaseModel):
    id: str
    label: str
    min_amount: float
    max_amount: float | None = None
    description: str = ""
    is_active: bool = True


@router.get("/pricing-tiers", response_model=List[PublicPricingTier])
async def get_public_pricing_tiers() -> Any:
    """
    Return active pricing tiers for public display — no auth required.
    Exposes only label, price range, description, and active status.
    """
    settings_data = await _get_active_settings()
    tiers = settings_data.get("pricing_tiers", [])
    return [t for t in tiers if t.get("is_active", True)]

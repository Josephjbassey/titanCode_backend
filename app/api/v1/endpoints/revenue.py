"""
TitanCode Technologies — Revenue Endpoints
=============================================
This module provides a public reporting API for external products to log 
earnings, and internal endpoints for admin dashboard statistics.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import Any, List
from decimal import Decimal

from app.db.database import get_db
from app.db.models import Revenue, Product, CompanyWallet
from app.schemas.revenue import Revenue as RevenueSchema, RevenueReport, RevenueStats
from app.api.v1.endpoints.auth import get_current_user, RoleChecker

# Create the router
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_admins = RoleChecker(["CEO", "Admin"])


# ═══════════════════════════════════════════════════════════════════════
# POST /revenue/report — Public endpoint for product earnings
# ═══════════════════════════════════════════════════════════════════════
@router.post("/report", response_model=RevenueSchema, status_code=status.HTTP_201_CREATED)
async def report_revenue(
    report: RevenueReport,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Allow an external product to report its latest revenue.

    The product must authenticate with its secret `api_key`. Once a valid
    report is received:
    1. A revenue record is created for historical tracking.
    2. The global **Company Wallet** balance is automatically updated.

    Args:
        report: API key, amount, and source of the revenue.

    Returns:
        RevenueSchema: The saved revenue record.
    """
    # 1. Authenticate the product via its API key
    result = await db.execute(select(Product).where(Product.api_key == report.api_key))
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 2. Record the revenue entry
    revenue = Revenue(
        product_id=product.id,
        amount=report.amount,
        source=report.source or f"External Report from {product.name}"
    )
    db.add(revenue)

    # 3. Synchronize with the Company Wallet (the corporate treasury)
    result = await db.execute(select(CompanyWallet))
    wallet = result.scalars().first()
    if not wallet:
        # Auto-create the wallet if this is the first report ever
        wallet = CompanyWallet(balance=Decimal("0.00"))
        db.add(wallet)
    
    wallet.balance += report.amount
    
    await db.commit()
    await db.refresh(revenue)
    return revenue


# ═══════════════════════════════════════════════════════════════════════
# GET /revenue/stats — Dashboard summary (Admin)
# ═══════════════════════════════════════════════════════════════════════
@router.get("/stats", response_model=RevenueStats)
async def get_revenue_stats(
    db: AsyncSession = Depends(get_db),
    _current_user: Any = Depends(allow_admins),
) -> Any:
    """
    Get aggregated revenue metrics for the Admin dashboard.

    Returns:
        RevenueStats: Total earnings, active product count, and last report date.
    """
    # Sum of all reported revenue
    total_result = await db.execute(select(func.sum(Revenue.amount)))
    total_amount = total_result.scalar() or Decimal("0.00")
    
    # Count of registered products
    count_result = await db.execute(select(func.count(Product.id)))
    product_count = count_result.scalar() or 0
    
    # Date/time of the most recent report
    last_report_result = await db.execute(select(func.max(Revenue.created_at)))
    last_report_at = last_report_result.scalar()

    return {
        "total_revenue": total_amount,
        "product_count": product_count,
        "last_report_at": last_report_at
    }


# ═══════════════════════════════════════════════════════════════════════
# GET /revenue/history — List all reports (Admin)
# ═══════════════════════════════════════════════════════════════════════
@router.get("/history", response_model=List[RevenueSchema])
async def get_revenue_history(
    db: AsyncSession = Depends(get_db),
    _current_user: Any = Depends(allow_admins),
) -> Any:
    """
    Retrieve the full history of revenue reports across all products.

    Returns:
        List[RevenueSchema]: History sorted by date, descending.
    """
    result = await db.execute(select(Revenue).order_by(Revenue.created_at.desc()))
    return result.scalars().all()

"""
TitanCode Technologies — Revenue Endpoints
=============================================
This module provides a public reporting API for external products to log
earnings, and internal endpoints for admin dashboard statistics.
"""

import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any, List

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.v1.endpoints.auth import RoleChecker
from app.core.config import settings
from app.db.database import get_db
from app.db.models import CompanyWallet, Product, Revenue
from app.schemas.revenue import Revenue as RevenueSchema, RevenueReport, RevenueStats

# Create the router
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_admins = RoleChecker(["CEO", "Admin"])

# Replay-protection configuration
REVENUE_SIGNATURE_MAX_AGE_SECONDS = 300
_REPLAY_NONCE_PREFIX = "revenue:nonce"
_replay_cache: Redis | None = None


def _get_replay_cache() -> Redis:
    """Return a shared Redis backend for replay nonce tracking."""
    global _replay_cache
    if _replay_cache is None:
        _replay_cache = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _replay_cache


def _verify_revenue_signature(
    raw_body: bytes,
    api_key: str,
    signature: str,
    timestamp: str,
    nonce: str,
) -> int:
    """Validate request HMAC signature and freshness checks."""
    if not api_key or not signature or not timestamp or not nonce:
        raise HTTPException(status_code=401, detail="Missing authentication headers")

    try:
        request_ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid timestamp header") from exc

    now = int(time.time())
    if abs(now - request_ts) > REVENUE_SIGNATURE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Stale timestamp")

    payload_to_sign = raw_body + timestamp.encode("utf-8") + nonce.encode("utf-8")
    expected_signature = hmac.new(
        key=api_key.encode("utf-8"),
        msg=payload_to_sign,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    return request_ts


async def _assert_nonce_not_replayed(product_id: int, nonce: str) -> None:
    """Persist nonce atomically in Redis; reject if it was seen already."""
    nonce_key = f"{_REPLAY_NONCE_PREFIX}:{product_id}:{nonce}"
    try:
        cache = _get_replay_cache()
        inserted = await cache.set(
            name=nonce_key,
            value="1",
            ex=REVENUE_SIGNATURE_MAX_AGE_SECONDS,
            nx=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Replay protection unavailable") from exc

    if not inserted:
        raise HTTPException(status_code=401, detail="Nonce already used")


# ═══════════════════════════════════════════════════════════════════════
# POST /revenue/report — Public endpoint for product earnings
# ═══════════════════════════════════════════════════════════════════════
@router.post("/report", response_model=RevenueSchema, status_code=status.HTTP_201_CREATED)
async def report_revenue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(default="", alias="X-API-Key"),
    x_signature: str = Header(default="", alias="X-Signature"),
    x_timestamp: str = Header(default="", alias="X-Timestamp"),
    x_nonce: str = Header(default="", alias="X-Nonce"),
) -> Any:
    """
    Allow an external product to report its latest revenue.

    The product authenticates with signed headers:
    - X-API-Key
    - X-Signature (HMAC-SHA256 over raw body + timestamp + nonce)
    - X-Timestamp (Unix seconds)
    - X-Nonce (single-use random value)

    Once a valid report is received:
    1. A revenue record is created for historical tracking.
    2. The global **Company Wallet** balance is automatically updated.

    Returns:
        RevenueSchema: The saved revenue record.
    """
    raw_body = await request.body()
    _verify_revenue_signature(raw_body, x_api_key, x_signature, x_timestamp, x_nonce)

    try:
        report = RevenueReport.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    # Authenticate the product via API key provided in header
    result = await db.execute(select(Product).where(Product.api_key == x_api_key))
    product = result.scalars().first()
    if not product or product.api_key_hash != hash_product_api_key(report.api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Block replay only after API key is validated against a real product
    await _assert_nonce_not_replayed(product.id, x_nonce)

    # Record the revenue entry
    revenue = Revenue(
        product_id=product.id,
        amount=report.amount,
        source=report.source or f"External Report from {product.name}",
    )
    db.add(revenue)

    # Synchronize with the Company Wallet (the corporate treasury)
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
        "last_report_at": last_report_at,
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

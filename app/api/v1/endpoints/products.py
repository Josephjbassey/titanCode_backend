"""
TitanCode Technologies — Products Endpoints
=============================================
This module handles the registration and management of external products.
Products are internal or external tools that generate revenue for the company.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List

from app.db.database import get_db
from app.db.models import Product, User
from app.schemas.product import ProductCreate, ProductPublic, ProductUpdate, ProductWithSecret
from app.api.v1.endpoints.auth import get_current_user, RoleChecker
from app.core.security import (
    extract_product_api_key_id,
    generate_product_api_key,
    hash_product_api_key,
    mask_product_api_key,
)

# Create a new router instance
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
# Only CEO and Admin roles are permitted to add or manage products.
allow_admins = RoleChecker(["CEO", "Admin"])


# ═══════════════════════════════════════════════════════════════════════
# POST /products/add — Register a new product
# ═══════════════════════════════════════════════════════════════════════
@router.post("/add", response_model=ProductWithSecret, status_code=status.HTTP_201_CREATED)
async def add_product(
    product_in: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allow_admins),
) -> Any:
    """
    Register a new external product for revenue tracking.

    If an `api_key` is not provided, the system generates a unique, 
    secure token for the product. This key is used for authentication 
    in the revenue reporting endpoint.

    Args:
        product_in: Details of the product (name, type, etc.).

    Returns:
        ProductSchema: The newly created product record with its API key.
    """
    # Generate API key if not manually provided
    if product_in.api_key:
        api_key = product_in.api_key
        try:
            api_key_id = extract_product_api_key_id(api_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        api_key, api_key_id = generate_product_api_key()
    
    product = Product(
        **product_in.model_dump(exclude={"api_key"}, mode="json"),
        api_key_id=api_key_id,
        api_key_hash=hash_product_api_key(api_key),
        created_by=current_user.id
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return ProductWithSecret(
        **product.__dict__,
        api_key=api_key,
        api_key_masked=mask_product_api_key(api_key),
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /products — List all registered products
# ═══════════════════════════════════════════════════════════════════════
@router.get("/", response_model=List[ProductPublic])
async def list_products(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admins),
) -> Any:
    """
    Retrieve a list of all products registered in the platform.

    ⚠️ CEO and Admin only — this includes sensitive API keys.

    Returns:
        List[ProductSchema]: A list of all product records.
    """
    result = await db.execute(select(Product))
    products = result.scalars().all()
    return [
        ProductPublic(
            id=product.id,
            name=product.name,
            product_type=product.product_type,
            revenue_endpoint=product.revenue_endpoint,
            product_url=product.product_url,
            api_key_id=product.api_key_id,
            api_key_masked=f"tc_{product.api_key_id}_********",
            created_at=product.created_at,
            created_by=product.created_by,
        )
        for product in products
    ]


# ═══════════════════════════════════════════════════════════════════════
# GET /products/{product_id} — Get product details
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{product_id}", response_model=ProductPublic)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get detailed information for a specific product by ID.

    Args:
        product_id: The unique primary key of the product.

    Returns:
        ProductSchema: The requested product record.
    """
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductPublic(
        id=product.id,
        name=product.name,
        product_type=product.product_type,
        revenue_endpoint=product.revenue_endpoint,
        product_url=product.product_url,
        api_key_id=product.api_key_id,
        api_key_masked=f"tc_{product.api_key_id}_********",
        created_at=product.created_at,
        created_by=product.created_by,
    )

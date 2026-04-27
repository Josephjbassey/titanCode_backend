"""
TitanCode Technologies — Pydantic Schemas: Product
====================================================
This module defines the data structures for managing external products
that report revenue to the TitanCode platform.
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════
# PRODUCT SCHAMAS
# ═══════════════════════════════════════════════════════════════════════

class ProductBase(BaseModel):
    """
    Base fields shared by all Product schemas.
    
    Attributes:
        name:             The human-readable name of the product.
        product_type:     The category of product (e.g., SaaS, Mobile App, API).
        revenue_endpoint: Optional URL where the product handles billing.
        product_url:      The main public URL of the product.
    """
    name: str = Field(..., example="TitanCRM")
    product_type: str = Field(..., example="SaaS")
    revenue_endpoint: Optional[HttpUrl] = None
    product_url: Optional[HttpUrl] = None

class ProductCreate(ProductBase):
    """
    Schema for creating a new product (POST /products/add).
    
    Attributes:
        api_key: Optional custom API key. If omitted, one is auto-generated.
    """
    api_key: Optional[str] = None

class ProductUpdate(BaseModel):
    """
    Schema for updating an existing product (PUT /products/{id}).
    All fields are optional to allow partial updates.
    """
    name: Optional[str] = None
    product_type: Optional[str] = None
    revenue_endpoint: Optional[HttpUrl] = None
    product_url: Optional[HttpUrl] = None

class ProductInDBBase(ProductBase):
    """
    Internal base schema including server-generated fields.
    """
    id: int
    api_key_id: str
    api_key_masked: str
    created_at: datetime
    created_by: int

    model_config = {"from_attributes": True}


class ProductPublic(ProductInDBBase):
    """
    Product schema returned by list/get endpoints.
    """
    pass


class ProductWithSecret(ProductPublic):
    """
    Product schema returned when creating a product (includes raw key once).
    """
    api_key: str

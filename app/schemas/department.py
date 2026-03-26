"""
TitanCode Technologies — Pydantic Schemas: Department
======================================================
Schemas for Department CRUD operations.

Schema hierarchy:
    DepartmentBase   → Shared fields for creation and response.
    DepartmentCreate → Same as base (no extra fields needed).
    DepartmentUpdate → All fields optional for partial updates.
    Department       → Full read-only response schema.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DepartmentBase(BaseModel):
    """Fields required when creating a department."""
    name: str
    description: Optional[str] = None
    manager_id: Optional[int] = None
    assistant_id: Optional[int] = None


class DepartmentCreate(DepartmentBase):
    """Schema for POST /departments/create — inherits all base fields."""
    pass


class DepartmentUpdate(BaseModel):
    """Schema for PUT /departments/update — all fields optional."""
    name: Optional[str] = None
    description: Optional[str] = None
    manager_id: Optional[int] = None
    assistant_id: Optional[int] = None


class DepartmentInDBBase(DepartmentBase):
    """Adds server-generated fields for database responses."""
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class Department(DepartmentInDBBase):
    """Public Department schema returned in API responses."""
    pass

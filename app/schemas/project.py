"""
TitanCode Technologies — Pydantic Schemas: Project
====================================================
Schemas for client project management.

Status lifecycle: pending → active → completed | cancelled
"""

from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Optional, List


class ProjectBase(BaseModel):
    """Fields required when creating a project."""
    name: str
    description: Optional[str] = None
    client_id: int                          # FK → the client who requested the project
    budget: Decimal = Decimal('0.00')       # Use Decimal for precise monetary values
    deadline: Optional[datetime] = None


class ProjectCreate(ProjectBase):
    """Schema for POST /projects/create — inherits all base fields."""
    member_ids: Optional[List[int]] = None


class ProjectRequest(BaseModel):
    """Schema for POST /projects/client/request-project — client_id is inferred."""
    name: str
    description: Optional[str] = None
    budget: Decimal = Decimal('0.00')
    deadline: Optional[datetime] = None


class ProjectUpdate(BaseModel):
    """Schema for PUT /projects/update — all fields optional for partial updates."""
    name: Optional[str] = None
    description: Optional[str] = None
    budget: Optional[Decimal] = None
    deadline: Optional[datetime] = None
    status: Optional[str] = None            # pending | active | completed | cancelled
    member_ids: Optional[List[int]] = None


class ProjectInDBBase(ProjectBase):
    """Adds server-generated fields for database responses."""
    id: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Project(ProjectInDBBase):
    """Public Project schema returned in API responses."""
    member_ids: Optional[List[int]] = None

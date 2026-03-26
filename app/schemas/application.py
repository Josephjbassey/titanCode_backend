"""
TitanCode Technologies — Pydantic Schemas: Application
=======================================================
Schemas for the membership application workflow.

Workflow:
    1. User submits ApplicationCreate → POST /applications/apply
    2. Manager reviews → PUT /applications/approve or /reject (ApplicationUpdate)
    3. API returns Application schema with full status info.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ApplicationBase(BaseModel):
    """Fields submitted by the applicant."""
    department_id: int
    github_url: Optional[str] = None
    portfolio: Optional[str] = None


class ApplicationCreate(ApplicationBase):
    """Schema for POST /applications/apply — includes the applicant's user ID."""
    user_id: int


class ApplicationUpdate(BaseModel):
    """Schema for approving/rejecting an application (used by managers)."""
    status: str                   # "approved" or "rejected"
    reviewed_by: int              # ID of the reviewing manager
    reviewed_at: datetime         # When the review happened


class ApplicationInDBBase(ApplicationBase):
    """Adds server-generated fields for database responses."""
    id: int
    user_id: int
    status: str
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class Application(ApplicationInDBBase):
    """Public Application schema returned in API responses."""
    pass

"""
TitanCode Technologies — Pydantic Schemas: Meeting
==================================================
Schemas for meeting management and scheduling.
"""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MeetingBase(BaseModel):
    """Base fields shared across meeting schemas."""
    title: str
    description: Optional[str] = None
    meeting_type: str = "video"
    meeting_link: Optional[str] = None
    scheduled_at: datetime
    department_id: Optional[int] = None
    client_id: Optional[int] = None


class MeetingCreate(MeetingBase):
    """Schema for POST /meetings/create."""
    pass


class MeetingUpdate(BaseModel):
    """Schema for PUT /meetings/update — all fields are optional."""
    title: Optional[str] = None
    description: Optional[str] = None
    meeting_type: Optional[str] = None
    meeting_link: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None  # scheduled | cancelled | completed


class MeetingInDBBase(MeetingBase):
    """Internal schema including server-generated fields."""
    id: int
    created_by: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Meeting(MeetingInDBBase):
    """Public Meeting schema returned in API responses."""
    pass

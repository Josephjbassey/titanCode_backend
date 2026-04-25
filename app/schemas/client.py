"""
TitanCode Technologies — Pydantic Schemas: Client
===================================================
Schemas for the public "Hire Us" form and client onboarding magic link flow.
"""

from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class ClientInquiryCreate(BaseModel):
    """
    Schema for the public Hire Us form (POST /client/hire-us).

    All fields except full_name and email are optional, keeping the
    form lightweight and reducing friction for potential clients.
    """
    full_name: str
    email: EmailStr
    company: Optional[str] = None
    phone: Optional[str] = None
    service_interest: Optional[str] = None   # e.g. "Web App", "Mobile App", "UI/UX"
    message: Optional[str] = None


class ClientInquiry(BaseModel):
    """Response schema for a client inquiry record."""
    id: int
    full_name: str
    email: str
    company: Optional[str] = None
    phone: Optional[str] = None
    service_interest: Optional[str] = None
    message: Optional[str] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SendMagicLinkRequest(BaseModel):
    """Request body for sending a magic link to a specific client email."""
    email: EmailStr


class MagicLinkOnboardResponse(BaseModel):
    """Response returned when a client successfully activates via magic link."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    message: str = "Account activated successfully! Welcome to TitanCode."

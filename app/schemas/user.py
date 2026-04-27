"""
TitanCode Technologies — Pydantic Schemas: User
=================================================
These schemas define the shape of data for User-related API
requests and responses. Pydantic validates incoming data
automatically and serializes outgoing responses.

Schema hierarchy:
    UserBase   → Shared fields (used for both create and read).
    UserCreate → Extends UserBase with a `password` field (write-only).
    UserUpdate → All fields optional for partial PATCH/PUT updates.
    User       → The full read-only representation returned from the API.
"""

from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class UserBase(BaseModel):
    """
    Base schema with fields common to creation and response.

    These fields are shared between UserCreate (input) and
    User (output) to avoid duplicating field definitions.
    """
    full_name: str
    email: EmailStr                        # Pydantic validates email format
    country: Optional[str] = None
    phone_number: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    role: str = "Member"
    department_id: Optional[int] = None
    experience_years: int = 0
    skills: Optional[str] = None
    tools: Optional[str] = None


class UserCreate(UserBase):
    """
    Schema for the registration endpoint (POST /auth/register).

    Inherits all fields from UserBase and adds `password`.
    The password is never returned in responses — it's hashed
    and stored as `password_hash` in the database.
    """
    password: str
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None


class UserUpdate(BaseModel):
    """
    Schema for updating a user (PUT /users/update).

    All fields are optional so the client can send only the
    fields they want to change (partial update pattern).
    """
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    country: Optional[str] = None
    phone_number: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[int] = None
    experience_years: Optional[int] = None
    skills: Optional[str] = None
    tools: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    status: Optional[str] = None


class UserInDBBase(UserBase):
    """
    Base schema for data coming from the database.

    Adds server-generated fields (id, status, created_at) that
    don't exist at creation time but are present in responses.

    `model_config = {"from_attributes": True}` tells Pydantic to
    read data from SQLAlchemy model attributes (ORM mode).
    """
    id: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class User(UserInDBBase):
    """Public user schema (no sensitive fields)."""
    pass


class UserPrivate(User):
    """Private user schema (includes wallet/bank info for the owner/admin)."""
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None


class UserListResponse(BaseModel):
    """Paginated response for user listing endpoints."""
    items: List[User]
    total: int
    limit: int
    offset: int
    next_offset: Optional[int] = None

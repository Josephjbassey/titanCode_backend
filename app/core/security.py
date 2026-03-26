"""
TitanCode Technologies — Security Utilities
=============================================
This module handles the two core security operations:

1. **Password Hashing** — Uses bcrypt via Passlib to securely hash and
   verify user passwords. Plain-text passwords are never stored.

2. **JWT Token Creation** — Generates short-lived Access Tokens (15 min)
   and long-lived Refresh Tokens (7 days) signed with the app's SECRET_KEY.

Usage:
    from app.core.security import get_password_hash, verify_password
    from app.core.security import create_access_token, create_refresh_token
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Union, Optional

import jwt
from passlib.context import CryptContext

from app.core.config import settings

# ── Password Hashing Context ───────────────────────────────────────────
# CryptContext manages hashing schemes. We use bcrypt (industry standard).
# `deprecated="auto"` will automatically rehash passwords if the scheme
# is upgraded in the future — zero-downtime algorithm migration.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Compare a plain-text password against its bcrypt hash.

    Args:
        plain_password:  The password the user typed in (e.g. during login).
        hashed_password: The bcrypt hash stored in the database.

    Returns:
        True if the password matches, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a plain-text password using bcrypt.

    This should be called once when the user registers or changes
    their password. The resulting hash is stored in `users.password_hash`.

    Args:
        password: The plain-text password to hash.

    Returns:
        A bcrypt hash string (e.g. "$2b$12$...").
    """
    return pwd_context.hash(password)


def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Generate a short-lived JWT access token.

    The access token is sent with every API request in the
    `Authorization: Bearer <token>` header. It contains:
        - sub: The user's ID (as a string).
        - exp: Expiration timestamp.

    Args:
        subject:       The user's unique identifier (usually user.id).
        expires_delta: Optional custom expiry. Defaults to 15 minutes.

    Returns:
        An encoded JWT string.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    # Build the JWT payload
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Generate a long-lived JWT refresh token.

    Refresh tokens are used to obtain new access tokens without
    forcing the user to log in again. They include a `type: "refresh"`
    claim so the backend can distinguish them from access tokens.

    Args:
        subject:       The user's unique identifier (usually user.id).
        expires_delta: Optional custom expiry. Defaults to 7 days.

    Returns:
        An encoded JWT string.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    # The "type" claim lets /refresh endpoint verify this is a refresh token
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

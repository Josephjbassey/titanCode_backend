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

import hashlib
import hmac
import jwt
import secrets
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


def create_magic_link_token(email: str, expires_hours: int = 24) -> str:
    """
    Generate a one-time magic link JWT for client onboarding.

    The token encodes the client's EMAIL (not user ID) so it can be
    validated before the user record exists, and a `type: magic_link`
    claim to distinguish it from normal access/refresh tokens.

    Args:
        email:        The client's email address.
        expires_hours: How long before the link expires (default: 24h).

    Returns:
        A signed JWT string to be embedded in the onboarding URL.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    to_encode = {"exp": expire, "email": email, "type": "magic_link"}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_magic_link_token(token: str) -> str:
    """
    Decode and validate a magic link token.

    Args:
        token: The JWT string from the onboarding URL.

    Returns:
        The email address encoded in the token.

    Raises:
        ValueError: If the token is invalid, expired, or wrong type.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "magic_link":
            raise ValueError("Invalid token type")
        email = payload.get("email")
        if not email:
            raise ValueError("Token missing email claim")
        return email
    except jwt.ExpiredSignatureError:
        raise ValueError("Magic link has expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid magic link token")


def generate_product_api_key() -> tuple[str, str]:
    """
    Generate a product API key and its public key-id segment.

    Format: `tc_<key_id>_<secret>`
    """
    key_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    return f"tc_{key_id}_{secret}", key_id


def extract_product_api_key_id(api_key: str) -> str:
    """
    Extract the key-id from a product API key.
    """
    parts = api_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "tc" or not parts[1] or not parts[2]:
        raise ValueError("Invalid API key format")
    return parts[1]


def hash_product_api_key(api_key: str) -> str:
    """
    Create a deterministic HMAC-SHA256 digest for API key lookup/verification.
    """
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def mask_product_api_key(api_key: str) -> str:
    """
    Return a redacted API key suitable for API responses/logging.
    """
    if len(api_key) <= 10:
        return "********"
    return f"{api_key[:7]}...{api_key[-4:]}"

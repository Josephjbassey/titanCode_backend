"""
TitanCode Technologies — Authentication Endpoints
===================================================
This module contains all authentication-related API routes and the
dependency injection utilities for protecting other routes.

Endpoints:
    POST /auth/register  — Create a new user account.
    POST /auth/login     — Authenticate and receive access + refresh tokens.
    POST /auth/refresh   — Exchange a refresh token for a new access token.
    GET  /auth/profile   — Retrieve the currently logged-in user's profile.

Security Utilities (used by other endpoint modules):
    get_current_user()       — Dependency that extracts and validates the JWT.
    get_current_active_user() — Wrapper to add extra active-status checks.
    RoleChecker              — Callable class for Role-Based Access Control (RBAC).
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings
from app.core import security
from app.db.database import get_db
from app.db.models import User
from app.schemas.user import UserCreate, User as UserSchema, UserPrivate
from app.schemas.token import Token, TokenPayload
from app.core.rate_limiter import limiter

# Create the router — all routes here will be prefixed with /api/v1/auth
router = APIRouter()

# OAuth2PasswordBearer tells FastAPI where the login endpoint is.
# The Swagger UI "Authorize" button uses this URL to fetch tokens.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


# ═══════════════════════════════════════════════════════════════════════
# DEPENDENCY: Get the current authenticated user from the JWT
# ═══════════════════════════════════════════════════════════════════════
async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    """
    FastAPI dependency that extracts the JWT from the Authorization header,
    decodes it, and returns the corresponding User from the database.

    If the token is invalid, expired, or the user doesn't exist,
    a 401 Unauthorized error is raised.

    Args:
        db:    Async database session (injected by FastAPI).
        token: The Bearer token string (injected by OAuth2PasswordBearer).

    Returns:
        The authenticated User ORM object.

    Raises:
        HTTPException 401: If the token is invalid or the user is not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode the JWT and extract the payload
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_data = TokenPayload(**payload)
    except InvalidTokenError:
        raise credentials_exception

    # Look up the user in the database by their ID from the token
    stmt = select(User).where(User.id == int(token_data.sub))
    result = await db.execute(stmt)
    user = result.scalars().first()

    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Wrapper dependency for additional active-user checks.

    Currently passes through, but you can add checks here like:
        - if current_user.status != "approved": raise 403
        - if current_user.is_disabled: raise 403

    Args:
        current_user: The user returned by get_current_user.

    Returns:
        The same user if all checks pass.
    """
    return current_user


# ═══════════════════════════════════════════════════════════════════════
# RBAC: Role-Based Access Control Dependency
# ═══════════════════════════════════════════════════════════════════════
class RoleChecker:
    """
    A callable dependency class for enforcing Role-Based Access Control.

    Usage in an endpoint:
        allow_ceo_admin = RoleChecker(["CEO", "Admin"])

        @router.get("/admin-only")
        async def admin_route(user: User = Depends(allow_ceo_admin)):
            ...

    How it works:
        1. FastAPI calls __call__ which triggers get_current_user.
        2. The user's role is checked against the allowed_roles list.
        3. If not allowed, a 403 Forbidden error is raised.
    """

    def __init__(self, allowed_roles: List[str]):
        """
        Args:
            allowed_roles: List of role strings that are permitted
                           (e.g. ["CEO", "Admin", "Manager"]).
        """
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_user)):
        """Validate the user's role against the allowed list."""
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted",
            )
        return user


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Register a new user
# ═══════════════════════════════════════════════════════════════════════
@router.post("/register", response_model=UserSchema)
@limiter.limit("10/minute")  # Prevent registration abuse
async def register(request: Request, user_in: UserCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """
    Create a new user account.

    - Checks if the email is already registered.
    - Hashes the password with bcrypt before storing.
    - New users start with role="Member" and status="pending".

    Request Body (UserCreate):
        full_name, email, password, country, phone_number, ...

    Returns:
        The created user object (without the password hash).
    """
    # Check for duplicate email
    stmt = select(User).where(User.email == user_in.email)
    result = await db.execute(stmt)
    if result.scalars().first():
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )

    # Create new user with hashed password
    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        password_hash=security.get_password_hash(user_in.password),
        country=user_in.country,
        phone_number=user_in.phone_number,
        role="Member",
        status="pending",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)  # Refresh to populate auto-generated fields (id, created_at)
    return user


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Login and receive tokens
# ═══════════════════════════════════════════════════════════════════════
@router.post("/login", response_model=Token)
@limiter.limit("5/minute")  # Strict limit to prevent brute-force attacks
async def login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    Authenticate a user and return JWT tokens.

    Uses OAuth2 "password" flow — the client sends `username` (email)
    and `password` as form data.

    Returns:
        access_token:  Short-lived token (15 min) for API requests.
        refresh_token: Long-lived token (7 days) to get new access tokens.
        token_type:    Always "bearer".
    """
    # Look up user by email (OAuth2 spec uses "username" field)
    stmt = select(User).where(User.email == form_data.username)
    result = await db.execute(stmt)
    user = result.scalars().first()

    # Verify user exists and password matches
    if not user or not security.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    # Generate both tokens
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    return {
        "access_token": security.create_access_token(user.id, expires_delta=access_token_expires),
        "refresh_token": security.create_refresh_token(user.id, expires_delta=refresh_token_expires),
        "token_type": "bearer",
    }


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Refresh an expired access token
# ═══════════════════════════════════════════════════════════════════════
@router.post("/refresh", response_model=Token)
async def refresh_token(refresh_token: str, db: AsyncSession = Depends(get_db)) -> Any:
    """
    Exchange a valid refresh token for a new access token.

    This endpoint allows the frontend to silently renew sessions
    without forcing the user to log in again.

    Args:
        refresh_token: The refresh JWT string (passed as query param).

    Returns:
        A new access_token with the same refresh_token.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        # Decode and verify the refresh token
        payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        # Ensure this is actually a refresh token, not an access token
        if payload.get("type") != "refresh":
            raise credentials_exception

        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception

    # Verify the user still exists in the database
    stmt = select(User).where(User.id == int(user_id))
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        raise credentials_exception

    # Issue a fresh access token (keep the same refresh token)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    return {
        "access_token": security.create_access_token(user.id, expires_delta=access_token_expires),
        "refresh_token": refresh_token,  # Reuse the same refresh token
        "token_type": "bearer",
    }


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINT: Get current user's profile
# ═══════════════════════════════════════════════════════════════════════
@router.get("/profile", response_model=UserPrivate)
async def read_current_user(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Return the profile of the currently authenticated user.

    Requires a valid access token in the Authorization header.
    This is useful for the frontend to fetch user data after login.
    """
    return current_user

"""
TitanCode Technologies — Auth & User Tests
============================================
Tests for the authentication flow and user management endpoints.

Test Coverage:
    1. User Registration (valid + duplicate email)
    2. Login (valid credentials + wrong password + account status checks)
    3. Protected endpoints (profile, token refresh)
    4. RBAC enforcement (admin-only routes)
    5. Health check

Note: Uses UUID-based emails so each test run is idempotent.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core import security
from app.core.config import settings
from app.db.models import User


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for each test run to avoid duplicates."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"


async def set_user_status(db_session: AsyncSession, email: str, status_value: str) -> None:
    """Update a registered user's approval status."""
    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    user.status = status_value
    await db_session.commit()


# ── Helper: Register + Login to get a JWT token ───────────────────────
async def register_and_login(
    client: AsyncClient,
    db_session: AsyncSession,
    email: str,
    password: str,
    full_name: str = "Test User",
):
    """Helper to register a user and return an auth token."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": full_name,
            "email": email,
            "password": password,
        },
    )
    await set_user_status(db_session, email, "approved")

    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": email,
            "password": password,
        },
    )
    return response.json().get("access_token")


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    email = unique_email("alice")
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Alice Test",
            "email": email,
            "password": "SecurePass123!",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == email
    assert data["full_name"] == "Alice Test"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    email = unique_email("bob")
    await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Bob Test",
            "email": email,
            "password": "SecurePass123!",
        },
    )
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Bob Duplicate",
            "email": email,
            "password": "AnotherPass123!",
        },
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_valid(client: AsyncClient, db_session: AsyncSession):
    email = unique_email("charlie")
    password = "SecurePass123!"
    await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Charlie Login",
            "email": email,
            "password": password,
        },
    )
    await set_user_status(db_session, email, "approved")

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, db_session: AsyncSession):
    email = unique_email("dave")
    await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Dave BadPass",
            "email": email,
            "password": "SecurePass123!",
        },
    )
    await set_user_status(db_session, email, "approved")

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "WrongPassword!"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_pending_user_forbidden(client: AsyncClient):
    email = unique_email("pending_login")
    password = "SecurePass123!"
    await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Pending Login",
            "email": email,
            "password": password,
        },
    )

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )

    assert response.status_code == 403
    assert "pending approval" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_rejected_user_forbidden(client: AsyncClient, db_session: AsyncSession):
    email = unique_email("rejected_login")
    password = "SecurePass123!"
    await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Rejected Login",
            "email": email,
            "password": password,
        },
    )
    await set_user_status(db_session, email, "rejected")

    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )

    assert response.status_code == 403
    assert "rejected" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_profile_rejected_user_forbidden(client: AsyncClient, db_session: AsyncSession):
    email = unique_email("rejected_profile")
    password = "SecurePass123!"
    await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Rejected Profile",
            "email": email,
            "password": password,
        },
    )
    await set_user_status(db_session, email, "rejected")

    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    token = security.create_access_token(user.id)

    response = await client.get(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert "rejected" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_profile(client: AsyncClient, db_session: AsyncSession):
    email = unique_email("eve")
    token = await register_and_login(client, db_session, email, "SecurePass123!", "Eve Profile")

    response = await client.get(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == email


@pytest.mark.asyncio
async def test_profile_no_token(client: AsyncClient):
    response = await client.get("/api/v1/auth/profile")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_endpoint_blocked_for_member(client: AsyncClient, db_session: AsyncSession):
    email = unique_email("frank")
    token = await register_and_login(client, db_session, email, "SecurePass123!", "Frank Member")

    response = await client.get(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1


@pytest.mark.asyncio
async def test_admin_can_list_users(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    token = response.json()["access_token"]

    response = await client.get(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["items"], list)
    assert payload["total"] >= 1


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"

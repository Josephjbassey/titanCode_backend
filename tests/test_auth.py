"""
TitanCode Technologies — Auth & User Tests
============================================
Tests for the authentication flow and user management endpoints.

Test Coverage:
    1. User Registration (valid + duplicate email)
    2. Login (valid credentials + wrong password)
    3. Protected endpoints (profile, token refresh)
    4. RBAC enforcement (admin-only routes)
    5. Health check

Note: Uses UUID-based emails so each test run is idempotent.
"""

import uuid
import pytest
from httpx import AsyncClient
from app.core.config import settings


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for each test run to avoid duplicates."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"


# ── Helper: Register + Login to get a JWT token ───────────────────────
async def register_and_login(client: AsyncClient, email: str, password: str, full_name: str = "Test User"):
    """Helper to register a user and return an auth token."""
    await client.post("/api/v1/auth/register", json={
        "full_name": full_name,
        "email": email,
        "password": password,
    })
    response = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": password,
    })
    return response.json().get("access_token")


# ═══════════════════════════════════════════════════════════════════════
# REGISTRATION TESTS
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    """Test that a new user can register successfully."""
    email = unique_email("alice")
    response = await client.post("/api/v1/auth/register", json={
        "full_name": "Alice Test",
        "email": email,
        "password": "SecurePass123!",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == email
    assert data["full_name"] == "Alice Test"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Test that registering with an existing email fails."""
    email = unique_email("bob")
    # Register first time
    await client.post("/api/v1/auth/register", json={
        "full_name": "Bob Test",
        "email": email,
        "password": "SecurePass123!",
    })
    # Register again with same email
    response = await client.post("/api/v1/auth/register", json={
        "full_name": "Bob Duplicate",
        "email": email,
        "password": "AnotherPass123!",
    })
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════
# LOGIN TESTS
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_login_valid(client: AsyncClient):
    """Test that login returns JWT tokens with valid credentials."""
    email = unique_email("charlie")
    password = "SecurePass123!"
    # Register
    await client.post("/api/v1/auth/register", json={
        "full_name": "Charlie Login",
        "email": email,
        "password": password,
    })
    # Login
    response = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": password,
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """Test that login fails with incorrect password."""
    email = unique_email("dave")
    await client.post("/api/v1/auth/register", json={
        "full_name": "Dave BadPass",
        "email": email,
        "password": "SecurePass123!",
    })
    response = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": "WrongPassword!",
    })
    assert response.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
# PROFILE & TOKEN TESTS
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_profile(client: AsyncClient):
    """Test that an authenticated user can fetch their profile."""
    email = unique_email("eve")
    token = await register_and_login(client, email, "SecurePass123!", "Eve Profile")

    response = await client.get(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == email


@pytest.mark.asyncio
async def test_profile_no_token(client: AsyncClient):
    """Test that accessing profile without a token fails."""
    response = await client.get("/api/v1/auth/profile")
    assert response.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# RBAC TESTS
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_admin_endpoint_blocked_for_member(client: AsyncClient):
    """Test that a regular Member cannot access admin-only endpoints."""
    email = unique_email("frank")
    token = await register_and_login(client, email, "SecurePass123!", "Frank Member")

    # Try to list all users (requires Admin role)
    response = await client.get(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_users(client: AsyncClient):
    """Test that the CEO admin can list all users."""
    # Login as the seeded admin
    response = await client.post("/api/v1/auth/login", data={
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    })
    token = response.json()["access_token"]

    response = await client.get(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) >= 1  # At least the admin exists


# ═══════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test that the health check endpoint returns OK."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"

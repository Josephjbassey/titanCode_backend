"""
TitanCode Technologies — Test Configuration (conftest.py)
==========================================================
Sets up the test infrastructure using a separate async engine
with NullPool to avoid connection conflicts with the app's
lifespan event.

Usage:
    pytest tests/ -v
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import pool
from sqlalchemy.future import select

# Disable rate limiting during tests — all tests come from 127.0.0.1
# and would quickly exceed the 5/minute login limit.
os.environ["RATE_LIMIT_ENABLED"] = "false"
# Provide deterministic defaults for local/CI test bootstrapping when env vars are absent.
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_ci_only")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./titancode_test.db")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "TestAdminPass123!")

from app.core.config import settings
from app.db.database import get_db
from app.db.models import User
from main import app

# ── Separate test engine ───────────────────────────────────────────────
# NullPool disables connection pooling — each request gets a fresh
# connection and releases it immediately. This prevents conflicts
# between the app lifespan and test sessions.
test_engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=pool.NullPool,
)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Override the database dependency ───────────────────────────────────
async def override_get_db():
    """Provide a test database session to endpoints."""
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


# ── Async HTTP Client ─────────────────────────────────────────────────
@pytest_asyncio.fixture
async def client():
    """
    Provide an async HTTP client that sends requests directly to our
    FastAPI app (in-memory, no network needed).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
@pytest_asyncio.fixture
async def db_session():
    """Provide a fresh database session for a test function."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def admin_token_headers(client: AsyncClient):
    """Provide headers with a valid admin JWT token."""
    response = await client.post("/api/v1/auth/login", data={
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def user_token_headers(client: AsyncClient):
    """Provide headers with a valid regular user JWT token."""
    # Register a temporary user
    email = f"test_{os.urandom(4).hex()}@test.com"
    await client.post("/api/v1/auth/register", json={
        "full_name": "Test User",
        "email": email,
        "password": "SecurePass123!",
    })
    # Approve the user so status checks allow authentication
    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        user.status = "approved"
        await session.commit()

    # Login
    response = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": "SecurePass123!",
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def pytest_collection_modifyitems(config, items):
    """Auto-assign test tiers for selective execution in CI."""
    for item in items:
        path = str(item.fspath)
        if "integration" in path:
            item.add_marker(pytest.mark.integration)
        elif "e2e" in path:
            item.add_marker(pytest.mark.e2e)
        else:
            item.add_marker(pytest.mark.unit)

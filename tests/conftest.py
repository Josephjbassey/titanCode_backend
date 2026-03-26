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
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import pool

# Disable rate limiting during tests — all tests come from 127.0.0.1
# and would quickly exceed the 5/minute login limit.
os.environ["RATE_LIMIT_ENABLED"] = "false"

from app.core.config import settings
from app.db.database import get_db
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

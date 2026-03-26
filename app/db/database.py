"""
TitanCode Technologies — Async Database Setup
===============================================
This module configures the asynchronous SQLAlchemy 2.0 engine and session
factory for PostgreSQL via the `asyncpg` driver.

Key components:
    - engine:           The async database engine (one per application).
    - AsyncSessionLocal: A factory that produces async database sessions.
    - Base:             The declarative base class all ORM models inherit from.
    - get_db():         A FastAPI dependency that provides a session per request.
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

# ── Async Engine ────────────────────────────────────────────────────────
# The engine manages the connection pool to the PostgreSQL database.
# `echo=False` disables SQL query logging (set to True for debugging).
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

# ── Session Factory ─────────────────────────────────────────────────────
# Each request gets its own session (unit of work) from this factory.
# `expire_on_commit=False` keeps objects accessible after commit without
# a new query—useful for returning data in API responses.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """
    Declarative base class for all SQLAlchemy ORM models.

    Every model in `app/db/models.py` inherits from this class so that
    SQLAlchemy can manage table metadata and migrations.
    """
    pass


async def get_db():
    """
    FastAPI dependency that yields an async database session.

    Usage in an endpoint:
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...

    The session is automatically closed after the request finishes,
    and any exceptions trigger a rollback to keep data consistent.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

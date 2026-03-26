"""
TitanCode Technologies — Alembic Environment Configuration
============================================================
This file is the "brain" of Alembic — it tells Alembic HOW to connect
to the database and WHERE to find the SQLAlchemy models for
auto-generating migrations.

Key customizations from the default template:
    1. Uses ASYNC engine (asyncpg) instead of sync.
    2. Reads DATABASE_URL from our app settings (not alembic.ini).
    3. Points `target_metadata` at our Base.metadata so Alembic can
       detect model changes and auto-generate migration scripts.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Import our app's models and config ─────────────────────────────────
# We import Base (which holds all model metadata) and settings (for the DB URL).
# IMPORTANT: All models must be imported BEFORE target_metadata is read,
# otherwise Alembic won't detect them. Importing `models` ensures all
# model classes are registered with Base.metadata.
from app.core.config import settings
from app.db.database import Base
from app.db import models  # noqa: F401 — triggers model registration

# ── Alembic Config Object ──────────────────────────────────────────────
# This gives access to values in the alembic.ini file
config = context.config

# Set the database URL dynamically from our app settings
# This overrides the dummy URL in alembic.ini so we don't hardcode secrets
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Target Metadata ────────────────────────────────────────────────────
# This is the key line — it tells Alembic about ALL our SQLAlchemy models.
# When you run `alembic revision --autogenerate`, Alembic compares the
# models registered in Base.metadata against the actual database schema
# and generates migration code for any differences.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    In offline mode, Alembic generates SQL statements without actually
    connecting to the database. Useful for generating SQL scripts that
    a DBA can review and run manually.

    Usage: alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """
    Helper function that runs the actual migrations within a connection.

    This is separated out so it can be called from both sync and async
    contexts. The `compare_type=True` flag tells Alembic to also detect
    column TYPE changes (e.g., changing String(50) to String(100)).
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # Detect column type changes
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations using an ASYNC engine.

    This is the key difference from the default Alembic template —
    we use `async_engine_from_config` instead of `engine_from_config`
    because our app uses asyncpg (async PostgreSQL driver).
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # Don't pool connections for migrations
    )

    # Run the synchronous migration code inside an async connection
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode (the default).

    This connects to the database and applies migrations directly.
    We use asyncio.run() to bridge the async engine with Alembic's
    synchronous runner.
    """
    asyncio.run(run_async_migrations())


# ── Entry Point ────────────────────────────────────────────────────────
# Alembic calls this when you run any migration command
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

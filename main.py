"""
TitanCode Technologies — Application Entry Point
==================================================
This is the main FastAPI application file. It:

1. Creates the FastAPI app instance with the project title for Swagger UI.
2. Configures CORS, rate limiting, and request logging middleware.
3. Registers all API routers.
4. Runs startup logic via the `lifespan` context manager:
   - Initializes structured JSON logging.
   - Optionally seeds the default CEO admin account.
5. Provides a health check endpoint at GET /.

To run locally:
    uvicorn main:app --reload

To run with Docker:
    docker-compose up -d --build
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.future import select
from sqlalchemy import text
from redis.asyncio import Redis

from app.core.config import settings
from app.core import security
from app.core.logging_config import setup_logging
from app.core.rate_limiter import limiter, rate_limit_exceeded_handler
from app.core.middleware import RequestLoggingMiddleware
from app.core.observability import init_sentry
from app.db.database import engine, AsyncSessionLocal
from app.db.models import User
from app.core.domain_enums import UserRole, ApprovalStatus
from app.api.v1.endpoints import auth, users, departments, applications, projects, tasks, wallets, notifications, files, meetings, products, revenue, financials, webhooks, client, billing, leads, dashboard

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Configure a logger for startup events
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# DATABASE SEED: Default Admin Account
# ═══════════════════════════════════════════════════════════════════════
async def seed_default_admin():
    """
    Create the default CEO admin account if it doesn't already exist.

    Credentials (from MVP Architecture doc, Section 9):
        Email:    admin@titancode.com
        Password: Provided via FIRST_SUPERUSER_PASSWORD environment variable
        Role:     CEO
        Status:   approved (active from the start)

    This runs once on every server startup but is idempotent —
    it checks for the existing account before inserting.
    """
    async with AsyncSessionLocal() as session:
        # Check if the admin account already exists
        stmt = select(User).where(User.email == settings.FIRST_SUPERUSER)
        result = await session.execute(stmt)
        existing = result.scalars().first()

        if not existing:
            admin = User(
                full_name="TitanCode Admin",
                email=settings.FIRST_SUPERUSER,
                password_hash=security.get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                role=UserRole.CEO.value,
                status=ApprovalStatus.APPROVED.value,
            )
            session.add(admin)
            await session.commit()
            logger.info("Default admin account created: %s", settings.FIRST_SUPERUSER)
        else:
            logger.info("Default admin account already exists, skipping seed.")


# ═══════════════════════════════════════════════════════════════════════
# APPLICATION LIFESPAN (Startup & Shutdown)
# ═══════════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern FastAPI lifespan handler (replaces deprecated @app.on_event).

    Startup (before `yield`):
        1. Seed the default admin account.

    Shutdown (after `yield`):
        1. Dispose the database engine to close all connections cleanly.
    """
    # ── Startup ─────────────────────────────────────────────────────
    # Step 1: Initialize structured JSON logging (must be first)
    setup_logging()

    init_sentry()

    # Step 2: enforce secure bootstrap posture for non-development environments.
    if not settings.is_dev_environment and settings.AUTO_SEED_DEFAULT_ADMIN:
        logger.warning("AUTO_SEED_DEFAULT_ADMIN is enabled in %s; disable after initial bootstrap.", settings.ENVIRONMENT)

    # Step 2: Seed the default admin account only when explicitly enabled
    if settings.AUTO_SEED_DEFAULT_ADMIN:
        await seed_default_admin()
    else:
        logger.info(
            "Skipping default admin seed because AUTO_SEED_DEFAULT_ADMIN is disabled for ENVIRONMENT=%s",
            settings.ENVIRONMENT,
        )

    yield  # ← Application runs here, handling requests

    # ── Shutdown ────────────────────────────────────────────────────
    await engine.dispose()


# ═══════════════════════════════════════════════════════════════════════
# CREATE THE FASTAPI APPLICATION
# ═══════════════════════════════════════════════════════════════════════
app = FastAPI(
    title=settings.PROJECT_NAME,                         # Shows in Swagger UI header
    openapi_url=f"{settings.API_V1_STR}/openapi.json",   # OpenAPI spec location
    lifespan=lifespan,                                   # Attach startup/shutdown logic
)

# ── CORS Middleware ─────────────────────────────────────────────────────
# Cross-Origin Resource Sharing: allows the frontend (e.g. React on
# localhost:3000) to make requests to this backend (localhost:8000).
if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,   # Allow cookies / auth headers
        allow_methods=["*"],      # Allow all HTTP methods (GET, POST, PUT, DELETE)
        allow_headers=["*"],      # Allow all headers
    )

# ── Rate Limiting Middleware ────────────────────────────────────────────
# SlowAPI protects against brute-force and abuse.
# Default: 60 requests/minute per IP. Auth endpoints get stricter limits.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── Request Logging Middleware ──────────────────────────────────────────
# Logs every HTTP request with timing, status code, and client IP.
# Also adds X-Process-Time header to responses.
app.add_middleware(RequestLoggingMiddleware)

# ── Register API Routers ───────────────────────────────────────────────
# Each router handles a group of related endpoints.
# prefix: all routes are prefixed with /api/v1/<resource>
# tags:   groups endpoints in the Swagger UI sidebar
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(users.router, prefix=f"{settings.API_V1_STR}/users", tags=["users"])
app.include_router(departments.router, prefix=f"{settings.API_V1_STR}/departments", tags=["departments"])
app.include_router(applications.router, prefix=f"{settings.API_V1_STR}/applications", tags=["applications"])
app.include_router(projects.router, prefix=f"{settings.API_V1_STR}/projects", tags=["projects"])
app.include_router(tasks.router, prefix=f"{settings.API_V1_STR}/tasks", tags=["tasks"])
app.include_router(wallets.router, prefix=f"{settings.API_V1_STR}/wallets", tags=["wallets"])
app.include_router(notifications.router, prefix=f"{settings.API_V1_STR}/notifications", tags=["notifications"])
app.include_router(files.router, prefix=f"{settings.API_V1_STR}/files", tags=["files"])
app.include_router(meetings.router, prefix=f"{settings.API_V1_STR}/meetings", tags=["meetings"])
app.include_router(products.router, prefix=f"{settings.API_V1_STR}/products", tags=["products"])
app.include_router(revenue.router, prefix=f"{settings.API_V1_STR}/revenue", tags=["revenue"])
app.include_router(financials.router, prefix=f"{settings.API_V1_STR}/financials", tags=["financials"])
# This router handles specialized webhooks, like payment success notifications from Stripe.
app.include_router(webhooks.router, prefix=f"{settings.API_V1_STR}/webhooks", tags=["webhooks"])
app.include_router(client.router, prefix=f"{settings.API_V1_STR}/client", tags=["client"])
app.include_router(billing.router, prefix=f"{settings.API_V1_STR}/billing", tags=["billing"])
app.include_router(leads.router, prefix=f"{settings.API_V1_STR}/leads", tags=["leads"])
app.include_router(dashboard.router, prefix=f"{settings.API_V1_STR}/dashboard", tags=["dashboard"])


# ═══════════════════════════════════════════════════════════════════════
# HEALTH CHECK ENDPOINT
# ═══════════════════════════════════════════════════════════════════════
@app.get("/health/live", tags=["health"])
async def liveness_check():
    return {"status": "alive", "service": settings.PROJECT_NAME}


@app.get("/health/ready", tags=["health"])
async def readiness_check():
    """
    Simple health check endpoint.

    Used by Docker healthchecks, load balancers, and monitoring tools
    to verify the API is running. Returns the service name and status.
    """
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))

    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis_client.ping()
    finally:
        await redis_client.close()

    return {"status": "healthy", "service": settings.PROJECT_NAME}


@app.get("/", tags=["health"])
async def health_check_root():
    """Backward-compatible root health endpoint."""
    return await readiness_check()

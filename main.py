"""
TitanCode Technologies — Application Entry Point
==================================================
This is the main FastAPI application file. It:

1. Creates the FastAPI app instance with the project title for Swagger UI.
2. Configures CORS, rate limiting, and request logging middleware.
3. Registers all API routers.
4. Runs startup logic via the `lifespan` context manager:
   - Initializes structured JSON logging.
   - Creates all database tables if they don't exist.
   - Seeds the default CEO admin account (admin@titancode.com).
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

from app.core.config import settings
from app.core.security import get_password_hash
from app.core.logging_config import setup_logging
from app.core.rate_limiter import limiter, rate_limit_exceeded_handler
from app.core.middleware import RequestLoggingMiddleware
from app.db.database import engine, Base, AsyncSessionLocal
from app.db.models import User
from app.api.v1.endpoints import auth, users, departments, applications, projects, tasks, wallets, notifications, files, meetings, products, revenue, financials

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

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
        Password: TitanCodeAdmin123!
        Role:     CEO
        Status:   approved (active from the start)

    This runs once on every server startup but is idempotent —
    it checks for the existing account before inserting.
    """
    async with AsyncSessionLocal() as session:
        # Check if the admin account already exists
        stmt = select(User).where(User.email == "admin@titancode.com")
        result = await session.execute(stmt)
        existing = result.scalars().first()

        if not existing:
            admin = User(
                full_name="TitanCode Admin",
                email="admin@titancode.com",
                password_hash=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                role="CEO",
                status="approved",
            )
            session.add(admin)
            await session.commit()
            logger.info("Default admin account created: admin@titancode.com")
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
        1. Create all database tables from ORM models.
        2. Seed the default admin account.

    Shutdown (after `yield`):
        1. Dispose the database engine to close all connections cleanly.
    """
    # ── Startup ─────────────────────────────────────────────────────
    # Step 1: Initialize structured JSON logging (must be first)
    setup_logging()

    # Step 2: Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully.")

    # Step 3: Seed the default admin account
    await seed_default_admin()

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


# ═══════════════════════════════════════════════════════════════════════
# HEALTH CHECK ENDPOINT
# ═══════════════════════════════════════════════════════════════════════
@app.get("/", tags=["health"])
async def health_check():
    """
    Simple health check endpoint.

    Used by Docker healthchecks, load balancers, and monitoring tools
    to verify the API is running. Returns the service name and status.
    """
    return {"status": "healthy", "service": settings.PROJECT_NAME}

"""
TitanCode Technologies — Core Configuration
=============================================
This module loads all application settings from environment variables
using Pydantic's BaseSettings. Values are read from a `.env` file at
the project root so that secrets are never hardcoded in source code.

Usage:
    from app.core.config import settings
    print(settings.SECRET_KEY)
"""

from typing import Optional
from pydantic import EmailStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application-wide settings, automatically populated from environment
    variables or the `.env` file.

    Attributes:
        PROJECT_NAME:               Display name shown in Swagger UI.
        API_V1_STR:                 URL prefix for all v1 API routes.
        SECRET_KEY:                 Used to sign/verify JWT tokens — keep this private!
        ALGORITHM:                  JWT signing algorithm (default: HS256).
        ACCESS_TOKEN_EXPIRE_MINUTES: Lifespan of an access token in minutes.
        REFRESH_TOKEN_EXPIRE_DAYS:  Lifespan of a refresh token in days.
        BACKEND_CORS_ORIGINS:       List of allowed frontend origins for CORS.
        DATABASE_URL:               Async PostgreSQL connection string
                                    (e.g. postgresql+asyncpg://user:pass@host/db).
    """

    ENVIRONMENT: str = "development"

    PROJECT_NAME: str = "TitanCode Technologies Backend Service"

    # Admin Seeding
    FIRST_SUPERUSER: EmailStr = "admin@titancode.com"
    FIRST_SUPERUSER_PASSWORD: str = "TitanCodeAdmin123!"  # Default for dev, override in .env
    AUTO_SEED_DEFAULT_ADMIN: bool = True

    API_V1_STR: str = "/api/v1"

    # ── Security ────────────────────────────────────────────────────────
    SECRET_KEY: str                          # Required — loaded from .env
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15    # Short-lived access tokens
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7       # Longer-lived refresh tokens

    # ── CORS ────────────────────────────────────────────────────────────
    # Stored as a comma-separated string in .env (e.g. "http://localhost:3000,http://localhost:8000")
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Split the comma-separated CORS string into a list of origins."""
        return [origin.strip() for origin in self.BACKEND_CORS_ORIGINS.split(",") if origin.strip()]

    # ── Database ────────────────────────────────────────────────────────
    DATABASE_URL: str                        # Required — loaded from .env
    REDIS_URL: str = "redis://redis:6379/0"  # Default for Docker

    # ── AWS S3 Storage (Optional) ──────────────────────────────────────
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    S3_BUCKET: Optional[str] = None
    S3_REGION: str = "us-east-1"
    USE_S3: bool = False                     # Toggle between Local and S3

    # ── Email Configuration (SMTP) ──────────────────────────────────────
    SMTP_TLS: bool = True
    SMTP_PORT: Optional[int] = 587
    SMTP_HOST: Optional[str] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAILS_FROM_EMAIL: Optional[str] = "info@titancode.com"
    EMAILS_FROM_NAME: Optional[str] = "TitanCode Technologies"
    
    # ── Stripe Configuration ────────────────────────────────────────────
    # These are loaded from your .env file.
    # STRIPE_API_KEY: Used to actually talk to Stripe (like a password).
    # STRIPE_WEBHOOK_SECRET: Used to verify that messages from Stripe are real.
    STRIPE_API_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    # ── Miscellaneous ───────────────────────────────────────────────────
    VERSION: str = "1.0.0"
    RATE_LIMIT_ENABLED: bool = True
    STORAGE_TYPE: str = "local"
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # Tell Pydantic to read variables from the .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def is_dev_environment(self) -> bool:
        """Return True for local/dev/test environments where bootstrap defaults are allowed."""
        return self.ENVIRONMENT.lower() in {"dev", "development", "local", "test", "testing"}

    @model_validator(mode="after")
    def validate_secure_bootstrap_defaults(self):
        """Fail fast when insecure bootstrap defaults are used outside dev/test."""
        insecure_default_password = self.FIRST_SUPERUSER_PASSWORD == "TitanCodeAdmin123!"

        if not self.is_dev_environment and insecure_default_password:
            raise ValueError(
                "FIRST_SUPERUSER_PASSWORD must be overridden with a non-default secret "
                "when ENVIRONMENT is not development/test."
            )

        return self


# Singleton instance — import this throughout the app
settings = Settings()

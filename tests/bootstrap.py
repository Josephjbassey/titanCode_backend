"""Test bootstrap utilities for deterministic env setup."""

from __future__ import annotations

import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def bootstrap_test_env() -> None:
    """Load `.env.test` and apply required defaults for pytest runtime."""
    env_file = Path(__file__).resolve().parents[1] / ".env.test"
    _load_env_file(env_file)

    os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
    os.environ.setdefault("SECRET_KEY", "test_secret_key_for_ci_only")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./titancode_test.db")
    os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "TestAdminPass123!")

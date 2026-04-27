# ═══════════════════════════════════════════════════════════════════════
# TitanCode Technologies — Dockerfile
# ═══════════════════════════════════════════════════════════════════════
# This file defines how to build the FastAPI application into a Docker
# container. Docker creates an isolated environment with Python, all
# dependencies, and the application code bundled together.
#
# Build & Run:
#   docker build -t titancode-api .
#   docker run -p 8000:8000 titancode-api
#
# Or use docker-compose (recommended):
#   docker-compose up -d --build
# ═══════════════════════════════════════════════════════════════════════

# Step 1: Start from a lightweight Python 3.11 base image
# "slim" means it excludes development tools to keep the image small (~150MB)
FROM python:3.11-slim

# Step 2: Set environment variables for Python
# PYTHONUNBUFFERED=1       → Print output immediately (don't buffer logs)
# PYTHONDONTWRITEBYTECODE=1 → Don't create .pyc files (saves space in container)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Step 3: Set the working directory inside the container
# All subsequent commands run from /app
WORKDIR /app

# Step 4: Install system dependencies required by asyncpg and psycopg2
# gcc     → C compiler needed to build some Python packages
# libpq-dev → PostgreSQL client library (needed by asyncpg)
# We clean up apt cache afterward to keep the image small
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Step 5: Copy and install Python dependencies FIRST
# This is a Docker best practice — dependencies change less often than code,
# so Docker can cache this layer and skip reinstalling on every code change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 6: Copy the rest of the application code
COPY . .

# Step 7: Start the FastAPI server with Gunicorn (Production)
# We use Gunicorn as a process manager to run multiple Uvicorn workers.
# -w 4         → Run 4 worker processes (adjust based on CPU cores)
# -k uvicorn.workers.UvicornWorker → Use the Uvicorn worker class
# --bind 0.0.0.0:8000 → Listen on all interfaces
CMD ["sh", "-c", "alembic upgrade head && gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000"]

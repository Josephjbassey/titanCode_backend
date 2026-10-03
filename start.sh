#!/bin/bash
set -e

echo "=========================================================="
echo "Starting TitanCode Backend Service (Web + Celery Worker)"
echo "=========================================================="

# Step 1: Run Database Migrations
echo "--> [1/3] Running database migrations with Alembic..."
alembic upgrade head

# Step 2: Start the Celery Worker in the background
echo "--> [2/3] Starting background Celery worker..."
celery -A app.core.celery_app worker --loglevel=info -Q default,notifications,dead_letter --concurrency=2 &
CELERY_PID=$!
echo "--> Celery worker started with PID $CELERY_PID"

# Trap container termination to stop Celery cleanly
cleanup() {
  echo "--> Stopping background Celery worker (PID: $CELERY_PID)..."
  kill -TERM "$CELERY_PID" 2>/dev/null || true
  wait "$CELERY_PID" 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT EXIT

# Step 3: Start Gunicorn + Uvicorn in the foreground
echo "--> [3/3] Starting Gunicorn server on port ${PORT:-8000}..."
exec gunicorn main:app -w ${WEB_CONCURRENCY:-2} -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000}

#!/usr/bin/env bash
set -euo pipefail

echo "Running database migrations..."
alembic upgrade head

echo "Starting uvicorn..."
exec uvicorn phiacta.main:app --host 0.0.0.0 --port 8000 --workers 4

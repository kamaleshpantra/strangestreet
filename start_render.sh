#!/bin/bash
set -e

echo "Running database migrations..."
python -m alembic upgrade head

echo "Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port $PORT

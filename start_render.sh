#!/bin/bash
set -e

# Render provides DATABASE_URL with postgres:// but SQLAlchemy 2.x requires postgresql://
if [[ $DATABASE_URL == postgres://* ]]; then
  export DATABASE_URL=$(echo $DATABASE_URL | sed 's/^postgres:/postgresql:/')
fi

echo ">>> [STARTUP] Running database migrations..."
python -m alembic upgrade head

echo ">>> [STARTUP] Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}

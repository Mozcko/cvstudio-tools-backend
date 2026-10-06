#!/bin/sh
# Production entrypoint: bring the schema up to date, then serve.
set -e

alembic upgrade head
exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}"

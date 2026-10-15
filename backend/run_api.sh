#!/usr/bin/env bash
# Start the SuperPlanner API (ARCHITECTURE 18). Honours DATABASE_URL, PORT, HOST, CORS_ORIGINS, RUN_WORKERS.
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/uvicorn superplanner.api.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" "$@"

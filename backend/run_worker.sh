#!/usr/bin/env bash
# Start one SuperPlanner job worker (PHASE2B 2.9). Needs DATABASE_URL=postgresql+psycopg://... (JOB_BACKEND=queue,
# the default with PostgreSQL). Honours WORKER_CONCURRENCY, WORKER_KINDS, WORKER_ID, WORKER_METRICS_PORT and the
# JOB_* settings; extra arguments are passed on (e.g. --concurrency 1 --once). SIGTERM/SIGINT: graceful stop.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" -m superplanner.worker "$@"

#!/usr/bin/env bash
# Start the SuperPlanner API (ARCHITECTURE 18, PHASE2B 5.1/5.6). Honours DATABASE_URL, HOST, PORT, CORS_ORIGINS,
# RUN_WORKERS, LOG_FORMAT, FORWARDED_ALLOW_IPS and every other setting of docs/DEPLOY.md section 4.
# Zero setup: without DATABASE_URL it uses backend/superplanner.db (SQLite, inline jobs, single-user).
# Extra arguments are passed on to uvicorn (e.g. --reload).
set -euo pipefail
cd "$(dirname "$0")"
UVICORN=.venv/bin/uvicorn
[ -x "$UVICORN" ] || UVICORN=uvicorn
args=(superplanner.api.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
      --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}")
# With JSON logs the API writes its own `http.request` access line (with request id); uvicorn's would be text.
if [ "${LOG_FORMAT:-}" = "json" ]; then
  args+=(--no-access-log)
fi
exec "$UVICORN" "${args[@]}" "$@"

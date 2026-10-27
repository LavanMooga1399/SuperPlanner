#!/usr/bin/env bash
# Start the SuperPlanner API (ARCHITECTURE 18, PHASE2B 5.1/5.6). Honours DATABASE_URL, HOST, PORT, CORS_ORIGINS,
# RUN_WORKERS, LOG_FORMAT, FORWARDED_ALLOW_IPS and every other setting of docs/DEPLOY.md section 4.
# PostgreSQL only: DATABASE_URL is required, and the schema must be at head first
#   .venv/bin/python -m superplanner.migrate upgrade        (or AUTO_MIGRATE=true for local development)
# Local development: APP_ENV=development (default is production with its secure-default checks).
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

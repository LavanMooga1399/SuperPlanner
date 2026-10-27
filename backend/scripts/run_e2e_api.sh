#!/usr/bin/env bash
# The API for the Playwright e2e runs: a fresh PostgreSQL database $SP_E2E_DB on the dev/test cluster (created,
# migrated to head), then run_api.sh on it with APP_ENV=development. The Playwright global teardown drops the
# database again (scripts/e2e_db.py drop). Extra environment (AUTH_MODE, PORT, ...) comes from the config.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
PY="$here/.venv/bin/python"
[ -x "$PY" ] || PY=python3
: "${SP_E2E_DB:?set SP_E2E_DB to the database name}"
DATABASE_URL="$("$PY" "$here/scripts/e2e_db.py" create "$SP_E2E_DB")"
export DATABASE_URL
export APP_ENV="${APP_ENV:-development}"
exec "$here/run_api.sh" "$@"

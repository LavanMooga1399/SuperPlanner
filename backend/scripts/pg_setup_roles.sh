#!/usr/bin/env bash
# Create the SuperPlanner owner + app roles and database (wrapper around pg_setup_roles.sql; docs/DEPLOY.md).
#
#   SP_OWNER_PASSWORD=... SP_APP_PASSWORD=... backend/scripts/pg_setup_roles.sh [PSQL connection options...]
#   e.g. backend/scripts/pg_setup_roles.sh -h db.internal -U postgres
#
# Environment: SP_DB (default superplanner), SP_OWNER_ROLE (superplanner_owner), SP_APP_ROLE (superplanner_app),
# SP_OWNER_PASSWORD and SP_APP_PASSWORD (required). PSQL (default: psql on PATH). Connection options are passed to
# psql as given (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGSSLMODE also work); it connects to the `postgres` database
# unless -d is given. Prints the two URLs to use (passwords masked).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
PSQL="${PSQL:-psql}"
db="${SP_DB:-superplanner}"
owner="${SP_OWNER_ROLE:-superplanner_owner}"
app="${SP_APP_ROLE:-superplanner_app}"
: "${SP_OWNER_PASSWORD:?set SP_OWNER_PASSWORD}"
: "${SP_APP_PASSWORD:?set SP_APP_PASSWORD}"
has_db=0
for a in "$@"; do case "$a" in -d|--dbname|--dbname=*|-d*) has_db=1 ;; esac; done
extra=()
[ "$has_db" = 1 ] || extra=(-d postgres)
"$PSQL" "${extra[@]}" "$@" -X -q -v ON_ERROR_STOP=1 \
  -v db="$db" -v owner="$owner" -v owner_password="$SP_OWNER_PASSWORD" \
  -v app="$app" -v app_password="$SP_APP_PASSWORD" -f "$here/pg_setup_roles.sql"
echo "roles ready on database $db:"
echo "  MIGRATION_DATABASE_URL=postgresql+psycopg://$owner:***@HOST:5432/$db   (migrations only)"
echo "  DATABASE_URL=postgresql+psycopg://$app:***@HOST:5432/$db             (API and workers)"

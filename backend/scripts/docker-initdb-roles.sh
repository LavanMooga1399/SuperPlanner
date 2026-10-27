#!/bin/sh
# Runs once, on the first start of an empty `db` volume (mounted into /docker-entrypoint-initdb.d by
# docker-compose.yml): creates the owner + app roles of pg_setup_roles.sql for $POSTGRES_DB.
set -eu
psql -X -q -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v db="$POSTGRES_DB" \
  -v owner="${SP_DB_OWNER_USER:-superplanner_owner}" -v owner_password="$SP_DB_OWNER_PASSWORD" \
  -v app="${SP_DB_APP_USER:-superplanner_app}" -v app_password="$SP_DB_APP_PASSWORD" \
  -f /sp/pg_setup_roles.sql
echo "superplanner roles created: owner ${SP_DB_OWNER_USER:-superplanner_owner}, app ${SP_DB_APP_USER:-superplanner_app}"

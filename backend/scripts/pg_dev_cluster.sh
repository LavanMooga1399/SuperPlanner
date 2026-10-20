#!/usr/bin/env bash
# Local PostgreSQL 16 cluster for development and the Postgres test run (PHASE2B 3.6).
#
#   scripts/pg_dev_cluster.sh init  [DIR] [PORT]   create the cluster (idempotent), start it, create role sp_test
#   scripts/pg_dev_cluster.sh start [DIR] [PORT]   start it (idempotent)
#   scripts/pg_dev_cluster.sh stop  [DIR]          stop it (fast shutdown; idempotent)
#   scripts/pg_dev_cluster.sh status [DIR]
#   scripts/pg_dev_cluster.sh url   [DIR] [PORT]   print the admin URL for SP_TEST_PG_URL / DATABASE_URL
#
# DIR defaults to backend/.pgdata (git-ignored), PORT to 54329. The server listens on 127.0.0.1 only with
# `trust` auth (development only!). postgres refuses to run as root: when this script runs as root it creates
# the system user `spdb` (useradd -r -m) and runs every server command through `runuser -u spdb --`.
# Override the binaries with PG_BIN (default /usr/lib/postgresql/16/bin, else whatever is on PATH).
set -euo pipefail

cmd="${1:-}"
here="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${2:-$here/.pgdata}"
PORT="${3:-54329}"
PG_BIN="${PG_BIN:-/usr/lib/postgresql/16/bin}"
[ -x "$PG_BIN/initdb" ] || PG_BIN="$(dirname "$(command -v initdb 2>/dev/null || echo /usr/bin/initdb)")"
OS_USER="spdb"
ROLE="sp_test"

as_db() {
  if [ "$(id -u)" = "0" ]; then
    runuser -u "$OS_USER" -- "$@"
  else
    "$@"
  fi
}

ensure_user() {
  if [ "$(id -u)" = "0" ] && ! id "$OS_USER" >/dev/null 2>&1; then
    useradd -r -m "$OS_USER"
  fi
}

ensure_dir() {
  mkdir -p "$DIR"
  if [ "$(id -u)" = "0" ]; then
    chown "$OS_USER" "$DIR"
    # every parent must be traversable by spdb
    p="$(dirname "$DIR")"
    while [ "$p" != "/" ]; do
      chmod o+x "$p" 2>/dev/null || true
      p="$(dirname "$p")"
    done
  fi
  chmod 700 "$DIR"
}

is_running() {
  [ -f "$DIR/postmaster.pid" ] && as_db "$PG_BIN/pg_ctl" -D "$DIR" status >/dev/null 2>&1
}

start() {
  if is_running; then
    echo "postgres already running ($DIR)"
    return 0
  fi
  as_db "$PG_BIN/pg_ctl" -D "$DIR" -l "$DIR/server.log" -w -t 60 \
    -o "-p $PORT -c listen_addresses=127.0.0.1 -c unix_socket_directories=$DIR -c fsync=off -c max_connections=300" \
    start >/dev/null
  echo "postgres started on 127.0.0.1:$PORT ($DIR)"
}

psql_admin() {
  as_db "$PG_BIN/psql" -h 127.0.0.1 -p "$PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -qAt "$@"
}

ensure_role() {
  if [ "$(psql_admin -c "SELECT 1 FROM pg_roles WHERE rolname = '$ROLE'")" != "1" ]; then
    psql_admin -c "CREATE ROLE $ROLE LOGIN CREATEDB PASSWORD '$ROLE'"
  fi
}

case "$cmd" in
  init)
    ensure_user
    ensure_dir
    if [ ! -f "$DIR/PG_VERSION" ]; then
      as_db "$PG_BIN/initdb" -D "$DIR" -U postgres --locale=C --encoding=UTF8 -A trust >/dev/null
      echo "cluster created in $DIR"
    fi
    start
    ensure_role
    ;;
  start)
    ensure_user
    [ -f "$DIR/PG_VERSION" ] || { echo "no cluster in $DIR; run: $0 init $DIR $PORT" >&2; exit 1; }
    start
    ;;
  stop)
    if is_running; then
      as_db "$PG_BIN/pg_ctl" -D "$DIR" -m fast -w stop >/dev/null
      echo "postgres stopped ($DIR)"
    else
      echo "postgres not running ($DIR)"
    fi
    ;;
  status)
    if is_running; then echo "running"; else echo "stopped"; exit 1; fi
    ;;
  url)
    echo "postgresql+psycopg://$ROLE:$ROLE@127.0.0.1:$PORT/postgres"
    ;;
  *)
    echo "usage: $0 {init|start|stop|status|url} [DIR] [PORT]" >&2
    exit 2
    ;;
esac

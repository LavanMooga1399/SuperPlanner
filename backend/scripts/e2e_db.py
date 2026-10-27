"""Fresh PostgreSQL databases for the Playwright e2e runs (frontend/e2e/playwright*.config.ts).

    .venv/bin/python scripts/e2e_db.py create NAME   drop NAME if it exists, create it, migrate it to head and print
                                                     its URL (the e2e API then runs on it)
    .venv/bin/python scripts/e2e_db.py drop NAME     DROP DATABASE ... WITH (FORCE) (idempotent)

Admin URL (a role with CREATEDB): SP_E2E_PG_URL, else SP_TEST_PG_URL, else the dev cluster
(scripts/pg_dev_cluster.sh: postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres). NAME must match
[a-z0-9_]{1,63}. Exit codes: 0 ok, 2 usage, 3 database error.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_ADMIN_URL = "postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres"


def admin_url() -> str:
    from superplanner.api.config import normalize_database_url

    return normalize_database_url(os.environ.get("SP_E2E_PG_URL") or os.environ.get("SP_TEST_PG_URL")
                                  or DEFAULT_ADMIN_URL)


def _admin_exec(sql: str) -> None:
    from sqlalchemy import create_engine, pool, text

    eng = create_engine(admin_url(), poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            c.execute(text(sql))
    finally:
        eng.dispose()


def url_for(name: str) -> str:
    from sqlalchemy.engine import make_url

    return make_url(admin_url()).set(database=name).render_as_string(hide_password=False)


def create(name: str) -> str:
    from superplanner import migrate

    _admin_exec(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    _admin_exec(f'CREATE DATABASE "{name}"')
    url = url_for(name)
    migrate.upgrade(url)
    return url


def drop(name: str) -> None:
    _admin_exec(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("create", "drop") or not re.fullmatch(r"[a-z0-9_]{1,63}", argv[1]):
        print("usage: e2e_db.py {create|drop} NAME   (NAME: [a-z0-9_]{1,63})", file=sys.stderr)
        return 2
    import logging

    logging.basicConfig(level=logging.WARNING)
    try:
        if argv[0] == "create":
            print(create(argv[1]))
        else:
            drop(argv[1])
    except Exception as exc:
        print(f"e2e_db {argv[0]} {argv[1]} failed: {exc.__class__.__name__}: {str(exc).splitlines()[0]}",
              file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

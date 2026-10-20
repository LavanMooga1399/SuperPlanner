"""Alembic environment (PHASE2B 3.2).

Connection: `config.attributes["connection"]` when called from `superplanner.migrate` (which owns the transaction,
SQLite foreign keys and the Postgres advisory lock), else a URL from `-x url=...`, `DATABASE_URL`, or the Settings
default. `target_metadata` is the complete model metadata (autogenerate / compare only; revisions never use it).
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

from superplanner.api.config import DEFAULT_DATABASE_URL, normalize_database_url
from superplanner.api.db import load_all_models

config = context.config
target_metadata = load_all_models()


def _url() -> str:
    x = context.get_x_argument(as_dictionary=True)
    return normalize_database_url(x.get("url") or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL)


def _configure(connection) -> None:  # noqa: ANN001
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      render_as_batch=connection.dialect.name == "sqlite")


def run_migrations_offline() -> None:
    url = _url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True,
                      render_as_batch=url.startswith("sqlite"), dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        with context.begin_transaction():   # no-op when the caller already opened a transaction
            context.run_migrations()
        return
    url = _url()
    engine = create_engine(url, poolclass=pool.NullPool)
    if url.startswith("sqlite"):
        # Plain `alembic` CLI on SQLite: never run batch table rebuilds with foreign keys ON (review R1).
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk_off(dbapi_conn, _rec):  # noqa: ANN001
            dbapi_conn.execute("PRAGMA foreign_keys=OFF")
    with engine.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

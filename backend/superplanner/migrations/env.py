"""Alembic environment (PHASE2B 3.2). PostgreSQL only.

Connection: `config.attributes["connection"]` when called from `superplanner.migrate` (which owns the transaction
and the advisory lock), else a URL from `-x url=...`, MIGRATION_DATABASE_URL or DATABASE_URL (owner role).
`target_metadata` is the complete model metadata (autogenerate / compare only; revisions never use it).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from superplanner.api.config import resolve_migration_url
from superplanner.api.db import load_all_models

config = context.config
target_metadata = load_all_models()


def _url() -> str:
    x = context.get_x_argument(as_dictionary=True)
    return resolve_migration_url(x.get("url"))


def _configure(connection) -> None:  # noqa: ANN001
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        with context.begin_transaction():   # no-op when the caller already opened a transaction
            context.run_migrations()
        return
    engine = create_engine(_url(), poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

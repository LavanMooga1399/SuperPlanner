"""Q1 database-layer tests (PHASE2B 3, 4.7; plan Q1-1..Q1-13)."""

from __future__ import annotations

import sys
import uuid
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=".*httpx2.*")


@pytest.fixture
def empty_db_factory(request: pytest.FixtureRequest, db_kind: str, tmp_path: Path) -> Iterator[Callable[[], str]]:
    """Truly empty databases (no schema at all): a new SQLite file or `CREATE DATABASE` without our template."""
    created: list[str] = []

    def new() -> str:
        if db_kind == "sqlite":
            return f"sqlite:///{tmp_path / f'empty_{uuid.uuid4().hex[:6]}.db'}"
        admin = request.getfixturevalue("pg_admin")
        name = f"sp_e_{uuid.uuid4().hex[:8]}"
        admin.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        return admin.url_for(name)

    yield new
    if created:
        admin = request.getfixturevalue("pg_admin")
        for n in created:
            admin.drop(n)


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("db")

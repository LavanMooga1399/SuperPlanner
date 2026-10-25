"""WP-A database tests (M1-DESIGN 6; PLAN-M1 A1/A4): schema rules, migration, repository, plant lock."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def mfg_db(db_url_factory) -> Iterator["object"]:
    """A migrated database with ownership hooks (accounts semantics) and users usr_a, usr_b."""
    from mfgdb_helpers import open_db

    db = open_db(db_url_factory("mfgdb"))
    try:
        yield db
    finally:
        db.dispose()

"""WP-A M2 database tests (M2-DESIGN 17.2): migration, schema rules, repository, lockers (`mfgm2db`)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE), str(_HERE.parent / "mfg_db")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def m2_db(db_url_factory) -> Iterator["object"]:
    from mfgdb_helpers import open_db

    db = open_db(db_url_factory("mfgm2db"))
    try:
        yield db
    finally:
        db.dispose()

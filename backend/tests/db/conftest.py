"""Q1 database-layer tests (PHASE2B 3, 4.7; plan Q1-1..Q1-13)."""

from __future__ import annotations

import sys
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=".*httpx2.*")


@pytest.fixture
def empty_db_factory(empty_pg_db: Callable[[], str]) -> Callable[[], str]:
    """Truly empty databases (no schema at all): `CREATE DATABASE` without our template."""
    return empty_pg_db


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("db")

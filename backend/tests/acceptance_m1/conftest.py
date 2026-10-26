"""WP-D acceptance suite for M1 Gate 1 (M1-DESIGN 15.3 #1-#7, PLAN-M1 5): real app + real API on the selected
database (SQLite default, PostgreSQL with SP_TEST_DB=postgres). Every test gets fresh databases from
`db_url_factory("accm1")`; nothing is imported from other packages' test folders."""

from __future__ import annotations

import sys
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=".*httpx2.*")

pytest.importorskip("superplanner.api.mfg.router", reason="M1 API (WP-B) not available yet")

from fastapi.testclient import TestClient  # noqa: E402

from accm1_helpers import Api, acc_app, make_app, sign_up  # noqa: E402


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("accm1")


@pytest.fixture
def app(db_url: str):
    return make_app(db_url)


@pytest.fixture
def api(app) -> Iterator[Api]:
    with TestClient(app) as c:
        yield Api(c)


@pytest.fixture
def accounts(db_url: str) -> Iterator[tuple[Api, Api]]:
    """Two signed-up users (A, B) of one accounts-mode app (CSRF header set)."""
    a = acc_app(db_url)
    with TestClient(a):
        ca, cb = sign_up(a, "accm1-a@example.com"), sign_up(a, "accm1-b@example.com")
        try:
            yield Api(ca), Api(cb)
        finally:
            ca.close()
            cb.close()

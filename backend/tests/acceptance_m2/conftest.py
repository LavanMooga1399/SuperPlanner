"""WP-D acceptance suite for M2 Gate 2 (M2-DESIGN 18). Pure oracle tests run without a database; API tests use
fresh PostgreSQL databases from `db_url_factory("accm2")` and skip (with the missing endpoint/module named) while
the M2 API is not built yet. Nothing is imported from other packages' test folders."""

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


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("accm2")


@pytest.fixture
def app(db_url: str):
    from accm2_helpers import make_app

    return make_app(db_url)


@pytest.fixture
def api(app):
    from fastapi.testclient import TestClient

    from accm2_helpers import Api

    with TestClient(app) as c:
        yield Api(c, app)


@pytest.fixture
def acc(db_url: str) -> Iterator:
    """Accounts-mode app (CSRF) for the role / workspace tests: `acc.user(email) -> Api`."""
    from fastapi.testclient import TestClient

    from accm2_helpers import Accounts, acc_app

    a = acc_app(db_url)
    with TestClient(a):
        accounts = Accounts(a)
        try:
            yield accounts
        finally:
            accounts.close()

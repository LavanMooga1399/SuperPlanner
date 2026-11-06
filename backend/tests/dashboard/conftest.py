"""WP-S M6 tests (M6-DESIGN 9): every test gets its own app and database (`db_url_factory("m6dashboard")`)."""

from __future__ import annotations

import sys
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE), str(_HERE.parent / "api_mfg_m2"), str(_HERE.parent / "assistant")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=".*httpx2.*")

from fastapi.testclient import TestClient  # noqa: E402

from apimfgm2_helpers import Api, make_app  # noqa: E402


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("m6dashboard")


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with TestClient(make_app(db_url)) as c:
        yield c


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)

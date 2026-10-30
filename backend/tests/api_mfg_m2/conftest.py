"""WP-B M2 API tests (M2-DESIGN 17.2): every test gets its own app and database (`db_url_factory("apimfgm2")`)."""

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

from fastapi.testclient import TestClient  # noqa: E402

from apimfgm2_helpers import Api, make_app  # noqa: E402


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("apimfgm2")


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with TestClient(make_app(db_url)) as c:
        yield c


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)

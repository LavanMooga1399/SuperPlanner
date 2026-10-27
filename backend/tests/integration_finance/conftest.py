"""F4 finance integration setup: a live in-process app (create_app) on a fresh PostgreSQL database.

Puts `backend/`, this folder and `tests/integration` (for the scheduling `independent_check`, reused
read-only) on sys.path."""

from __future__ import annotations

import sys
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE), str(_HERE.parent / "integration")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=".*httpx2.*")

from fastapi.testclient import TestClient  # noqa: E402

from finint_helpers import Fin, make_app  # noqa: E402


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("finint")


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with TestClient(make_app(db_url)) as c:
        yield c


@pytest.fixture
def fin(client: TestClient) -> Fin:
    return Fin(client)


@pytest.fixture(scope="module")
def shared_fin(db_url_factory_module) -> Iterator[Fin]:
    """One app per module for the expensive sweeps (templates, random plans)."""
    with TestClient(make_app(db_url_factory_module("shared"))) as c:
        yield Fin(c)

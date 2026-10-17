"""Intake test setup (PHASE2 2.16): `backend/` and this folder on sys.path; every app gets its own DB.

No test touches the network: AI is disabled explicitly or given a fake `client_factory`.
"""

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

from intake_helpers import CTX, make_app  # noqa: E402


@pytest.fixture
def ctx():
    return CTX


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'intake.db'}"


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with TestClient(make_app(db_url)) as c:
        yield c

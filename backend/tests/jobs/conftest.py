"""Q2 job-queue tests (PHASE2B 2; plan Q2-1..Q2-15)."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=".*httpx2.*")


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("jobs")

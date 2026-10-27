"""Q3 accounts tests (PHASE2B 4; plan Q3-1..Q3-11)."""

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
    return db_url_factory("auth")

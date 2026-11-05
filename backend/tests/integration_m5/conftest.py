"""M5 integration tests (M5-DESIGN 13 T-I*): accounts-mode apps on their own databases."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE), str(_HERE.parent / "api_mfg_m2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("intm5")

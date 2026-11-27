"""M9 API tests (M9-DESIGN 12): network, S&OP and trade over an organisation of plants, a DC and the network
workspace. Reuses the M2 API helpers; every test gets its own database."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE.parent / "api_mfg_m2"), str(_HERE.parent / "api_mfg_m7"), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=".*httpx2.*")


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("m9")

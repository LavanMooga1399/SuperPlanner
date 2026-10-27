"""Q5 operations tests (PHASE2B 5.2-5.6, 6; plan Q5-1..Q5-9)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("ops")

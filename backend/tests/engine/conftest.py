"""WP1 engine test setup: put `backend/` and this folder on sys.path (works before pyproject exists)."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parents[1]
for p in (str(_BACKEND), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: long-running engine checks")

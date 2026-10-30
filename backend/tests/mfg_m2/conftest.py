"""WP-A M2 pure tests (M2-DESIGN 17.2): no database."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

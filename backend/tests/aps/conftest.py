"""WP-S pure APS tests (M3-DESIGN 15.1)."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE), str(_HERE.parent / "mfg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

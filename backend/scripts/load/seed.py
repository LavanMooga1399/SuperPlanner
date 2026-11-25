"""Seed the BD-like load-test data (M8-DESIGN 14.2) - a thin wrapper of `manage.py load-seed`.

    DATABASE_URL=... python scripts/load/seed.py [--profile bd|small] [--email E] [--seed N]
"""

from __future__ import annotations

import sys

from superplanner import manage

if __name__ == "__main__":
    sys.exit(manage.main(["load-seed", *sys.argv[1:]]))

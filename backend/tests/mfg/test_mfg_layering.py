"""A1-5: `superplanner.mfg` imports neither FastAPI, SQLAlchemy, `superplanner.api` nor `superplanner.engine`."""

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def test_pure_package_layering():
    code = ("import sys, json; import superplanner.mfg, superplanner.mfg.samples; "
            "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in ('fastapi', 'sqlalchemy') "
            "or m.startswith(('superplanner.api', 'superplanner.engine')))))")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=BACKEND, timeout=120,
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND)})
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == []

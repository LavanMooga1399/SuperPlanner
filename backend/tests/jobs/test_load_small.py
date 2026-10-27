"""Small load run of `scripts/load_queue.py` (PHASE2B 6, Q5-6): 10 mixed runs, 2 worker processes, PostgreSQL only.

Same checks as the full G8 run via the script's `run(argv) -> Report` (exactly-once, events, results, replays)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location("load_queue", BACKEND / "scripts" / "load_queue.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["load_queue"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.pg_load
def test_load_small(db_url_factory, tmp_path):
    lq = _load_script()
    url = db_url_factory("load")
    out = tmp_path / "report.json"
    report = lq.run(["--runs", "10", "--workers", "2", "--database-url", url, "--json", str(out),
                     "--log-dir", str(tmp_path / "logs")])
    assert report.ok, report.text()
    assert report.runs == 10 and report.solver_runs == 5 and report.finance_runs == 5
    assert report.duplicates == 0 and report.lost == 0 and report.requeues == 0
    assert report.replays_sent >= 1 and report.replays_ok == report.replays_sent
    assert sum(report.jobs_per_worker.values()) == 10
    assert all(w.startswith("load-w") for w in report.jobs_per_worker)
    assert report.throughput_runs_per_min > 0
    data = json.loads(out.read_text())
    assert data["ok"] is True and data["lost"] == 0 and data["duplicates"] == 0


def test_load_script_refuses_a_non_postgres_url():
    lq = _load_script()
    with pytest.raises(lq.LoadError):
        lq.run(["--runs", "2", "--database-url", "mysql://u@127.0.0.1/x"])
    assert lq.main(["--runs", "2", "--database-url", "mysql://u@127.0.0.1/x"]) == 2


def test_percentile():
    lq = _load_script()
    assert lq.percentile([], 0.5) == 0.0
    assert lq.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert lq.percentile([5.0], 0.95) == 5.0

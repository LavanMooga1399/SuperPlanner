"""F4 (acceptance 4.8): compliance sweep. The F.21 denylist (shared list in tests/finance/fin_helpers.py) and the
forbidden-word list are checked on frontend/src/finance/** and on every API response of every template
(templates list, instantiated plan, defaults, results with explanations and fixes, what-if, CSV, planner)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from finint_helpers import API, DISCLAIMER_START, FIN, TEMPLATE_IDS, all_text, forbidden_hits

ROOT = Path(__file__).resolve().parents[3]
UI = ROOT / "frontend" / "src" / "finance"

_spec = importlib.util.spec_from_file_location("fin_helpers_denylist", ROOT / "backend" / "tests" / "finance" /
                                               "fin_helpers.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
denylist_hits = _mod.denylist_hits


def _ui_strings(text: str) -> str:
    """String literals and JSX text of a TS/TSX file (identifiers and imports are not user-facing)."""
    out = re.findall(r'"((?:[^"\\\n]|\\.)*)"', text) + re.findall(r"'((?:[^'\\\n]|\\.)*)'", text)
    out += re.findall(r"`((?:[^`\\]|\\.)*)`", text, re.S)
    out += re.findall(r">([^<>{}]+)<", text)
    return "\n".join(out)


def test_frontend_finance_has_no_product_names_or_forbidden_wording():
    files = [p for p in UI.rglob("*") if p.suffix in (".ts", ".tsx", ".css")]
    assert len(files) > 20
    hits = []
    for p in files:
        text = p.read_text()
        for w in denylist_hits(text):
            hits.append(f"{p.relative_to(ROOT)}: product/issuer name {w!r}")
        if p.suffix != ".css":
            for w in forbidden_hits(_ui_strings(text)):
                hits.append(f"{p.relative_to(ROOT)}: forbidden wording {w!r}")
    assert hits == [], "\n".join(hits)


def test_frontend_labels_probabilities_and_assumptions():
    text = "\n".join(p.read_text() for p in UI.rglob("*.tsx"))
    assert "estimated chance" in text.lower()
    assert "Your assumption" in text and "Calculated" in text
    assert "SuperPlanner Finance is an educational planning tool." in "\n".join(
        p.read_text() for p in UI.rglob("*.ts*"))


def _scan(label: str, payload) -> list[str]:
    text = payload if isinstance(payload, str) else all_text(payload)
    return [f"{label}: {w!r}" for w in denylist_hits(text)] + [f"{label}: forbidden {w!r}" for w in forbidden_hits(text)]


@pytest.mark.parametrize("tid", TEMPLATE_IDS)
def test_api_responses_of_every_template_are_compliant(shared_fin, tid):
    c = shared_fin.c
    hits: list[str] = []
    hits += _scan("templates", c.get(f"{FIN}/templates").json())
    d = c.get(f"{FIN}/defaults").json()
    assert d["disclaimer"].startswith(DISCLAIMER_START)
    hits += _scan("defaults", d)
    rec = shared_fin.instantiate(tid)
    hits += _scan("plan", rec)
    pid = rec["id"]
    out = shared_fin.solve(pid, {"time_limit_seconds": 60, "seed": 1, "simulation": {"n_paths": 500},
                                 "compute_fixes": True, "calibration_rounds": 2})
    res = out["result"]
    assert res["disclaimer"].startswith(DISCLAIMER_START)
    hits += _scan("result", {k: v for k, v in res.items() if k != "assumptions_used"})
    hits += _scan("validate", c.post(f"{FIN}/plans/{pid}/validate").json())
    hits += _scan("csv", c.get(f"{FIN}/results/{out['id']}/contributions.csv").text)
    fixes = [f for g in res["explanation"]["goals"].values() for f in g["fixes"]]
    for f in fixes[:2]:
        hits += _scan("fix", f)
        w = shared_fin.solve_what_if(pid, f["what_if"], base_result_id=out["id"])
        hits += _scan("what-if result", w["result"])
    if res["feasibility"] == "feasible" and res["goals"]:
        s = c.post(f"{FIN}/results/{out['id']}/send-to-planner", json={})
        assert s.status_code == 201, s.text
        prob = c.get(f"{API}/problems/{s.json()['problem_id']}").json()
        hits += _scan("planner problem", {k: v for k, v in prob["problem"].items() if k != "resources"})
    assert hits == [], "\n".join(hits)

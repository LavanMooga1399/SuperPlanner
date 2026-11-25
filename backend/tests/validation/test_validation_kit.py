"""Validation kit v1 (M8-DESIGN 10): register parsing, trace matrix from the repository (CSV/HTML, JUnit merge,
high-risk gap -> exit 1), configuration baselines and their diff."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from superplanner import manage
from superplanner.validation import baseline, register, trace

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "api_mfg_m2"))
sys.path.insert(0, str(_HERE.parent / "api_mfg_m8"))


def test_register_parses_and_rejects_bad_rows():
    reqs = register.load()
    ids = {r.id for r in reqs}
    assert {"M8-RATE-05", "M8-STER-02", "M7-ESIG-01", "M8-VAL-01"} <= ids
    with pytest.raises(register.RegisterError):
        register.parse('- {id: X, title: "t", source: "s", risk: huge, assurance: scripted, intended_use: gxp}')
    with pytest.raises(register.RegisterError):
        register.parse('- {id: X, title: "t", source: "s", risk: low, assurance: scripted, intended_use: gxp}\n'
                       '- {id: X, title: "t", source: "s", risk: low, assurance: scripted, intended_use: gxp}')


@pytest.mark.req("M8-VAL-01")
def test_trace_matrix_on_repo_and_high_risk_gap_exit(tmp_path):
    m = trace.build()
    rows = {r["id"]: r for r in m["rows"]}
    assert any("test_validator_detects_mutations" in t for t in rows["M8-RATE-05"]["tests"])
    assert rows["M7-ESIG-01"]["tests"] and not rows["M7-QA-11"]["gap"]
    assert m["high_risk_gaps"] == 0, [g for g in m["gaps"] if g["risk"] == "high"]
    junit = tmp_path / "r.xml"
    junit.write_text('<testsuite><testcase classname="tests.rate.test_rate_engine" '
                     'name="test_validator_detects_mutations"/><testcase classname="tests.rate.test_rate_engine" '
                     'name="test_periodic_cleaning_inserted_and_validator_ok"><failure/></testcase></testsuite>')
    m2 = trace.build(junit=[junit])
    r2 = {r["id"]: r for r in m2["rows"]}
    assert r2["M8-RATE-05"]["last_result"] == "passed" and r2["M8-RATE-04"]["last_result"] == "failed"
    out = io.StringIO()
    assert manage.main(["trace-matrix", "--out", str(tmp_path / "out")], out=out) == 0
    assert (tmp_path / "out" / "trace-matrix.csv").read_text().startswith("id,title")
    assert b"<table>" in (tmp_path / "out" / "trace-matrix.html").read_bytes()
    reg = tmp_path / "reg.yaml"
    reg.write_text(register.DEFAULT_PATH.read_text() +
                   '- {id: ZZ-HIGH-1, title: "Untested", source: "x", risk: high, assurance: scripted, '
                   'intended_use: gxp}\n')
    out = io.StringIO()
    assert manage.main(["trace-matrix", "--register", str(reg)], out=out) == 1
    assert "gap: ZZ-HIGH-1 (high)" in out.getvalue()


def test_baseline_redaction_and_diff():
    c = baseline.redact({"sap": {"password_enc": "x", "username": "u"}, "list": [{"client_secret": "s"}]})
    assert c == {"sap": {"password_enc": "<redacted>", "username": "u"}, "list": [{"client_secret": "<redacted>"}]}
    d = baseline.diff({"a": {"b": 1, "c": 2}}, {"a": {"b": 1, "c": 3, "d": 4}})
    assert d == [{"path": "a.c", "kind": "changed", "a": 2, "b": 3}, {"path": "a.d", "kind": "added", "a": None,
                                                                      "b": 4}]
    assert baseline.digest({"x": 1, "y": 2}) == baseline.digest({"y": 2, "x": 1})


@pytest.mark.req("M8-VAL-02")
def test_baseline_twice_with_policy_change(db_url_factory):
    from fastapi.testclient import TestClient

    from apimfgm2_helpers import Api, make_app
    from superplanner.api.db.ownership import owner_scope
    from superplanner.api.mfg.db_models_m7 import EsigPolicyRow

    url = db_url_factory("val")
    with TestClient(make_app(url)) as c:
        api = Api(c)
        api.get("/esig/policies")
        a = api.post("/validation/baselines", {"label": "Before"})
        assert len(a["sha256"]) == 64 and a["content"]["app"]["migration_head"] == "0011_m8"
        with owner_scope("usr_local"), c.app.state.ctx.db.write() as s:
            pol = s.query(EsigPolicyRow).filter_by(record_type="ncr", action="approve").one()
            pol.auth = "password_totp"
        b = api.post("/validation/baselines", {"label": "After"})
        d = api.get(f"/validation/baselines/{a['id']}/diff/{b['id']}")
        assert d["same"] is False and a["sha256"] != b["sha256"]
        assert [x["path"] for x in d["changes"]] == ["esig_policies.ncr.approve.auth"]
        assert api.get("/validation/baselines")["total"] == 2
        tm = api.get("/validation/trace-matrix")
        assert tm["requirements"] >= 50
        csv = api.req("GET", "/validation/trace-matrix", 200, params={"format": "csv"})
        assert csv.headers["content-type"].startswith("text/csv")

"""Sample `meddev` (fictional single-use medical-device plant): golden hash and counts, canonical round trip, no
health issues, naming rules (fictional, generic names), and the pinned planning outcomes at the default anchor -
MRP: the rush IV-set line (make lead time) and the second prefillable-syringe line (bought-in glass barrels) are
late, the expiring polypropylene lot and the glass-barrel expedites are flagged; APS: the base run suggests overtime
and the Allow run opens it and cuts the lateness."""

from __future__ import annotations

import hashlib
from datetime import date

from superplanner.mfg import bundle_to_dataset, canonical_json, dataset_to_bundle, run_health_check, samples
from superplanner.mfg.aps.engine import schedule
from superplanner.mfg.aps.model import ApsParams
from superplanner.mfg.aps.pure import sample_snapshot
from superplanner.mfg.dataset import mrp_inputs
from superplanner.mfg.mrp import MrpParams, MrpSnapshot, run_mrp

A = date(2026, 11, 2)
GOLDEN = "d14c745c55332c6827827a42d87bbeee62492887f10d810cfec4a1c9d308c209"
COUNTS = {"plant": 1, "items": 54, "skills": 10, "tool_pools": 0, "groups": 11, "lines": 23, "shift_templates": 6,
          "shifts": 9, "shift_assignments": 15, "calendar_exceptions": 5, "operators": 38, "boms": 27,
          "bom_lines": 92, "routings": 27, "operations": 68, "locations": 4, "suppliers": 8, "item_suppliers": 28,
          "stock": 49, "purchase_docs": 9, "purchase_lines": 9, "purchase_schedules": 17, "demand_orders": 8,
          "demand_lines": 21, "work_orders": 3, "wo_components": 17, "operation_line_rates": 0, "setup_matrix": 11,
          "operator_absences": 1}


def test_registered_golden_counts_and_round_trip():
    assert "meddev" in samples.SAMPLES and samples.SAMPLES["meddev"].prefix == "MDV-"
    b = samples.build("meddev")
    assert hashlib.sha256(canonical_json(b)).hexdigest() == GOLDEN
    assert samples.counts("meddev") == COUNTS
    assert dataset_to_bundle(bundle_to_dataset(b)) == b


def test_health_clean_and_naming_rules():
    b = samples.build("meddev")
    r = run_health_check(bundle_to_dataset(b), A, 120)
    assert r.ok and r.by_code == {}
    assert all(row["part_number"].startswith("MDV-") for row in b["items"])
    assert all(str(row.get("attr:mpn", "SYN-")).startswith("SYN-") for row in b["items"])
    assert b["plant"][0]["time_zone"] == "America/Toronto" and b["plant"][0]["currency"] == "CAD"
    assert "Fictional" in samples.SAMPLES["meddev"].description
    names = [r["name"] for r in b["suppliers"]] + [r["customer"] for r in b["demand_orders"]]
    assert all("(fictional)" in n or "internal" in n for n in names)
    # lot control with expiry on resins, tubing, elastomers, labels and lidding; finished goods lot-controlled
    items = {r["part_number"]: r for r in b["items"]}
    for pn in ("MDV-RES-PP", "MDV-RES-PET", "MDV-FEP-20", "MDV-STP-10", "MDV-LBL-UDI", "MDV-TYV-LID", "MDV-IVS-20"):
        assert items[pn]["lot_controlled"] and items[pn]["shelf_life_days"], pn
    assert any(r["lot_code"] == "PP-2609-A" and r["expires_on"] == date(2026, 11, 11) for r in b["stock"])


def test_mrp_pinned_outcomes():
    ds = samples.mrp_state("meddev", A)
    r = run_mrp(MrpSnapshot(as_of=A, dataset=ds, **mrp_inputs(ds, A)), MrpParams())
    late = {(d.order_number, d.line_no): d.late_days for d in r.demand if d.status == "late"}
    assert late == {("DO-MDV-1003", 10): 3, ("DO-MDV-1006", 20): 17}
    pfs = next(d for d in r.demand if (d.order_number, d.line_no) == ("DO-MDV-1006", 20))
    assert pfs.limiting[-1].part_number == "MDV-GLS-1ML" and pfs.limiting[-1].reason == "supply_date"
    codes = {(e.code, e.subject.label) for e in r.exceptions}
    for want in (("MRP_DEMAND_LATE", "DO-MDV-1003/10"), ("MRP_EXPEDITE", "PO-MDV-2002/10/1"),
                 ("MRP_EXPIRING_STOCK", "PP-2609-A"), ("MRP_PAST_DUE_SUPPLY", "PO-MDV-2004/10/1"),
                 ("MRP_WO_LATE", "WO-MDV-0001")):
        assert want in codes, want
    assert 20 <= len(r.planned_orders) <= 60


def test_aps_suggests_overtime_and_allow_cuts_lateness():
    snap = sample_snapshot("meddev", A)
    base = schedule(snap, ApsParams(improve_seconds=0, overtime="suggest"))
    allow = schedule(snap, ApsParams(improve_seconds=0, overtime="allow"))
    assert base.validation.ok and allow.validation.ok
    assert base.summary.late_demand_count >= 1 and base.summary.suggested_overtime_minutes > 0
    assert allow.summary.overtime_minutes > 0
    assert allow.summary.weighted_tardiness < 0.5 * base.summary.weighted_tardiness
    assert allow.summary.max_lateness_minutes < base.summary.max_lateness_minutes
    assert base.summary.setup_minutes > 0                     # mould changeovers through the setup matrix

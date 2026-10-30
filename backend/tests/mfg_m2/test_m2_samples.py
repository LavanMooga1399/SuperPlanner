"""A3 (M2-DESIGN 13): M2 samples are canonical and deterministic, round trip through the bundle, pass Gate 1 with the
M1 intended issue sets, and their MRP run (as_of = anchor, default params) gives the pinned outcomes of 13.2-13.4.
Also the M2 health codes 44-47 (3.11)."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pytest

from superplanner.mfg import bundle_to_dataset, dataset_to_bundle, fingerprint, run_health_check, samples
from superplanner.mfg.dataset import mrp_inputs
from superplanner.mfg.mrp import MrpParams, MrpSnapshot, run_mrp

A = date(2026, 11, 2)


def _run(sid: str, anchor: date = A):
    ds = samples.mrp_state(sid, anchor)
    return ds, run_mrp(MrpSnapshot(as_of=anchor, dataset=ds, **mrp_inputs(ds, anchor)), MrpParams())


@pytest.mark.parametrize("sid", ["small", "medium", "kavach"])
def test_round_trip_and_master_only_build(sid):
    b = samples.build(sid)
    ds = bundle_to_dataset(b)
    assert dataset_to_bundle(ds) == b
    m = samples.build(sid, include_transactions=False)
    assert all(not m[s] for s in ("stock", "purchase_docs", "demand_orders", "work_orders"))
    assert fingerprint(bundle_to_dataset(m)) == fingerprint(ds)          # transactions never in the fingerprint


def test_anchor_shifts_every_transactional_date():
    a = samples.build("small")
    b = samples.build("small", anchor=A + timedelta(days=7))
    da = [r["due_date"] for r in a["demand_lines"]]
    db = [r["due_date"] for r in b["demand_lines"]]
    assert [x + timedelta(days=7) for x in da] == db
    assert a["items"] == b["items"]


def test_small_intended_outcome():
    _ds, r = _run("small")
    by = {(d.order_number, d.line_no): d for d in r.demand}
    assert by[("DO-SM-001", 10)].status == "on_time"
    assert by[("DO-SM-002", 10)].status == "late" and by[("DO-SM-002", 10)].late_days == 6
    codes = {(e.code, e.subject.label) for e in r.exceptions}
    assert ("MRP_EXPEDITE", "PO-SM-0001/10/2") in codes
    pcb = [p for p in r.planned_orders if p.part_number == "SM-BPCB-100"]
    assert pcb and pcb[0].release_status == "release_now"


def test_medium_intended_outcome():
    _ds, r = _run("medium")
    late = sorted((d.order_number, d.line_no) for d in r.demand if d.status == "late")
    assert late == [("DO-MD-002", 10)]
    lim = next(d for d in r.demand if d.order_number == "DO-MD-002").limiting
    assert lim[-1].part_number == "MD-MCU-BLANK"


def test_kavach_pinned_outcomes():
    ds, r = _run("kavach")
    late = {(d.order_number, d.line_no): d.late_days for d in r.demand if d.status == "late"}
    assert late == {("DO-KV-001", 10): 11, ("DO-KV-001", 20): 15, ("DO-KV-002", 10): 54, ("DO-KV-003", 10): 85,
                    ("DO-KV-004", 10): 3}
    proto = next(d for d in r.demand if d.order_number == "DO-KV-004")
    assert proto.limiting[0].part_number == "KV-TPU-1000" and proto.limiting[0].reason == "component"
    assert "working days" in proto.limiting[0].label
    codes = {(e.code, e.subject.label) for e in r.exceptions}
    for want in (("MRP_DEMAND_LATE", "DO-KV-004/10"), ("MRP_EXPEDITE", "PO-KV-0101/10/2"),
                 ("MRP_EXPEDITE", "PO-KV-0104/10/2"), ("MRP_PAST_DUE_SUPPLY", "PO-KV-0102/10/1"),
                 ("MRP_CANCEL", "PO-KV-0105/10/1"), ("MRP_EXPIRING_STOCK", "L-2610"),
                 ("MRP_SHORTAGE", "KV-MOD-GSM"), ("MRP_WO_LATE", "WO-KV-0003")):
        assert want in codes, want
    exp = next(e for e in r.exceptions if e.code == "MRP_EXPIRING_STOCK")
    assert "L-2610" in exp.message and exp.date == A + timedelta(days=18)
    alts = [e for e in r.exceptions if e.code == "MRP_ALTERNATE_USED"]
    assert alts and all("KV-CAP-1210-22U" in e.message for e in alts)
    c = Counter(e.code for e in r.exceptions)
    assert c["MRP_RELEASE_NOW"] > 10 and r.iterations == 2
    tpu = sorted((p.segment.serial_from, p.segment.serial_to, p.qty) for p in r.planned_orders
                 if p.part_number == "KV-TPU-1000")
    assert (121, 125, 5.0) in tpu and (126, 135, 10.0) in tpu
    doc_b = [p for p in r.planned_orders if p.part_number == "KV-DOC-PACK-B"]
    assert doc_b and not [p for p in r.planned_orders if p.part_number == "KV-DOC-PACK"]
    assert len(ds.txn.balances) > 1000 and len(ds.txn.purchase_docs) == 13 and ds.txn.reservations


def test_samples_raise_no_m2_health_codes():
    for sid in ("small", "medium", "kavach"):
        rep = run_health_check(bundle_to_dataset(samples.build(sid)), A, 90)
        assert not set(rep.by_code) & {"MFG_BUY_NO_SUPPLIER", "MFG_PREFERRED_SUPPLIER_INACTIVE",
                                       "MFG_NO_NETTABLE_LOCATION", "MFG_PACK_FRACTIONAL"}


def test_health_44_to_47():
    b = samples.build("small", include_transactions=False)
    b["item_suppliers"] = [r for r in b["item_suppliers"] if r["part_number"] != "SM-CON-01"]
    for r in b["item_suppliers"]:
        if r["part_number"] == "SM-LBL-01":
            r["units_per_purchase_unit"] = 2.5
    for sp in b["suppliers"]:
        if sp["code"] == "SUP-A":
            sp["active"] = False
    for loc in b["locations"]:
        if loc["kind"] == "stores":
            loc["active"] = False
    import superplanner.mfg.bundle as B

    with pytest.raises(B.BundleError):          # the strict bundle refuses fractional packs of count items
        bundle_to_dataset(b)
    for r in b["item_suppliers"]:
        if r["part_number"] == "SM-LBL-01":
            r["units_per_purchase_unit"] = 2.0
    ds = bundle_to_dataset(b)
    lbl = next(r for r in ds.item_suppliers.values() if ds.items[r.item_id].part_number == "SM-LBL-01")
    lbl.units_per_purchase_unit = 2.5                       # stored before the rule
    rep = run_health_check(ds, A, 90)
    by = rep.by_code
    assert by.get("MFG_BUY_NO_SUPPLIER", 0) >= 1 and by.get("MFG_PREFERRED_SUPPLIER_INACTIVE", 0) >= 1
    assert by.get("MFG_NO_NETTABLE_LOCATION") == 1 and by.get("MFG_PACK_FRACTIONAL") == 1
    issue = next(i for i in rep.issues if i.code == "MFG_PREFERRED_SUPPLIER_INACTIVE")
    assert issue.link.startswith("/mfg/purchasing/suppliers/") and "?item_supplier=" in issue.link
    m1 = bundle_to_dataset(samples.build("small", include_transactions=False))
    m1.suppliers.clear()
    m1.item_suppliers.clear()
    m1.locations.clear()
    assert run_health_check(m1, A, 90).by_code == {}     # M1-only data: 44/46 do not apply

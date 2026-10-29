"""E0 hand-off: `superplanner/mfg/mrp/fixtures/example_result.json` is the canonical JSON of a small run covering
make + buy, a staggered PO, a late demand with its limiting path, an alternate, a serial ECO split and the main
exception codes (for WP-B `mrp_store` and WP-C types). Regenerate with `MRP_WRITE_FIXTURE=1 pytest
tests/mrp/test_mrp_fixture.py`."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import superplanner.mfg.mrp as mrp_pkg
from mrp_helpers import D, Plant, Snap
from superplanner.mfg.mrp import MrpTooLarge, canonical_json

FIXTURE = Path(mrp_pkg.__file__).resolve().parent / "fixtures" / "example_result.json"


def example_snap() -> Snap:
    p = Plant(horizon=120)
    p.item("TPU", "make", serialized=True, lead_time_days=3).item("PCB", "make", lead_time_days=2)
    p.item("FPGA", "buy", lead_time_days=60, receiving_days=2, lot_controlled=True)
    p.item("CAP-A", "buy", lead_time_days=56).item("CAP-B", "buy", lead_time_days=56)
    p.item("DOC", "buy", lead_time_days=14).item("DOC-B", "buy", lead_time_days=14)
    p.item("RES", "buy", lead_time_days=30, min_order_qty=5000, order_multiple=5000, safety_stock=100)
    p.bom("TPU", [("PCB", 1), ("DOC", 1)])
    p.serial_bom("TPU", [("PCB", 1), ("DOC-B", 1)], 126, 1_000_000_000)
    p.bom("PCB", [("FPGA", 1), ("CAP-A", 2, {"alt_group": "C1", "alt_priority": 1}),
                  ("CAP-B", 2, {"alt_group": "C1", "alt_priority": 2}), ("RES", 12)])
    ds = p.dataset()
    s = Snap(ds)
    s.stock("FPGA", 4, lot="F-1", expires=D("12-31", 2027))
    s.stock("CAP-B", 100)
    s.stock("RES", 60)
    s.schedule("FPGA", 6, D("11-20"), number="PO-0101")
    s.schedule("FPGA", 6, D("12-20"), confirmed=D("01-05", 2027), number="PO-0101")
    s.schedule("DOC", 20, D("11-10"), number="PO-0105")
    s.dem("TPU", 6, D("11-20"), priority=1, number="DO-004", serials=(97, 102))
    s.dem("TPU", 6, D("12-28"), priority=2, number="DO-002", serials=(121, 126))
    return s


def test_example_fixture_is_current():
    r = example_snap().run()
    got = json.loads(canonical_json(r))
    codes = {e["code"] for e in got["exceptions"]}
    assert {"MRP_DEMAND_LATE", "MRP_ALTERNATE_USED", "MRP_EXPEDITE", "MRP_START_IN_PAST"} <= codes
    assert r.iterations == 2 and any(d.limiting for d in r.demand)
    text = json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("MRP_WRITE_FIXTURE") == "1":
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, "regenerate with MRP_WRITE_FIXTURE=1"


def test_too_large(monkeypatch):
    import superplanner.mfg.mrp.engine as eng
    monkeypatch.setattr(eng, "MRP_MAX_REQUIREMENTS", 3)
    with pytest.raises(MrpTooLarge):
        example_snap().run()

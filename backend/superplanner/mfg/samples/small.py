"""Sample `small` (M1-DESIGN 10.2): "SM-100 Sensor interface board", 10 items, zero health issues."""

from __future__ import annotations

from datetime import date

from ..bundle import MfgBundle
from .common import DESC_FICTIONAL, EVE, EXT, REG, Builder, line, op

ID = "small"
NAME = "SM-100 Sensor interface board"
DESCRIPTION = f"{DESC_FICTIONAL} One PCB assembly with a four-stage routing (~10 parts)."


def build() -> MfgBundle:
    b = Builder()
    b.plant("Sample plant (small)")
    syn = {"manufacturer": "Synthetic"}
    b.item("SM-100", "make", "Sensor interface board assembly", family="PCBA", revision="A", serialized=False)
    b.item("SM-BPCB-100", "buy", "Bare PCB, sensor interface board", lead_time_days=21, min_order_qty=50,
           attributes={**syn, "mpn": "SYN-PCB-100"})
    b.item("SM-RES-10K", "buy", "Resistor 10k 0603 1%", lead_time_days=28, min_order_qty=5000, order_multiple=5000,
           attributes={**syn, "mpn": "SYN-R0603-10K"})
    b.item("SM-RES-1K", "buy", "Resistor 1k 0603 1%", lead_time_days=28, min_order_qty=5000, order_multiple=5000,
           attributes={**syn, "mpn": "SYN-R0603-1K"})
    b.item("SM-CAP-100N", "buy", "Capacitor 100n 0603 X7R", lead_time_days=28, min_order_qty=5000,
           order_multiple=5000, attributes={**syn, "mpn": "SYN-C0603-100N"})
    b.item("SM-CAP-10U", "buy", "Capacitor 10u 0805 X5R", lead_time_days=35, min_order_qty=4000, order_multiple=4000,
           attributes={**syn, "mpn": "SYN-C0805-10U"})
    b.item("SM-MCU-01", "buy", "Microcontroller, 32-bit, QFN48", lead_time_days=84, handling_class="MSL3",
           handling_note="Bake 24 h at 125 C if floor life is exceeded.", shelf_life_days=365,
           attributes={**syn, "mpn": "SYN-MCU-32Q48"})
    b.item("SM-CON-01", "buy", "Connector, 8-pin, through-hole", lead_time_days=42,
           attributes={**syn, "mpn": "SYN-CON-TH8"})
    b.item("SM-COAT-01", "buy", "Conformal coating, acrylic", uom="L", lead_time_days=14, shelf_life_days=365)
    b.item("SM-LBL-01", "buy", "Serial number label", lead_time_days=7)
    b.bom("SM-100", [
        line(10, "SM-BPCB-100", 1),
        line(20, "SM-RES-10K", 4, ref_designators="R1-R4"),
        line(30, "SM-RES-1K", 2, ref_designators="R5-R6", scrap_pct=1),
        line(40, "SM-CAP-100N", 6, ref_designators="C1-C6", scrap_pct=1),
        line(50, "SM-CAP-10U", 2, ref_designators="C7-C8"),
        line(60, "SM-MCU-01", 1, ref_designators="U1"),
        line(70, "SM-CON-01", 1, ref_designators="J1", operation_seq=30),
        line(80, "SM-COAT-01", 2, uom="ML", operation_seq=30),
        line(90, "SM-LBL-01", 1, operation_seq=40),
    ])
    for code, name in (("SMT-OP", "SMT operator"), ("TEST", "Test technician")):
        b.skill(code, name)
    b.tool("SM-STN-T", "Stencil SM-100 top", 1, kind="stencil")
    b.tool("SM-JIG-FCT", "Functional test jig SM-100", 1, kind="jig")
    b.routing("SM-100", [
        op(10, "SMT top", "SMT", setup_minutes=30, run_minutes=1.0, run_per="panel", units_per_panel=4,
           skill_code="SMT-OP", tools=["SM-STN-T:1"], move_minutes=5),
        op(20, "AOI", "AOI", setup_minutes=10, run_minutes=0.5, skill_code="SMT-OP", queue_minutes=10),
        op(30, "THT and coating", "THT", setup_minutes=15, run_minutes=3.0),
        op(40, "Functional test", "FCT", setup_minutes=20, run_minutes=4.0, skill_code="TEST",
           tools=["SM-JIG-FCT:1"], inspection_gate=True, yield_pct=98),
    ])
    for g, ln, kind in (("SMT", "SMT-1", "machine"), ("AOI", "AOI-1", "machine"), ("THT", "THT-1", "bench"),
                        ("FCT", "FCT-1", "test")):
        b.group(g, {"SMT": "Surface mount", "AOI": "Optical inspection", "THT": "Through-hole assembly",
                    "FCT": "Functional test"}[g], kind=kind)
        b.line(ln, g, f"{g} line 1")
    b.template("REG", "Regular day shift (Mon-Sat)", REG)
    b.template("EVE", "Evening overtime (Mon-Sat)", EVE)
    b.template("EXT", "Extended hours 09:00-22:00 (Mon-Sat)", EXT)
    for g in ("SMT", "AOI", "THT", "FCT"):
        b.assign("REG", "group", g)
    for g in ("THT", "FCT"):
        b.assign("EVE", "group", g, kind="optional", cost_per_hour=300.0, max_hours_per_week=12.0)
    b.exception("plant", None, "holiday", date(2026, 12, 25), date(2026, 12, 25), "Plant holiday")
    b.operator("SM-OP-1", "Operator 1", ["SMT-OP"], "REG", home="SMT")
    b.operator("SM-OP-2", "Operator 2", ["TEST"], "EXT", home="FCT")
    b.operator("SM-OP-3", "Operator 3", ["SMT-OP", "TEST"], "REG", home="AOI")
    return b.canonical()

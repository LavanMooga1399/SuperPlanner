"""Sample `medium` (M1-DESIGN 10.3): "MD-200 Industrial I/O controller", ~200 parts, 4 levels.

Intended health content: `MFG_LONG_LEAD_TIME` (info, the 210-day MCU) only. Also shows an alternate group on
MD-PCB-PWR, an alternate routing on MD-PCB-IO and a draft BOM v2 of MD-PCB-MAIN.
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any

from ..bundle import MfgBundle
from .common import (DESC_FICTIONAL, EVE, REG, THREE_SHIFT, Builder, Designators, Library, Weighted,
                     fill_components, line, op)

ID = "medium"
NAME = "MD-200 Industrial I/O controller"
DESCRIPTION = f"{DESC_FICTIONAL} Controller with three PCBs, harnesses and an enclosure (~200 parts, 4 levels)."
SEED = 20261102


def _pcb_routing(b: Builder, rng: random.Random, pn: str, board: str, *, code: str = "STD", priority: int = 1,
                 wave: bool = False) -> None:
    ops = [
        op(10, "SMT top", "SMT", setup_minutes=40, run_minutes=rng.choice([1.2, 1.6, 2.0]), run_per="panel",
           units_per_panel=rng.choice([2, 4]), skill_code="SMT-OP", tools=[f"MD-STN-{board}-T:1"], move_minutes=5),
        op(20, "SMT bottom", "SMT", setup_minutes=40, run_minutes=rng.choice([0.8, 1.0, 1.2]), run_per="panel",
           units_per_panel=2, skill_code="SMT-OP", tools=[f"MD-STN-{board}-B:1"], move_minutes=5),
        op(30, "AOI", "AOI", setup_minutes=10, run_minutes=rng.choice([0.8, 1.0, 1.5]), queue_minutes=15),
        op(40, "Wave solder" if wave else "Selective solder", "THT", setup_minutes=40 if wave else 20,
           run_minutes=1.5 if wave else rng.choice([3.0, 4.0, 5.0]), skill_code="THT-SOLDER"),
        op(50, "Conformal coat", "COAT", setup_minutes=15, run_minutes=rng.choice([2.0, 3.0]), skill_code="COATING"),
        op(60, "Cure", "CURE", run_minutes=60, run_per="batch", units_per_batch=20, labor="unattended", crew_size=0,
           interruptible=False, wait_minutes=30),
        op(70, "Functional test", "FCT", setup_minutes=15, run_minutes=rng.choice([6.0, 8.0, 10.0]),
           skill_code="TEST-TECH", tools=[f"MD-FCT-{board}:1"], inspection_gate=True, yield_pct=98),
    ]
    b.routing(pn, ops, code=code, priority=priority)


def build() -> MfgBundle:
    rng = random.Random(SEED)
    b = Builder()
    b.plant("Sample plant (medium)")
    lib = Library(b, rng, "MD-")
    popular = Weighted([("resistor", ("0603", "10K")), ("resistor", ("0603", "4K7")), ("capacitor", ("0603", "100N")),
                        ("capacitor", ("0805", "10U")), ("resistor", ("0603", "1K"))], [5, 3, 6, 3, 2])

    # make items and structure
    b.item("MD-200", "make", "Industrial I/O controller, complete", family="FINAL", revision="B", serialized=True)
    b.item("MD-CTL", "make", "Controller assembly", family="SUBASSY", serialized=True)
    b.item("MD-ENC", "make", "Enclosure assembly", family="MECH")
    b.item("MD-HAR-1", "make", "Internal harness, power", family="HARNESS")
    b.item("MD-HAR-2", "make", "Internal harness, I/O", family="HARNESS")
    b.item("MD-KIT-HW", "phantom", "Hardware kit")
    for pcb, desc in (("MAIN", "Main controller board"), ("IO", "I/O board"), ("PWR", "Power board")):
        b.item(f"MD-PCB-{pcb}", "make", desc, family="PCBA", serialized=True)
    b.item("MD-PRG-MCU", "make", "Programmed MCU", family="PROG")
    coat = lib.get("MD-COAT-01", "Conformal coating, acrylic", uom="L", lead_time_days=14, shelf_life_days=365)
    blank = lib.get("MD-MCU-BLANK", "Microcontroller, blank, LQFP100", lead_time_days=210, handling_class="MSL3",
                    handling_note="Long-lead part.")

    # PCBs
    sizes = {"MAIN": 70, "IO": 45, "PWR": 30}
    main_lines: list[dict[str, Any]] = []
    for pcb, n in sizes.items():
        des = Designators()
        used: set[str] = set()
        bare = lib.get(f"MD-BPCB-{pcb}", f"Bare PCB, {pcb.lower()} board", lead_time_days=28)
        lines = [line(10, bare, 1), line(20, coat, 3, uom="ML", operation_seq=50)]
        fixed = [line(30, lib.capacitor("0603", "100N"), 8, ref_designators=des.next("C", 8), scrap_pct=1.0)]
        used.update({bare, coat, fixed[0]["child_part_number"]})
        extra = n - len(lines) - len(fixed)
        if pcb == "PWR":
            extra -= 2
        comps = fill_components(lib, rng, des, used, extra, popular=popular, popular_share=0.12, tht_seq=40)
        lines += fixed
        fn = 10 * (len(lines) + 1)
        for c in comps:
            lines.append(line(fn, c["child"], c["qty"], ref_designators=c["ref_designators"],
                              **{k: c[k] for k in ("operation_seq", "scrap_pct") if k in c}))
            fn += 10
        if pcb == "PWR":   # connector A/B alternates at one position
            a = lib.get("MD-CON-PWR-A", "Power connector 4-pin, source A", lead_time_days=56)
            bb = lib.get("MD-CON-PWR-B", "Power connector 4-pin, source B", lead_time_days=56)
            ref = des.next("J", 1)
            lines.append(line(fn, a, 1, ref_designators=ref, alt_group=str(fn), alt_priority=1, operation_seq=40))
            lines.append(line(fn, bb, 1, ref_designators=ref, alt_group=str(fn), alt_priority=2, operation_seq=40))
        b.bom(f"MD-PCB-{pcb}", lines)
        if pcb == "MAIN":
            main_lines = lines
        b.tool(f"MD-STN-{pcb}-T", f"Stencil {pcb} top", 1, kind="stencil")
        b.tool(f"MD-STN-{pcb}-B", f"Stencil {pcb} bottom", 1, kind="stencil")
        b.tool(f"MD-FCT-{pcb}", f"Functional test jig {pcb}", 1, kind="jig")
        _pcb_routing(b, rng, f"MD-PCB-{pcb}", pcb)
    _pcb_routing(b, rng, "MD-PCB-IO", "IO", code="WAVE", priority=2, wave=True)
    b.bom("MD-PCB-MAIN", main_lines, version=2, status="draft", effective_from=None,
          note="Engineering change in preparation (copy of v1).")

    b.bom("MD-PRG-MCU", [line(10, blank, 1)])
    b.tool("MD-PGA-LQFP", "Programming adapter LQFP100", 2, kind="adapter")
    b.routing("MD-PRG-MCU", [op(10, "Program", "PROG", setup_minutes=15, run_minutes=1.5, skill_code="PROG-OP",
                                tools=["MD-PGA-LQFP:1"])])

    # harnesses
    for h in ("MD-HAR-1", "MD-HAR-2"):
        lines = []
        fn = 10
        for awg, color in (("18", "RED"), ("18", "BLK"), ("22", "WHT"), ("22", "BLU")):
            w = lib.get(f"MD-WIR-{awg}-{color}", f"Wire {awg} AWG {color.lower()}", uom="M", lead_time_days=14,
                        min_order_qty=100)
            lines.append(line(fn, w, rng.randrange(400, 1600, 50), uom="MM"))
            fn += 10
        for part, desc, q in ((f"MD-TRM-PIN-{h[-1]}", "Crimp pin", rng.randrange(8, 25)),
                              (f"MD-HSG-{h[-1]}", "Connector housing", 2), ("MD-BSH-1", "Backshell", 1),
                              ("MD-TIE-150", "Cable tie 150 mm", 6), ("MD-LBL-HAR", "Harness label", 2)):
            lines.append(line(fn, lib.get(part, desc, lead_time_days=28), q))
            fn += 10
        lines.append(line(fn, lib.get("MD-HSK-6", "Heat shrink 6 mm", uom="M", lead_time_days=14), 200, uom="MM"))
        b.bom(h, lines)
        tool = f"MD-HTA-{h[-1]}"
        b.tool(tool, f"Harness test adapter {h}", 1, kind="adapter")
        b.routing(h, [op(10, "Assemble harness", "HAR-ASSY", setup_minutes=20, run_minutes=rng.choice([30, 45]),
                         skill_code="HARNESS", transfer_batch=5),
                      op(20, "Continuity test", "TEST", setup_minutes=5, run_minutes=3, skill_code="TEST-TECH",
                         tools=[f"{tool}:1"], inspection_gate=True, yield_pct=99)])

    # mechanics, kit, controller, top
    screws = [lib.get(f"MD-SCR-M{d}x{ln}", f"Screw M{d} x {ln} mm", lead_time_days=21) for d, ln in
              (("3", "6"), ("3", "8"), ("4", "10"), ("4", "12"))]
    b.bom("MD-ENC", [line(10, lib.get("MD-SHT-AL-2", "Aluminium sheet blank 2 mm", lead_time_days=35), 1),
                     line(20, lib.get("MD-PNL-FRONT", "Front panel, printed", lead_time_days=42), 1),
                     line(30, lib.get("MD-GSK-01", "Gasket, enclosure", lead_time_days=35), 1),
                     line(40, screws[2], 8), line(50, lib.get("MD-STD-M3", "Standoff M3 x 10", lead_time_days=21), 4)])
    b.bom("MD-KIT-HW", [line(10 * (i + 1), s, 4 + 2 * i) for i, s in enumerate(screws)] +
          [line(50, lib.get("MD-WSH-M3", "Washer M3", lead_time_days=21), 8),
           line(60, lib.get("MD-NUT-M4", "Nut M4", lead_time_days=21), 8)])
    b.bom("MD-CTL", [line(10, "MD-PCB-MAIN", 1), line(20, "MD-PCB-IO", 1), line(30, "MD-PCB-PWR", 1),
                     line(35, "MD-PRG-MCU", 1),
                     line(40, lib.get("MD-BPL-FRAME", "Board carrier frame", lead_time_days=35), 1),
                     line(50, screws[0], 12)])
    b.bom("MD-200", [line(10, "MD-CTL", 1), line(20, "MD-ENC", 1), line(30, "MD-HAR-1", 1), line(40, "MD-HAR-2", 1),
                     line(50, "MD-KIT-HW", 1), line(60, lib.get("MD-LBL-RATING", "Rating label", lead_time_days=14), 1),
                     line(70, lib.get("MD-DOC-MAN", "User manual, printed", lead_time_days=14), 1)])
    b.routing("MD-ENC", [op(10, "Mechanical assembly", "ASSY", setup_minutes=10, run_minutes=25),
                         op(20, "Inspection", "ASSY", run_minutes=5, inspection_gate=True)])
    b.routing("MD-CTL", [op(10, "Controller assembly", "ASSY", setup_minutes=15, run_minutes=40),
                         op(20, "Controller test", "TEST", setup_minutes=10, run_minutes=20, skill_code="TEST-TECH",
                            inspection_gate=True, yield_pct=99)])
    b.routing("MD-200", [op(10, "Final assembly", "ASSY", setup_minutes=15, run_minutes=60),
                         op(20, "Final test", "TEST", setup_minutes=10, run_minutes=45, skill_code="TEST-TECH",
                            inspection_gate=True, yield_pct=99),
                         op(30, "Pack", "ASSY", run_minutes=10)])

    # plant
    for code, name, kind, lines in (
            ("SMT", "Surface mount", "machine", [("SMT-1", 1.0), ("SMT-2", 0.8)]),
            ("AOI", "Optical inspection", "machine", [("AOI-1", 1.0)]),
            ("THT", "Through-hole soldering", "bench", [("THT-1", 1.0), ("THT-2", 1.0)]),
            ("COAT", "Conformal coating", "machine", [("COAT-1", 1.0)]),
            ("CURE", "Curing oven", "oven", [("OVEN-1", 1.0)]),
            ("FCT", "Functional test", "test", [("FCT-1", 1.0), ("FCT-2", 1.0)]),
            ("PROG", "Device programming", "bench", [("PROG-1", 1.0)]),
            ("HAR-ASSY", "Harness assembly", "bench", [("HB-1", 1.0), ("HB-2", 1.0)]),
            ("ASSY", "Mechanical and final assembly", "bench", [("ASSY-1", 1.0)]),
            ("TEST", "System test", "test", [("TEST-1", 1.0)])):
        b.group(code, name, kind=kind)
        for lc, speed in lines:
            b.line(lc, code, f"{name} {lc}", speed_factor=speed, parallel_capacity=4 if code == "CURE" else 1)
    b.template("REG", "Regular day shift (Mon-Sat)", REG)
    b.template("EVE", "Evening overtime (Mon-Sat)", EVE)
    b.template("3SHIFT", "24 hours, three shifts (Mon-Sat)", THREE_SHIFT)
    b.assign("3SHIFT", "group", "SMT")
    for g in ("AOI", "THT", "COAT", "CURE", "FCT", "PROG", "HAR-ASSY", "ASSY", "TEST"):
        b.assign("REG", "group", g)
    b.assign("EVE", "group", "FCT", kind="optional", cost_per_hour=450.0, max_hours_per_week=12.0)
    for d in (date(2026, 11, 9), date(2026, 12, 25)):
        b.exception("plant", None, "holiday", d, d, "Plant holiday")
    for code, name in (("SMT-OP", "SMT operator"), ("THT-SOLDER", "Through-hole soldering"),
                       ("COATING", "Conformal coating"), ("TEST-TECH", "Test technician"),
                       ("PROG-OP", "Programming"), ("HARNESS", "Harness assembly")):
        b.skill(code, name)
    crew = [(["SMT-OP"], "3SHIFT", ["A"], "SMT"), (["SMT-OP"], "3SHIFT", ["B"], "SMT"),
            (["SMT-OP"], "3SHIFT", ["C"], "SMT"), (["THT-SOLDER"], "REG", [], "THT"),
            (["THT-SOLDER", "COATING"], "REG", [], "THT"), (["COATING"], "REG", [], "COAT"),
            (["TEST-TECH"], "REG", [], "FCT"), (["TEST-TECH"], "REG", [], "TEST"), (["TEST-TECH"], "EVE", [], "FCT"),
            (["PROG-OP", "TEST-TECH"], "REG", [], "PROG"), (["HARNESS"], "REG", [], "HAR-ASSY"),
            (["HARNESS"], "REG", [], "HAR-ASSY")]
    for i, (skills, tpl, names, home) in enumerate(crew, 1):
        b.operator(f"MD-OP-{i:02d}", f"Operator {i:02d}", skills, tpl, names, home=home)
    return b.canonical()

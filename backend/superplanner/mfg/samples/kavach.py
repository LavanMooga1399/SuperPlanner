"""Sample `kavach` (M1-DESIGN 10.4): "KV-TPU-1000 Loco train-protection unit (fictional)", ~2,400 BOM lines,
5 levels (0..4), 20 work-center groups.

Fictional sample data. Structure inspired by a loco-mounted train-protection unit; not real HBL or Kavach data.
Intended health content (asserted exactly by the tests): `MFG_LONG_LEAD_TIME` (infos: FPGAs/processors and the
radio module), `MFG_SKILL_NOT_ON_SHIFT` (one warning: skill COATING on line COAT-1, its EVE overtime has no
operator) and `MFG_DUPLICATE_COMPONENT` (one info: the backplane uses the same press-fit connector twice).
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..bundle import MfgBundle
from .common import (EVE, EXT, H24X7, REG, SUN, THREE_SHIFT, Builder, Designators, Library, Weighted,
                     fill_components, line, op)

ID = "kavach"
NAME = "KV-TPU-1000 Loco train-protection unit (fictional)"
DESCRIPTION = ("Fictional sample data. Structure inspired by a loco-mounted train-protection unit; not real HBL or "
               "Kavach data. ~2,400 BOM lines, 5 levels, 20 stages.")
SEED = 1000
IST = timezone(timedelta(hours=5, minutes=30))

# board: (description, family, component lines, double-sided, programmed ICs, long-lead parts)
BOARDS: dict[str, tuple[str, str, int, bool, list[str], list[tuple[str, str, int]]]] = {
    "CPU": ("Vital CPU board", "PCBA-HDI", 280, True, ["CPU-MCU", "CPU-CFG"],
            [("KV-IC-PROC-V1", "Safety processor, dual-core lockstep", 266),
             ("KV-IC-FPGA-V1", "FPGA, 85k LE, BGA484", 308)]),
    "VIO": ("Vital I/O board", "PCBA-HDI", 220, True, ["VIO-CFG"], [("KV-IC-FPGA-V2", "FPGA, 25k LE, BGA256", 224)]),
    "COM": ("Comms controller board", "PCBA-STD", 180, True, ["COM-MCU"], []),
    "EVR": ("Event recorder board", "PCBA-STD", 150, True, ["EVR-MCU"], []),
    "BPL": ("VCU backplane", "PCBA-STD", 60, True, [], []),
    "RMD": ("Radio modem board", "PCBA-HDI", 240, True, ["RMD-MCU"], [("KV-IC-PROC-R1", "Baseband processor", 364)]),
    "RFE": ("RF front-end board", "PCBA-STD", 120, True, [], []),
    "GNS": ("GNSS/GSM interface board", "PCBA-STD", 90, True, ["GNS-MCU"], []),
    "DSC": ("Display controller board", "PCBA-HDI", 200, True, ["DSC-MCU"],
            [("KV-IC-PROC-D1", "Application processor, graphics", 210)]),
    "KPD": ("Keypad board", "PCBA-STD", 50, False, ["KPD-MCU"], []),
    "RFI": ("RFID interface board", "PCBA-STD", 160, True, ["RFI-MCU"], [("KV-IC-FPGA-R1", "FPGA, 12k LE", 238)]),
    "DCC": ("DC-DC converter board", "PCBA-STD", 110, True, ["DCC-MCU"], []),
    "FLT": ("Input filter board", "PCBA-STD", 45, True, [], []),
    "LED": ("Status LED board", "PCBA-STD", 25, False, [], []),
}
HARNESSES: dict[str, tuple[str, int]] = {
    "L01": ("Loco harness, speed sensor", 22), "L02": ("Loco harness, brake interface", 30),
    "L03": ("Loco harness, cab radio", 18), "L04": ("Loco harness, power input", 14),
    "L05": ("Loco harness, DMI cab 1", 24), "L06": ("Loco harness, DMI cab 2", 24),
    "L07": ("Loco harness, RFID antenna front", 16), "L08": ("Loco harness, RFID antenna rear", 16),
    "VCU1": ("VCU internal harness 1", 14), "VCU2": ("VCU internal harness 2", 12),
    "RF1": ("RCU RF harness", 10), "DMI": ("DMI internal harness", 12), "RIU": ("RIU internal harness", 10),
    "PSU": ("PSU internal harness", 12), "ENC": ("Enclosure internal harness", 14),
    "GND": ("Ground strap set", 8),
}
MECH = {"VCU": "VCU chassis", "RCU": "RCU chassis", "BZL": "DMI bezel", "RIU": "RIU housing",
        "HSK": "PSU heat sink", "PSU": "PSU chassis", "DMI-RR": "DMI rear cover", "ENC-FRM": "Enclosure frame",
        "ENC-DOOR": "Enclosure door"}
TERMINAL_FAMILIES = ["FASTON", "RING", "PINM", "PINF", "FERR"]
PROG_PACKAGES = ["QFP", "BGA", "QFN", "SOIC"]


def build() -> MfgBundle:
    rng = random.Random(SEED)
    b = Builder()
    b.plant("Sample plant (Kavach-like)")
    lib = Library(b, rng, "KV-")
    popular = Weighted([("capacitor", ("0402", "100N")), ("capacitor", ("0402", "1U")), ("capacitor", ("0402", "10N")),
                        ("capacitor", ("0603", "10U")), ("resistor", ("0402", "10K")), ("resistor", ("0402", "4K7")),
                        ("resistor", ("0402", "1K")), ("resistor", ("0402", "100R")), ("resistor", ("0402", "0R")),
                        ("resistor", ("0603", "22R"))], [8, 5, 3, 3, 8, 5, 4, 3, 2, 2])
    _plant(b)
    _resources(b)
    coat = lib.get("KV-COAT-UR", "Conformal coating, urethane", uom="L", lead_time_days=21, shelf_life_days=365,
                   handling_note="Shelf life 12 months; store below 25 C.")
    b.tool("KV-BIH", "Burn-in harness", 8, kind="fixture")
    for pkg in PROG_PACKAGES:
        b.tool(f"KV-PGA-{pkg}", f"Programming adapter {pkg}", 2, kind="adapter")

    # programmed ICs (L3) -> blank ICs (L4)
    for i, prg in enumerate(sorted({p for v in BOARDS.values() for p in v[4]})):
        pn = f"KV-PRG-{prg}"
        b.item(pn, "make", f"Programmed device {prg}", family="PROG")
        blank = lib.get(f"KV-BLK-{prg}", f"Blank device for {prg}", lead_time_days=lib.lead(56, 168),
                        handling_class="MSL3")
        b.bom(pn, [line(10, blank, 1)])
        b.routing(pn, [op(10, "Program and verify", "PROG", setup_minutes=15, run_minutes=1.5, skill_code="PROG-OP",
                          tools=[f"KV-PGA-{PROG_PACKAGES[i % len(PROG_PACKAGES)]}:1"])])

    # PCBs (L2/L3)
    for code, (desc, family, n, double, prgs, longs) in BOARDS.items():
        pn = f"KV-PCB-{code}"
        b.item(pn, "make", desc, family=family, serialized=code not in ("LED", "KPD", "FLT"), revision="B")
        des = Designators()
        used: set[str] = set()
        bare = lib.get(f"KV-BPCB-{code}", f"Bare PCB, {desc.lower()}", lead_time_days=lib.lead(21, 35))
        cap100n = lib.capacitor("0402", "100N")
        lines = [line(10, bare, 1), line(20, coat, rng.randrange(3, 9), uom="ML", operation_seq=80),
                 line(30, cap100n, rng.randrange(8, 41), scrap_pct=1.0)]
        lines[-1]["ref_designators"] = des.next("C", int(lines[-1]["qty_per"]))
        used.update({bare, coat, cap100n})
        fn = 40
        for prg in prgs:
            lines.append(line(fn, f"KV-PRG-{prg}", 1, ref_designators=des.next("U", 1)))
            used.add(f"KV-PRG-{prg}")
            fn += 10
        for lpn, ldesc, lead in longs:
            lib.get(lpn, ldesc, lead_time_days=lead, handling_class="MSL4",
                    handling_note="Floor life 72 h; dry-pack after opening.", shelf_life_days=730)
            lines.append(line(fn, lpn, 1, ref_designators=des.next("U", 1)))
            used.add(lpn)
            fn += 10
        if code == "BPL":       # press-fit backplane; one connector at two positions (intended DUPLICATE_COMPONENT)
            pf = [lib.get(f"KV-CON-PF-{p}", f"Press-fit connector {p}-pin", lead_time_days=lib.lead(42, 84))
                  for p in (24, 32, 48, 64, 72, 96, 110, 120)]
            for p in pf:
                lines.append(line(fn, p, 1, ref_designators=des.next("J", 1)))
                fn += 10
            used.update(pf)
            lines.append(line(fn, pf[5], 1, ref_designators=des.next("J", 1), note="Second slot, same connector."))
            fn += 10
        alt_slots = 2 if code == "DCC" else 0
        extra = round(n * 1.06) - len(lines) - 2 * alt_slots
        for c in fill_components(lib, rng, des, used, extra, popular=popular, tht_seq=50):
            lines.append(line(fn, c["child"], c["qty"], ref_designators=c["ref_designators"],
                              **{k: c[k] for k in ("operation_seq", "scrap_pct") if k in c}))
            fn += 10
        for a in range(alt_slots):   # two complete capacitor alternate groups
            p1 = lib.get(f"KV-CAP-1210-{22 * (a + 1)}U-A", f"Capacitor {22 * (a + 1)}u 1210, source A",
                         lead_time_days=56)
            p2 = lib.get(f"KV-CAP-1210-{22 * (a + 1)}U-B", f"Capacitor {22 * (a + 1)}u 1210, source B",
                         lead_time_days=56)
            ref = des.next("C", 2)
            lines.append(line(fn, p1, 2, ref_designators=ref, alt_group=str(fn), alt_priority=1))
            lines.append(line(fn, p2, 2, ref_designators=ref, alt_group=str(fn), alt_priority=2))
            fn += 10
        b.bom(pn, lines, revision="B")
        _pcb_tools(b, code, double)
        _pcb_routing(b, rng, pn, code, double)
        if code in ("FLT", "BPL"):
            _pcb_routing(b, rng, pn, code, double, wave=True)

    # harnesses (L2)
    wires = [(awg, col) for awg in ("16", "18", "20", "22", "24")
             for col in ("BLK", "RED", "WHT", "BLU", "GRN", "YEL", "ORN", "BRN", "VIO", "GRY")]
    applicators: dict[str, None] = {}
    for code, (desc, n) in HARNESSES.items():
        pn = f"KV-HAR-{code}"
        b.item(pn, "make", desc, family="HARNESS")
        fam = TERMINAL_FAMILIES[len(applicators) % len(TERMINAL_FAMILIES)] if code[0] != "L" else \
            rng.choice(TERMINAL_FAMILIES)
        applicators.setdefault(fam, None)
        lines = []
        used = set()
        fn = 10

        def add(child: str, qty: float, **kw: Any) -> None:
            nonlocal fn
            if child in used:
                return
            used.add(child)
            lines.append(line(fn, child, qty, **kw))
            fn += 10

        n_wires = max(3, n // 3)
        pool = list(wires)
        rng.shuffle(pool)
        for awg, col in pool[:n_wires]:
            add(lib.get(f"KV-WIR-{awg}-{col}", f"Wire {awg} AWG {col.lower()}, railway grade", uom="M",
                        lead_time_days=14, min_order_qty=100), rng.randrange(300, 3000, 50), uom="MM")
        for k in range(1, 4):
            add(lib.get(f"KV-TRM-{fam}-{k}", f"Terminal {fam} size {k}", lead_time_days=lib.lead(28, 56)),
                rng.randrange(4, 30))
        add(lib.get(f"KV-HSK-{rng.choice([3, 6, 9, 12])}", "Heat-shrink tube", uom="M", lead_time_days=14),
            rng.randrange(100, 600, 50), uom="MM")
        while len(lines) < n:
            kind = rng.choice(["HSG", "BSH", "CON", "LBL", "TIE", "GRM", "SLV"])
            if kind == "HSG":
                t = rng.choice(["MATE", "MICRO", "M12", "DTM"])
                p = rng.choice([2, 3, 4, 6, 8, 12])
                add(lib.get(f"KV-HSG-{t}-{p}", f"Housing {t} {p}-way", lead_time_days=lib.lead(42, 84)),
                    rng.choice([1, 2]))
            elif kind == "BSH":
                k = rng.randrange(1, 11)
                add(lib.get(f"KV-BSH-{k:02d}", f"Backshell size {k}", lead_time_days=lib.lead(42, 84)), 1)
            elif kind == "CON":
                add(lib.connector(rng.choice(["DSUB", "M12"])), rng.choice([1, 2]))
            elif kind == "LBL":
                add(lib.get(f"KV-LBL-WIRE-{rng.randrange(1, 5)}", "Wire marker label", lead_time_days=14),
                    rng.randrange(4, 40))
            elif kind == "TIE":
                add(lib.get(f"KV-TIE-{rng.choice([100, 150, 200, 300])}", "Cable tie", lead_time_days=14),
                    rng.randrange(4, 20))
            elif kind == "GRM":
                add(lib.get(f"KV-GRM-{rng.randrange(1, 7)}", "Grommet", lead_time_days=28), rng.choice([1, 2]))
            else:
                add(lib.get(f"KV-SLV-{rng.randrange(1, 7)}", "Braided sleeve", uom="M", lead_time_days=21),
                    rng.randrange(200, 1500, 50), uom="MM")
        b.bom(pn, lines)
        b.tool(f"KV-HTA-{code}", f"Harness test adapter {code}", 1, kind="adapter")
        b.routing(pn, [
            op(10, "Cut and strip", "HAR-CUT", setup_minutes=20, run_minutes=rng.randrange(2, 7),
               skill_code="HARNESS-CRIMP"),
            op(20, "Crimp", "HAR-CRIMP", setup_minutes=15, run_minutes=rng.randrange(3, 11),
               skill_code="HARNESS-CRIMP", tools=[f"KV-APL-{fam}:1"]),
            op(30, "Assemble", "HAR-ASSY", setup_minutes=10, run_minutes=rng.randrange(25, 121, 5),
               skill_code="HARNESS-ASSY", transfer_batch=5),
            op(40, "Continuity test", "HAR-TEST", setup_minutes=5, run_minutes=rng.randrange(4, 13),
               skill_code="HARNESS-TEST", tools=[f"KV-HTA-{code}:1"], inspection_gate=True, yield_pct=99)])
        if code == "L02":   # alternate routing: hand crimping on the assembly benches
            b.routing(pn, [
                op(10, "Cut and strip", "HAR-CUT", setup_minutes=20, run_minutes=4, skill_code="HARNESS-CRIMP"),
                op(20, "Hand crimp", "HAR-ASSY", setup_minutes=5, run_minutes=18, skill_code="HARNESS-ASSY"),
                op(30, "Assemble", "HAR-ASSY", setup_minutes=10, run_minutes=90, skill_code="HARNESS-ASSY",
                   transfer_batch=5),
                op(40, "Continuity test", "HAR-TEST", setup_minutes=5, run_minutes=8, skill_code="HARNESS-TEST",
                   tools=["KV-HTA-L02:1"], inspection_gate=True, yield_pct=99)], code="HAND", priority=2)
    for i, fam in enumerate(applicators):
        b.tool(f"KV-APL-{fam}", f"Crimp applicator {fam}", 1 + i % 2, kind="applicator")

    # hardware and mechanics
    hw_specs = [(f"KV-SCR-M{d}x{ln}", f"Screw M{d} x {ln} mm, stainless")
                for d in ("2.5", "3", "4", "5") for ln in ("6", "8", "10", "12", "16", "20")]
    hw_specs += [("KV-WSH-M3", "Washer M3"), ("KV-WSH-M4", "Washer M4"), ("KV-WSH-M5", "Washer M5"),
                 ("KV-NUT-M3", "Nut M3"), ("KV-NUT-M4", "Nut M4"), ("KV-NUT-M5", "Nut M5"),
                 ("KV-LWS-M3", "Lock washer M3"), ("KV-LWS-M4", "Lock washer M4"),
                 ("KV-STD-M3x10", "Standoff M3 x 10"), ("KV-STD-M3x15", "Standoff M3 x 15"),
                 ("KV-STD-M4x20", "Standoff M4 x 20"), ("KV-CLP-01", "Cable clamp")]

    def hw(spec: tuple[str, str]) -> str:          # created on first use (no orphans)
        return lib.get(spec[0], spec[1], lead_time_days=21)

    hardware = hw_specs
    sheets = [(f"KV-SHT-{m}-{t}", f"Sheet blank {m} {t} mm")
              for m, t in (("AL", "1.5"), ("AL", "2"), ("AL", "3"), ("SS", "1"), ("SS", "1.5"), ("SS", "2"))]
    for code, desc in MECH.items():
        pn = f"KV-MEC-{code}"
        b.item(pn, "make", desc, family="MECH")
        picks = list(hardware)
        rng.shuffle(picks)
        lines = [line(10, hw(rng.choice(sheets)), 1)] + [line(20 + 10 * k, hw(h), rng.randrange(2, 13))
                                                      for k, h in enumerate(picks[:rng.randrange(3, 7)])]
        b.bom(pn, lines)
        b.routing(pn, [op(10, "Mechanical assembly", "MECH", setup_minutes=10, run_minutes=rng.randrange(10, 41)),
                       op(20, "Inspection", "MECH", run_minutes=5, inspection_gate=True)])
    kits = {"T": "Top-level hardware kit", "A": "VCU hardware kit", "R": "RCU hardware kit", "D": "DMI hardware kit",
            "P": "PSU hardware kit"}
    for code, desc in kits.items():
        pn = f"KV-KIT-HW-{code}"
        b.item(pn, "phantom", desc)
        picks = list(hardware)
        rng.shuffle(picks)
        b.bom(pn, [line(10 * (k + 1), hw(h), rng.randrange(4, 25)) for k, h in enumerate(picks[:rng.randrange(5, 9)])])

    def buy(pn: str, desc: str, lead: int, **kw: Any) -> str:
        return lib.get(pn, desc, lead_time_days=lead, **kw)

    labels = [buy("KV-LBL-SER", "Serial number label", 14), buy("KV-LBL-RATING", "Rating plate", 21)]
    subs: dict[str, tuple[str, list[tuple[str, int]]]] = {
        "KV-VCU-2000": ("Vital computer unit", [("KV-PCB-CPU", 3), ("KV-PCB-VIO", 2), ("KV-PCB-COM", 1),
                                                ("KV-PCB-EVR", 1), ("KV-PCB-BPL", 1), ("KV-HAR-VCU1", 1),
                                                ("KV-HAR-VCU2", 1), ("KV-MEC-VCU", 1), ("KV-KIT-HW-A", 1)]),
        "KV-RCU-3000": ("Radio communication unit", [
            ("KV-PCB-RMD", 1), ("KV-PCB-RFE", 1), ("KV-PCB-GNS", 1),
            (buy("KV-MOD-GSM", "Radio module, GSM-R (bought in)", 182, handling_class="ESD"), 1),
            ("KV-HAR-RF1", 1), ("KV-MEC-RCU", 1), ("KV-KIT-HW-R", 1)]),
        "KV-DMI-4000": ("Driver display unit", [
            ("KV-PCB-DSC", 1), ("KV-PCB-KPD", 1), (buy("KV-LCD-104", "10.4 inch TFT panel, sunlight readable", 120), 1),
            ("KV-HAR-DMI", 1), ("KV-MEC-BZL", 1), ("KV-MEC-DMI-RR", 1), ("KV-KIT-HW-D", 1)]),
        "KV-RIU-5000": ("RFID reader interface unit", [("KV-PCB-RFI", 1), ("KV-HAR-RIU", 1), ("KV-MEC-RIU", 1)]),
        "KV-PSU-6000": ("Power supply unit", [("KV-PCB-DCC", 2), ("KV-PCB-FLT", 1), ("KV-MEC-HSK", 1),
                                              ("KV-HAR-PSU", 1), ("KV-MEC-PSU", 1), ("KV-KIT-HW-P", 1)]),
        "KV-CHS-7000": ("Loco cable/harness set", [(f"KV-HAR-L0{i}", 1) for i in range(1, 9)]),
    }
    for pn, (desc, kids) in subs.items():
        b.item(pn, "make", desc, family="SUBASSY", serialized=True, revision="B")
        lines = [line(10 * (k + 1), c, q) for k, (c, q) in enumerate(kids)]
        lines.append(line(10 * (len(kids) + 1), labels[0], 1))
        b.bom(pn, lines, revision="B")
        short = pn.split("-")[1]
        b.tool(f"KV-STJ-{short}", f"Sub-assembly test jig {short}", 1, kind="jig")
        b.routing(pn, [op(10, "Sub-assembly", "SUBASSY", setup_minutes=20, run_minutes=rng.randrange(60, 181, 10),
                          skill_code="ELEC-ASSY"),
                       op(20, "Sub-assembly test", "FINAL-TEST", setup_minutes=15, run_minutes=rng.randrange(30, 91, 5),
                          skill_code="TEST-ENG", tools=[f"KV-STJ-{short}:1"], inspection_gate=True, yield_pct=98)])
    b.item("KV-ENC-8000", "make", "Enclosure / rack assembly", family="MECH", revision="B")
    panels = [buy(f"KV-PNL-{k}", f"Enclosure panel {k}", 42) for k in ("TOP", "BOT", "LEFT", "RIGHT", "REAR")]
    gaskets = [buy(f"KV-GSK-{k}", f"Gasket {k}", 35) for k in ("DOOR", "PANEL", "CABLE")]
    enc_lines = [line(10, "KV-MEC-ENC-FRM", 1), line(20, "KV-MEC-ENC-DOOR", 1), line(30, "KV-PCB-LED", 1),
                 line(40, "KV-HAR-ENC", 1), line(50, "KV-HAR-GND", 1)]
    for k, p in enumerate(panels + gaskets):
        enc_lines.append(line(60 + 10 * k, p, 1 if p in panels else 2))
    enc_lines.append(line(200, hw(hw_specs[8]), 24))
    b.bom("KV-ENC-8000", enc_lines, revision="B")
    b.routing("KV-ENC-8000", [op(10, "Mechanical assembly", "MECH", setup_minutes=20, run_minutes=40),
                              op(20, "Inspection", "MECH", run_minutes=10, inspection_gate=True)])
    b.item("KV-TPU-1000", "make", "Loco TPU unit (fictional)", family="FINAL", serialized=True, revision="B")
    top = [("KV-VCU-2000", 1), ("KV-RCU-3000", 1), ("KV-DMI-4000", 2), ("KV-RIU-5000", 1), ("KV-PSU-6000", 1),
           ("KV-CHS-7000", 1), ("KV-ENC-8000", 1), ("KV-KIT-HW-T", 1),
           (buy("KV-DOC-PACK", "Documentation pack", 14), 1), (labels[0], 1), (labels[1], 1)]
    b.bom("KV-TPU-1000", [line(10 * (k + 1), c, q) for k, (c, q) in enumerate(top)], revision="B")
    b.tool("KV-FTJ-TPU", "Final test station adapter", 2, kind="jig")
    b.routing("KV-TPU-1000", [
        op(10, "Final assembly", "FINAL", setup_minutes=30, run_minutes=240, skill_code="ELEC-ASSY"),
        op(20, "Burn-in", "BURNIN", run_minutes=1440, run_per="batch", units_per_batch=8, labor="unattended",
           crew_size=0, interruptible=False, tools=["KV-BIH:8"], wait_minutes=60),
        op(30, "Final test", "FINAL-TEST", setup_minutes=20, run_minutes=180, skill_code="TEST-ENG",
           tools=["KV-FTJ-TPU:1"], inspection_gate=True, yield_pct=96),
        op(40, "Pack", "FINAL", run_minutes=20, skill_code="ELEC-ASSY")])
    return b.canonical()


def _pcb_tools(b: Builder, code: str, double: bool) -> None:
    b.tool(f"KV-STN-{code}-T", f"Stencil {code} top", 2 if code == "CPU" else 1, kind="stencil")
    if double:
        b.tool(f"KV-STN-{code}-B", f"Stencil {code} bottom", 2 if code == "CPU" else 1, kind="stencil")
    b.tool(f"KV-ICT-{code}", f"ICT fixture {code}", 1, kind="fixture")
    b.tool(f"KV-FCT-{code}", f"FCT jig {code}", 2 if code in ("CPU", "VIO") else 1, kind="jig")


def _pcb_ops(rng: random.Random, code: str, double: bool, wave: bool) -> list[dict[str, Any]]:
    upp = rng.randrange(2, 7)
    ops = [op(10, "SMT top", "SMT", setup_minutes=45, run_minutes=rng.choice([1.0, 1.2, 1.6, 2.0, 2.4]),
              run_per="panel", units_per_panel=upp, skill_code="SMT-OP", tools=[f"KV-STN-{code}-T:1"],
              move_minutes=5),
           op(20, "AOI top", "AOI", setup_minutes=10, run_minutes=rng.choice([0.8, 1.0, 1.2, 1.5]), run_per="panel",
              units_per_panel=upp, skill_code="AOI-OP")]
    if double:
        ops += [op(30, "SMT bottom", "SMT", setup_minutes=45, run_minutes=rng.choice([1.0, 1.2, 1.6, 2.0]),
                   run_per="panel", units_per_panel=upp, skill_code="SMT-OP", tools=[f"KV-STN-{code}-B:1"],
                   move_minutes=5),
                op(40, "AOI bottom", "AOI", setup_minutes=10, run_minutes=rng.choice([0.8, 1.0, 1.2]),
                   run_per="panel", units_per_panel=upp, skill_code="AOI-OP")]
    ops += [op(50, "THT", "THT", setup_minutes=15, run_minutes=rng.randrange(6, 26), skill_code="THT-SOLDER"),
            op(60, "Wave solder" if wave else "Selective solder", "WAVE" if wave else "SEL",
               setup_minutes=30 if wave else 20, run_minutes=1.5 if wave else rng.randrange(2, 6),
               skill_code="SEL-SOLDER"),
            op(70, "Wash", "WASH", setup_minutes=10, run_minutes=30, run_per="batch", units_per_batch=20,
               skill_code="WASH-OP"),
            op(80, "Conformal coat", "COAT", setup_minutes=15, run_minutes=rng.randrange(2, 5), skill_code="COATING"),
            op(90, "Cure", "CURE", run_minutes=120, run_per="batch", units_per_batch=50, labor="unattended",
               crew_size=0, interruptible=False),
            op(100, "ICT", "ICT", setup_minutes=15, run_minutes=rng.randrange(3, 7), skill_code="ICT-TECH",
               tools=[f"KV-ICT-{code}:1"], inspection_gate=True, yield_pct=rng.choice([97.0, 97.5, 98.0, 98.5, 99.0])),
            op(110, "FCT", "FCT", setup_minutes=20, run_minutes=rng.randrange(8, 21), skill_code="FCT-TECH",
               tools=[f"KV-FCT-{code}:1"], inspection_gate=True, yield_pct=rng.choice([97.0, 97.5, 98.0, 98.5, 99.0]))]
    return ops


def _pcb_routing(b: Builder, rng: random.Random, pn: str, code: str, double: bool, wave: bool = False) -> None:
    b.routing(pn, _pcb_ops(rng, code, double, wave), code="WAVE" if wave else "STD", priority=2 if wave else 1)


def _plant(b: Builder) -> None:
    groups = [
        ("SMT", "Surface mount", "machine", [("SMT-1", 1.0), ("SMT-2", 1.0), ("SMT-3", 0.7)], "3SHIFT", ("SUN", 1200.0, 16.0)),
        ("AOI", "Automated optical inspection", "machine", [("AOI-1", 1.0), ("AOI-2", 1.0)], "3SHIFT", None),
        ("THT", "Through-hole assembly", "bench", [(f"THT-B{i}", 1.0) for i in range(1, 5)], "REG", ("EVE", 450.0, 12.0)),
        ("SEL", "Selective soldering", "machine", [("SEL-1", 1.0), ("SEL-2", 1.0)], "REG", ("EVE", 500.0, None)),
        ("WAVE", "Wave soldering", "machine", [("WAVE-1", 1.0)], "REG", None),
        ("WASH", "Board wash", "machine", [("WASH-1", 1.0)], "REG", ("EVE", 300.0, None)),
        ("COAT", "Conformal coating", "machine", [("COAT-1", 1.0)], "REG", ("EVE", 400.0, None)),
        ("CURE", "Curing ovens", "oven", [("OVEN-1", 1.0), ("OVEN-2", 1.0)], "24x7", None),
        ("ICT", "In-circuit test", "test", [("ICT-1", 1.0), ("ICT-2", 1.0)], "REG", ("EVE", 450.0, 12.0)),
        ("FCT", "Functional test", "test", [("FCT-1", 1.0), ("FCT-2", 1.0), ("FCT-3", 1.0)], "REG", ("EVE", 450.0, 12.0)),
        ("PROG", "Device programming", "bench", [("PROG-1", 1.0)], "REG", None),
        ("HAR-CUT", "Wire cut and strip", "machine", [("CUT-1", 1.0), ("CUT-2", 1.0)], "REG", ("EVE", 350.0, None)),
        ("HAR-CRIMP", "Crimping", "machine", [(f"CRIMP-{i}", 1.0) for i in range(1, 4)], "REG", ("EVE", 350.0, None)),
        ("HAR-ASSY", "Harness assembly", "bench", [(f"HB-{i}", 1.0) for i in range(1, 7)], "REG", ("EVE", 400.0, 12.0)),
        ("HAR-TEST", "Harness test", "test", [("CT-1", 1.0), ("CT-2", 1.0)], "REG", ("EVE", 350.0, None)),
        ("MECH", "Mechanical assembly", "bench", [("MB-1", 1.0), ("MB-2", 1.0)], "REG", None),
        ("SUBASSY", "Sub-assembly", "bench", [(f"SA-{i}", 1.0) for i in range(1, 5)], "REG", ("EVE", 450.0, None)),
        ("BURNIN", "Burn-in", "oven", [("BI-1", 1.0), ("BI-2", 1.0)], "24x7", None),
        ("FINAL", "Final assembly", "bench", [(f"FA-{i}", 1.0) for i in range(1, 4)], "REG", ("EVE", 500.0, None)),
        ("FINAL-TEST", "Test bay (sub-assembly and final test)", "test",
         [("FT-1", 1.0), ("FT-2", 1.0), ("ST-1", 1.0), ("ST-2", 1.0)], "REG", ("EVE", 450.0, None)),
    ]
    b.template("REG", "Regular day shift (Mon-Sat)", REG)
    b.template("EVE", "Evening overtime (Mon-Sat)", EVE)
    b.template("EXT", "Extended hours 09:00-22:00 (Mon-Sat)", EXT)
    b.template("3SHIFT", "24 hours, three shifts (Mon-Sat)", THREE_SHIFT)
    b.template("24x7", "Continuous 24 x 7", H24X7)
    b.template("SUN", "Sunday 06:00-22:00", SUN)
    for code, name, kind, lines, base, optional in groups:
        b.group(code, name, kind=kind)
        for lc, speed in lines:
            kw: dict[str, Any] = {"speed_factor": speed}
            if code in ("CURE",):
                kw["parallel_capacity"] = 4
            if code == "BURNIN":
                kw["parallel_capacity"] = 8
            if lc == "SMT-3":
                kw["eligible_families"] = ["PCBA-STD"]
            b.line(lc, code, f"{name} {lc}", **kw)
        b.assign(base, "group", code)
        if optional is not None:
            tpl, cost, max_h = optional
            b.assign(tpl, "group", code, kind="optional", cost_per_hour=cost, max_hours_per_week=max_h)
    b.assign("EVE", "line", "SMT-3", effective_from=date(2026, 1, 1), effective_to=date(2026, 4, 1),
             note="Evening-only operation during the Q1 line move (expired).")
    for d in (date(2026, 1, 26), date(2026, 8, 15), date(2026, 10, 2), date(2026, 11, 9), date(2026, 12, 25)):
        b.exception("plant", None, "holiday", d, d, "Plant holiday")
    b.exception("plant", None, "shutdown", date(2026, 12, 28), date(2026, 12, 31), "Annual shutdown")
    b.exception("line", "SMT-2", "maintenance", datetime(2026, 11, 14, 6, 0, tzinfo=IST),
                datetime(2026, 11, 14, 18, 0, tzinfo=IST), "Preventive maintenance")
    b.exception("line", "OVEN-1", "maintenance", datetime(2026, 11, 21, 8, 0, tzinfo=IST),
                datetime(2026, 11, 21, 16, 0, tzinfo=IST), "Oven profiling")


def _resources(b: Builder) -> None:
    for code, name in (("SMT-OP", "SMT operator"), ("AOI-OP", "AOI operator"), ("THT-SOLDER", "Hand soldering"),
                       ("SEL-SOLDER", "Selective/wave soldering"), ("WASH-OP", "Wash operator"),
                       ("COATING", "Conformal coating"), ("ICT-TECH", "ICT technician"),
                       ("FCT-TECH", "FCT technician"), ("PROG-OP", "Programming"),
                       ("HARNESS-CRIMP", "Harness cutting and crimping"), ("HARNESS-ASSY", "Harness assembly"),
                       ("HARNESS-TEST", "Harness test"), ("ELEC-ASSY", "Electromechanical assembly"),
                       ("TEST-ENG", "Test engineer")):
        b.skill(code, name)
    crew: list[tuple[list[str], str, list[str], str]] = []
    for sh in ("A", "B", "C"):       # SMT/AOI on three shifts
        crew += [(["SMT-OP", "AOI-OP"], "3SHIFT", [sh], "SMT"), (["SMT-OP"], "3SHIFT", [sh], "SMT"),
                 (["AOI-OP"], "3SHIFT", [sh], "AOI")]
    crew += [(["THT-SOLDER"], "REG", [], "THT")] * 3
    crew += [(["SEL-SOLDER", "WASH-OP"], "REG", [], "SEL"), (["SEL-SOLDER"], "REG", [], "SEL"),
             (["COATING"], "REG", [], "COAT"), (["COATING", "WASH-OP"], "REG", [], "COAT"),
             (["ICT-TECH"], "REG", [], "ICT"), (["ICT-TECH", "FCT-TECH"], "REG", [], "ICT"),
             (["FCT-TECH"], "REG", [], "FCT"), (["FCT-TECH"], "REG", [], "FCT"),
             (["PROG-OP", "ICT-TECH"], "REG", [], "PROG"),
             (["HARNESS-CRIMP"], "REG", [], "HAR-CRIMP"), (["HARNESS-CRIMP"], "REG", [], "HAR-CUT"),
             (["HARNESS-CRIMP", "HARNESS-ASSY"], "REG", [], "HAR-CRIMP"),
             (["HARNESS-ASSY"], "REG", [], "HAR-ASSY"), (["HARNESS-ASSY"], "REG", [], "HAR-ASSY"),
             (["HARNESS-ASSY"], "REG", [], "HAR-ASSY"), (["HARNESS-TEST"], "REG", [], "HAR-TEST"),
             (["HARNESS-TEST", "HARNESS-ASSY"], "REG", [], "HAR-TEST"),
             (["ELEC-ASSY"], "REG", [], "SUBASSY"), (["ELEC-ASSY"], "REG", [], "SUBASSY"),
             (["ELEC-ASSY"], "REG", [], "FINAL"), (["ELEC-ASSY", "TEST-ENG"], "REG", [], "FINAL"),
             (["TEST-ENG"], "REG", [], "FINAL-TEST"), (["TEST-ENG"], "REG", [], "FINAL-TEST"),
             (["ELEC-ASSY"], "REG", [], "MECH"), (["FCT-TECH", "TEST-ENG"], "REG", [], "FCT")]
    # overtime crews on EXT (cover the EVE windows; deliberately nobody with COATING)
    crew += [(["THT-SOLDER", "SEL-SOLDER"], "EXT", [], "THT"), (["WASH-OP", "ICT-TECH"], "EXT", [], "WASH"),
             (["FCT-TECH", "ICT-TECH"], "EXT", [], "FCT"), (["HARNESS-CRIMP", "HARNESS-ASSY"], "EXT", [], "HAR-CRIMP"),
             (["HARNESS-TEST", "HARNESS-CRIMP"], "EXT", [], "HAR-TEST"), (["ELEC-ASSY", "TEST-ENG"], "EXT", [], "FINAL"),
             (["ELEC-ASSY"], "EXT", [], "SUBASSY"), (["TEST-ENG", "FCT-TECH"], "EXT", [], "FINAL-TEST"),
             (["HARNESS-ASSY"], "EXT", [], "HAR-ASSY")]
    for i, (skills, tpl, names, home) in enumerate(crew[:46], 1):
        b.operator(f"OP-{i:03d}", f"Operator {i:03d}", skills, tpl, names, home=home)
    for i in (47, 48):        # weekend crew for the optional SMT Sunday shift
        b.operator(f"OP-{i:03d}", f"Operator {i:03d}", ["SMT-OP"], "SUN", [], home="SMT")

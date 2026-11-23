"""Sample `meddev`: "Fictional Medical Devices plant - Quebec", a single-use medical-device plant (fictional).

Fictional sample data. Products are generic single-use device types modelled on a typical medical-device portfolio
(medication delivery, specimen collection, prefillable syringes, infusion); no real company, brand or product names.
Stages: injection moulding (six presses, mould changeovers through item setup families and a setup matrix), tubing
extrusion, cannula grinding and bonding, barrel printing, cleanroom assembly, prefillable-syringe processing, fill and
finish, blood-tube processing, packaging and labelling, EtO sterilisation (batch loads with aeration) and a QC release
hold. Shifts: three shifts 24/5 on moulding and extrusion, two shifts on assembly and packaging, optional Saturday and
night overtime on assembly and packaging, continuous EtO.

Intended health content (asserted by `tests/mfg/test_meddev_sample.py`): none. Planning lead times of made items
are fixed (`lead_time_days`), so MRP does not chain the EtO cycle and aeration into every routing sum.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..bundle import MfgBundle
from .common import DESC_FICTIONAL, Builder, line, op, shift

ID = "meddev"
NAME = "Single-use medical devices plant (fictional)"
DESCRIPTION = (f"{DESC_FICTIONAL} Generic single-use devices (syringes, safety needles, IV catheters, saline flush, "
               "blood collection tubes, prefillable syringes, IV sets): moulding, cleanroom assembly, packaging, EtO "
               "sterilisation and QC release; lot-controlled materials with expiry. ~55 parts, 11 stages.")
EST = timezone(timedelta(hours=-5))
MON_FRI = ["mon", "tue", "wed", "thu", "fri"]

SYN = {"manufacturer": "Synthetic"}


def _attrs(n: int) -> dict[str, Any]:
    return {**SYN, "mpn": f"SYN-MDV-{n:04d}"}


# buy items: part number -> (description, uom, lead days, shelf life days or None, lot controlled, extra)
BUY: dict[str, tuple[str, str, int, int | None, bool, dict[str, Any]]] = {
    "MDV-RES-PP": ("Polypropylene resin, medical grade", "KG", 21, 730, True, {"min_order_qty": 1000}),
    "MDV-RES-PET": ("PET resin, medical grade", "KG", 28, 730, True, {"min_order_qty": 1000}),
    "MDV-RES-PVC": ("PVC compound, DEHP-free, medical grade", "KG", 21, 365, True, {"min_order_qty": 500}),
    "MDV-STL-TUBE": ("Stainless steel cannula tubing, 304", "M", 42, None, True, {"min_order_qty": 2000}),
    "MDV-FEP-20": ("FEP catheter tubing, 20G", "M", 56, 1095, True, {"min_order_qty": 500}),
    "MDV-FEP-22": ("FEP catheter tubing, 22G", "M", 56, 1095, True, {"min_order_qty": 500}),
    "MDV-STP-03": ("Rubber plunger stopper, 3 mL", "EA", 35, 1095, True, {"min_order_qty": 50000}),
    "MDV-STP-10": ("Rubber plunger stopper, 10 mL", "EA", 35, 1095, True, {"min_order_qty": 50000}),
    "MDV-CLS-13": ("Tube closure with butyl stopper, 13 mm", "EA", 35, 1095, True, {"min_order_qty": 50000}),
    "MDV-TIP-CAP": ("Luer tip cap", "EA", 28, None, False, {"min_order_qty": 50000}),
    "MDV-NSH-1ML": ("Elastomeric needle shield, 1 mL syringe", "EA", 49, 1095, True, {"min_order_qty": 20000}),
    "MDV-GLS-1ML": ("Glass syringe barrel 1 mL, borosilicate Type I", "EA", 98, None, True,
                    {"min_order_qty": 20000, "handling_note": "Fragile; store in sealed tubs."}),
    "MDV-SIL-OIL": ("Silicone oil, medical grade", "L", 28, 730, True, {}),
    "MDV-ADH-UV": ("UV-cure adhesive, medical grade", "L", 35, 180, True,
                   {"handling_note": "Store at 5-25 C, away from light."}),
    "MDV-SOLV": ("Bonding solvent (cyclohexanone)", "L", 21, 365, True, {}),
    "MDV-NACL": ("Sodium chloride 0.9 %, bulk", "L", 14, 365, True, {}),
    "MDV-EDTA": ("K2EDTA additive solution", "L", 28, 365, True, {}),
    "MDV-SST-GEL": ("Separator gel with clot activator", "KG", 35, 365, True, {}),
    "MDV-CLAMP": ("Roller clamp", "EA", 28, None, False, {"min_order_qty": 20000}),
    "MDV-LUER-M": ("Male luer-lock connector with cap", "EA", 28, None, False, {"min_order_qty": 20000}),
    "MDV-LBL-UDI": ("UDI label stock, printed on demand", "EA", 14, 730, True, {"min_order_qty": 100000}),
    "MDV-TYV-LID": ("Tyvek lidding", "M2", 42, 1095, True, {"min_order_qty": 200}),
    "MDV-POUCH-S": ("Peel pouch, paper/film, small", "EA", 21, 1095, False, {"min_order_qty": 50000}),
    "MDV-POUCH-L": ("Peel pouch, paper/film, large", "EA", 21, 1095, False, {"min_order_qty": 20000}),
    "MDV-NEST-1ML": ("Nest and tub, 100 x 1 mL", "EA", 42, None, False, {"min_order_qty": 500}),
    "MDV-CTN-100": ("Shipper carton, 100 units", "EA", 14, None, False, {"min_order_qty": 1000}),
    "MDV-IFU-IVS": ("Instructions for use, IV set", "EA", 14, None, False, {"min_order_qty": 20000}),
}

# moulded parts: part number -> (description, mould setup family, cavities, cycle minutes, resin, kg per part)
MOULDED: dict[str, tuple[str, str, int, float, str, float]] = {
    "MDV-BRL-03": ("Syringe barrel 3 mL, moulded", "MLD-SYR", 32, 0.25, "MDV-RES-PP", 0.0026),
    "MDV-PLG-03": ("Plunger rod 3 mL, moulded", "MLD-SYR", 32, 0.22, "MDV-RES-PP", 0.0018),
    "MDV-BRL-10": ("Syringe barrel 10 mL, moulded", "MLD-SYR", 16, 0.30, "MDV-RES-PP", 0.0062),
    "MDV-PLG-10": ("Plunger rod 10 mL, moulded", "MLD-SYR", 16, 0.26, "MDV-RES-PP", 0.0041),
    "MDV-HUB-N": ("Needle hub, moulded", "MLD-HUB", 48, 0.18, "MDV-RES-PP", 0.0004),
    "MDV-SHD-N": ("Safety shield, moulded", "MLD-HUB", 32, 0.20, "MDV-RES-PP", 0.0007),
    "MDV-HUB-C": ("Catheter hub with flash chamber, moulded", "MLD-HUB", 32, 0.22, "MDV-RES-PP", 0.0009),
    "MDV-DCH": ("Drip chamber, moulded", "MLD-IV", 16, 0.30, "MDV-RES-PP", 0.0045),
    "MDV-SPK": ("Spike with vent, moulded", "MLD-IV", 16, 0.28, "MDV-RES-PP", 0.0030),
    "MDV-PET-13": ("Blood collection tube 13 x 75 mm, PET, moulded", "MLD-PET", 32, 0.20, "MDV-RES-PET", 0.0042),
}

CANNULAS = {"MDV-CAN-20": "20G", "MDV-CAN-22": "22G", "MDV-CAN-23": "23G", "MDV-CAN-25": "25G",
            "MDV-CAN-27": "27G"}


def build() -> MfgBundle:
    b = Builder()
    b.plant("Fictional Medical Devices plant - Quebec", utc_offset="-05:00", horizon=120, currency="CAD")
    _plant(b)
    _resources(b)
    for n, (pn, (desc, uom, lead, shelf, lot, extra)) in enumerate(BUY.items(), 1):
        kw: dict[str, Any] = {"uom": uom, "lead_time_days": lead, "lot_controlled": lot, **extra}
        if shelf:
            kw["shelf_life_days"] = shelf
        b.item(pn, "buy", desc, attributes=_attrs(n), **kw)

    # moulded components (lot-controlled: the press WO number is the lot)
    for pn, (desc, fam, cav, cycle, resin, kg) in MOULDED.items():
        b.item(pn, "make", desc, family="MOULDED", setup_family=fam, lot_controlled=True, shelf_life_days=1825,
               lot_rule="period", lot_period_days=10, lead_time_days=3)
        b.bom(pn, [line(10, resin, kg, uom="KG", scrap_pct=2.0)])
        b.routing(pn, [op(10, "Injection mould", "MOULD", setup_minutes=90, run_minutes=cycle, run_per="panel",
                          units_per_panel=cav, skill_code="MOULD-TECH", yield_pct=99.5)])
    # cannulas (cut, grind, clean)
    for pn, g in CANNULAS.items():
        b.item(pn, "make", f"Cannula {g}, ground and cleaned", family="CANNULA", lot_controlled=True,
               lot_rule="period", lot_period_days=10, lead_time_days=3)
        b.bom(pn, [line(10, "MDV-STL-TUBE", 0.04, uom="M", scrap_pct=1.5)])
        b.routing(pn, [op(10, "Cut, grind and clean cannula", "CANN", setup_minutes=45, run_minutes=0.004,
                          skill_code="CANN-OP", yield_pct=99)])
    # extruded tubing
    b.item("MDV-TUB-IV", "make", "IV tubing 3 mm ID, extruded PVC", uom="M", family="TUBING", lot_controlled=True,
           shelf_life_days=1825, lot_rule="period", lot_period_days=10, lead_time_days=2)
    b.bom("MDV-TUB-IV", [line(10, "MDV-RES-PVC", 0.012, uom="KG", scrap_pct=3.0)])
    b.routing("MDV-TUB-IV", [op(10, "Extrude tubing", "EXTR", setup_minutes=120, run_minutes=0.02,
                                skill_code="EXTR-OP", yield_pct=98)])

    def fin(pn: str, desc: str, family: str) -> None:
        b.item(pn, "make", desc, family=family, lot_controlled=True, shelf_life_days=1825, revision="B",
               lead_time_days=6, handling_note="Sterile; store dry, below 30 C.")

    def tail(seq: int, pack_run: float, batch: int, *, ster: bool = True) -> list[dict[str, Any]]:
        out = [op(seq, "Pack and label (UDI)", "PACK", setup_minutes=30, run_minutes=pack_run, skill_code="PACK-OP")]
        if ster:
            out.append(op(seq + 10, "EtO sterilisation and aeration", "STER", run_minutes=720, run_per="batch",
                          units_per_batch=batch, labor="unattended", crew_size=0, interruptible=False,
                          wait_minutes=720))
        out.append(op(seq + (20 if ster else 10), "QC release hold", "QC", run_minutes=90, run_per="batch",
                      units_per_batch=100_000, skill_code="QA-REL", inspection_gate=True, queue_minutes=240))
        return out

    # medication delivery: hypodermic syringes
    for size, ml in (("03", "3 mL"), ("10", "10 mL")):
        pn = f"MDV-SYR-{size}"
        fin(pn, f"Hypodermic syringe {ml}, luer lock, sterile", "SYRINGE")
        b.bom(pn, [line(10, f"MDV-BRL-{size}", 1, operation_seq=10), line(20, f"MDV-PLG-{size}", 1),
                   line(30, f"MDV-STP-{size}", 1, scrap_pct=0.5), line(40, "MDV-POUCH-S", 1, operation_seq=30),
                   line(50, "MDV-LBL-UDI", 1, operation_seq=30), line(60, "MDV-CTN-100", 0.01, operation_seq=30)],
              revision="B")
        b.routing(pn, [op(10, "Print barrel graduations", "PRINT", setup_minutes=30, run_minutes=0.004,
                          skill_code="PRINT-OP"),
                       op(20, "Assemble plunger and barrel", "ASSY", setup_minutes=45, run_minutes=0.006,
                          skill_code="CR-ASSY", yield_pct=99.6)] + tail(30, 0.004, 100000))
    # safety hypodermic needles
    for g in ("23", "25"):
        pn = f"MDV-NDL-{g}"
        fin(pn, f"Safety hypodermic needle {g}G x 25 mm, sterile", "NEEDLE")
        b.bom(pn, [line(10, f"MDV-CAN-{g}", 1, operation_seq=10), line(20, "MDV-HUB-N", 1, operation_seq=10),
                   line(30, "MDV-ADH-UV", 0.0000004, uom="L", operation_seq=10), line(40, "MDV-SHD-N", 1),
                   line(50, "MDV-POUCH-S", 1, operation_seq=30), line(60, "MDV-LBL-UDI", 1, operation_seq=30),
                   line(70, "MDV-CTN-100", 0.01, operation_seq=30)], revision="B")
        b.routing(pn, [op(10, "Bond cannula to hub (UV cure)", "CANN", setup_minutes=30, run_minutes=0.006,
                          skill_code="CANN-OP", yield_pct=99.5),
                       op(20, "Assemble safety shield", "ASSY", setup_minutes=45, run_minutes=0.006,
                          skill_code="CR-ASSY", yield_pct=99.7)] + tail(30, 0.004, 100000))
    # peripheral IV catheters
    for g in ("20", "22"):
        pn = f"MDV-IVC-{g}"
        fin(pn, f"Peripheral IV catheter {g}G, sterile", "CATHETER")
        b.bom(pn, [line(10, f"MDV-CAN-{g}", 1, operation_seq=20), line(20, f"MDV-FEP-{g}", 0.032, uom="M",
                                                                        operation_seq=10, scrap_pct=2.0),
                   line(30, "MDV-HUB-C", 1, operation_seq=10), line(40, "MDV-ADH-UV", 0.000001, uom="L",
                                                                    operation_seq=10),
                   line(50, "MDV-POUCH-S", 1, operation_seq=30), line(60, "MDV-LBL-UDI", 1, operation_seq=30),
                   line(70, "MDV-CTN-100", 0.02, operation_seq=30)], revision="B")
        b.routing(pn, [op(10, "Tip and bond catheter", "ASSY", setup_minutes=60, run_minutes=0.02,
                          skill_code="CR-ASSY", yield_pct=99.2),
                       op(20, "Insert introducer needle", "ASSY", setup_minutes=20, run_minutes=0.012,
                          skill_code="CR-ASSY", yield_pct=99.8)] + tail(30, 0.006, 80000))
    # prefilled saline flush syringe (fill and finish)
    fin("MDV-FLS-10", "Prefilled saline flush syringe 10 mL", "FLUSH")
    b.bom("MDV-FLS-10", [line(10, "MDV-BRL-10", 1), line(20, "MDV-PLG-10", 1), line(30, "MDV-STP-10", 1),
                         line(40, "MDV-TIP-CAP", 1), line(50, "MDV-NACL", 0.0105, uom="L", scrap_pct=1.0),
                         line(60, "MDV-POUCH-S", 1, operation_seq=20), line(70, "MDV-LBL-UDI", 1, operation_seq=20),
                         line(80, "MDV-CTN-100", 0.01, operation_seq=20)], revision="B")
    b.routing("MDV-FLS-10", [op(10, "Fill, stopper and cap", "FILL", setup_minutes=60, run_minutes=0.01,
                                skill_code="FILL-OP", yield_pct=99.5)] + tail(20, 0.004, 1, ster=False))
    # specimen collection: evacuated blood collection tubes
    for pn, desc, add, qty, uom in (("MDV-BCT-EDTA4", "Evacuated blood collection tube, K2EDTA, 4 mL", "MDV-EDTA",
                                     0.00004, "L"),
                                    ("MDV-BCT-SST5", "Evacuated blood collection tube, serum separator, 5 mL",
                                     "MDV-SST-GEL", 0.0011, "KG")):
        fin(pn, desc, "TUBE")
        b.bom(pn, [line(10, "MDV-PET-13", 1, operation_seq=10, scrap_pct=0.5), line(20, add, qty, uom=uom,
                                                                                 operation_seq=10),
                   line(30, "MDV-CLS-13", 1, operation_seq=20), line(40, "MDV-LBL-UDI", 1, operation_seq=30),
                   line(50, "MDV-CTN-100", 0.01, operation_seq=30)], revision="B")
        b.routing(pn, [op(10, "Dose additive", "TUBE", setup_minutes=40, run_minutes=0.003, skill_code="TUBE-OP"),
                       op(20, "Evacuate and close", "TUBE", setup_minutes=20, run_minutes=0.003, skill_code="TUBE-OP",
                          yield_pct=99.6),
                       op(30, "Label and tray", "PACK", setup_minutes=20, run_minutes=0.003, skill_code="PACK-OP"),
                       op(40, "QC release hold", "QC", run_minutes=90, run_per="batch", units_per_batch=100_000,
                          skill_code="QA-REL", inspection_gate=True, queue_minutes=240)])
    # prefillable glass syringe, nested (bought-in barrel, in-house processing)
    fin("MDV-PFS-1ML", "Prefillable glass syringe 1 mL, staked needle 27G, nested", "PFS")
    b.bom("MDV-PFS-1ML", [line(10, "MDV-GLS-1ML", 1, operation_seq=10, scrap_pct=1.0),
                          line(20, "MDV-SIL-OIL", 0.00002, uom="L", operation_seq=20),
                          line(30, "MDV-CAN-27", 1, operation_seq=30), line(40, "MDV-ADH-UV", 0.0000003, uom="L",
                                                                           operation_seq=30),
                          line(50, "MDV-NSH-1ML", 1, operation_seq=30), line(60, "MDV-NEST-1ML", 0.01,
                                                                             operation_seq=40),
                          line(70, "MDV-TYV-LID", 0.0004, uom="M2", operation_seq=40),
                          line(80, "MDV-LBL-UDI", 0.01, operation_seq=40)], revision="B")
    b.routing("MDV-PFS-1ML", [
        op(10, "Wash and depyrogenate barrels", "PFS", setup_minutes=45, run_minutes=0.004, skill_code="PFS-OP"),
        op(20, "Siliconise", "PFS", setup_minutes=20, run_minutes=0.004, skill_code="PFS-OP"),
        op(30, "Stake needle and fit shield", "PFS", setup_minutes=30, run_minutes=0.006, skill_code="PFS-OP",
           yield_pct=99.3),
        op(40, "Nest, tub and lid", "PFS", setup_minutes=15, run_minutes=0.003, skill_code="PFS-OP"),
        op(50, "EtO sterilisation and aeration", "STER", run_minutes=720, run_per="batch", units_per_batch=60000,
           labor="unattended", crew_size=0, interruptible=False, wait_minutes=720),
        op(60, "QC release hold", "QC", run_minutes=120, run_per="batch", units_per_batch=100_000,
           skill_code="QA-REL", inspection_gate=True, queue_minutes=240)])
    # infusion: IV administration set
    fin("MDV-IVS-20", "IV administration set, 20 drops/mL, 2.2 m", "IVSET")
    b.bom("MDV-IVS-20", [line(10, "MDV-SPK", 1), line(20, "MDV-DCH", 1), line(30, "MDV-TUB-IV", 2.2, uom="M",
                                                                            scrap_pct=1.0),
                         line(40, "MDV-CLAMP", 1), line(50, "MDV-LUER-M", 1),
                         line(60, "MDV-SOLV", 0.0004, uom="L"),
                         line(70, "MDV-POUCH-L", 1, operation_seq=30), line(80, "MDV-LBL-UDI", 1, operation_seq=30),
                         line(90, "MDV-IFU-IVS", 1, operation_seq=30), line(100, "MDV-CTN-100", 0.02,
                                                                            operation_seq=30)], revision="B")
    b.routing("MDV-IVS-20", [
        op(10, "Solvent-bond and assemble set", "ASSY", setup_minutes=45, run_minutes=0.1, skill_code="CR-ASSY"),
        op(20, "Leak and occlusion test", "ASSY", setup_minutes=15, run_minutes=0.02, skill_code="CR-ASSY",
           inspection_gate=True, yield_pct=99.5)] + tail(30, 0.02, 30000))
    return b.canonical()


def _plant(b: Builder) -> None:
    b.template("3X8-5", "Three shifts 24/5 (Mon-Fri)", [
        shift("A", MON_FRI, "06:00", "14:00", "Meal=10:00-10:30"),
        shift("B", MON_FRI, "14:00", "22:00", "Meal=18:00-18:30"),
        shift("C", MON_FRI, "22:00", "06:00", "Meal=02:00-02:30")])
    b.template("2X8-5", "Two shifts (Mon-Fri)", [
        shift("Day", MON_FRI, "06:00", "14:00", "Meal=10:00-10:30"),
        shift("Evening", MON_FRI, "14:00", "22:00", "Meal=18:00-18:30")])
    b.template("QA-DAY", "QA day shift (Mon-Fri)", [shift("Day", MON_FRI, "08:00", "16:30", "Lunch=12:00-12:30")])
    b.template("SAT-OT", "Saturday overtime", [shift("Saturday", ["sat"], "06:00", "14:00")])
    b.template("NIGHT-OT", "Night overtime (Mon-Fri)", [shift("Night", MON_FRI, "22:00", "06:00")])
    b.template("24X7", "Continuous 24 x 7", [shift("Day", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                                                   "00:00", "00:00")])
    groups = [
        ("MOULD", "Injection moulding", "machine", [f"IMM-0{i}" for i in range(1, 7)], "3X8-5", None),
        ("EXTR", "Tubing extrusion", "machine", ["EXT-01"], "3X8-5", None),
        ("CANN", "Cannula grinding and bonding", "machine", ["CAN-01", "CAN-02"], "2X8-5", None),
        ("PRINT", "Barrel printing", "machine", ["PRT-01"], "2X8-5", None),
        ("ASSY", "Cleanroom assembly (ISO 8)", "line", ["ASM-01", "ASM-02", "ASM-03", "ASM-04"], "2X8-5",
         [("SAT-OT", 95.0, 8.0), ("NIGHT-OT", 110.0, 40.0)]),
        ("PFS", "Prefillable syringe processing", "machine", ["PFS-01"], "2X8-5", [("SAT-OT", 120.0, 8.0)]),
        ("FILL", "Fill and finish", "machine", ["FIL-01"], "2X8-5", None),
        ("TUBE", "Blood tube processing", "machine", ["BCT-01"], "2X8-5", None),
        ("PACK", "Packaging and labelling", "line", ["PKG-01", "PKG-02"], "2X8-5", [("SAT-OT", 85.0, 8.0)]),
        ("STER", "EtO sterilisation", "oven", ["ETO-01", "ETO-02"], "24X7", None),
        ("QC", "QC release", "test", ["QCR-01", "QCR-02"], "QA-DAY", None),
    ]
    eligible = {"ASM-01": ["SYRINGE", "NEEDLE"], "ASM-02": ["SYRINGE", "NEEDLE"], "ASM-03": ["CATHETER"],
                "ASM-04": ["IVSET"]}
    names = {"IMM": "Press", "EXT": "Extruder", "CAN": "Cannula cell", "PRT": "Pad printer", "ASM": "Assembly line",
             "PFS": "PFS line", "FIL": "Filler", "BCT": "Tube line", "PKG": "Packaging line", "ETO": "EtO chamber",
             "QCR": "QC release desk"}
    for code, name, kind, lines, base, optional in groups:
        b.group(code, name, kind=kind)
        for lc in lines:
            kw: dict[str, Any] = {}
            if lc in eligible:
                kw["eligible_families"] = eligible[lc]
            if code == "MOULD":
                kw["cost_per_hour"] = 140.0
            b.line(lc, code, f"{names[lc.split('-')[0]]} {lc.split('-')[1]}", **kw)
        b.assign(base, "group", code)
        for tpl, cost, max_h in optional or []:
            b.assign(tpl, "group", code, kind="optional", cost_per_hour=cost, max_hours_per_week=max_h)
    for d, label in ((date(2026, 12, 25), "Christmas Day"), (date(2026, 12, 26), "Boxing Day"),
                     (date(2027, 1, 1), "New Year's Day")):
        b.exception("plant", None, "holiday", d, d, label)
    b.exception("line", "IMM-04", "maintenance", datetime(2026, 11, 26, 6, 0, tzinfo=EST),
                datetime(2026, 11, 26, 18, 0, tzinfo=EST), "Mould tool refurbishment")
    b.exception("line", "ETO-02", "maintenance", datetime(2026, 12, 2, 8, 0, tzinfo=EST),
                datetime(2026, 12, 3, 8, 0, tzinfo=EST), "Chamber requalification")


def _resources(b: Builder) -> None:
    for code, name in (("MOULD-TECH", "Moulding technician"), ("EXTR-OP", "Extrusion operator"),
                       ("CANN-OP", "Cannula cell operator"), ("PRINT-OP", "Print operator"),
                       ("CR-ASSY", "Cleanroom assembler"), ("PFS-OP", "PFS line operator"),
                       ("FILL-OP", "Fill and finish operator"), ("TUBE-OP", "Tube line operator"),
                       ("PACK-OP", "Packaging operator"), ("QA-REL", "QA release reviewer")):
        b.skill(code, name)
    crew: list[tuple[list[str], str, list[str], str]] = []
    for sh in ("A", "B", "C"):
        crew += [(["MOULD-TECH"], "3X8-5", [sh], "MOULD"), (["MOULD-TECH"], "3X8-5", [sh], "MOULD"),
                 (["MOULD-TECH", "EXTR-OP"], "3X8-5", [sh], "EXTR")]
    for sh in ("Day", "Evening"):
        crew += [(["CR-ASSY"], "2X8-5", [sh], "ASSY")] * 4
        crew += [(["CANN-OP", "CR-ASSY"], "2X8-5", [sh], "CANN"), (["PRINT-OP", "PACK-OP"], "2X8-5", [sh], "PRINT"),
                 (["PFS-OP"], "2X8-5", [sh], "PFS"), (["FILL-OP", "TUBE-OP"], "2X8-5", [sh], "FILL"),
                 (["TUBE-OP"], "2X8-5", [sh], "TUBE"), (["PACK-OP"], "2X8-5", [sh], "PACK"),
                 (["PACK-OP"], "2X8-5", [sh], "PACK")]
    crew += [(["QA-REL"], "QA-DAY", [], "QC"), (["QA-REL"], "QA-DAY", [], "QC")]
    # overtime crews (Saturday and night)
    crew += [(["CR-ASSY", "PACK-OP"], "SAT-OT", [], "ASSY"), (["CR-ASSY", "PACK-OP"], "SAT-OT", [], "ASSY"),
             (["PFS-OP", "PACK-OP"], "SAT-OT", [], "PACK"), (["CR-ASSY"], "NIGHT-OT", [], "ASSY"),
             (["CR-ASSY"], "NIGHT-OT", [], "ASSY")]
    for i, (skills, tpl, names, home) in enumerate(crew, 1):
        b.operator(f"OP-{i:03d}", f"Operator {i:03d}", skills, tpl, names, home=home)

"""M7 additions to the fictional `meddev` sample (M7-DESIGN 12): sampling schemes, inspection plans, equipment and a
quality history. Pure data; applied by `api/mfg/services/qa_sample.py` after the M1-M4 sample and its history (no
change to their content, stock or health expectations: no ledger postings, no holds on free stock except the QC
release holds the sample already had, line equipment valid).

The `EXAMPLE-TABLE` scheme is a made-up, test-only table: load your licensed sampling tables for real use.
"""

from __future__ import annotations

from typing import Any

EXAMPLE_TABLE: dict[str, Any] = {
    "levels": ["S-4", "II"],
    "lot_size_ranges": [
        {"min": 1, "max": 1200, "letters": {"S-4": "E", "II": "J"}},
        {"min": 1201, "max": 10000, "letters": {"S-4": "G", "II": "L"}},
        {"min": 10001, "max": None, "letters": {"S-4": "H", "II": "N"}}],
    "plans": {
        "normal": {"E": {"0.65": {"n": 13, "ac": 0, "re": 1}, "2.5": {"n": 13, "ac": 1, "re": 2}},
                   "G": {"0.65": {"n": 32, "ac": 0, "re": 1}, "2.5": {"n": 32, "ac": 2, "re": 3}},
                   "H": {"0.65": {"n": 50, "ac": 1, "re": 2}, "2.5": {"n": 50, "ac": 3, "re": 4}},
                   "J": {"0.65": {"n": 80, "ac": 1, "re": 2}, "2.5": {"n": 80, "ac": 5, "re": 6}},
                   "L": {"0.65": {"n": 200, "ac": 3, "re": 4}, "2.5": {"n": 200, "ac": 10, "re": 11}},
                   "N": {"0.65": {"n": 500, "ac": 7, "re": 8}, "2.5": {"n": 500, "ac": 21, "re": 22}}},
        "tightened": {"E": {"0.65": {"n": 20, "ac": 0, "re": 1}, "2.5": {"n": 20, "ac": 1, "re": 2}},
                      "G": {"0.65": {"n": 50, "ac": 0, "re": 1}, "2.5": {"n": 50, "ac": 2, "re": 3}},
                      "H": {"0.65": {"n": 80, "ac": 1, "re": 2}, "2.5": {"n": 80, "ac": 3, "re": 4}},
                      "J": {"0.65": {"n": 125, "ac": 1, "re": 2}, "2.5": {"n": 125, "ac": 5, "re": 6}},
                      "L": {"0.65": {"n": 315, "ac": 3, "re": 4}, "2.5": {"n": 315, "ac": 10, "re": 11}},
                      "N": {"0.65": {"n": 800, "ac": 7, "re": 8}, "2.5": {"n": 800, "ac": 21, "re": 22}}}},
    "switching": {"to_tightened": {"rejected": 2, "of_last": 5}, "to_normal": {"consecutive_accepted": 5}},
}

SCHEMES = [
    {"code": "EXAMPLE-TABLE", "name": "Example attribute table (test only - load your licensed tables)",
     "kind": "table", "table": EXAMPLE_TABLE, "switching": True,
     "note": "test only - load your licensed tables"},
    {"code": "FIXED-5", "name": "Fixed sample of 5", "kind": "fixed", "fixed_n": 5, "switching": False, "note": ""},
    {"code": "FULL", "name": "100 % inspection", "kind": "full", "switching": False, "note": ""},
]

AQL = {"critical": "0.65", "major": "0.65", "minor": "2.5"}

#: (key, name, item, scope, scheme, operation_seq, supplier code, customer, characteristics)
PLANS = [
    ("INC-STP", "Incoming plunger stoppers 3 mL", "MDV-STP-03", "incoming", "EXAMPLE-TABLE", None, None, None, [
        {"seq": 10, "code": "DIM-OD", "name": "Outer diameter", "kind": "variable", "severity": "major",
         "unit": "mm", "nominal": 8.65, "lsl": 8.60, "usl": 8.70, "equipment_class": "CALIPER"},
        {"seq": 20, "code": "VIS", "name": "Visual: no flash, no particles", "kind": "attribute",
         "severity": "minor"}]),
    ("INC-GLS", "Incoming glass barrels 1 mL (SUP-GLASS)", "MDV-GLS-1ML", "incoming", "FIXED-5", None, "SUP-GLASS",
     None, [
         {"seq": 10, "code": "COSM", "name": "Cosmetic: no cracks or chips", "kind": "attribute",
          "severity": "critical"},
         {"seq": 20, "code": "LEN", "name": "Barrel length", "kind": "variable", "severity": "major", "unit": "mm",
          "nominal": 54.0, "lsl": 53.7, "usl": 54.3, "equipment_class": "CALIPER"}]),
    ("IPC-NDL", "Needle pull force before release (QC gate)", "MDV-NDL-23", "in_process", "FIXED-5", 50, None,
     None, [
         {"seq": 10, "code": "PULL", "name": "Needle pull force", "kind": "variable", "severity": "critical",
          "unit": "N", "nominal": 40.0, "lsl": 22.0, "equipment_class": "FORCE", "destructive": True}]),
    ("FIN-SYR", "Final release syringe 3 mL", "MDV-SYR-03", "final", "EXAMPLE-TABLE", None, None, None, [
        {"seq": 10, "code": "LEAK", "name": "Leak test", "kind": "attribute", "severity": "critical"},
        {"seq": 20, "code": "GRAD", "name": "Graduation legibility", "kind": "attribute", "severity": "minor"}]),
    ("FIN-PFS", "Final release PFS 1 mL (biologics customer)", "MDV-PFS-1ML", "final", "FIXED-5", None, None,
     "Biologics fill-finish customer (fictional)", [
         {"seq": 10, "code": "GLIDE", "name": "Break-loose / glide force", "kind": "variable", "severity": "major",
          "unit": "N", "nominal": 5.0, "lsl": 2.0, "usl": 10.0, "equipment_class": "FORCE"},
         {"seq": 20, "code": "CCI", "name": "Container closure integrity", "kind": "attribute",
          "severity": "critical"}]),
]

#: (code, name, kind, class, line code, due offset days, interval days)
EQUIPMENT = [
    ("CAL-0001", "Digital caliper 0-150 mm", "gauge", "CALIPER", None, 120, 365),
    ("CAL-0002", "Digital caliper 0-150 mm", "gauge", "CALIPER", None, 200, 365),
    ("CAL-0003", "Digital caliper 0-300 mm", "gauge", "CALIPER", None, 3, 365),      # due in 3 days
    ("CAL-0004", "Digital caliper 0-150 mm", "gauge", "CALIPER", None, -5, 365),     # overdue
    ("FG-0001", "Force gauge 50 N", "gauge", "FORCE", None, 90, 180),
    ("FG-0002", "Force gauge 50 N", "gauge", "FORCE", None, 150, 180),
    ("FG-0003", "Force gauge 500 N", "gauge", "FORCE", None, 60, 180),
    ("EQ-ASM01-UV", "UV cure lamp, ASM-01", "line_equipment", "UV-LAMP", "ASM-01", 75, 90),
    ("EQ-ASM01-LEAK", "Leak tester, ASM-01", "line_equipment", "LEAK", "ASM-01", 110, 180),
    ("EQ-ASM01-TORQ", "Torque driver, ASM-01", "line_equipment", "TORQUE", "ASM-01", 40, 180),
    ("EQ-ETO-01-PROBE", "EtO chamber humidity probe", "chamber", "HUMIDITY", None, 30, 365),
    ("EQ-QC-BAL", "Analytical balance, QC lab", "instrument", "BALANCE", None, 45, 365),
]

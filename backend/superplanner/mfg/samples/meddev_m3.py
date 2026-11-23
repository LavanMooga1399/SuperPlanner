"""Meddev M3 additions: plant time zone (America/Toronto), mould changeovers on the presses (line setup family
`MOULD`, a matrix by mould family: same family 60 min, different family 240 min, to/from PET 360 min for the resin
change and drying), one operator absence, and the operation progress of WO-MDV-0001 (barrel printing done)."""

from __future__ import annotations

from datetime import datetime

from ..bundle import MfgBundle

PROGRESS: dict[str, list[int]] = {"WO-MDV-0001": [10]}


def master(b: MfgBundle) -> MfgBundle:
    b["plant"][0]["time_zone"] = "America/Toronto"
    for ln in b["lines"]:
        if ln["group_code"] == "MOULD":
            ln["setup_family"] = "MOULD"
    fams = ("MLD-SYR", "MLD-HUB", "MLD-IV")
    rows = [{"line_setup_family": "MOULD", "from_family": "*", "to_family": "*", "setup_minutes": 240}]
    rows += [{"line_setup_family": "MOULD", "from_family": f, "to_family": f, "setup_minutes": 60}
             for f in fams + ("MLD-PET",)]
    rows += [{"line_setup_family": "MOULD", "from_family": f, "to_family": "MLD-PET", "setup_minutes": 360}
             for f in fams]
    rows += [{"line_setup_family": "MOULD", "from_family": "MLD-PET", "to_family": f, "setup_minutes": 360}
             for f in fams]
    b["setup_matrix"] = rows
    b["operator_absences"] = [
        {"operator_code": "OP-012", "start": datetime.fromisoformat("2026-11-30T00:00"),
         "end": datetime.fromisoformat("2026-12-05T00:00"), "kind": "leave",
         "note": "Cleanroom assembler leave"}]
    return b

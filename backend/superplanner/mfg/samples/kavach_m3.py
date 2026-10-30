"""Kavach M3 additions (M3-DESIGN 13): plant time zone, SMT setup families and matrix, two-person coating, three
line rates, operator absences (master; dated from the default anchor 2026-11-02) and the operation progress of
WO-KV-0001 (applied by the sample load / `aps.pure.sample_snapshot`)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from ..bundle import MfgBundle

PROGRESS: dict[str, list[int]] = {"WO-KV-0001": [10, 20, 30, 40]}


def master(b: MfgBundle) -> MfgBundle:
    b["plant"][0]["time_zone"] = "Asia/Kolkata"
    for ln in b["lines"]:
        if ln["code"] in ("SMT-1", "SMT-2", "SMT-3"):
            ln["setup_family"] = "SMT"
    for op in b["operations"]:          # two-person conformal coating (the absence of 13 then shows on COAT-1)
        if op.get("group_code") == "COAT":
            op["crew_size"] = 2
    b["setup_matrix"] = [
        {"line_setup_family": "SMT", "from_family": "*", "to_family": "*", "setup_minutes": 45},
        {"line_setup_family": "SMT", "from_family": "PCBA-HDI", "to_family": "PCBA-HDI", "setup_minutes": 20},
        {"line_setup_family": "SMT", "from_family": "PCBA-STD", "to_family": "PCBA-STD", "setup_minutes": 20},
        {"line_setup_family": "SMT", "from_family": "PCBA-HDI", "to_family": "PCBA-STD", "setup_minutes": 60},
        {"line_setup_family": "SMT", "from_family": "PCBA-STD", "to_family": "PCBA-HDI", "setup_minutes": 60}]
    # master data, so dated from the default anchor (a sample loaded with another anchor keeps these dates)
    b.update(_absences(date(2026, 11, 2)))
    b["operation_line_rates"] = [
        {"part_number": "KV-PCB-BPL", "code": "STD", "version": 1, "seq": 10, "line_code": "SMT-3",
         "run_minutes": 3.0, "note": "SMT-3 slower on the backplane"},
        {"part_number": "KV-PCB-BPL", "code": "STD", "version": 1, "seq": 30, "line_code": "SMT-3",
         "run_minutes": 1.6, "note": "SMT-3 slower on the backplane"},
        {"part_number": "KV-PCB-FLT", "code": "WAVE", "version": 1, "seq": 60, "line_code": "WAVE-1",
         "run_minutes": 1.2, "setup_minutes": 25, "note": "WAVE-1 profile for the filter board"},
        {"part_number": "KV-TPU-1000", "code": "STD", "version": 1, "seq": 30, "line_code": "FT-2",
         "run_minutes": 150.0, "note": "FT-2 has the faster test rack"}]
    return b


def _absences(anchor: date) -> dict[str, Any]:
    def at(days: int) -> datetime:
        d = anchor + timedelta(days=days)
        return datetime(d.year, d.month, d.day)

    return {"operator_absences": [
        {"operator_code": "OP-015", "start": at(7), "end": at(12), "kind": "leave", "note": "Coating operator leave"},
        {"operator_code": "OP-002", "start": at(14), "end": at(21), "kind": "leave", "note": "SMT operator leave"},
        {"operator_code": "OP-040", "start": at(3), "end": at(4), "kind": "sick", "note": "Test technician sick"}]}

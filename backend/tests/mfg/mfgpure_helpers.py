"""Small scenario builders for the pure mfg tests (bundles -> strict datasets)."""

from __future__ import annotations

from datetime import date
from typing import Any

from superplanner.mfg.bundle import bundle_to_dataset
from superplanner.mfg.dataset import MfgDataset
from superplanner.mfg.samples.common import REG, Builder, line, op, shift

AS_OF = date(2026, 11, 2)       # a Monday
MON_SAT = ["mon", "tue", "wed", "thu", "fri", "sat"]


def base_plant(b: Builder | None = None, *, offset: str = "+05:30") -> Builder:
    """One make item P (BOM: buy C; routing on group G/line L1 with REG), one operator with skill S."""
    b = b or Builder()
    b.plant("Test plant", utc_offset=offset)
    b.item("P", "make", "Parent", family="FAM")
    b.item("C", "buy", "Component", lead_time_days=10)
    b.bom("P", [line(10, "C", 2)])
    b.group("G", "Stage")
    b.line("L1", "G", "Line 1")
    b.template("REG", "Regular", REG)
    b.assign("REG", "group", "G")
    b.skill("S", "Skill")
    b.operator("O1", "Operator", ["S"], "REG")
    b.routing("P", [op(10, "Work", "G", setup_minutes=10, run_minutes=1, skill_code="S")])
    return b


def ds_of(b: Builder) -> MfgDataset:
    return bundle_to_dataset(b.b)


def item(ds: MfgDataset, pn: str) -> Any:
    return ds.items_by_pn[pn]


def by_code(ds: MfgDataset, code: str) -> Any:
    for table in (ds.groups, ds.lines, ds.skills, ds.tool_pools, ds.shift_templates, ds.operators):
        for x in table.values():
            if x.code == code:
                return x
    raise KeyError(code)


__all__ = ["AS_OF", "MON_SAT", "Builder", "base_plant", "by_code", "ds_of", "item", "line", "op", "shift"]

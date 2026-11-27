"""S0 contract freeze (M9-DESIGN 11): M9 service functions that are not implemented yet answer from
`api/mfg/fixtures/example_m9.json`. Each M9 service module ends with `__getattr__ = m9_examples.module_getattr(
__name__)` (PEP 562, as M8): a real definition always wins; a missing one resolves to an example-backed stub. Once
the build is complete no stub is reached (`tests/api_mfg_m9/test_m9_s0_contract.py` asserts the list is empty)."""

from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "example_m9.json"
#: function name -> (example key, shape) per module; shape: one | list | items | none
STUBS: dict[str, dict[str, tuple[str, str]]] = {
    "network": {"list_nodes": ("net_node", "items"), "list_lanes": ("net_lane", "items"),
                "create_lane": ("net_lane", "one"), "update_lane": ("net_lane", "one"), "delete_lane": ("", "none"),
                "list_sourcing": ("net_sourcing", "items"), "create_sourcing": ("net_sourcing", "one"),
                "update_sourcing": ("net_sourcing", "one"), "delete_sourcing": ("", "none"),
                "resolve": ("net_resolve", "one"), "list_runs": ("net_run", "list"), "create_run": ("net_run", "one"),
                "get_run": ("net_run", "one"), "grid": ("net_grid", "one"), "transfers": ("net_transfer", "list"),
                "shortages": ("net_shortage", "list"), "utilisation": ("net_utilisation", "items"),
                "pegging": ("net_pegging", "one"), "publish": ("net_run", "one"),
                "get_curves": ("ramp_curve", "items"), "put_curves": ("ramp_curve", "items")},
    "sop": {"list_cycles": ("sop_cycle", "list"), "create_cycle": ("sop_cycle", "one"),
            "get_cycle": ("sop_cycle", "one"), "advance": ("sop_cycle", "one"), "reopen": ("sop_cycle", "one"),
            "cancel": ("sop_cycle", "one"), "demand": ("sop_demand", "one"),
            "list_overrides": ("sop_override", "items"), "create_override": ("sop_override", "one"),
            "remove_override": ("sop_override", "one"), "put_asp": ("sop_demand", "one"),
            "recommend": ("sop_cycle", "one"), "approve": ("sop_cycle", "one"), "publish": ("sop_cycle", "one"),
            "list_scenarios": ("sop_scenario", "list"), "create_scenario": ("sop_scenario", "one"),
            "get_scenario": ("sop_scenario", "one"), "update_scenario": ("sop_scenario", "one"),
            "delete_scenario": ("", "none"), "run_scenario": ("sop_scenario", "one"),
            "copy_scenario": ("sop_scenario", "one"), "plan": ("sop_plan", "one"),
            "rough_cut": ("sop_rough_cut", "one"), "financial": ("sop_financial", "one"),
            "make_buy": ("sop_make_buy", "items"), "compare": ("sop_compare", "one")},
    "trade": {"get_tariffs": ("tariff", "items"), "put_tariffs": ("bulk_result", "one"), "get_fx": ("fx", "items"),
              "put_fx": ("bulk_result", "one"), "get_milestones": ("milestone", "items"),
              "put_milestones": ("bulk_result", "one"), "get_country_risk": ("country_risk", "items"),
              "put_country_risk": ("bulk_result", "one"), "list_reports": ("trade_report", "list"),
              "create_report": ("trade_report", "one"), "get_report": ("trade_report", "one"),
              "network_lot_content": ("lot_content", "one"), "risk": ("risk_row", "items"),
              "landed_rows": ("landed_row", "items"), "get_item_trade": ("item_trade", "one"),
              "put_item_trade": ("item_trade", "one"), "lot_content": ("lot_content", "one"),
              "mps_targets": ("mps_target", "items")},
}


@lru_cache(maxsize=1)
def examples() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _stub(key: str, shape: str) -> Callable[..., Any]:
    def fn(*_a: Any, **_k: Any) -> Any:
        if shape == "none":
            return None
        ex = examples()[key]
        if shape == "list":
            return {"items": [ex], "total": 1, "limit": 50, "offset": 0}
        if shape == "items":
            return {"items": [ex]}
        return ex

    fn.m9_stub = True  # type: ignore[attr-defined]
    return fn


def module_getattr(module: str) -> Callable[[str], Any]:
    short = module.rsplit(".", 1)[-1]

    def __getattr__(name: str) -> Any:
        spec = STUBS.get(short, {}).get(name)
        if spec is None:
            raise AttributeError(f"module {module!r} has no attribute {name!r}")
        return _stub(*spec)

    return __getattr__


def remaining() -> list[str]:
    """`module.function` names still answered from the examples."""
    out = []
    for short, fns in STUBS.items():
        mod = importlib.import_module(f"{__package__}.{short}")
        out += [f"{short}.{fn}" for fn in fns if fn not in vars(mod)]
    return sorted(out)

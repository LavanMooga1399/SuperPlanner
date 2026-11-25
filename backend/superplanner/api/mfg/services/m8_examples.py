"""S0 contract freeze (M8-DESIGN 13): M8 service functions that are not implemented yet answer from
`api/mfg/fixtures/example_m8.json`. Each M8 service module ends with `__getattr__ = m8_examples.module_getattr(
__name__)` (PEP 562): a real definition always wins; a missing one resolves to an example-backed stub. Once the
build is complete no stub is reached (`tests/api_mfg_m8/test_m8_s0_contract.py` asserts the list is empty)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "example_m8.json"
#: function name -> (example key, shape) per module; shape: one | list | none | items | file
STUBS: dict[str, dict[str, tuple[str, str]]] = {
    "forecast": {"list_history": ("history", "list"), "refresh_history": ("history_refresh", "one"),
                 "update_history": ("history", "one"), "list_runs": ("forecast_run", "list"),
                 "create_run": ("forecast_run", "one"), "get_run": ("forecast_run_detail", "one"),
                 "list_versions": ("forecast_version", "list"), "create_version": ("forecast_version", "one"),
                 "get_version": ("forecast_version", "one"), "version_lines": ("forecast_line", "list"),
                 "activate_version": ("forecast_version", "one"), "delete_version": ("", "none"),
                 "list_overrides": ("forecast_override", "items"), "create_override": ("forecast_override", "one"),
                 "remove_override": ("forecast_override", "one"), "item_view": ("forecast_item", "one"),
                 "accuracy": ("accuracy", "one")},
    "invopt": {"list_runs": ("ss_run", "list"), "create_run": ("ss_run", "one"), "get_run": ("ss_run", "one"),
               "list_lines": ("ss_line", "list"), "decide": ("ss_decide", "one")},
    "planning": {"get_item_planning": ("item_planning", "one"), "put_item_planning": ("item_planning", "one"),
                 "get_packaging": ("packaging", "one"), "put_packaging": ("packaging", "one"),
                 "get_line_rates": ("line_rates", "one"), "put_line_rates": ("line_rates", "one"),
                 "get_changeover_matrix": ("changeover_matrix", "one"),
                 "put_changeover_matrix": ("changeover_matrix", "one"), "get_settings": ("planning_settings", "one"),
                 "put_settings": ("planning_settings", "one"), "nightly_run_now": ("nightly", "one")},
    "rate": {"list_runs": ("rate_run", "list"), "create_run": ("rate_run", "one"), "get_run": ("rate_run", "one"),
             "list_blocks": ("rate_block", "list"), "grid": ("rate_grid", "one"), "publish": ("rate_publish", "one"),
             "compare": ("rate_compare", "one")},
    "ster": {"plan": ("ster_plan", "one"), "list_loads": ("ster_load", "list"), "get_load": ("ster_load", "one"),
             "load": ("ster_load", "one"), "advance": ("ster_load", "one"), "release": ("ster_load", "one"),
             "fail": ("ster_load", "one")},
    "kanban": {"list_loops": ("kanban_loop", "list"), "create_loop": ("kanban_loop", "one"),
               "get_loop": ("kanban_loop", "one"), "update_loop": ("kanban_loop", "one"),
               "list_cards": ("kanban_card", "items"), "scan": ("kanban_scan", "one")},
    "valid": {"trace_matrix": ("trace_matrix", "one"), "list_baselines": ("baseline", "list"),
              "create_baseline": ("baseline", "one"), "get_baseline": ("baseline", "one"),
              "diff_baselines": ("baseline_diff", "one")},
    "sap": {"get_settings": ("sap_settings", "one"), "put_settings": ("sap_settings", "one"),
            "sync": ("sap_sync", "one")},
}


@lru_cache(maxsize=1)
def examples() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _stub(key: str, shape: str) -> Callable[..., Any]:
    def fn(*_a: Any, **k: Any) -> Any:
        if shape == "none":
            return None
        ex = examples()[key]
        if shape == "list":
            return {"items": [ex], "total": 1, "limit": 50, "offset": 0}
        if shape == "items":
            return {"items": [ex]}
        if key == "trace_matrix" and _a and len(_a) > 1 and _a[1] != "json":
            return b"id,title,risk,tests,last_result\n", "trace-matrix.csv", "text/csv"
        return ex

    fn.m8_stub = True  # type: ignore[attr-defined]
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
    """Stubbed names that the service modules do not define yet."""
    import importlib

    out = []
    for short, names in STUBS.items():
        mod = importlib.import_module(f"{__package__}.{short}")
        out += [f"{short}.{n}" for n in names if n not in vars(mod)]
    return out

"""S0 contract freeze (M10-DESIGN 12): M10 service functions that are not implemented yet answer from
`api/mfg/fixtures/example_m10.json`. Each M10 service module ends with `__getattr__ = m10_examples.module_getattr(
__name__)` (PEP 562, as M8/M9): a real definition always wins; a missing one resolves to an example-backed stub.
Once the build is complete no stub is reached (`tests/api_mfg_m10/test_m10_s0_contract.py` asserts the list is
empty)."""

from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "example_m10.json"
#: function name -> (example key, shape) per module; shape: one | list | items | none
STUBS: dict[str, dict[str, tuple[str, str]]] = {
    "dhr": {"list_records": ("dhr_summary", "list"), "review_queue": ("review_queue_row", "items"),
            "live": ("dhr_live", "one"), "assemble": ("dhr_record", "one"), "get_record": ("dhr_record", "one"),
            "section": ("dhr_section", "one"), "disposition": ("dhr_exception", "one"),
            "start_review": ("dhr_record", "one"), "release": ("dhr_record", "one"), "export": ("dhr_record", "one")},
    "deviations": {"list_deviations": ("deviation", "list"), "create": ("deviation", "one"),
                   "get": ("deviation", "one"), "update": ("deviation", "one"), "approve": ("deviation", "one"),
                   "close": ("deviation", "one")},
    "coa": {"list_agreements": ("agreement", "list"), "create_agreement": ("agreement", "one"),
            "get_agreement": ("agreement", "one"), "update_agreement": ("agreement", "one"),
            "approve_agreement": ("agreement", "one"), "new_agreement_version": ("agreement", "one"),
            "list_coas": ("coa", "list"), "create_coa": ("coa", "one"), "get_coa": ("coa", "one"),
            "approve_coa": ("coa", "one"), "void_coa": ("coa", "one"), "export_coa": ("coa", "one"),
            "list_packs": ("batch_pack", "list"), "create_pack": ("batch_pack", "one"),
            "get_pack": ("batch_pack", "one"), "download_pack": ("batch_pack", "one")},
    "udi": {"list_devices": ("udi_device", "items"), "put_device": ("udi_device", "one"),
            "parse": ("udi_parse", "one"), "approve_device": ("udi_device", "one"),
            "list_exports": ("udi_export", "list"), "create_export": ("udi_export", "one"),
            "get_export": ("udi_export", "one"), "download_export": ("udi_export", "one")},
    "labels": {"list_templates": ("label_template", "list"), "create_template": ("label_template", "one"),
               "get_template": ("label_template", "one"), "update_template": ("label_template", "one"),
               "new_version": ("label_template", "one"), "preview_svg": ("label_template", "one"),
               "list_assignments": ("label_assignment", "items"), "put_assignments": ("label_assignment", "items"),
               "list_printers": ("printer", "items"), "create_printer": ("printer", "one"),
               "update_printer": ("printer", "one"), "list_jobs": ("print_job", "list"),
               "create_job": ("print_job", "one"), "get_job": ("print_job", "one"), "output": ("print_job", "one"),
               "add_event": ("print_job", "one"), "verify": ("verify_result", "one"),
               "reconcile": ("print_job", "one"), "void_job": ("print_job", "one")},
    "valpkg": {"iq_check": ("iq_result", "one"), "list_packages": ("val_package", "list"),
               "create_package": ("val_package", "one"), "get_package": ("val_package", "one"),
               "download_package": ("val_package", "one"), "approve_package": ("val_package", "one"),
               "upload_evidence": ("val_package", "one")},
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

    fn.m10_stub = True  # type: ignore[attr-defined]
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

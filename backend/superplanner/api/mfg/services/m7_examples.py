"""S0 contract freeze (M7-DESIGN 11): M7 service functions that are not implemented yet answer from
`qa/fixtures/example_m7.json`. Each M7 service module ends with `__getattr__ = m7_examples.module_getattr(__name__)`
(PEP 562): a real definition in the module always wins; a missing one resolves to an example-backed stub. Once the
build is complete no stub is reached (`tests/api_mfg_m7/test_m7_s0_contract.py` asserts the list is empty)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

FIXTURE = Path(__file__).resolve().parents[3] / "qa" / "fixtures" / "example_m7.json"
#: function name -> (example key, shape) per module; shape: one | list | none | file | pair
STUBS: dict[str, dict[str, tuple[str, str]]] = {
    "esig": {"status": ("esig_status", "one"), "enroll": ("esig_status", "one"),
             "stepup_start": ("", "redirect"), "revoke": ("esig_status", "one"), "time_info": ("time", "one"),
             "list_policies": ("policy", "list"), "update_policy": ("policy", "one"),
             "preview": ("preview", "one"), "list_signatures": ("signature_manifest", "list"),
             "verify": ("verify", "one")},
    "part11": {"record_audit": ("audit_record", "one"), "package": ("package", "one"),
               "create_export": ("export", "one"), "list_exports": ("export", "list"),
               "download_export": ("", "zip"), "get_mode": ("part11_mode", "one"), "enable": ("part11_mode", "one")},
    "qa_common": {"get_settings": ("qa_settings", "one"), "put_settings": ("qa_settings", "one"),
                  "add_attachment": ("attachment", "one"), "get_attachment": ("", "file"),
                  "delete_attachment": ("", "none"), "create_link": ("link", "one"), "delete_link": ("", "none")},
    "qa_inspection": {"list_schemes": ("scheme", "list"), "create_scheme": ("scheme", "one"),
                      "get_scheme": ("scheme", "one"), "preview_scheme": ("sampling_preview", "one"),
                      "update_scheme": ("scheme", "one"), "delete_scheme": ("", "none"),
                      "approve_scheme": ("scheme", "one"), "list_plans": ("plan", "list"),
                      "create_plan": ("plan", "one"), "get_plan": ("plan", "one"), "update_plan": ("plan", "one"),
                      "delete_plan": ("", "none"), "copy_plan": ("plan", "one"), "approve_plan": ("plan", "one"),
                      "obsolete_plan": ("plan", "one"), "list_lots": ("inspection_lot", "list"),
                      "create_lot": ("inspection_lot", "one"), "get_lot": ("inspection_lot", "one"),
                      "post_results": ("results_batch_response", "one"), "decide": ("inspection_lot", "one"),
                      "cancel_lot": ("inspection_lot", "one")},
    "qa_holds": {"list_holds": ("hold", "list"), "place_manual": ("hold", "one"), "release": ("hold", "one")},
    "qa_ncr": {"list_ncrs": ("ncr", "list"), "create_ncr": ("ncr", "one"), "get_ncr": ("ncr", "one"),
               "update_ncr": ("ncr", "one"), "open_ncr": ("ncr", "one"), "propose": ("ncr", "one"),
               "approve": ("pending", "one"), "implement": ("ncr", "one"), "close": ("ncr", "one"),
               "cancel": ("ncr", "one")},
    "qa_capa": {"list_capas": ("capa", "list"), "create_capa": ("capa", "one"), "get_capa": ("capa", "one"),
                "update_capa": ("capa", "one"), "add_action": ("capa", "one"), "update_action": ("capa", "one"),
                "delete_action": ("", "none"), "advance": ("capa", "one"), "approve_plan": ("capa", "one"),
                "verify": ("capa", "one"), "close": ("capa", "one"), "cancel": ("capa", "one")},
    "qa_complaints": {"list_complaints": ("complaint", "list"), "create_complaint": ("complaint", "one"),
                      "get_complaint": ("complaint", "one"), "update_complaint": ("complaint", "one"),
                      "advance": ("complaint", "one"), "close": ("complaint", "one")},
    "qa_field_actions": {"list_field_actions": ("field_action", "list"),
                         "create_field_action": ("field_action", "one"), "get_field_action": ("field_action", "one"),
                         "update_field_action": ("field_action", "one"), "approve": ("field_action", "one"),
                         "complete": ("field_action", "one"), "close": ("field_action", "one"),
                         "cancel": ("field_action", "one"), "list_units": ("field_action_unit", "list"),
                         "bulk_units": ("field_action", "one"), "export": ("", "file")},
    "qa_equipment": {"list_equipment": ("equipment", "list"), "create_equipment": ("equipment", "one"),
                     "get_equipment": ("equipment", "one"), "update_equipment": ("equipment", "one"),
                     "set_status": ("equipment", "one"), "impact": ("impact", "one"),
                     "list_calibrations": ("calibration", "list"), "record_calibration": ("calibration", "one")},
}


@lru_cache(maxsize=1)
def examples() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _stub(key: str, shape: str) -> Callable[..., Any]:
    def fn(*_a: Any, **_k: Any) -> Any:
        if shape == "none":
            return None
        if shape == "redirect":
            return "/esig/stepup-done#error=not_implemented", ""
        if shape == "zip":
            return b"PK\x05\x06" + b"\x00" * 18, "export.zip"
        if shape == "file":
            return b"example", "example.txt", "text/plain"
        ex = examples()[key]
        if shape == "list":
            return {"items": [ex], "total": 1, "limit": 50, "offset": 0}
        return ex

    fn.m7_stub = True  # type: ignore[attr-defined]
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

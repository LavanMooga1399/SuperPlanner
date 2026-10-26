"""The PHASE2B 4.8 endpoint access table, as data. `test_route_coverage` asserts that the app's OpenAPI operations
equal PUBLIC_ALLOWLIST + PROTECTED, so a new endpoint cannot be added without deciding its access rule here."""

from __future__ import annotations

import re
import uuid

API = "/api/v1"
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# B 4.8 rows 1-8 (public or session-checked by the auth router itself). /health/live and /health/ready arrive
# with Q5; they are allowed but not required.
PUBLIC_ALLOWLIST = frozenset({
    ("GET", "/health"), ("GET", "/health/live"), ("GET", "/health/ready"),
    ("GET", "/auth/session"), ("POST", "/auth/sign-up"), ("POST", "/auth/sign-in"),
    ("POST", "/auth/sign-out"), ("POST", "/auth/change-password"),
})
PUBLIC_REQUIRED = PUBLIC_ALLOWLIST - {("GET", "/health/live"), ("GET", "/health/ready")}

# B 4.8 rows 9-63: require_user (401 without a session; CSRF on unsafe methods).
PROTECTED = frozenset({
    ("GET", "/templates"), ("POST", "/templates/{template_id}/instantiate"),
    ("GET", "/problems"), ("POST", "/problems"), ("POST", "/problems/import"),
    ("GET", "/problems/{problem_id}"), ("PUT", "/problems/{problem_id}"), ("DELETE", "/problems/{problem_id}"),
    ("GET", "/problems/{problem_id}/export"), ("POST", "/problems/{problem_id}/validate"),
    ("POST", "/problems/{problem_id}/solver-runs"), ("GET", "/problems/{problem_id}/solver-runs"),
    ("GET", "/solver-runs/{run_id}"), ("POST", "/solver-runs/{run_id}/cancel"),
    ("GET", "/solver-runs/{run_id}/events"),
    ("GET", "/problems/{problem_id}/schedules"), ("GET", "/schedules/compare"),
    ("GET", "/schedules/{schedule_id}"), ("POST", "/schedules/{schedule_id}/approve"),
    ("GET", "/schedules/{schedule_id}/export.csv"), ("POST", "/schedules/{schedule_id}/replan"),
    ("GET", "/finance/defaults"), ("GET", "/finance/templates"),
    ("POST", "/finance/templates/{template_id}/instantiate"), ("POST", "/finance/preview"),
    ("GET", "/finance/plans"), ("POST", "/finance/plans"), ("POST", "/finance/plans/import"),
    ("GET", "/finance/plans/{plan_id}"), ("PUT", "/finance/plans/{plan_id}"),
    ("DELETE", "/finance/plans/{plan_id}"), ("GET", "/finance/plans/{plan_id}/export"),
    ("POST", "/finance/plans/{plan_id}/validate"), ("POST", "/finance/plans/{plan_id}/runs"),
    ("POST", "/finance/plans/{plan_id}/what-if"), ("GET", "/finance/plans/{plan_id}/runs"),
    ("GET", "/finance/runs/{run_id}"), ("POST", "/finance/runs/{run_id}/cancel"),
    ("GET", "/finance/runs/{run_id}/events"), ("GET", "/finance/plans/{plan_id}/results"),
    ("GET", "/finance/results/compare"), ("GET", "/finance/results/{result_id}"),
    ("GET", "/finance/results/{result_id}/contributions.csv"),
    ("POST", "/finance/results/{result_id}/send-to-planner"),
    ("GET", "/intake/capabilities"),
    *{("POST", f"/intake/{d}/{step}") for d in ("schedule", "finance")
      for step in ("describe", "answer", "build", "table/parse", "table/apply")},
})

# M1-DESIGN 9.3 / 9.5: the 77 manufacturing operations (all require_user; CSRF on unsafe methods).
_M = "/mfg"
MFG_PROTECTED = frozenset({
    ("GET", f"{_M}/meta"), ("GET", f"{_M}/summary"), ("GET", f"{_M}/plant"), ("PUT", f"{_M}/plant"),
    ("GET", f"{_M}/items"), ("POST", f"{_M}/items"), ("GET", f"{_M}/items/{{item_id}}"),
    ("PUT", f"{_M}/items/{{item_id}}"), ("DELETE", f"{_M}/items/{{item_id}}"),
    ("GET", f"{_M}/items/{{item_id}}/explosion"), ("GET", f"{_M}/items/{{item_id}}/where-used"),
    ("GET", f"{_M}/items/{{item_id}}/boms"), ("GET", f"{_M}/items/{{item_id}}/routings"),
    *{op for doc, pid in (("boms", "bom_id"), ("routings", "routing_id")) for op in (
        ("POST", f"{_M}/{doc}"), ("GET", f"{_M}/{doc}/{{{pid}}}"), ("PUT", f"{_M}/{doc}/{{{pid}}}"),
        ("DELETE", f"{_M}/{doc}/{{{pid}}}"), ("POST", f"{_M}/{doc}/{{{pid}}}/release"),
        ("POST", f"{_M}/{doc}/{{{pid}}}/obsolete"), ("POST", f"{_M}/{doc}/{{{pid}}}/copy"))},
    ("GET", f"{_M}/routings/{{routing_id}}/time-preview"),
    *{op for coll, pid in (("groups", "group_id"), ("lines", "line_id")) for op in (
        ("GET", f"{_M}/{coll}"), ("POST", f"{_M}/{coll}"), ("GET", f"{_M}/{coll}/{{{pid}}}"),
        ("PUT", f"{_M}/{coll}/{{{pid}}}"), ("DELETE", f"{_M}/{coll}/{{{pid}}}"))},
    ("GET", f"{_M}/lines/{{line_id}}/windows"),
    ("GET", f"{_M}/shift-templates"), ("POST", f"{_M}/shift-templates"), ("POST", f"{_M}/shift-templates/preview"),
    ("GET", f"{_M}/shift-templates/{{shift_template_id}}"), ("PUT", f"{_M}/shift-templates/{{shift_template_id}}"),
    ("DELETE", f"{_M}/shift-templates/{{shift_template_id}}"),
    *{op for coll, pid in (("shift-assignments", "assignment_id"), ("calendar-exceptions", "exception_id"),
                           ("skills", "skill_id"), ("tool-pools", "tool_pool_id"), ("operators", "operator_id"))
      for op in (("GET", f"{_M}/{coll}"), ("POST", f"{_M}/{coll}"), ("PUT", f"{_M}/{coll}/{{{pid}}}"),
                 ("DELETE", f"{_M}/{coll}/{{{pid}}}"))},
    ("GET", f"{_M}/operators/{{operator_id}}"),
    ("GET", f"{_M}/health"),
    ("POST", f"{_M}/imports"), ("GET", f"{_M}/imports/{{import_id}}"), ("PUT", f"{_M}/imports/{{import_id}}/mapping"),
    ("POST", f"{_M}/imports/{{import_id}}/commit"), ("DELETE", f"{_M}/imports/{{import_id}}"),
    ("GET", f"{_M}/export"), ("GET", f"{_M}/import-templates"),
    ("GET", f"{_M}/samples"), ("POST", f"{_M}/samples/{{sample_id}}/load"), ("POST", f"{_M}/reset"),
})
assert len(MFG_PROTECTED) == 77, len(MFG_PROTECTED)

PARAM = re.compile(r"\{([a-z_]+)\}")


def openapi_operations(app) -> set[tuple[str, str]]:
    """(METHOD, path without /api/v1) for every documented operation under /api/v1 (black-box: OpenAPI)."""
    out: set[tuple[str, str]] = set()
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith(API):
            continue
        for method in ops:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                out.add((method.upper(), path[len(API):]))
    return out


def path_params(path: str) -> list[str]:
    return PARAM.findall(path)


def fill_path(path: str, ids: dict[str, str] | None = None) -> str:
    """Substitute path parameters; unknown names get a random id."""
    ids = ids or {}
    return PARAM.sub(lambda m: ids.get(m.group(1), f"x{uuid.uuid4().hex}"), path)

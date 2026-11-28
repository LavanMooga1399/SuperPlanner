"""Signature policies (M7-DESIGN 4.3): seeded defaults per plant, fixed actions, validation and step logic (pure).

Keys are `(record_type, action)`. `inspection_lot.decide` has two policies: `decide` (incoming, in-process) and
`decide_final` (final inspection; signers = QA settings `final_release_role`, password + TOTP). Its step meaning is
`released` (accept) or `rejected` (reject) - `expected_meanings`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ALL_QA = ["qa_inspector", "qa_engineer", "qa_approver"]
#: (record_type, action) -> (steps, auth, distinct_signers, exclude_author)
DEFAULTS: dict[tuple[str, str], tuple[list[dict[str, Any]], str, bool, bool]] = {
    ("inspection_plan", "approve"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password", True, False),
    ("sampling_scheme", "approve"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password", True, False),
    ("inspection_lot", "decide"): ([{"meaning": "released", "roles": ALL_QA}], "password", True, False),
    ("inspection_lot", "decide_final"): ([{"meaning": "released", "roles": ["qa_approver"]}], "password_totp", True,
                                         False),
    ("hold", "release"): ([{"meaning": "released", "roles": ["qa_approver"]}], "password", True, False),
    ("ncr", "approve"): ([{"meaning": "reviewed", "roles": ["qa_engineer"]},
                          {"meaning": "approved", "roles": ["qa_approver"]}], "password", True, True),
    ("ncr", "close"): ([{"meaning": "closed", "roles": ["qa_approver"]}], "password", True, False),
    ("capa", "approve_plan"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password", True, False),
    ("capa", "verify"): ([{"meaning": "verified", "roles": ["qa_approver"]}], "password", True, False),
    ("capa", "close"): ([{"meaning": "closed", "roles": ["qa_approver"]}], "password", True, False),
    ("complaint", "close"): ([{"meaning": "closed", "roles": ["qa_engineer", "qa_approver"]}], "password", True,
                             False),
    ("field_action", "approve"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password_totp", True, False),
    ("field_action", "close"): ([{"meaning": "closed", "roles": ["qa_approver"]}], "password_totp", True, False),
    ("calibration", "record"): ([{"meaning": "performed", "roles": ["metrology", "qa_engineer"]}], "password", True,
                                False),
    ("equipment", "return_to_service"): ([{"meaning": "approved", "roles": ["qa_engineer", "qa_approver"]}],
                                         "password", True, False),
    ("eco", "approve"): ([{"meaning": "approved", "roles": ["approver", "qa_approver"]}], "password", True, False),
    ("esig_policy", "update"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password_totp", True, False),
    ("qa_settings", "sor_change"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password", True, False),
    ("plant", "part11_on"): ([{"meaning": "approved", "roles": ["owner", "plant_admin"]}], "password_totp", True,
                             False),
    # M8-DESIGN 8: sterility release of a sterilisation load (always signed)
    ("ster_load", "release"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password", True, False),
    # M9-DESIGN 6.6: S&OP cycle approval in the network workspace (always signed)
    ("sop_cycle", "approve"): ([{"meaning": "reviewed", "roles": ["plant_manager"]},
                                {"meaning": "approved", "roles": ["executive"]}], "password", True, False),
    # M10-DESIGN 3: eDHR release (last step = QA settings `final_release_role`; meaning released / rejected)
    ("dhr", "release"): ([{"meaning": "reviewed", "roles": ["qa_engineer", "qa_approver"]},
                          {"meaning": "released", "roles": ["qa_approver"]}], "password_totp", True, False),
    ("deviation", "approve"): ([{"meaning": "reviewed", "roles": ["qa_engineer"]},
                                {"meaning": "approved", "roles": ["qa_approver"]}], "password", True, False),
    ("customer_agreement", "approve"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password", True,
                                        False),
    ("coa", "approve"): ([{"meaning": "approved", "roles": ["qa_approver"]}], "password", True, False),
    ("eco", "approve_label"): ([{"meaning": "reviewed", "roles": ["approver"]},
                                {"meaning": "approved", "roles": ["qa_approver"]}], "password", True, True),
    ("udi_device", "approve"): ([{"meaning": "approved", "roles": ["regulatory", "qa_approver"]}], "password", True,
                                False),
    ("label_job", "reconcile"): ([{"meaning": "verified", "roles": ["qa_inspector", "qa_engineer", "supervisor"]}],
                                 "password", True, False),
    ("validation_package", "approve"): ([{"meaning": "reviewed", "roles": ["qa_engineer"]},
                                         {"meaning": "approved", "roles": ["qa_approver"]}], "password_totp", True,
                                        False),
    ("plant", "assistant_on"): ([{"meaning": "approved", "roles": ["owner", "plant_admin"]}], "password_totp", True,
                                False),
    ("int_endpoint", "cross_region"): ([{"meaning": "approved", "roles": ["owner", "plant_admin"]}],
                                       "password_totp", True, False),
}
#: policies seeded only in the organisation's network workspace (M9 6.6)
NETWORK_ONLY: frozenset[tuple[str, str]] = frozenset({("sop_cycle", "approve")})
#: actions whose last step cannot be removed (4.3)
FIXED: frozenset[tuple[str, str]] = frozenset({("esig_policy", "update"), ("plant", "part11_on"), ("dhr", "release"),
                                               ("plant", "assistant_on"), ("int_endpoint", "cross_region")})
#: actions that create their record when signed: one step only (14)
SINGLE_STEP: frozenset[tuple[str, str]] = frozenset({("calibration", "record")})
#: actions that are signed even when the plant is not in Part 11 mode
ALWAYS: frozenset[tuple[str, str]] = frozenset({("plant", "part11_on"), ("ster_load", "release"),
                                               ("sop_cycle", "approve"),
                                               # M10-DESIGN 0.3, 0.7, 6, 8, 9.1: signed wherever they are used
                                               ("dhr", "release"), ("deviation", "approve"),
                                               ("customer_agreement", "approve"), ("coa", "approve"),
                                               ("eco", "approve_label"), ("udi_device", "approve"),
                                               ("validation_package", "approve"), ("plant", "assistant_on"),
                                               ("int_endpoint", "cross_region")})
#: M10-DESIGN 3: signed in Part 11 mode and whenever the service asks for it (`label_job.reconcile` when diff != 0)
CONDITIONAL: frozenset[tuple[str, str]] = frozenset({("label_job", "reconcile")})
PLANT_ROLES: frozenset[str] = frozenset({"owner", "plant_admin", "planner", "purchaser", "store_keeper", "approver",
                                         "viewer", "operator", "supervisor", "qa_inspector", "qa_engineer",
                                         "qa_approver", "metrology", "plant_manager", "auditor", "executive",
                                         "regulatory", "labeling"})
AUTH_RANK = {"password": 0, "password_totp": 1}


@dataclass(frozen=True)
class Policy:
    id: str | None
    record_type: str
    action: str
    steps: list[dict[str, Any]]
    auth: str
    distinct_signers: bool
    exclude_author: bool
    version: int


def default(record_type: str, action: str, final_release_role: str = "qa_approver") -> Policy | None:
    d = DEFAULTS.get((record_type, action))
    if d is None:
        return None
    steps = [dict(x, roles=list(x["roles"])) for x in d[0]]
    if (record_type, action) == ("inspection_lot", "decide_final"):
        steps[0]["roles"] = [final_release_role]
    if (record_type, action) == ("dhr", "release"):           # M10-DESIGN 0.3: released by final_release_role
        steps[-1]["roles"] = [final_release_role]
    return Policy(None, record_type, action, steps, d[1], d[2], d[3], 1)


def validate(record_type: str, action: str, steps: list[dict[str, Any]], auth: str) -> str | None:
    """None when valid, else the reason (422 `ESIG_POLICY_INVALID`)."""
    key = (record_type, action)
    if key not in DEFAULTS:
        return f"No signature policy exists for {record_type}.{action}."
    if key in FIXED and not steps:
        return "This action is always signed: keep at least one step."
    if key in SINGLE_STEP and len(steps) > 1:
        return "This action creates its record when signed: one step only."
    if key in FIXED and AUTH_RANK.get(auth, 0) < AUTH_RANK[DEFAULTS[key][1]]:
        return "The authentication level of this action cannot be lowered."
    if key == ("sop_cycle", "approve") and not any(st.get("meaning") == "approved" for st in steps):
        return "The S&OP approval keeps at least one 'approved' step."
    if key == ("dhr", "release") and (not steps or steps[-1].get("meaning") != "released"):
        return "The eDHR release ends with a 'released' step."
    for st in steps:
        bad = [r for r in st["roles"] if r not in PLANT_ROLES]
        if bad:
            return f"Unknown plant role(s): {', '.join(bad)}."
    return None


def expected_meanings(action: str, step: dict[str, Any], decision: str | None) -> list[str]:
    if action in ("decide", "decide_final"):
        return ["rejected"] if decision == "reject" else ["released"]
    if action == "release" and step.get("meaning") == "released" and decision == "rejected":   # M10 eDHR reject
        return ["rejected"]
    return [step["meaning"]]


def step_block(policy: Policy, step_index: int, roles: tuple[str, ...], user_id: str, earlier: list[str],
               author_id: str | None) -> str | None:
    """Why `user_id` may not sign step `step_index` (0-based): None or an error code."""
    st = policy.steps[step_index]
    if not set(roles) & set(st["roles"]):
        return "ESIG_ROLE"
    if policy.distinct_signers and user_id in earlier:
        return "ESIG_SAME_SIGNER"
    if policy.exclude_author and author_id is not None and author_id == user_id:
        return "ESIG_AUTHOR"
    return None


__all__ = ["ALWAYS", "AUTH_RANK", "CONDITIONAL", "DEFAULTS", "FIXED", "PLANT_ROLES", "Policy", "SINGLE_STEP", "default",
           "expected_meanings", "step_block", "validate"]

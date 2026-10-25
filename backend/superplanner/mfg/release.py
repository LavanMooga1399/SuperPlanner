"""Release and document rules (M1-DESIGN 4.2, 3.5, 3.6; review R3). Pure: used by the API services and by
`io.plan` for `release: true`. Nothing here mutates the dataset; the caller applies `superseded`.

Error dicts of `validate_*_document` have the A 14 shape `{"loc", "msg", "type"}`; `type` tells the service which
API code applies: `mfg_unknown_reference` -> 422 `MFG_UNKNOWN_REFERENCE`, `mfg_bom_cycle` -> 422 `MFG_BOM_CYCLE`,
anything else -> 422 `VALIDATION_ERROR`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from .bom import would_create_cycle
from .dataset import MfgDataset, windows_overlap
from .health import doc_label, eref, make_issue
from .model import BomLineInput, HealthIssue, OperationInput
from .units import same_dimension


class ReleaseError(ValueError):
    """A release request that is invalid as such (API 422 `VALIDATION_ERROR`), e.g. `supersede_previous` without
    an `effective_from`, or an `effective_from` not before the document's `effective_to`."""


def _candidate(doc: Any, effective_from: date | None, supersede_previous: bool) -> SimpleNamespace:
    new_from = effective_from if effective_from is not None else doc.effective_from
    if supersede_previous and new_from is None:
        raise ReleaseError("Releasing with supersede_previous needs an effective_from date.")
    if new_from is not None and doc.effective_to is not None and not new_from < doc.effective_to:
        raise ReleaseError("effective_from must be before the document's effective_to.")
    return SimpleNamespace(effective_from=new_from, effective_to=doc.effective_to, serial_from=doc.serial_from,
                           serial_to=doc.serial_to)


def _supersede(ds: MfgDataset, doc: Any, others: list[Any], cand: SimpleNamespace, supersede: bool, code: str,
               typ: str) -> tuple[list[HealthIssue], list[dict[str, Any]]]:
    issues: list[HealthIssue] = []
    superseded: list[dict[str, Any]] = []
    for o in sorted(others, key=lambda d: (d.effective_from or date.min, d.version, d.id)):
        if not windows_overlap(cand, o):
            continue
        if supersede and (o.effective_from or date.min) < cand.effective_from:
            superseded.append({"id": o.id, "version": o.version, "effective_to": cand.effective_from})
            continue
        kw = {"prio": doc.priority} if typ == "routing" else {}
        issues.append(make_issue(ds, code, typ, doc.id, related=[eref(ds, typ, o.id)], doc=doc_label(doc),
                                 other=doc_label(o), pn=ds.items[doc.item_id].part_number, **kw))
    return issues, superseded


def bom_release_issues(ds: MfgDataset, bom_id: str, effective_from: date | None, supersede_previous: bool
                       ) -> tuple[list[HealthIssue], list[dict[str, Any]]]:
    """(blocking issues, superseded `[{id, version, effective_to}]`). `effective_from=None` keeps the document's
    own `effective_from`."""
    b = ds.boms[bom_id]
    item = ds.items[b.item_id]
    cand = _candidate(b, effective_from, supersede_previous)
    issues: list[HealthIssue] = []
    ctx = {"doc": doc_label(b), "pn": item.part_number}
    if not b.lines:
        issues.append(make_issue(ds, "MFG_BOM_EMPTY", "bom", b.id, **ctx))
    others_edges = [(o.item_id, ln.child_item_id) for o in ds.boms.values() if o.id != b.id
                    and o.status != "obsolete" for ln in o.lines]
    cyc = would_create_cycle(others_edges, [(b.item_id, ln.child_item_id) for ln in b.lines])
    if cyc is not None:
        issues.append(make_issue(ds, "MFG_BOM_CYCLE", "item", cyc[0],
                                 path=" -> ".join(ds.items[i].part_number if i in ds.items else i for i in cyc)))
    groups: dict[str, list[Any]] = {}
    for ln in b.lines:
        ch = ds.items.get(ln.child_item_id)
        if ch is None:
            continue
        if not same_dimension(ln.uom, ch.uom):
            issues.append(make_issue(ds, "MFG_UOM_MISMATCH", "bom_line", ln.id, field="uom", fn=ln.find_number,
                                     uom=ln.uom, child=ch.part_number, child_uom=ch.uom, **ctx))
        if not ch.active:
            issues.append(make_issue(ds, "MFG_INACTIVE_COMPONENT", "bom_line", ln.id, field="child_item_id",
                                     fn=ln.find_number, child=ch.part_number, **ctx))
        if ln.alt_group is not None:
            groups.setdefault(ln.alt_group, []).append(ln)
    for grp, members in groups.items():
        if not any(m.alt_priority == 1 for m in members):
            issues.append(make_issue(ds, "MFG_ALT_NO_PRIMARY", "bom_line", members[0].id, field="alt_priority",
                                     grp=grp, **ctx))
        seen: set[int] = set()
        for m in members:
            if m.alt_priority in seen:
                issues.append(make_issue(ds, "MFG_ALT_DUPLICATE_PRIORITY", "bom_line", m.id, field="alt_priority",
                                         grp=grp, prio=m.alt_priority, **ctx))
            seen.add(m.alt_priority)
    if b.serial_from is not None and not item.serialized:
        issues.append(make_issue(ds, "MFG_SERIAL_NOT_ALLOWED", "item", item.id, field="serial_from",
                                 pn=item.part_number, what="BOM", doc=doc_label(b)))
    others = [o for o in ds.boms_by_item.get(b.item_id, []) if o.id != b.id and o.status == "released"]
    ov, superseded = _supersede(ds, b, others, cand, supersede_previous, "MFG_BOM_EFFECTIVITY_OVERLAP", "bom")
    return issues + ov, superseded


def routing_release_issues(ds: MfgDataset, routing_id: str, effective_from: date | None, supersede_previous: bool
                           ) -> tuple[list[HealthIssue], list[dict[str, Any]]]:
    r = ds.routings[routing_id]
    item = ds.items[r.item_id]
    cand = _candidate(r, effective_from, supersede_previous)
    issues: list[HealthIssue] = []
    if not r.operations:
        issues.append(make_issue(ds, "MFG_ROUTING_NO_OPERATIONS", "routing", r.id, doc=doc_label(r),
                                 pn=item.part_number))
    if r.serial_from is not None and not item.serialized:
        issues.append(make_issue(ds, "MFG_SERIAL_NOT_ALLOWED", "item", item.id, field="serial_from",
                                 pn=item.part_number, what="routing", doc=doc_label(r)))
    others = [o for o in ds.routings_by_item.get(r.item_id, []) if o.id != r.id and o.status == "released"
              and o.priority == r.priority]
    ov, superseded = _supersede(ds, r, others, cand, supersede_previous, "MFG_ROUTING_EFFECTIVITY_OVERLAP",
                                "routing")
    return issues + ov, superseded


def validate_bom_document(ds: MfgDataset, item_id: str, lines: list[BomLineInput]) -> list[dict[str, Any]]:
    """Document rules of 3.5 on every write (drafts too): unknown child, child == parent, duplicate
    `(find_number, child)`, duplicate child inside an alternate group."""
    errors: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], int] = {}
    alt: dict[tuple[str, str], int] = {}
    for i, ln in enumerate(lines):
        loc = ["body", "lines", i]
        if ln.child_item_id not in ds.items:
            errors.append({"loc": loc + ["child_item_id"], "msg": f"Item {ln.child_item_id!r} was not found.",
                           "type": "mfg_unknown_reference"})
            continue
        if ln.child_item_id == item_id:
            errors.append({"loc": loc + ["child_item_id"], "msg": "An item cannot contain itself.",
                           "type": "mfg_bom_cycle"})
        k = (ln.find_number, ln.child_item_id)
        if k in seen:
            errors.append({"loc": loc + ["find_number"], "msg": f"Find number {ln.find_number} uses this item "
                           f"already (line {seen[k] + 1}).", "type": "duplicate_line"})
        else:
            seen[k] = i
        if ln.alt_group is not None:
            ak = (ln.alt_group, ln.child_item_id)
            if ak in alt:
                errors.append({"loc": loc + ["child_item_id"], "msg": f"Alternate group {ln.alt_group} lists this "
                               f"item twice (line {alt[ak] + 1}).", "type": "duplicate_alternate"})
            else:
                alt[ak] = i
    return errors


def validate_routing_document(ds: MfgDataset, item_id: str, operations: list[OperationInput]) -> list[dict[str, Any]]:
    """Document rules of 3.6: `seq` unique; group, skill and tool pools exist."""
    errors: list[dict[str, Any]] = []
    seen: dict[int, int] = {}
    del item_id
    for i, op in enumerate(operations):
        loc = ["body", "operations", i]
        if op.seq in seen:
            errors.append({"loc": loc + ["seq"], "msg": f"Operation number {op.seq} is used twice (operation "
                           f"{seen[op.seq] + 1}).", "type": "duplicate_seq"})
        else:
            seen[op.seq] = i
        if op.group_id not in ds.groups:
            errors.append({"loc": loc + ["group_id"], "msg": f"Stage {op.group_id!r} was not found.",
                           "type": "mfg_unknown_reference"})
        if op.skill_id is not None and op.skill_id not in ds.skills:
            errors.append({"loc": loc + ["skill_id"], "msg": f"Skill {op.skill_id!r} was not found.",
                           "type": "mfg_unknown_reference"})
        for j, t in enumerate(op.tools):
            if t.tool_pool_id not in ds.tool_pools:
                errors.append({"loc": loc + ["tools", j, "tool_pool_id"], "msg": f"Tool pool {t.tool_pool_id!r} "
                               "was not found.", "type": "mfg_unknown_reference"})
    return errors

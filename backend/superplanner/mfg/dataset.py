"""In-memory snapshot of one owner's manufacturing data (M1-DESIGN 5) and the indexes the computations use.

`MfgDataset` is built by `api.mfg.repo.load_dataset` or `bundle.bundle_to_dataset`; both call `link(ds)`, which
fills every denormalised record field (refs and counts) from the ids. `BomIndex` / `ParentIndex` are what
`bom.explode` / `bom.where_used` need; the repository builds them level-wise without loading the whole dataset.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from typing import Any, Literal

from .model import (BomLineRecord, BomRecord, CalendarExceptionRecord, GroupRecord, ItemRecord, ItemRef,
                    LineRecord, OperationRecord, OperatorRecord, PlantRecord, Ref, RoutingRecord,
                    ShiftAssignmentRecord, ShiftTemplateRecord, SkillRecord, TargetRef, ToolPoolRecord)

# ---------------------------------------------------------------- ordering and effectivity helpers


def natural(fn: str) -> tuple[int, int, str]:
    """Find-number order (3.5): numeric find numbers first, by value; others after, by text."""
    return (0, int(fn), "") if fn.isdigit() else (1, 0, fn)


def line_sort_key(line: BomLineRecord) -> tuple[Any, ...]:
    pn = line.child.part_number if getattr(line, "child", None) is not None else ""
    return (natural(line.find_number), line.alt_group or "", line.alt_priority, pn, line.id)


def date_window_contains(doc: Any, on: date) -> bool:
    return (doc.effective_from is None or doc.effective_from <= on) and \
        (doc.effective_to is None or on < doc.effective_to)


def is_effective(doc: Any, on: date, serial: int | None = None) -> bool:
    """4.1: released, the date inside `[from, to)`, generic or the serial inside the serial range."""
    if doc.status != "released" or not date_window_contains(doc, on):
        return False
    if doc.serial_from is None:
        return True
    return serial is not None and doc.serial_from <= serial <= doc.serial_to


def _pick_key(doc: Any) -> tuple[Any, ...]:
    return (doc.effective_from or date.min, doc.version, doc.revision, doc.id)


def pick_effective(docs: Iterable[Any], on: date, serial: int | None = None) -> Any | None:
    """Serial-specific effective documents win over generic ones; then the highest `(effective_from, version)`."""
    cands = [d for d in docs if is_effective(d, on, serial)]
    specific = [d for d in cands if d.serial_from is not None]
    pool = specific or cands
    return max(pool, key=_pick_key) if pool else None


def windows_overlap(a: Any, b: Any) -> bool:
    """4.1 overlap of two documents: date windows intersect and both generic or both specific with intersecting
    serial ranges (generic + specific never overlap)."""
    lo_a, lo_b = a.effective_from or date.min, b.effective_from or date.min
    hi_a, hi_b = a.effective_to or date.max, b.effective_to or date.max
    if not (lo_a < hi_b and lo_b < hi_a):
        return False
    if (a.serial_from is None) != (b.serial_from is None):
        return False
    if a.serial_from is None:
        return True
    return a.serial_from <= b.serial_to and b.serial_from <= a.serial_to


# ---------------------------------------------------------------- dataset


@dataclass
class MfgDataset:
    plant: PlantRecord
    items: dict[str, ItemRecord] = field(default_factory=dict)
    boms: dict[str, BomRecord] = field(default_factory=dict)
    routings: dict[str, RoutingRecord] = field(default_factory=dict)
    groups: dict[str, GroupRecord] = field(default_factory=dict)
    lines: dict[str, LineRecord] = field(default_factory=dict)
    shift_templates: dict[str, ShiftTemplateRecord] = field(default_factory=dict)
    shift_assignments: dict[str, ShiftAssignmentRecord] = field(default_factory=dict)
    calendar_exceptions: dict[str, CalendarExceptionRecord] = field(default_factory=dict)
    skills: dict[str, SkillRecord] = field(default_factory=dict)
    operators: dict[str, OperatorRecord] = field(default_factory=dict)
    tool_pools: dict[str, ToolPoolRecord] = field(default_factory=dict)

    # derived (lazy). Call `invalidate()` after mutating the dataset.
    _DERIVED = ("boms_by_item", "routings_by_item", "lines_by_group", "parents_of", "operation_routing",
                "items_by_pn")

    def invalidate(self) -> None:
        for name in self._DERIVED:
            self.__dict__.pop(name, None)

    @cached_property
    def boms_by_item(self) -> dict[str, list[BomRecord]]:
        out: dict[str, list[BomRecord]] = {}
        for b in sorted(self.boms.values(), key=lambda b: (b.revision, b.version, b.id)):
            out.setdefault(b.item_id, []).append(b)
        return out

    @cached_property
    def routings_by_item(self) -> dict[str, list[RoutingRecord]]:
        out: dict[str, list[RoutingRecord]] = {}
        for r in sorted(self.routings.values(), key=lambda r: (r.priority, r.code, r.revision, r.version, r.id)):
            out.setdefault(r.item_id, []).append(r)
        return out

    @cached_property
    def lines_by_group(self) -> dict[str, list[LineRecord]]:
        out: dict[str, list[LineRecord]] = {}
        for ln in sorted(self.lines.values(), key=lambda x: (x.code, x.id)):
            out.setdefault(ln.group_id, []).append(ln)
        return out

    @cached_property
    def parents_of(self) -> dict[str, list[tuple[BomRecord, BomLineRecord]]]:
        """child item id -> (BOM, line) of every non-obsolete BOM using it."""
        out: dict[str, list[tuple[BomRecord, BomLineRecord]]] = {}
        for b in self.boms.values():
            if b.status == "obsolete":
                continue
            for ln in b.lines:
                out.setdefault(ln.child_item_id, []).append((b, ln))
        return out

    @cached_property
    def operation_routing(self) -> dict[str, RoutingRecord]:
        return {op.id: r for r in self.routings.values() for op in r.operations}

    @cached_property
    def items_by_pn(self) -> dict[str, ItemRecord]:
        return {i.part_number: i for i in self.items.values()}


def item_ref(i: ItemRecord) -> ItemRef:
    return ItemRef.model_construct(id=i.id, part_number=i.part_number, revision=i.revision,
                                   description=i.description, uom=i.uom, make_buy=i.make_buy, active=i.active)


def ref(x: Any) -> Ref:
    return Ref.model_construct(id=x.id, code=x.code, name=x.name)


def _missing_item(item_id: str) -> ItemRef:
    return ItemRef.model_construct(id=item_id, part_number="?", revision="", description="", uom="EA",
                                   make_buy="buy", active=False)


def _missing_ref(x_id: str | None) -> Ref:
    return Ref.model_construct(id=x_id or "", code="?", name="")


def link(ds: MfgDataset) -> MfgDataset:
    """Fill every denormalised field (refs, counts, line order) from the ids. Idempotent."""
    ds.invalidate()
    refs = {i: item_ref(it) for i, it in ds.items.items()}

    def iref(item_id: str) -> ItemRef:
        return refs.get(item_id) or _missing_item(item_id)

    def gref(gid: str | None) -> Ref:
        g = ds.groups.get(gid or "")
        return ref(g) if g is not None else _missing_ref(gid)

    has_bom: set[str] = set()
    has_routing: set[str] = set()
    parents: dict[str, set[str]] = {}
    for b in ds.boms.values():
        b.item = iref(b.item_id)
        for ln in b.lines:
            ln.child = iref(ln.child_item_id)
        b.lines.sort(key=line_sort_key)
        if b.status != "obsolete":
            has_bom.add(b.item_id)
            for ln in b.lines:
                parents.setdefault(ln.child_item_id, set()).add(b.item_id)
    skill_ops: dict[str, int] = {}
    tool_ops: dict[str, int] = {}
    for r in ds.routings.values():
        r.item = iref(r.item_id)
        r.operations.sort(key=lambda o: o.seq)
        if r.status != "obsolete":
            has_routing.add(r.item_id)
        for op in r.operations:
            op.group = gref(op.group_id)
            if op.skill_id is not None:
                s = ds.skills.get(op.skill_id)
                op.skill = ref(s) if s is not None else _missing_ref(op.skill_id)
                skill_ops[op.skill_id] = skill_ops.get(op.skill_id, 0) + 1
            else:
                op.skill = None
            for t in op.tools:
                tp = ds.tool_pools.get(t.tool_pool_id)
                t.tool_pool = ref(tp) if tp is not None else _missing_ref(t.tool_pool_id)
            for pool_id in {t.tool_pool_id for t in op.tools}:
                tool_ops[pool_id] = tool_ops.get(pool_id, 0) + 1
    for i, it in ds.items.items():
        it.has_bom = i in has_bom
        it.has_routing = i in has_routing
        it.used_in_count = len(parents.get(i, ()))
    line_count: dict[str, int] = {}
    for ln in ds.lines.values():
        ln.group = gref(ln.group_id)
        ln.eligible_items = [iref(x) for x in ln.eligible_item_ids]
        line_count[ln.group_id] = line_count.get(ln.group_id, 0) + 1
    for g in ds.groups.values():
        g.line_count = line_count.get(g.id, 0)

    def target(type_: str, gid: str | None, lid: str | None) -> TargetRef | None:
        if type_ == "group":
            g = ds.groups.get(gid or "")
            return TargetRef.model_construct(type="group", id=gid or "", code=g.code if g else "?",
                                             name=g.name if g else "")
        if type_ == "line":
            ln = ds.lines.get(lid or "")
            return TargetRef.model_construct(type="line", id=lid or "", code=ln.code if ln else "?",
                                             name=ln.name if ln else "")
        return None

    tpl_assign: dict[str, int] = {}
    for a in ds.shift_assignments.values():
        t = ds.shift_templates.get(a.shift_template_id)
        a.template = ref(t) if t is not None else _missing_ref(a.shift_template_id)
        a.target = target(a.target_type, a.group_id, a.line_id)  # type: ignore[assignment]
        tpl_assign[a.shift_template_id] = tpl_assign.get(a.shift_template_id, 0) + 1
    for e in ds.calendar_exceptions.values():
        e.target = target(e.scope, e.group_id, e.line_id)
    tpl_ops: dict[str, int] = {}
    skill_holders: dict[str, int] = {}
    for o in ds.operators.values():
        o.skills = [ref(ds.skills[s]) if s in ds.skills else _missing_ref(s) for s in o.skill_ids]
        o.skills.sort(key=lambda r: r.code)
        for s in o.skill_ids:
            skill_holders[s] = skill_holders.get(s, 0) + 1
        if o.shift_template_id is not None:
            t = ds.shift_templates.get(o.shift_template_id)
            o.shift_template = ref(t) if t is not None else _missing_ref(o.shift_template_id)
            tpl_ops[o.shift_template_id] = tpl_ops.get(o.shift_template_id, 0) + 1
        else:
            o.shift_template = None
        o.home_group = gref(o.home_group_id) if o.home_group_id is not None else None
    for t in ds.shift_templates.values():
        t.assignment_count = tpl_assign.get(t.id, 0)
        t.operator_count = tpl_ops.get(t.id, 0)
    for s in ds.skills.values():
        s.operator_count = skill_holders.get(s.id, 0)
        s.operation_count = skill_ops.get(s.id, 0)
    for tp in ds.tool_pools.values():
        tp.operation_count = tool_ops.get(tp.id, 0)
    return ds


# ---------------------------------------------------------------- indexes


def primary_ops_of(routing: RoutingRecord | None) -> list[OperationRecord]:
    return sorted(routing.operations, key=lambda o: o.seq) if routing is not None else []


class BomIndex:
    """What `explode` needs: items, the effective BOM per make/phantom item (None if none) and the operations of
    the primary effective routing per make item. `routing_ids` (item -> primary routing id), `on` and `serial` are
    echoed in the explosion (keyword-only extensions of the M 5 signature)."""

    def __init__(self, items: dict[str, ItemRecord], effective: dict[str, BomRecord | None],
                 primary_ops: dict[str, list[OperationRecord]], *, routing_ids: dict[str, str] | None = None,
                 on: date | None = None, serial: int | None = None):
        self.items = items
        self.effective = effective
        self.primary_ops = primary_ops
        self.routing_ids = routing_ids or {}
        self.on = on
        self.serial = serial

    @classmethod
    def from_dataset(cls, ds: MfgDataset, on: date, serial: int | None = None) -> "BomIndex":
        from .routing import effective_routings

        effective: dict[str, BomRecord | None] = {}
        ops: dict[str, list[OperationRecord]] = {}
        rids: dict[str, str] = {}
        for item_id, it in ds.items.items():
            if it.make_buy in ("make", "phantom"):
                effective[item_id] = pick_effective(ds.boms_by_item.get(item_id, ()), on, serial)
            if it.make_buy == "make":
                rs = effective_routings(ds, item_id, on, serial)
                if rs:
                    ops[item_id] = primary_ops_of(rs[0])
                    rids[item_id] = rs[0].id
        return cls(ds.items, effective, ops, routing_ids=rids, on=on, serial=serial)


class ParentIndex:
    """What `where_used` needs: items and child item id -> [(BOM header, line)] of the BOMs in scope."""

    def __init__(self, items: dict[str, ItemRecord],
                 parent_lines: dict[str, list[tuple[BomRecord, BomLineRecord]]], *,
                 on: date | None = None, include: Literal["effective", "all"] = "effective"):
        self.items = items
        self.parent_lines = parent_lines
        self.on = on
        self.include = include

    @staticmethod
    def bom_in_scope(bom: Any, on: date | None, include: str) -> bool:
        """`all`: draft + released (obsolete never); `effective`: released and, if `on` is given, its date window
        contains `on` (serial ranges are not filtered)."""
        if include == "all":
            return bom.status != "obsolete"
        return bom.status == "released" and (on is None or date_window_contains(bom, on))

    @classmethod
    def from_dataset(cls, ds: MfgDataset, on: date | None,
                     include: Literal["effective", "all"]) -> "ParentIndex":
        out: dict[str, list[tuple[BomRecord, BomLineRecord]]] = {}
        for b in ds.boms.values():
            if not cls.bom_in_scope(b, on, include):
                continue
            for ln in b.lines:
                out.setdefault(ln.child_item_id, []).append((b, ln))
        return cls(ds.items, out, on=on, include=include)


def fingerprint(ds: MfgDataset) -> str:
    """sha256 of the canonical bundle (natural keys only: no ids, timestamps or row versions)."""
    import hashlib

    from .bundle import canonical_json, dataset_to_bundle

    return hashlib.sha256(canonical_json(dataset_to_bundle(ds))).hexdigest()

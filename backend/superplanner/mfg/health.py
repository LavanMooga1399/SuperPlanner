"""Data-health check, "Gate 1" (M1-DESIGN 7, review R1 and R8).

Scope rules (interpretations recorded in M 17.WP-A):
- *In use*: reachable from an end item over the union graph of released BOMs (of make/phantom items) whose window
  intersects the horizon `[as_of, as_of + horizon_days)`; one traversal.
- *Relevant routings*: released routings of active, in-use make items whose window intersects the horizon; their
  operations are the subjects of the stage/line/skill/tool errors (#5, #6, #7, #9, #20, #21, #24).
- *Live documents*: released and not ended before `as_of`. BOM-line errors (#12, #13, #16, #17) use live released
  BOMs; line warnings/infos (#23, #33, #34, #38) also look at drafts. #18 uses BOMs effective inside the horizon.
- An item's own documents (#3, #19, #28, overlaps, gaps) are evaluated at `as_of` and at each of their effectivity
  boundaries inside the horizon.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from .bom import find_cycles, refdes_count
from .calendar import (DAY, _clip_merge, line_detail, longest_window, operator_intervals, subtract, union)
from .dataset import (MfgDataset, date_window_contains, fingerprint, is_effective, line_sort_key, pick_effective,
                      windows_overlap)
from .limits import MAX_BOM_DEPTH, MAX_HEALTH_ISSUES, SKILL_COVERAGE_TOLERANCE_MINUTES
from .messages import CODE_INFO, CODE_ORDER, SEVERITY_ORDER, fix, fmt_date, message
from .model import (WEEKDAYS, BomRecord, EntityRef, HealthCounts, HealthIssue, HealthReport, ItemRecord,
                    OperationRecord, RoutingRecord)
from .routing import effective_routings, line_eligible, operation_minutes
from .units import UOM_CODES, is_count, same_dimension

# ---------------------------------------------------------------- labels and links (11.3)


def doc_label(doc: Any) -> str:
    if isinstance(doc, RoutingRecord):
        return f"{doc.code} v{doc.version}"
    return f"{doc.revision} v{doc.version}"


def _pn(ds: MfgDataset, item_id: str) -> str:
    it = ds.items.get(item_id)
    return it.part_number if it else item_id


def entity_label(ds: MfgDataset, type_: str, id_: str | None) -> str:
    if type_ == "plant":
        return ds.plant.name
    if type_ == "item":
        return _pn(ds, id_ or "")
    if type_ == "bom":
        b = ds.boms[id_ or ""]
        return f"{_pn(ds, b.item_id)} {doc_label(b)}"
    if type_ == "routing":
        r = ds.routings[id_ or ""]
        return f"{_pn(ds, r.item_id)} {doc_label(r)}"
    if type_ == "bom_line":
        for b in ds.boms.values():
            for ln in b.lines:
                if ln.id == id_:
                    return f"{_pn(ds, b.item_id)} {doc_label(b)} find {ln.find_number}"
        return id_ or ""
    if type_ == "operation":
        r = ds.operation_routing.get(id_ or "")
        if r is not None:
            op = next(o for o in r.operations if o.id == id_)
            return f"{_pn(ds, r.item_id)} {doc_label(r)} op {op.seq}"
        return id_ or ""
    if type_ == "shift_assignment":
        a = ds.shift_assignments[id_ or ""]
        t = ds.shift_templates.get(a.shift_template_id)
        tgt = ds.groups.get(a.group_id or "") if a.target_type == "group" else ds.lines.get(a.line_id or "")
        return f"{t.code if t else '?'} on {tgt.code if tgt else '?'} ({a.kind})"
    table = {"group": ds.groups, "line": ds.lines, "shift_template": ds.shift_templates, "skill": ds.skills,
             "operator": ds.operators, "tool_pool": ds.tool_pools, "calendar_exception": ds.calendar_exceptions}
    x = table.get(type_, {}).get(id_ or "")
    if x is None:
        return id_ or ""
    return getattr(x, "code", None) or getattr(x, "label", "") or x.id


def _bom_of_line(ds: MfgDataset, line_id: str) -> BomRecord | None:
    for b in ds.boms.values():
        if any(ln.id == line_id for ln in b.lines):
            return b
    return None


def entity_link(ds: MfgDataset, type_: str, id_: str | None) -> str | None:
    if type_ == "plant":
        return "/mfg/plant/settings"
    if id_ is None:
        return None
    if type_ == "item":
        return f"/mfg/items/{id_}"
    if type_ == "bom":
        return f"/mfg/items/{ds.boms[id_].item_id}/bom?bom={id_}"
    if type_ == "bom_line":
        b = _bom_of_line(ds, id_)
        if b is None:
            return None
        if b.status == "draft":
            return f"/mfg/items/{b.item_id}/bom/{b.id}/edit?line={id_}"
        return f"/mfg/items/{b.item_id}/bom?bom={b.id}&line={id_}"
    if type_ == "routing":
        return f"/mfg/items/{ds.routings[id_].item_id}/routing?routing={id_}"
    if type_ == "operation":
        r = ds.operation_routing.get(id_)
        if r is None:
            return None
        op = next(o for o in r.operations if o.id == id_)
        return f"/mfg/items/{r.item_id}/routing?routing={r.id}&op={op.seq}"
    simple = {"group": "/mfg/plant/groups?group={}", "line": "/mfg/plant/groups?line={}",
              "shift_template": "/mfg/plant/shifts?template={}", "shift_assignment": "/mfg/plant/shifts?assignment={}",
              "calendar_exception": "/mfg/plant/calendar?exception={}", "skill": "/mfg/resources/skills?skill={}",
              "operator": "/mfg/resources/operators?operator={}", "tool_pool": "/mfg/resources/tooling?tool={}"}
    tpl = simple.get(type_)
    return tpl.format(id_) if tpl else None


def eref(ds: MfgDataset, type_: str, id_: str | None, label: str | None = None) -> EntityRef:
    return EntityRef.model_construct(type=type_, id=id_, label=label if label is not None else
                                     entity_label(ds, type_, id_))


def make_issue(ds: MfgDataset, code: str, type_: str, id_: str | None, *, related: Iterable[EntityRef] = (),
               field: str | None = None, link: str | None = None, label: str | None = None,
               fix_kw: dict[str, Any] | None = None, **kw: Any) -> HealthIssue:
    info = CODE_INFO[code]
    return HealthIssue.model_construct(
        code=code, severity=info.severity, message=message(code, **kw), fix=fix(code, **(fix_kw or {})),
        entity=eref(ds, type_, id_, label), related=list(related),
        link=link if link is not None else entity_link(ds, type_, id_), field=field)


def sort_issues(issues: list[HealthIssue]) -> list[HealthIssue]:
    return sorted(issues, key=lambda i: (SEVERITY_ORDER[i.severity], CODE_ORDER.get(i.code, 999), i.entity.label,
                                         i.entity.id or ""))


# ---------------------------------------------------------------- helpers


def _intersects(doc: Any, d0: date, d1: date) -> bool:
    return (doc.effective_from is None or doc.effective_from < d1) and (doc.effective_to is None or doc.effective_to > d0)


def _check_dates(docs: Iterable[Any], as_of: date, h1: date) -> list[date]:
    out = {as_of}
    for d in docs:
        for x in (d.effective_from, d.effective_to):
            if x is not None and as_of < x < h1:
                out.add(x)
    return sorted(out)


def fmt_days(days: Iterable[int]) -> str:
    ds = sorted(set(days))
    parts: list[str] = []
    i = 0
    while i < len(ds):
        j = i
        while j + 1 < len(ds) and ds[j + 1] == ds[j] + 1:
            j += 1
        names = [WEEKDAYS[k].capitalize() for k in ds[i:j + 1]]
        parts.append(f"{names[0]}-{names[-1]}" if len(names) >= 3 else ", ".join(names))
        i = j + 1
    return ", ".join(parts)


def _hhmm(m: int) -> str:
    m %= DAY
    return f"{m // 60:02d}:{m % 60:02d}"


class _Check:
    def __init__(self, ds: MfgDataset, as_of: date, horizon_days: int):
        self.ds = ds
        self.as_of = as_of
        self.h1 = as_of + timedelta(days=horizon_days)
        self.issues: list[HealthIssue] = []
        self._details: dict[str, Any] = {}
        self._intervals: dict[str, list[tuple[int, int, str, str]]] = {}

    def add(self, *a: Any, **kw: Any) -> None:
        self.issues.append(make_issue(self.ds, *a, **kw))

    # line windows over the horizon (cached)
    def detail(self, line_id: str) -> Any:
        if line_id not in self._details:
            self._details[line_id] = line_detail(self.ds, line_id, self.as_of, self.h1)
        return self._details[line_id]

    def intervals(self, line_id: str) -> list[tuple[int, int, str, str]]:
        if line_id not in self._intervals:
            det = self.detail(line_id)
            merged = _clip_merge(det.pieces, self.as_of.toordinal() * DAY, self.h1.toordinal() * DAY)
            self._intervals[line_id] = [(s, e, k, f"{t}/{'+'.join(n)}") for s, e, k, _a, n, t, _c in merged]
        return self._intervals[line_id]


# ---------------------------------------------------------------- the check


def run_health_check(ds: MfgDataset, as_of: date, horizon_days: int) -> HealthReport:
    c = _Check(ds, as_of, horizon_days)
    items = ds.items
    h1 = c.h1
    non_obs_boms = [b for b in ds.boms.values() if b.status != "obsolete"]
    released_boms = [b for b in ds.boms.values() if b.status == "released"]
    live_boms = [b for b in released_boms if b.effective_to is None or b.effective_to > as_of]
    drafts_and_live = [b for b in non_obs_boms if b.status == "draft"] + live_boms
    child_of_non_obs = {ln.child_item_id for b in non_obs_boms for ln in b.lines}

    # union graph, end items, in-use
    graph: dict[str, list[str]] = {}
    for b in released_boms:
        it = items.get(b.item_id)
        if it is None or it.make_buy == "buy" or not _intersects(b, as_of, h1):
            continue
        graph.setdefault(b.item_id, []).extend(ln.child_item_id for ln in b.lines)
    end_items = sorted((i for i, it in items.items() if it.active and it.make_buy == "make"
                        and i not in child_of_non_obs
                        and (any(b.status == "released" for b in ds.boms_by_item.get(i, ()))
                             or any(r.status == "released" for r in ds.routings_by_item.get(i, ())))),
                       key=lambda i: items[i].part_number)
    in_use: set[str] = set(end_items)
    stack = list(end_items)
    while stack:
        v = stack.pop()
        for w in graph.get(v, ()):
            if w not in in_use and w in items:
                in_use.add(w)
                stack.append(w)

    _cycles_and_depth(c, end_items, graph)
    _item_documents(c, in_use)
    relevant_ops = _relevant_operations(c, in_use)
    _operations(c, relevant_ops)
    _resources(c, relevant_ops)
    _bom_lines(c, live_boms, drafts_and_live, released_boms)
    _simple_items(c, child_of_non_obs)
    _routing_warnings(c)

    issues = sort_issues(c.issues)
    counts = HealthCounts.model_construct(error=0, warning=0, info=0)
    by_code: dict[str, int] = {}
    for i in issues:
        setattr(counts, i.severity, getattr(counts, i.severity) + 1)
        by_code[i.code] = by_code.get(i.code, 0) + 1
    by_code = dict(sorted(by_code.items(), key=lambda kv: CODE_ORDER.get(kv[0], 999)))
    return HealthReport.model_construct(
        ok=counts.error == 0, as_of=as_of, horizon_days=horizon_days, fingerprint=fingerprint(ds), counts=counts,
        by_code=by_code, truncated=len(issues) > MAX_HEALTH_ISSUES, issues=issues[:MAX_HEALTH_ISSUES],
        data_version=ds.plant.data_version)


def _cycles_and_depth(c: _Check, end_items: list[str], graph: dict[str, list[str]]) -> None:
    ds = c.ds
    from .bom import bom_edges

    for cyc in find_cycles(bom_edges(ds), key=lambda i: _pn(ds, i)):
        start = cyc[0]
        c.add("MFG_BOM_CYCLE", "item", start, path=" -> ".join(_pn(ds, i) for i in cyc),
              related=[eref(ds, "item", i) for i in dict.fromkeys(cyc[1:-1])])
    # height over the union graph with back edges ignored (iterative post-order)
    height: dict[str, int] = {}
    for root in end_items:
        if root in height:
            continue
        on_path: set[str] = {root}
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, i = work[-1]
            kids = graph.get(v, [])
            if i < len(kids):
                work[-1] = (v, i + 1)
                w = kids[i]
                if w in height or w in on_path or w not in ds.items:
                    continue
                on_path.add(w)
                work.append((w, 0))
                continue
            work.pop()
            on_path.discard(v)
            height[v] = max((height.get(w, -1) + 1 for w in kids if w in height and w not in on_path), default=0)
        if height[root] > MAX_BOM_DEPTH:
            c.add("MFG_BOM_TOO_DEEP", "item", root, pn=_pn(ds, root), limit=MAX_BOM_DEPTH,
                  depth=f"{height[root]} levels")


def _item_documents(c: _Check, in_use: set[str]) -> None:
    ds, as_of, h1 = c.ds, c.as_of, c.h1
    for item_id, it in ds.items.items():
        if not it.active:
            continue
        boms = ds.boms_by_item.get(item_id, [])
        rtgs = ds.routings_by_item.get(item_id, [])
        rel_boms = [b for b in boms if b.status == "released"]
        rel_rtgs = [r for r in rtgs if r.status == "released"]
        # overlaps (released documents whose common window intersects the horizon)
        for docs, code in ((rel_boms, "MFG_BOM_EFFECTIVITY_OVERLAP"), (rel_rtgs, "MFG_ROUTING_EFFECTIVITY_OVERLAP")):
            for i, a in enumerate(docs):
                for b in docs[i + 1:]:
                    if code == "MFG_ROUTING_EFFECTIVITY_OVERLAP" and a.priority != b.priority:
                        continue
                    if not windows_overlap(a, b):
                        continue
                    lo = max(a.effective_from or date.min, b.effective_from or date.min)
                    hi = min(a.effective_to or date.max, b.effective_to or date.max)
                    if not (lo < h1 and hi > as_of):
                        continue
                    later, other = sorted((a, b), key=lambda d: (d.effective_from or date.min, d.version, d.id))[::-1]
                    typ = "routing" if code == "MFG_ROUTING_EFFECTIVITY_OVERLAP" else "bom"
                    kw = {"prio": later.priority} if typ == "routing" else {}
                    c.add(code, typ, later.id, related=[eref(ds, typ, other.id)], doc=doc_label(later),
                          other=doc_label(other), pn=it.part_number, **kw)
        # gaps between consecutive generic windows inside the horizon
        for docs, code in (([b for b in rel_boms if b.serial_from is None], "MFG_BOM_EFFECTIVITY_GAP"),
                           ([r for r in rel_rtgs if r.serial_from is None and r.priority == 1],
                            "MFG_ROUTING_EFFECTIVITY_GAP")):
            if code == "MFG_BOM_EFFECTIVITY_GAP" and it.make_buy == "buy":
                continue
            if code == "MFG_ROUTING_EFFECTIVITY_GAP" and it.make_buy != "make":
                continue
            segs = []
            for d in docs:
                lo = max(d.effective_from or date.min, as_of)
                hi = min(d.effective_to or date.max, h1)
                if lo < hi:
                    segs.append((lo.toordinal(), hi.toordinal()))
            merged = union(segs)
            if len(merged) > 1:
                c.add(code, "item", item_id, pn=it.part_number, g0=fmt_date(date.fromordinal(merged[0][1])),
                      g1=fmt_date(date.fromordinal(merged[1][0])))
        if item_id not in in_use:
            continue
        dates = _check_dates(rel_boms + rel_rtgs, as_of, h1)
        if it.make_buy == "make":
            missing = next((d for d in dates if not effective_routings(ds, item_id, d)), None)
            if missing is not None:
                draft = next((r for r in rtgs if r.status == "draft"), None)
                link = f"/mfg/items/{item_id}/routing" + (f"?routing={draft.id}" if draft else "")
                c.add("MFG_MAKE_NO_ROUTING", "item", item_id, link=link,
                      related=[eref(ds, "routing", draft.id, f"{doc_label(draft)} (draft)")] if draft else [],
                      pn=it.part_number, desc=it.description, day=fmt_date(missing),
                      draft=f" (it has a draft routing {doc_label(draft)})" if draft else "",
                      fix_kw={"fix_draft": f"Open the routing {doc_label(draft)} and release it, or add a routing "
                                           "for this item." if draft else "Add a routing for this item and release "
                                                                          "it."})
        if it.make_buy in ("make", "phantom"):
            missing = next((d for d in dates if pick_effective(boms, d) is None), None)
            if missing is not None:
                draft = next((b for b in boms if b.status == "draft"), None)
                link = f"/mfg/items/{item_id}/bom" + (f"?bom={draft.id}" if draft else "")
                code = "MFG_PHANTOM_NO_BOM" if it.make_buy == "phantom" else "MFG_MAKE_NO_BOM"
                c.add(code, "item", item_id, link=link,
                      related=[eref(ds, "bom", draft.id, f"{doc_label(draft)} (draft)")] if draft else [],
                      pn=it.part_number, desc=it.description, day=fmt_date(missing))


def _relevant_operations(c: _Check, in_use: set[str]) -> list[tuple[RoutingRecord, OperationRecord, ItemRecord]]:
    out = []
    for r in sorted(c.ds.routings.values(), key=lambda r: r.id):
        it = c.ds.items.get(r.item_id)
        if (it is None or not it.active or it.make_buy != "make" or r.item_id not in in_use
                or r.status != "released" or not _intersects(r, c.as_of, c.h1)):
            continue
        for op in sorted(r.operations, key=lambda o: o.seq):
            out.append((r, op, it))
    return out


def _active_lines(c: _Check, group_id: str) -> list[Any]:
    g = c.ds.groups.get(group_id)
    if g is None or not g.active:
        return []
    return [ln for ln in c.ds.lines_by_group.get(group_id, ()) if ln.active]


def _operations(c: _Check, ops: list[tuple[RoutingRecord, OperationRecord, ItemRecord]]) -> None:
    ds = c.ds
    group_lines: dict[str, dict[str, Any]] = {}       # used group -> eligible lines (union over its operations)
    for r, op, it in ops:
        g = ds.groups.get(op.group_id)
        gcode = g.code if g else "?"
        opname = f"{op.seq} {op.name}"
        lines = _active_lines(c, op.group_id)
        group_lines.setdefault(op.group_id, {})
        if not lines:
            c.add("MFG_GROUP_NO_LINE", "operation", op.id, related=[eref(ds, "group", op.group_id)] if g else [],
                  op=opname, pn=it.part_number, group=gcode)
            continue
        elig = [ln for ln in lines if line_eligible(ln, it)]
        if not elig:
            c.add("MFG_NO_ELIGIBLE_LINE", "operation", op.id, related=[eref(ds, "group", op.group_id)],
                  op=opname, pn=it.part_number, group=gcode)
            continue
        for ln in elig:
            group_lines[op.group_id][ln.id] = ln
        if not op.interruptible:
            def too_long(q: float) -> tuple[bool, float, int]:
                worst_need, best_long = 0.0, 0
                for ln in elig:
                    need = operation_minutes(op, q, ln.speed_factor).total
                    longest = longest_window(c.intervals(ln.id))
                    best_long = max(best_long, longest)
                    worst_need = need if worst_need == 0 else min(worst_need, need)
                    if need <= longest:
                        return False, need, longest
                return True, worst_need, best_long

            bad, need, longest = too_long(1.0)
            if bad:
                c.add("MFG_UNINTERRUPTIBLE_TOO_LONG", "operation", op.id, related=[eref(ds, "group", op.group_id)],
                      op=opname, pn=it.part_number, need=f"{need:g}", group=gcode, longest=longest)
            else:
                lot = it.fixed_lot_qty if it.lot_rule == "fixed" and it.fixed_lot_qty else it.min_order_qty
                if lot and lot > 1:
                    bad, need, longest = too_long(float(lot))
                    if bad:
                        c.add("MFG_UNINTERRUPTIBLE_LOT_TOO_LONG", "operation", op.id,
                              related=[eref(ds, "group", op.group_id)], op=opname, pn=it.part_number,
                              need=f"{need:g}", qty=f"{lot:g}", group=gcode, longest=longest)
    d0, d1 = fmt_date(c.as_of), fmt_date(c.h1 - timedelta(days=1))
    for gid in sorted(group_lines, key=lambda g: ds.groups[g].code if g in ds.groups else g):
        g = ds.groups.get(gid)
        if g is None or not group_lines[gid]:
            continue
        base = opt = 0
        for lid in group_lines[gid]:
            for s, e, kind, _l in c.intervals(lid):
                if kind == "base":
                    base += e - s
                else:
                    opt += e - s
        if base == 0 and opt == 0:
            c.add("MFG_GROUP_NO_SHIFT", "group", gid, group=g.code, d0=d0, d1=d1)
        elif base == 0:
            c.add("MFG_GROUP_OPTIONAL_ONLY", "group", gid, group=g.code, d0=d0, d1=d1)
        lines = _active_lines(c, gid)
        with_time = [ln for ln in lines if c.intervals(ln.id)]
        if with_time:
            for ln in lines:
                if not c.intervals(ln.id):
                    c.add("MFG_LINE_NO_SHIFT", "line", ln.id, related=[eref(ds, "group", gid)], line=ln.code,
                          group=g.code, d0=d0, d1=d1)


def _resources(c: _Check, ops: list[tuple[RoutingRecord, OperationRecord, ItemRecord]]) -> None:
    ds = c.ds
    holders: dict[str, list[str]] = {}
    for o in sorted(ds.operators.values(), key=lambda o: o.code):
        if o.active:
            for s in o.skill_ids:
                holders.setdefault(s, []).append(o.id)
    pairs: dict[tuple[str, str], None] = {}
    for r, op, it in ops:
        opname = f"{op.seq} {op.name}"
        if op.skill_id is not None:
            sk = ds.skills.get(op.skill_id)
            if not holders.get(op.skill_id):
                c.add("MFG_SKILL_NO_OPERATOR", "operation", op.id,
                      related=[eref(ds, "skill", op.skill_id)] if sk else [], op=opname, pn=it.part_number,
                      skill=sk.code if sk else op.skill_id)
            elif op.crew_size > 0:
                for ln in _active_lines(c, op.group_id):
                    if line_eligible(ln, it):
                        pairs[(op.skill_id, ln.id)] = None
        for t in op.tools:
            tp = ds.tool_pools.get(t.tool_pool_id)
            have = tp.quantity if tp else 0
            if have < t.qty:
                c.add("MFG_TOOL_SHORT", "operation", op.id,
                      related=[eref(ds, "tool_pool", t.tool_pool_id)] if tp else [], op=opname, pn=it.part_number,
                      need=t.qty, tool=tp.code if tp else t.tool_pool_id, have=have)
    # MFG_SKILL_NOT_ON_SHIFT (review R1): line windows minus qualified operators' shift spans, real horizon dates
    cover: dict[str, list[tuple[int, int]]] = {}
    for (skill_id, line_id) in sorted(pairs, key=lambda p: (ds.skills[p[0]].code, ds.lines[p[1]].code)):
        if skill_id not in cover:
            cover[skill_id] = union([iv for oid in holders.get(skill_id, [])
                                     for iv in operator_intervals(ds, oid, c.as_of, c.h1)])
        patterns: dict[tuple[str, str, str, str], list[int]] = {}
        for s, e, kind, label in c.intervals(line_id):
            for us, ue in subtract([(s, e)], cover[skill_id]):
                if ue - us < SKILL_COVERAGE_TOLERANCE_MINUTES:
                    continue
                key = (label, kind, _hhmm(us), _hhmm(ue))
                patterns.setdefault(key, []).append(date.fromordinal(us // DAY).weekday())
        if not patterns:
            continue
        texts = [f"{lab} ({kind}) {fmt_days(days)} {s}-{e}" for (lab, kind, s, e), days in patterns.items()]
        shown = "; ".join(texts[:3]) + (f" and {len(texts) - 3} more" if len(texts) > 3 else "")
        ln = ds.lines[line_id]
        sk = ds.skills[skill_id]
        c.add("MFG_SKILL_NOT_ON_SHIFT", "skill", skill_id, label=f"{sk.code} / {ln.code}",
              related=[eref(ds, "line", line_id), eref(ds, "group", ln.group_id)], skill=sk.code, line=ln.code,
              patterns=shown)
    # assignments
    for a in sorted(ds.shift_assignments.values(), key=lambda a: a.id):
        if a.effective_to is not None and a.effective_to <= c.as_of:
            continue
        t = ds.shift_templates.get(a.shift_template_id)
        tgt = ds.groups.get(a.group_id or "") if a.target_type == "group" else ds.lines.get(a.line_id or "")
        kw = {"tpl": t.code if t else "?", "target": tgt.code if tgt else "?"}
        if tgt is not None and not tgt.active:
            c.add("MFG_ASSIGNMENT_INACTIVE_TARGET", "shift_assignment", a.id, ttype=a.target_type, **kw)
            continue
        if a.kind != "optional":
            continue
        if a.cost_per_hour is None:
            c.add("MFG_OPTIONAL_NO_COST", "shift_assignment", a.id, **kw)
        lines = [a.line_id] if a.target_type == "line" else [ln.id for ln in _active_lines(c, a.group_id or "")]
        raw = after = 0
        for lid in lines:
            if lid is None or lid not in ds.lines:
                continue
            det = c.detail(lid)
            raw += det.optional_raw.get(a.id, 0)
            after += det.optional_after_base.get(a.id, 0)
        if raw > 0 and after == 0:
            c.add("MFG_OPTIONAL_OVERLAPS_BASE", "shift_assignment", a.id, **kw)


def _bom_lines(c: _Check, live: list[BomRecord], drafts_and_live: list[BomRecord],
               released: list[BomRecord]) -> None:
    ds = c.ds
    items = ds.items

    def ctx(b: BomRecord) -> dict[str, Any]:
        return {"doc": doc_label(b), "pn": _pn(ds, b.item_id)}

    def parent_ok(b: BomRecord) -> bool:
        p = items.get(b.item_id)
        return p is not None and p.active and p.make_buy != "buy"

    for b in sorted(live, key=lambda b: b.id):
        if not parent_ok(b):
            continue
        effective_in_h = _intersects(b, c.as_of, c.h1)
        groups: dict[str, list[Any]] = {}
        for ln in sorted(b.lines, key=line_sort_key):
            ch = items.get(ln.child_item_id)
            if ch is None:
                continue
            if not same_dimension(ln.uom, ch.uom):
                c.add("MFG_UOM_MISMATCH", "bom_line", ln.id, field="uom", fn=ln.find_number, uom=ln.uom,
                      child=ch.part_number, child_uom=ch.uom, **ctx(b))
            if ch.serialized and abs(ln.qty_per - round(ln.qty_per)) > 1e-9:
                c.add("MFG_FRACTIONAL_SERIALIZED", "bom_line", ln.id, field="qty_per", fn=ln.find_number,
                      child=ch.part_number, qty=f"{ln.qty_per:g}", **ctx(b))
            if effective_in_h and not ch.active:
                c.add("MFG_INACTIVE_COMPONENT", "bom_line", ln.id, field="child_item_id", fn=ln.find_number,
                      child=ch.part_number, **ctx(b))
            if ln.alt_group is not None:
                groups.setdefault(ln.alt_group, []).append(ln)
        for grp, members in groups.items():
            if len(members) > 1 and not any(m.alt_priority == 1 for m in members):
                c.add("MFG_ALT_NO_PRIMARY", "bom_line", members[0].id, field="alt_priority", grp=grp, **ctx(b))
            seen: dict[int, Any] = {}
            for m in members:
                if m.alt_priority in seen:
                    c.add("MFG_ALT_DUPLICATE_PRIORITY", "bom_line", m.id, field="alt_priority", grp=grp,
                          prio=m.alt_priority, **ctx(b))
                else:
                    seen[m.alt_priority] = m
    for b in sorted(drafts_and_live, key=lambda b: b.id):
        if not parent_ok(b):
            continue
        prim = None
        p = items[b.item_id]
        if p.make_buy == "make":
            rs = effective_routings(ds, b.item_id, c.as_of)
            prim = rs[0] if rs else None
        seqs = {o.seq for o in prim.operations} if prim else set()
        groups = {}
        by_child: dict[str, list[Any]] = {}
        for ln in sorted(b.lines, key=line_sort_key):
            ch = items.get(ln.child_item_id)
            if ch is None:
                continue
            if prim is not None and ln.operation_seq is not None and ln.operation_seq not in seqs:
                c.add("MFG_OPERATION_SEQ_REF", "bom_line", ln.id, field="operation_seq", fn=ln.find_number,
                      seq=ln.operation_seq, **ctx(b))
            if ln.ref_designators.strip() and ln.uom in UOM_CODES and is_count(ln.uom):
                n, bad = refdes_count(ln.ref_designators)
                if bad or abs(n - ln.qty_per) > 1e-9:
                    c.add("MFG_REFDES_COUNT", "bom_line", ln.id, field="ref_designators", fn=ln.find_number,
                          count=n, qty=f"{ln.qty_per:g}",
                          invalid=f" (not understood: {', '.join(bad[:5])})" if bad else "", **ctx(b))
            if ln.alt_group is not None:
                groups.setdefault(ln.alt_group, []).append(ln)
            else:
                by_child.setdefault(ln.child_item_id, []).append(ln)
        for grp, members in groups.items():
            if len(members) == 1:
                c.add("MFG_ALT_SINGLE", "bom_line", members[0].id, field="alt_group", grp=grp, **ctx(b))
        for child_id, lns in by_child.items():
            fns = list(dict.fromkeys(ln.find_number for ln in lns))
            if len(fns) > 1:
                c.add("MFG_DUPLICATE_COMPONENT", "bom_line", lns[1].id, child=_pn(ds, child_id),
                      fns=", ".join(fns), **ctx(b))
    del released


def _simple_items(c: _Check, child_of_non_obs: set[str]) -> None:
    ds = c.ds
    for item_id, it in ds.items.items():
        if not it.active:
            continue
        boms = [b for b in ds.boms_by_item.get(item_id, []) if b.status != "obsolete"]
        rtgs = [r for r in ds.routings_by_item.get(item_id, []) if r.status != "obsolete"]
        if it.make_buy == "buy":
            if it.lead_time_days is None:
                c.add("MFG_BUY_NO_LEAD_TIME", "item", item_id, field="lead_time_days", pn=it.part_number,
                      desc=it.description)
            elif it.lead_time_days > 180:
                c.add("MFG_LONG_LEAD_TIME", "item", item_id, field="lead_time_days", pn=it.part_number,
                      desc=it.description, days=it.lead_time_days)
            if boms:
                c.add("MFG_BUY_WITH_BOM", "item", item_id, related=[eref(ds, "bom", boms[0].id)], pn=it.part_number,
                      doc=doc_label(boms[0]))
        if it.make_buy in ("buy", "phantom") and rtgs:
            c.add("MFG_BUY_WITH_ROUTING", "item", item_id, related=[eref(ds, "routing", rtgs[0].id)],
                  mb=it.make_buy.capitalize(), pn=it.part_number, doc=doc_label(rtgs[0]))
        if (item_id not in child_of_non_obs and not boms
                and not (it.make_buy == "make" and rtgs)):
            c.add("MFG_ORPHAN_ITEM", "item", item_id, pn=it.part_number, desc=it.description)
        docs = boms + rtgs
        if docs and all(d.status == "draft" for d in docs) and \
                not any(d.status == "released" for d in ds.boms_by_item.get(item_id, []) +
                        ds.routings_by_item.get(item_id, [])):
            what = " and ".join(w for w, have in (("BOMs", boms), ("routings", rtgs)) if have)
            c.add("MFG_DRAFT_ONLY", "item", item_id, pn=it.part_number, what=what)


def _routing_warnings(c: _Check) -> None:
    ds = c.ds
    for r in sorted(ds.routings.values(), key=lambda r: r.id):
        it = ds.items.get(r.item_id)
        if it is None or not it.active or it.make_buy != "make" or r.status != "released":
            continue
        if not r.operations:
            c.add("MFG_ROUTING_NO_OPERATIONS", "routing", r.id, doc=doc_label(r), pn=it.part_number)
            continue
        if r.effective_to is not None and r.effective_to <= c.as_of:
            continue
        y = 1.0
        for op in sorted(r.operations, key=lambda o: o.seq):
            y *= op.yield_pct / 100.0
            if op.setup_minutes == 0 and op.run_minutes == 0:
                c.add("MFG_ZERO_TIME_OPERATION", "operation", op.id, op=f"{op.seq} {op.name}", pn=it.part_number)
        if y < 0.5:
            c.add("MFG_LOW_YIELD", "routing", r.id, doc=doc_label(r), pn=it.part_number, pct=f"{y * 100:.1f}")


__all__ = ["doc_label", "entity_label", "entity_link", "is_effective", "date_window_contains", "make_issue",
           "run_health_check", "sort_issues"]

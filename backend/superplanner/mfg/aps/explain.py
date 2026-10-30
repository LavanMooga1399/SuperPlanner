"""Why late (M3-DESIGN 8): walk back from an order's last operation along the binding start reasons to a root -
material (part + supply), capacity (stage + competing order), calendar (no shift), crew, tool, frozen/locked, or
lead time (processing time alone exceeds due - as_of)."""

from __future__ import annotations

from typing import Any

from .model import LateStep, RefItem

MAX_STEPS = 8


def _fmt(m: Any, minute: int) -> str:
    return m.clock.to_dt(minute).astimezone(m.clock.tz).strftime("%d %b %H:%M")


def late_chain(m: Any, sc: Any, order: Any, by_no: dict[int, Any]) -> tuple[list[LateStep], str]:
    steps: list[LateStep] = []
    if not order.ops:
        return steps, ""
    op = order.ops[-1]
    seen: set[Any] = set()
    while op is not None and len(steps) < MAX_STEPS and op.key not in seen:
        seen.add(op.key)
        ps = sc.placed.get(op.key)
        if not ps:
            break
        p = max(ps, key=lambda x: x.end)
        nxt = None
        ln = m.lines[p.line_id]
        r = p.fixed or p.reason or "as_of"
        if r in ("frozen", "in_progress"):
            steps.append(LateStep(kind="frozen", op_no=op.no, text=f"{op.rec.name} on {ln.code} is frozen."))
            break
        if r in ("locked", "edit"):
            steps.append(LateStep(kind="locked", op_no=op.no, text=f"{op.rec.name} on {ln.code} is locked."))
            break
        if r == "material":
            lab = "; ".join(x["label"] for x in p.reason_refs[:2]) or "material"
            steps.append(LateStep(kind="material", op_no=op.no,
                                  text=f"{ln.code} waits for {lab} ({_fmt(m, p.start)})",
                                  refs=[RefItem(type=str(x.get("type")), id=x.get("id"), label=str(x.get("label")))
                                        for x in p.reason_refs[:3]]))
            prov = [x for x in p.reason_refs if x.get("type") in ("work_order", "planned")]
            if prov:
                child = next((o for o in m.orders.values() if o.id == prov[0].get("id")), None)
                nxt = child.ops[-1] if child and child.ops else None
            else:
                break
        elif r == "predecessor":
            nxt = order_op(op, -1)
            if nxt is None and p.reason_refs:
                nxt = by_no.get(int(p.reason_refs[0]["id"])) if str(p.reason_refs[0].get("id", "")).isdigit() else None
        elif r == "line_busy":
            comp = p.reason_refs[0]["label"] if p.reason_refs else "other orders"
            grp = m.ds.groups.get(ln.group_id)
            steps.append(LateStep(kind="capacity", op_no=op.no,
                                  text=f"{grp.code if grp else 'stage'} {ln.code} busy until {_fmt(m, p.start)} with "
                                       f"{comp}",
                                  refs=[RefItem(type="group", id=ln.group_id, label=grp.code if grp else ""),
                                        RefItem(type="line", id=ln.id, label=ln.code)]))
            nxt = order_op(op, -1)
        elif r == "no_window":
            steps.append(LateStep(kind="calendar", op_no=op.no,
                                  text=f"{ln.code} has no open shift until {_fmt(m, p.start)}",
                                  refs=[RefItem(type="line", id=ln.id, label=ln.code)]))
            nxt = order_op(op, -1)
        elif r == "crew":
            steps.append(LateStep(kind="crew", op_no=op.no,
                                  text=f"{op.rec.name} on {ln.code} waits for qualified operators until "
                                       f"{_fmt(m, p.start)}",
                                  refs=[RefItem(type="line", id=ln.id, label=ln.code)]))
            nxt = order_op(op, -1)
        elif r == "tool":
            steps.append(LateStep(kind="tool", op_no=op.no, text=f"{op.rec.name} waits for tooling until "
                                                                  f"{_fmt(m, p.start)}"))
            nxt = order_op(op, -1)
        else:      # as_of: nothing waited -> processing time is the cause
            steps.append(LateStep(kind="lead_time", op_no=op.no,
                                  text=f"processing time from the planning start exceeds the time to the due date"))
            break
        op = nxt
    head = f"{order.number} ({order.part_number} x{order.qty:g})"
    return steps, (f"{head}: " + "; earlier: ".join(s.text for s in steps)) if steps else ""


def order_op(op: Any, delta: int) -> Any:
    i = op.idx + delta
    return op.order.ops[i] if 0 <= i < len(op.order.ops) else None


__all__ = ["late_chain"]

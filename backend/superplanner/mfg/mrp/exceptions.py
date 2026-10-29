"""Exception messages (M2-DESIGN 8.12). Codes and severities are stable; wording may improve.

Every exception carries a plain-language `message`, an `action`, the numbers it is based on (`date`, `qty`,
`days`, `suggested`) and `related` objects; the API adds `link` (14.3). Planned-order subjects use
`id = str(planned_no)` (the API maps it to the stored `mpo_` id).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .lotsize import round_order_qty
from .model import EPS, ExRef, MrpException

CODES: tuple[tuple[str, str], ...] = (
    ("MRP_DEMAND_LATE", "critical"), ("MRP_DEMAND_PAST_DUE", "critical"), ("MRP_SHORTAGE", "warning"),
    ("MRP_START_IN_PAST", "warning"), ("MRP_EXPEDITE", "warning"), ("MRP_PAST_DUE_SUPPLY", "warning"),
    ("MRP_WO_LATE", "warning"), ("MRP_EXPIRED_STOCK", "warning"), ("MRP_EXPIRING_STOCK", "warning"),
    ("MRP_CANCEL", "warning"), ("MRP_REDUCE", "info"), ("MRP_DEFER", "info"), ("MRP_RELEASE_NOW", "info"),
    ("MRP_BELOW_SAFETY_STOCK", "info"), ("MRP_ALTERNATE_USED", "info"), ("MRP_NO_SUPPLIER", "info"),
    ("MRP_MERGE_INTO_PR", "info"), ("MRP_DEMAND_SERIAL_OVERLAP", "warning"), ("MRP_RESERVATION_EXCESS", "info"),
    ("MRP_WO_COMPONENT_CYCLE", "warning"), ("MRP_DEMAND_OUTSIDE_HORIZON", "info"),
)
SEVERITY = dict(CODES)
CODE_ORDER = {c: i for i, (c, _s) in enumerate(CODES)}
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def fdate(d: date | None) -> str:
    return f"{d.day} {d:%b %Y}" if d is not None else "-"


def fqty(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x)):,}"
    return f"{x:,.3f}".rstrip("0").rstrip(".")


def sort_key(e: MrpException) -> tuple:
    return (SEVERITY_ORDER[e.severity], CODE_ORDER[e.code], e.date or date.max, e.part_number or "", e.subject.label,
            e.subject.id or "")


def _top_labels(reqs: list[Any], n: int = 3) -> str:
    acc: dict[str, float] = {}
    for r in reqs:
        for (_lid, label), f in (r.share or []):
            acc[label] = acc.get(label, 0.0) + f * r.qty
    labels = [k for k, _v in sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
    return ", ".join(labels) if labels else "-"


class _Builder:
    def __init__(self, c: Any, p: Any):
        self.c = c
        self.p = p
        self.out: list[MrpException] = []

    def add(self, code: str, *, item_id: str | None, subject: ExRef, message: str, action: str,
            demand_line_id: str | None = None, d: date | None = None, qty: float | None = None,
            days: int | None = None, suggested: dict[str, Any] | None = None,
            related: list[ExRef] | None = None) -> None:
        it = self.c.ds.items.get(item_id) if item_id else None
        sug = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in (suggested or {}).items()}
        self.out.append(MrpException(
            code=code, severity=SEVERITY[code], item_id=item_id, part_number=it.part_number if it else None,
            subject=subject, demand_line_id=demand_line_id, date=d,
            qty=round(qty, 6) if qty is not None else None, days=days, message=message[:1000], action=action[:500],
            suggested=sug, related=related or []))


def _supply_subject(s: Any) -> ExRef:
    if s.kind in ("po", "pr"):
        return ExRef(f"{s.kind}_schedule", s.sched.schedule_id, s.ref.label)
    return ExRef("work_order", s.wo.id, s.wo.number)


def build_exceptions(c: Any, p: Any, alt_records: list[dict[str, Any]], demand_info: dict[int, Any]
                     ) -> list[MrpException]:
    b = _Builder(c, p)
    items = c.ds.items
    as_of = c.as_of
    tol = c.settings.defer_tolerance_days

    # 1, 2 demand
    for r, d, idx in p.demand_reqs:
        proj = demand_info[id(r)]
        it = items[r.item_id]
        label = r.source.label
        dl = d.line_id if idx is None else None
        subj = ExRef("demand_line", d.line_id, label) if idx is None else ExRef("extra", f"extra:{idx}", label)
        if proj.status == "past_due":
            b.add("MRP_DEMAND_PAST_DUE", item_id=r.item_id, subject=subj, demand_line_id=dl, d=r.need, qty=r.qty,
                  days=(as_of - r.need).days,
                  message=f"{label}: {fqty(r.qty)} x {it.part_number} was due {fdate(r.need)}, {fqty(r.qty)} open"
                          f" (projected {fdate(proj.projected_date)}).",
                  action="Ship from stock or re-date the line.", suggested={"date": proj.projected_date})
        elif proj.late_days > 0:
            steps = []
            for s in proj.limiting:
                if s.reason == "supply_date":
                    steps.append(f"{s.part_number} from {s.label} available {fdate(s.date)}")
                elif s.reason == "start_in_past":
                    steps.append(f"{s.part_number} ({s.label}) should have started before {fdate(as_of)}")
                else:
                    steps.append(f"{s.part_number} ({s.label})")
            lim = "; ".join(steps)
            b.add("MRP_DEMAND_LATE", item_id=r.item_id, subject=subj, demand_line_id=dl, d=proj.projected_date,
                  qty=r.qty, days=proj.late_days,
                  message=f"{label}: {fqty(r.qty)} x {it.part_number} due {fdate(r.need)} is projected for "
                          f"{fdate(proj.projected_date)} ({proj.late_days} days late)." + (f" Limiting: {lim}." if lim
                                                                                          else ""),
                  action="Expedite the parts on the limiting path, or agree a new date.",
                  suggested={"date": proj.projected_date},
                  related=[ExRef("item", s.item_id, s.part_number) for s in proj.limiting])

    for iid in c.order:
        st = p.states.get(iid)
        if st is None:
            continue
        it = st.item
        # 3 shortage
        late_reqs = []
        short = 0.0
        for r in st.reqs:
            if r.kind == "safety_stock":
                continue
            n = max(r.need, as_of)
            q = sum(pg.qty for pg in r.pegs if pg.sup.proj is not None and pg.sup.proj > n)
            if q > EPS:
                late_reqs.append(r)
                short += q
        if late_reqs:
            first = min(r.need for r in late_reqs)
            b.add("MRP_SHORTAGE", item_id=iid, subject=ExRef("item", iid, it.part_number), d=first, qty=short,
                  days=max(r.late for r in late_reqs),
                  message=f"{it.part_number} short {fqty(short)} from {fdate(first)} (first need), for "
                          f"{_top_labels(late_reqs)}; earliest new supply {fdate(st.protect)}.",
                  action="Expedite open orders or use an alternate.")
        # existing supplies: 5, 7, 10, 11, 12
        lp = c.lot(it)
        for s in st.sups:
            if s.kind not in ("po", "pr", "wo"):
                continue
            subj = _supply_subject(s)
            pegs = s.pegs
            if s.pegged <= EPS:
                if s.kind != "wo" or s.wo.status == "planned":
                    b.add("MRP_CANCEL", item_id=iid, subject=subj, d=s.avail, qty=s.qty,
                          message=f"{s.ref.label} ({fqty(s.qty)} x {it.part_number}, available {fdate(s.avail)}) "
                                  f"is not needed in the horizon.", action="Cancel or push out.")
                continue
            real = [pg for pg in pegs if pg.req.kind != "safety_stock"]
            if real:
                raw_need = min(pg.req.need for pg in real)
                n_min = max(raw_need, as_of)
                when = s.proj if s.kind == "wo" else s.avail
                if when is not None and when > n_min:
                    if s.kind == "wo":
                        sug = raw_need
                        msg = (f"{s.wo.number} ({fqty(s.qty)} x {it.part_number}, projected {fdate(when)}) is "
                               f"needed by {fdate(raw_need)}.")
                        act = f"Expedite the work order to finish by {fdate(sug)}."
                    else:
                        sug = raw_need - timedelta(days=it.receiving_days)
                        which = "confirmed" if s.sched.confirmed_date else "requested"
                        msg = (f"{s.ref.label} ({fqty(s.qty)} x {it.part_number}, {which} {fdate(s.dock_override)})"
                               f" is needed by {fdate(raw_need)}.")
                        act = f"Ask the supplier to deliver by {fdate(sug)}."
                    b.add("MRP_EXPEDITE", item_id=iid, subject=subj, d=when, qty=s.qty, days=(when - n_min).days,
                          message=msg, action=act, suggested={"date": sug})
            n_all = max(min(pg.req.need for pg in pegs), as_of)
            if n_all > s.avail + timedelta(days=tol):
                sug = n_all - timedelta(days=it.receiving_days) if s.kind != "wo" else n_all
                b.add("MRP_DEFER", item_id=iid, subject=subj, d=s.avail, qty=s.qty, days=(n_all - s.avail).days,
                      message=f"{s.ref.label} ({fqty(s.qty)} x {it.part_number}) arrives {fdate(s.avail)} but is "
                              f"first needed {fdate(n_all)}.", action=f"Push out to {fdate(sug)}.",
                      suggested={"date": sug})
            if s.kind in ("po", "pr") and s.pegged < s.qty - EPS:
                rq = round_order_qty(s.pegged, lp)
                if rq < s.qty - EPS:
                    b.add("MRP_REDUCE", item_id=iid, subject=subj, d=s.avail, qty=s.qty,
                          message=f"{s.ref.label}: only {fqty(s.pegged)} of {fqty(s.qty)} {it.part_number} are "
                                  f"needed.", action=f"Reduce to {fqty(rq)}.", suggested={"qty": rq})
            if s.kind == "wo" and s.proj is not None and s.proj > s.due:
                comps = sorted((r for r in s.comps if r.sat is not None and r.sat > max(s.start, as_of)),
                               key=lambda r: (-(r.sat - as_of).days, items[r.item_id].part_number))
                names = ", ".join(items[r.item_id].part_number for r in comps[:3])
                b.add("MRP_WO_LATE", item_id=iid, subject=subj, d=s.proj, qty=s.qty, days=(s.proj - s.due).days,
                      message=f"{s.wo.number} projected {fdate(s.proj)}, due {fdate(s.due)}"
                              + (f" (components: {names})." if names else " (lead time from today)."),
                      action="Expedite the late components or re-date the work order.",
                      related=[ExRef("item", r.item_id, items[r.item_id].part_number) for r in comps[:3]])
        # 9 expiring stock (per lot)
        lots: dict[str, list[Any]] = {}
        for s in st.sups:
            if s.kind in ("stock", "inspection") and s.exp is not None and as_of < s.exp <= c.horizon_end:
                lots.setdefault(s.lot_id or s.ref.id, []).append(s)
        for lot_id, ss in sorted(lots.items()):
            free = sum(max(0.0, s.qty - s.pegged) for s in ss)
            if free > EPS:
                code = c.lot_code(lot_id) or lot_id
                exp = min(s.exp for s in ss)
                b.add("MRP_EXPIRING_STOCK", item_id=iid, subject=ExRef("lot", lot_id, code), d=exp, qty=free,
                      days=(exp - as_of).days,
                      message=f"{fqty(free)} {it.uom} of lot {code} ({it.part_number}) expires {fdate(exp)} unused.",
                      action="Use it first, or move it to quarantine when it expires.")
        # 14 safety stock
        for r in st.reqs:
            if r.kind != "safety_stock":
                continue
            cov = sum(pg.qty for pg in r.pegs if pg.sup.kind != "planned" and pg.sup.avail <= as_of)
            if cov < r.qty - EPS:
                b.add("MRP_BELOW_SAFETY_STOCK", item_id=iid, subject=ExRef("item", iid, it.part_number), d=as_of,
                      qty=r.qty - cov,
                      message=f"{it.part_number} is below its safety stock of {fqty(r.qty)}: {fqty(cov)} available "
                              f"now.", action="Release the planned orders that restore it.")
        # 16 no supplier
        if any(po.kind == "buy" and po.supplier_id is None for po in st.planned):
            b.add("MRP_NO_SUPPLIER", item_id=iid, subject=ExRef("item", iid, it.part_number),
                  message=f"Planned PRs for {it.part_number} have no supplier.",
                  action="Add a supplier for this part.")

    # 4, 13, 17 planned orders
    pr_drafts: dict[str, list[Any]] = {}
    for sc in c.snap.schedules:
        if sc.doc_type == "pr" and sc.doc_status == "draft" and sc.open_qty > EPS:
            pr_drafts.setdefault(sc.item_id, []).append(sc)
    for po in p.planned:
        it = items[po.item_id]
        subj = ExRef("planned_order", str(po.no), f"P-{po.no}")
        word = "PR" if po.kind == "buy" else "WO"
        if po.start < as_of:
            days = (as_of - po.start).days
            late = max(0, (po.sup.proj - po.need).days) if po.sup.proj else 0
            b.add("MRP_START_IN_PAST", item_id=po.item_id, subject=subj, d=po.start, qty=po.qty, days=days,
                  message=f"Planned {word} P-{po.no} for {fqty(po.qty)} {it.part_number} should have been "
                          f"{'ordered' if po.kind == 'buy' else 'started'} {days} days ago (needed {fdate(po.need)}).",
                  action=f"Release now; expect {late} days delay.", suggested={"date": as_of})
        elif po.start <= as_of + timedelta(days=c.settings.release_window_days):
            b.add("MRP_RELEASE_NOW", item_id=po.item_id, subject=subj, d=po.start, qty=po.qty,
                  days=(po.start - as_of).days,
                  message=f"Planned {word} P-{po.no} for {fqty(po.qty)} {it.part_number}: "
                          f"{'order' if po.kind == 'buy' else 'start'} by {fdate(po.start)}.",
                  action="Release now.")
        if po.kind == "buy" and po.dock is not None:
            best = None
            for sc in pr_drafts.get(po.item_id, ()):
                if sc.supplier_id != po.supplier_id:
                    continue
                dock = sc.confirmed_date or sc.requested_date
                diff = abs((dock - po.dock).days)
                if diff <= tol:
                    k = (diff, sc.number, sc.line_no, sc.seq)
                    if best is None or k < best[0]:
                        best = (k, sc)
            if best is not None:
                sc = best[1]
                b.add("MRP_MERGE_INTO_PR", item_id=po.item_id, subject=subj, d=po.dock, qty=po.qty,
                      message=f"Add P-{po.no} ({fqty(po.qty)} x {it.part_number}) to {sc.number} instead of a new PR.",
                      action=f"Convert with add to {sc.number}.", suggested={"add_to_pr_id": sc.doc_id},
                      related=[ExRef("purchase_request", sc.doc_id, sc.number)])

    # 6 past-due supply
    for s in p.past_due:
        it = items[s.item_id]
        b.add("MRP_PAST_DUE_SUPPLY", item_id=s.item_id, subject=_supply_subject(s), d=s.dock_override,
              qty=s.qty, days=(as_of - s.dock_override).days,
              message=f"{s.ref.label}: {fqty(s.qty)} x {it.part_number} due {fdate(s.dock_override)}, not received.",
              action="Chase the supplier or re-date.")
    # 8 expired stock
    exp_lots: dict[tuple[str, str], list[Any]] = {}
    for bal in p.expired:
        exp_lots.setdefault((bal.item_id, bal.lot_id or bal.id), []).append(bal)
    for (iid, lot_id), bals in sorted(exp_lots.items()):
        it = items[iid]
        qty = sum(x.qty_on_hand for x in bals)
        code = c.lot_code(lot_id) or lot_id
        exp = min(x.expires_on for x in bals)
        b.add("MRP_EXPIRED_STOCK", item_id=iid, subject=ExRef("lot", lot_id, code), d=exp, qty=qty,
              days=(as_of - exp).days,
              message=f"Lot {code} of {it.part_number} ({fqty(qty)} {it.uom}) expired {fdate(exp)}.",
              action="Move to quarantine.")
    # 15 alternates
    by_key = {po.order_key: po for po in p.planned}
    for rec in alt_records:
        po = by_key.get(rec["order_key"])
        if po is None:
            continue
        alt_pn = items[rec["alt_item_id"]].part_number
        prim_pn = items[rec["primary_item_id"]].part_number
        b.add("MRP_ALTERNATE_USED", item_id=rec["alt_item_id"],
              subject=ExRef("planned_order", str(po.no), f"P-{po.no}"), d=po.start, qty=rec["alt_qty"],
              message=f"{fqty(rec['alt_qty'])} of {alt_pn} (alternate) instead of {prim_pn} for P-{po.no} "
                      f"({items[po.item_id].part_number}), primary late.",
              action="Check the alternate is acceptable for this order.",
              related=[ExRef("item", rec["primary_item_id"], prim_pn)])
    # 18 serial overlap (open lines, across orders)
    by_item: dict[str, list[Any]] = {}
    for d in c.snap.demand:
        if d.serial_from is not None and d.serial_to is not None and d.open_qty > EPS:
            by_item.setdefault(d.item_id, []).append(d)
    for iid, lines in sorted(by_item.items()):
        lines.sort(key=lambda d: (d.serial_from, d.serial_to, d.number, d.line_no))
        hits: dict[str, list[Any]] = {}
        for i, a in enumerate(lines):
            for bb in lines[i + 1:]:
                if bb.serial_from > a.serial_to:
                    break
                if bb.order_id != a.order_id:
                    hits.setdefault(a.line_id, [a]).append(bb)
                    hits.setdefault(bb.line_id, [bb]).append(a)
        for _lid, (d, *others) in sorted(hits.items()):
            label = f"{d.number}/{d.line_no}"
            b.add("MRP_DEMAND_SERIAL_OVERLAP", item_id=iid if iid in items else None,
                  subject=ExRef("demand_line", d.line_id, label), demand_line_id=d.line_id, d=d.due_date,
                  message=f"{label}: serials {d.serial_from}-{d.serial_to} overlap "
                          + ", ".join(f"{o.number}/{o.line_no} ({o.serial_from}-{o.serial_to})" for o in others) + ".",
                  action="Correct the serial ranges.",
                  related=[ExRef("demand_line", o.line_id, f"{o.number}/{o.line_no}") for o in others])
    # 19 reservation excess
    wo_of_comp: dict[str, Any] = {}
    for w in c.snap.work_orders:
        for comp in w.components:
            wo_of_comp[comp[0]] = w
    for s, r, excess in p.res_excess:
        w = wo_of_comp.get(s.reserved_for or "")
        it = items[s.item_id]
        subj = ExRef("work_order", w.id, w.number) if w is not None else ExRef("work_order", None, "?")
        b.add("MRP_RESERVATION_EXCESS", item_id=s.item_id, subject=subj, qty=excess,
              message=f"{subj.label}: {fqty(s.qty)} {it.part_number} reserved, {fqty(r.qty if r else 0)} still "
                      f"needed; {fqty(excess)} treated as free stock.", action="Unreserve the excess.")
    # 20 cycles
    wos = {w.id: w for w in c.snap.work_orders}
    for wid in c.cycle_wos:
        w = wos[wid]
        b.add("MRP_WO_COMPONENT_CYCLE", item_id=w.item_id, subject=ExRef("work_order", w.id, w.number),
              message=f"{w.number}: a component makes the item part of its own structure; its components are "
                      f"planned at their own level.", action="Correct the work order components.")
    # 21 outside horizon
    if p.outside:
        b.add("MRP_DEMAND_OUTSIDE_HORIZON", item_id=None, subject=ExRef("plant", None, "Plant"), qty=p.outside,
              d=c.horizon_end,
              message=f"{p.outside} open demand line(s) are due after the horizon end {fdate(c.horizon_end)} and "
                      f"were not planned.", action="Extend the horizon to include them.")
    b.out.sort(key=sort_key)
    return b.out


__all__ = ["CODES", "CODE_ORDER", "SEVERITY", "build_exceptions", "fdate", "fqty", "sort_key"]

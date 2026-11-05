"""Genealogy (M5-DESIGN 6): trace-edge writers, backfill, traces, where-used, recalls and quarantine.

Writers run in the business transaction (I2/I3): `write_posting_edges` after every posting (issues, receipts,
shipments, transfer ship / receipt, reversals as negative quantities) and `write_serial_edges` after every floor
event that captures or consumes serials. Every edge has a deterministic `source_key`
(`<posting id>:<txn id>` / `ser:<serial id>:<p|c|pp>`), so writers and `trace-backfill` are idempotent
(`INSERT .. ON CONFLICT (source_key) DO NOTHING`).

Node ids: `lot` = lot row id, `serial` = serial row id, `wo` = WO id, `demand_line` = demand line id,
`item_stock` = `<item id>@<location id>` (non-lot stock), `transfer` = the **source** transfer line id (one node
shared by both plants; edges carry `plant_owner_id` of the other plant).

Traces walk the edges level by level (one indexed query per level and plant; 6.2 asks for recursive CTEs - same
result, but the per-level walk applies the precision rule and the cross-plant visibility in Python, 15.WP-S).
"""

from __future__ import annotations

import io
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ....mfg.model_m5 import MAX_TRACE_DEPTH, MAX_TRACE_ROWS
from ....mfg.trace.query import Edge, Node, link_precision, merge_parallel
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.ownership import current_owner, system_scope
from ...errors import ApiError, not_found
from ...schemas import as_utc
from ..db_models import MfgItemRow
from ..db_models_m2 import (MfgDemandLineRow, MfgDemandOrderRow, MfgInvBalanceRow, MfgInvPostingRow,
                            MfgInvTransactionRow, MfgLocationRow, MfgLotRow, MfgPlantMemberRow,
                            MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow, MfgWorkOrderRow)
from ..db_models_m4 import MfgUnitSerialRow
from ..db_models_m5 import MfgRecallRow, MfgTraceEdgeRow, MfgTransferLineRow, MfgTransferOrderRow
from .common import audit, check_version, read_tx, touch
from .m2util import actor_id, iref, page, run_tx

EPS = 1e-9
#: posting types that can produce edges (others - receipts, counts, adjustments, transfers - are skipped cheaply)
TRACE_POSTING_TYPES = ("wo_issue", "wo_return", "wo_receipt", "ship", "transfer_ship", "transfer_receipt")


def stock_id(ex: dict[str, Any], item_id: str, location_id: str) -> str:
    """`item_stock` node id = the non-lot balance row of (item, location) (always exists after a posting)."""
    return ex.get("stock", {}).get((item_id, location_id)) or f"{item_id[:30]}@{location_id[:30]}"


# ---------------------------------------------------------------- writers (6.1)

def _insert(s: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    if s.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        n = 0
        for k in range(0, len(rows), 2000):
            res = s.execute(insert(MfgTraceEdgeRow.__table__).values(rows[k:k + 2000])
                            .on_conflict_do_nothing(index_elements=["source_key"])
                            .returning(MfgTraceEdgeRow.__table__.c.id))
            n += len(res.all())
        return n
    have = set(s.execute(select(MfgTraceEdgeRow.source_key).where(
        MfgTraceEdgeRow.source_key.in_([r["source_key"] for r in rows]))).scalars())
    new = [r for r in rows if r["source_key"] not in have]
    if new:
        s.execute(MfgTraceEdgeRow.__table__.insert(), new)
    return len(new)


def _edge(owner: str, key: str, fk: str, fid: str, fitem: str | None, tk: str, tid: str, titem: str | None,
          qty: float | None, precision: str, at: datetime, posting_id: str | None = None,
          floor_event_id: str | None = None, plant_owner_id: str | None = None) -> dict[str, Any]:
    return {"id": new_id("tre_"), "owner_id": owner, "source_key": key[:200], "from_kind": fk, "from_id": fid,
            "from_item_id": fitem, "to_kind": tk, "to_id": tid, "to_item_id": titem, "qty": qty,
            "precision": precision, "event_at": at, "posting_id": posting_id, "floor_event_id": floor_event_id,
            "plant_owner_id": plant_owner_id}


def _txn_edges(p: MfgInvPostingRow, t: MfgInvTransactionRow, extra: dict[str, Any]) -> list[dict[str, Any]]:
    at = p.created_at or utcnow()
    key = f"{p.id}:{t.id}"
    owner = p.owner_id
    src = ("lot", t.lot_id, "exact") if t.lot_id else ("item_stock", stock_id(extra, t.item_id, t.location_id),
                                                        "possible")
    tt = t.txn_type
    if tt in ("wo_issue", "wo_return") and t.wo_id:
        wo_item = extra.get("wo_items", {}).get(t.wo_id)
        return [_edge(owner, key, src[0], src[1], t.item_id, "wo", t.wo_id, wo_item, -t.qty, src[2], at, p.id)]
    if tt == "wo_receipt" and t.wo_id and abs(t.qty) > EPS:
        return [_edge(owner, key, "wo", t.wo_id, t.item_id, src[0], src[1], t.item_id, t.qty, src[2], at, p.id)]
    if tt == "ship" and t.demand_line_id:
        return [_edge(owner, key, src[0], src[1], t.item_id, "demand_line", t.demand_line_id, t.item_id, -t.qty,
                      src[2], at, p.id)]
    if tt in ("transfer_ship", "transfer_receipt") and t.transfer_line_id:
        node, other = extra.get("transfer", {}).get(t.transfer_line_id, (t.transfer_line_id, None))
        if tt == "transfer_ship":
            return [_edge(owner, key, src[0], src[1], t.item_id, "transfer", node, t.item_id, -t.qty, src[2], at,
                          p.id, plant_owner_id=other)]
        return [_edge(owner, key, "transfer", node, t.item_id, src[0], src[1], t.item_id, t.qty, src[2], at, p.id,
                      plant_owner_id=other)]
    return []


def _extra(s: Session, txns: list[MfgInvTransactionRow]) -> dict[str, Any]:
    wo_ids = sorted({t.wo_id for t in txns if t.wo_id and t.txn_type in ("wo_issue", "wo_return")})
    out: dict[str, Any] = {"wo_items": {}, "transfer": {}}
    if wo_ids:
        out["wo_items"] = dict(s.execute(select(MfgWorkOrderRow.id, MfgWorkOrderRow.item_id)
                                         .where(MfgWorkOrderRow.id.in_(wo_ids))).all())
    pairs = sorted({(t.item_id, t.location_id) for t in txns if not t.lot_id})
    if pairs:
        out["stock"] = {}
        items_ = sorted({p[0] for p in pairs})
        for k in range(0, len(items_), 2000):
            for b in s.execute(select(MfgInvBalanceRow.id, MfgInvBalanceRow.item_id, MfgInvBalanceRow.location_id)
                               .where(MfgInvBalanceRow.item_id.in_(items_[k:k + 2000]),
                                      MfgInvBalanceRow.lot_key == "")).all():
                out["stock"][(b[1], b[2])] = b[0]
    tl = sorted({t.transfer_line_id for t in txns if t.transfer_line_id})
    if tl:
        with system_scope():
            for ln, o in s.execute(select(MfgTransferLineRow, MfgTransferOrderRow).join(
                    MfgTransferOrderRow, MfgTransferOrderRow.id == MfgTransferLineRow.order_id)
                    .where(MfgTransferLineRow.id.in_(tl))).all():
                if o.direction == "out":
                    out["transfer"][ln.id] = (ln.id, o.dest_owner_id)
                else:
                    out["transfer"][ln.id] = (ln.mirror_line_id or ln.id, o.source_owner_id)
    return out


def write_posting_edges(s: Session, posting: MfgInvPostingRow) -> int:
    if posting.type not in TRACE_POSTING_TYPES:
        return 0
    txns = list(s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id == posting.id)
                          .order_by(MfgInvTransactionRow.line_no, MfgInvTransactionRow.id)).scalars())
    ex = _extra(s, txns)
    rows = [e for t in txns for e in _txn_edges(posting, t, ex)]
    return _insert(s, rows)


def _serial_edges(u: MfgUnitSerialRow, wo_items: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    at = u.captured_at or u.created_at
    if u.wo_id:
        out.append(_edge(u.owner_id, f"ser:{u.id}:p", "wo", u.wo_id, u.item_id, "serial", u.id, u.item_id, 1.0,
                         "exact", at, floor_event_id=u.event_id))
    if u.consumed_wo_id:
        out.append(_edge(u.owner_id, f"ser:{u.id}:c", "serial", u.id, u.item_id, "wo", u.consumed_wo_id,
                         wo_items.get(u.consumed_wo_id), 1.0, "exact", u.consumed_at or at))
    if u.parent_serial_id:
        out.append(_edge(u.owner_id, f"ser:{u.id}:pp", "serial", u.id, u.item_id, "serial", u.parent_serial_id,
                         None, 1.0, "exact", u.consumed_at or at))
    return out


def write_serial_edges(s: Session, serials: Iterable[MfgUnitSerialRow]) -> int:
    rows_ = [u for u in serials if u is not None]
    if not rows_:
        return 0
    s.flush()
    wids = sorted({u.consumed_wo_id for u in rows_ if u.consumed_wo_id})
    wo_items = dict(s.execute(select(MfgWorkOrderRow.id, MfgWorkOrderRow.item_id)
                              .where(MfgWorkOrderRow.id.in_(wids))).all()) if wids else {}
    return _insert(s, [e for u in rows_ for e in _serial_edges(u, wo_items)])


def backfill(s: Session, owner_id: str | None = None) -> dict[str, int]:
    """Rebuild edges from the ledger and the M4 serial history (idempotent; 6.1). `owner_id=None`: every plant
    (caller in `system_scope`)."""
    t0 = time.monotonic()
    cond = [MfgInvPostingRow.owner_id == owner_id] if owner_id else []
    n_post = n_edges = 0
    last = ""
    while True:
        posts = list(s.execute(select(MfgInvPostingRow).where(*cond, MfgInvPostingRow.id > last)
                               .order_by(MfgInvPostingRow.id).limit(1000)).scalars())
        if not posts:
            break
        last = posts[-1].id
        by = {p.id: p for p in posts if p.type in TRACE_POSTING_TYPES}
        if not by:
            n_post += len(posts)
            continue
        txns = list(s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id.in_(sorted(by)))
                              .order_by(MfgInvTransactionRow.posting_id, MfgInvTransactionRow.line_no)).scalars())
        ex = _extra(s, txns)
        n_edges += _insert(s, [e for t in txns for e in _txn_edges(by[t.posting_id], t, ex)])
        n_post += len(posts)
    scond = [MfgUnitSerialRow.owner_id == owner_id] if owner_id else []
    last = ""
    n_ser = 0
    while True:
        sers = list(s.execute(select(MfgUnitSerialRow).where(*scond, MfgUnitSerialRow.id > last)
                              .order_by(MfgUnitSerialRow.id).limit(2000)).scalars())
        if not sers:
            break
        last = sers[-1].id
        n_ser += len(sers)
        n_edges += write_serial_edges(s, sers)
    s.flush()
    return {"postings": n_post, "serials": n_ser, "edges_added": n_edges,
            "duration_ms": int((time.monotonic() - t0) * 1000)}


# ---------------------------------------------------------------- traversal (6.2)

def visible_owners(s: Session, user_id: str, home: str) -> set[str]:
    out = {home, user_id}
    out |= set(s.execute(select(MfgPlantMemberRow.owner_id).where(MfgPlantMemberRow.user_id == user_id,
                                                                  MfgPlantMemberRow.active.is_(True))).scalars())
    return out


def _as_edge(r: MfgTraceEdgeRow) -> Edge:
    return Edge(r.owner_id, r.from_kind, r.from_id, r.from_item_id, r.to_kind, r.to_id, r.to_item_id, r.qty,
                r.precision, r.event_at, r.plant_owner_id)


def _fetch(s: Session, frontier: list[Node], forward: bool) -> dict[tuple[str, str, str], list[Edge]]:
    by_owner: dict[str, set[str]] = defaultdict(set)
    for n in frontier:
        by_owner[n.owner_id].add(n.id)
    out: dict[tuple[str, str, str], list[Edge]] = defaultdict(list)
    col = MfgTraceEdgeRow.from_id if forward else MfgTraceEdgeRow.to_id
    for owner, ids in by_owner.items():
        ids_ = sorted(ids)
        for k in range(0, len(ids_), 2000):
            for r in s.execute(select(MfgTraceEdgeRow).where(MfgTraceEdgeRow.owner_id == owner,
                                                             col.in_(ids_[k:k + 2000]))).scalars():
                e = _as_edge(r)
                key = (owner, e.from_kind, e.from_id) if forward else (owner, e.to_kind, e.to_id)
                out[key].append(e)
    return out


def walk(s: Session, roots: list[tuple[str, str, str]], forward: bool, depth: int, include_possible: bool,
         visible: set[str], limit: int = MAX_TRACE_ROWS) -> tuple[list[Node], list[Node], bool]:
    """BFS from `roots` [(owner, kind, id)] -> (root nodes, all nodes, truncated)."""
    seen: dict[tuple[str, str, str], Node] = {}
    rootn = []
    for o, k, i in roots:
        n = Node(o, k, i, None, None, "exact", None, 0)
        seen[n.key] = n
        rootn.append(n)
    frontier = list(rootn)
    truncated = False
    for d in range(1, depth + 1):
        if not frontier:
            break
        adj = _fetch(s, frontier, forward)
        nxt: list[Node] = []
        for parent in frontier:
            edges = merge_parallel(adj.get(parent.key, []), forward)
            # a transfer node continues in the other plant (shared node id), when that plant is visible
            if parent.kind == "transfer" and parent.via is not None and not any(
                    e.plant_owner_id for e in edges):
                pass
            for e in edges:
                kind, nid, item = (e.to_kind, e.to_id, e.to_item_id) if forward else \
                    (e.from_kind, e.from_id, e.from_item_id)
                prec = link_precision(parent, e.precision, kind)
                if prec == "possible" and not include_possible:
                    continue
                key = (parent.owner_id, kind, nid)
                if key in seen:
                    continue
                if len(seen) >= limit:
                    truncated = True
                    break
                n = Node(parent.owner_id, kind, nid, item, e.qty, prec, e.event_at, d, parent)
                seen[key] = n
                parent.children.append(n)
                nxt.append(n)
                if kind == "transfer" and e.plant_owner_id and e.plant_owner_id != parent.owner_id:
                    okey = (e.plant_owner_id, "transfer", nid)
                    if okey not in seen and e.plant_owner_id in visible:
                        on = Node(e.plant_owner_id, "transfer", nid, item, e.qty, "exact", e.event_at, d, n)
                        seen[okey] = on
                        n.children.append(on)
                        nxt.append(on)
                    elif e.plant_owner_id not in visible:
                        n.children.append(Node(e.plant_owner_id, "plant", e.plant_owner_id, None, None, "exact",
                                               None, d + 1, n))
            if truncated:
                break
        frontier = nxt
        if truncated:
            break
    return rootn, list(seen.values()), truncated


def _plant_codes(s: Session, owners: Iterable[str]) -> dict[str, str]:
    from ...auth.models import UserRow
    from ..db_models_m5 import OrgPlantRow

    owners = sorted(set(owners))
    if not owners:
        return {}
    out = dict(s.execute(select(OrgPlantRow.plant_owner_id, OrgPlantRow.code)
                         .where(OrgPlantRow.plant_owner_id.in_(owners))).all())
    for uid, email in s.execute(select(UserRow.id, UserRow.email).where(UserRow.id.in_(owners))).all():
        out.setdefault(uid, email or uid)
    return out


def describe(s: Session, nodes: list[Node], home: str, visible: set[str]) -> dict[tuple[str, str, str], dict]:
    """Labels / status / item / location per node (batched per kind)."""
    by: dict[str, set[str]] = defaultdict(set)
    for n in nodes:
        by[n.kind].add(n.id)
    info: dict[tuple[str, str], dict[str, Any]] = {}
    ids = sorted(by["lot"])
    for r in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_(ids))).scalars() if ids else []:
        info[("lot", r.id)] = {"item_id": r.item_id, "label_code": r.lot_code, "status": "on_hold" if r.hold else None,
                               "supplier_lot": r.supplier_lot, "link": f"/mfg/lots?id={r.id}"}
    ids = sorted(by["serial"])
    for r in s.execute(select(MfgUnitSerialRow).where(MfgUnitSerialRow.id.in_(ids))).scalars() if ids else []:
        info[("serial", r.id)] = {"item_id": r.item_id, "label": r.serial, "status": r.status,
                                  "link": f"/mfg/serials/{r.id}"}
    ids = sorted(by["wo"])
    for r in s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.id.in_(ids))).scalars() if ids else []:
        info[("wo", r.id)] = {"item_id": r.item_id, "label": r.number, "status": r.status, "qty": r.qty,
                              "link": f"/mfg/work-orders/{r.id}"}
    ids = sorted(by["demand_line"])
    if ids:
        for dl, o in s.execute(select(MfgDemandLineRow, MfgDemandOrderRow).join(
                MfgDemandOrderRow, MfgDemandOrderRow.id == MfgDemandLineRow.order_id)
                .where(MfgDemandLineRow.id.in_(ids))).all():
            info[("demand_line", dl.id)] = {"item_id": dl.item_id, "label": f"{o.number}/{dl.line_no}"
                                            + (f" {o.customer}" if o.customer else ""), "status": o.status,
                                            "customer": o.customer, "program": o.program, "order": o.number,
                                            "order_id": o.id, "link": f"/mfg/demand/{o.id}"}
    ids = sorted(by["transfer"])
    if ids:
        for ln, o in s.execute(select(MfgTransferLineRow, MfgTransferOrderRow).join(
                MfgTransferOrderRow, MfgTransferOrderRow.id == MfgTransferLineRow.order_id)
                .where(or_(MfgTransferLineRow.id.in_(ids), MfgTransferLineRow.mirror_line_id.in_(ids)))).all():
            node = ln.id if o.direction == "out" else (ln.mirror_line_id or ln.id)
            info[("transfer", node)] = {"item_id": ln.item_id, "label": f"{o.number}/{ln.line_no}",
                                        "status": o.status, "link": f"/mfg/transfers/{o.id}"}
    locs: set[str] = set()
    ids = sorted(by["item_stock"])
    for b in s.execute(select(MfgInvBalanceRow).where(MfgInvBalanceRow.id.in_(ids))).scalars() if ids else []:
        locs.add(b.location_id)
        info[("item_stock", b.id)] = {"item_id": b.item_id, "location_id": b.location_id,
                                      "on_hand": b.qty_on_hand}
    loc_codes = dict(s.execute(select(MfgLocationRow.id, MfgLocationRow.code)
                               .where(MfgLocationRow.id.in_(sorted(locs)))).all()) if locs else {}
    item_ids = {v["item_id"] for v in info.values() if v.get("item_id")} | {n.item_id for n in nodes if n.item_id}
    its = {r.id: r for r in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(sorted(item_ids)))).scalars()} \
        if item_ids else {}
    codes = _plant_codes(s, {n.owner_id for n in nodes if n.owner_id != home} | {n.id for n in nodes
                                                                                 if n.kind == "plant"})
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for n in nodes:
        d = dict(info.get((n.kind, n.id), {}))
        iid = d.get("item_id") or n.item_id
        it = its.get(iid) if iid else None
        if n.kind == "lot":
            d["label"] = f"{it.part_number if it else '?'} lot {d.get('label_code', '?')}"
        elif n.kind == "item_stock":
            d["label"] = f"{it.part_number if it else '?'} @ {loc_codes.get(d.get('location_id'), '?')}"
            d["status"] = loc_codes.get(d.get("location_id"))
        elif n.kind == "plant":
            d["label"] = f"in plant {codes.get(n.id, n.id)}, not visible"
        d.setdefault("label", n.id)
        d["item"] = iref(it, iid).__dict__ if it is not None else None
        if n.owner_id != home or n.kind == "plant":
            oid = n.id if n.kind == "plant" else n.owner_id
            d["plant"] = {"owner_id": oid, "code": codes.get(oid, ""), "visible": oid in visible}
        out[n.key] = d
    return out


def _render(n: Node, meta: dict[tuple[str, str, str], dict]) -> dict[str, Any]:
    d = meta.get(n.key, {})
    return {"kind": "transfer" if n.kind == "plant" else n.kind, "id": n.id, "item": d.get("item"),
            "label": d.get("label", n.id), "qty": round(n.qty, 6) if n.qty is not None else None,
            "precision": n.precision, "at": as_utc(n.at) if n.at else None, "status": d.get("status"),
            "plant": d.get("plant"), "link": d.get("link", ""), "depth": n.depth,
            "children": [_render(c, meta) for c in n.children]}


def _root_owner_check(s: Session, kind: str, id_: str, owner: str) -> None:
    model = {"lot": MfgLotRow, "serial": MfgUnitSerialRow, "wo": MfgWorkOrderRow}[kind]
    r = s.get(model, id_)
    if r is None or r.owner_id != owner:
        raise not_found({"lot": "Lot", "serial": "Serial", "wo": "Work order"}[kind], id_)


def trace(ctx: AppContext, kind: str, id_: str, direction: str, depth: int, include_possible: bool) -> dict[str, Any]:
    if depth > MAX_TRACE_DEPTH:
        raise ApiError(422, "TRACE_TOO_DEEP", f"The depth is limited to {MAX_TRACE_DEPTH}.", {"max": MAX_TRACE_DEPTH})
    home = str(current_owner())
    user = actor_id()
    with system_scope(), ctx.db.read() as s:
        _root_owner_check(s, kind, id_, home)
        vis = visible_owners(s, user, home)
        roots, nodes, trunc = walk(s, [(home, kind, id_)], direction == "forward", depth, include_possible, vis)
        meta = describe(s, nodes, home, vis)
        root = roots[0]
        r = _render(root, meta)
        if kind == "serial" or kind == "wo":
            r["qty"] = 1.0 if kind == "serial" else meta.get(root.key, {}).get("qty")
    return {"root": r, "direction": direction, "depth": depth, "nodes": len(nodes), "truncated": trunc}


def _source_lots(s: Session, owner: str, item_id: str, lot_code: str | None, supplier_lot: str | None) -> list[str]:
    q = select(MfgLotRow.id).where(MfgLotRow.owner_id == owner, MfgLotRow.item_id == item_id)
    if lot_code:
        q = q.where(MfgLotRow.lot_code == lot_code)
    if supplier_lot:
        q = q.where(MfgLotRow.supplier_lot == supplier_lot)
    return list(s.execute(q.order_by(MfgLotRow.lot_code)).scalars())


def where_used(ctx: AppContext, item_id: str, lot_code: str | None, supplier_lot: str | None) -> dict[str, Any]:
    if not lot_code and not supplier_lot:
        raise ApiError(422, "VALIDATION_ERROR", "Give lot_code or supplier_lot.",
                       {"errors": [{"loc": ["query", "lot_code"], "msg": "required", "type": "missing"}]})
    home = str(current_owner())
    with system_scope(), ctx.db.read() as s:
        lots = _source_lots(s, home, item_id, lot_code, supplier_lot)
        vis = visible_owners(s, actor_id(), home)
        roots, nodes, trunc = walk(s, [(home, "lot", x) for x in lots], True, MAX_TRACE_DEPTH, True, vis)
        meta = describe(s, nodes, home, vis)
        rootkeys = {r.key for r in roots}
        items = [{"kind": n.kind, "id": n.id, "label": meta[n.key].get("label", n.id), "precision": n.cumulative(),
                  "depth": n.depth, "status": meta[n.key].get("status"), "link": meta[n.key].get("link", "")}
                 for n in sorted(nodes, key=lambda n: (n.depth, n.kind, n.id)) if n.key not in rootkeys
                 and n.kind != "plant"]
    return {"items": items, "lots": lots, "truncated": trunc}


# ---------------------------------------------------------------- recalls (6.3)

def _report(s: Session, home: str, sources: list[dict[str, Any]], include_possible: bool, user: str
            ) -> dict[str, Any]:
    t0 = time.monotonic()
    roots: list[tuple[str, str, str]] = []
    for src in sources:
        if src.get("supplier_lot"):
            roots += [(home, "lot", x) for x in _source_lots(s, home, src["item_id"], None, src["supplier_lot"])]
        else:
            _root_owner_check(s, src["kind"], src["id"], home)
            roots.append((home, src["kind"], src["id"]))
    vis = visible_owners(s, user, home)
    rootn, nodes, trunc = walk(s, roots, True, MAX_TRACE_DEPTH, include_possible, vis)
    meta = describe(s, nodes, home, vis)

    def label(n: Node) -> str:
        return meta.get(n.key, {}).get("label", n.id)

    units, wos, ships = [], [], []
    lot_ids = []
    for n in nodes:
        m = meta.get(n.key, {})
        if n.kind == "serial":
            downstream = [c for c in _desc(n) if c.kind == "demand_line"]
            d0 = meta.get(downstream[0].key, {}) if downstream else {}
            units.append({"serial_id": n.id, "serial": m.get("label"), "item": (m.get("item") or {}).get(
                "part_number"), "status": m.get("status"), "precision": n.cumulative(),
                "customer": d0.get("customer") or None, "demand_order": d0.get("order"),
                "shipped_on": as_utc(downstream[0].at).date().isoformat() if downstream and downstream[0].at
                else None, "plant": m.get("plant"), "path": [label(x) for x in n.path()]})
        elif n.kind == "wo":
            wos.append({"id": n.id, "number": m.get("label"), "status": m.get("status"), "precision": n.cumulative()})
        elif n.kind == "demand_line":
            ships.append({"demand_line_id": n.id, "demand_order": m.get("order"), "customer": m.get("customer") or "",
                          "program": m.get("program"), "qty": round(n.qty or 0.0, 6), "precision": n.cumulative(),
                          "shipped_on": as_utc(n.at).date().isoformat() if n.at else None,
                          "item": (m.get("item") or {}).get("part_number"), "path": [label(x) for x in n.path()]})
        elif n.kind == "lot" and n.owner_id == home:
            lot_ids.append(n.id)
    lots = []
    if lot_ids:
        locs = {r.id: r for r in s.execute(select(MfgLocationRow).where(MfgLocationRow.owner_id == home)).scalars()}
        lot_rows = {r.id: r for r in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_(lot_ids))).scalars()}
        its = {r.id: r for r in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(
            sorted({x.item_id for x in lot_rows.values()})))).scalars()}
        bal = defaultdict(list)
        for b in s.execute(select(MfgInvBalanceRow).where(MfgInvBalanceRow.lot_id.in_(lot_ids),
                                                          MfgInvBalanceRow.qty_on_hand > EPS)).scalars():
            bal[b.lot_id].append(b)
        node_of = {n.id: n for n in nodes if n.kind == "lot"}
        for lid in lot_ids:
            lr = lot_rows.get(lid)
            if lr is None:
                continue
            bs = bal.get(lid) or [None]
            for b in bs:
                lc = locs.get(b.location_id) if b is not None else None
                lots.append({"lot_id": lid, "lot_code": lr.lot_code, "supplier_lot": lr.supplier_lot,
                             "item": its[lr.item_id].part_number if lr.item_id in its else "?",
                             "item_id": lr.item_id, "on_hand": round(b.qty_on_hand, 6) if b is not None else 0,
                             "location": lc.code if lc else None, "location_id": lc.id if lc else None,
                             "location_kind": lc.kind if lc else None, "hold": lr.hold,
                             "precision": node_of[lid].cumulative()})
    by_customer: dict[str, dict[str, Any]] = {}
    for u in units:
        if u["customer"]:
            by_customer.setdefault(u["customer"], {"customer": u["customer"], "units": 0, "shipments": 0})
            by_customer[u["customer"]]["units"] += 1
    by_program: dict[str, dict[str, Any]] = {}
    for sh in ships:
        c = sh["customer"] or "(none)"
        by_customer.setdefault(c, {"customer": c, "units": 0, "shipments": 0})["shipments"] += 1
        by_customer[c]["qty"] = round(by_customer[c].get("qty", 0.0) + sh["qty"], 6)
        if sh["program"]:
            p = by_program.setdefault(sh["program"], {"program": sh["program"], "shipments": 0, "qty": 0.0})
            p["shipments"] += 1
            p["qty"] = round(p["qty"] + sh["qty"], 6)
    # open purchase orders of the source items (for quarantine of incoming material)
    src_items = {lr for lr in (s.execute(select(MfgLotRow.item_id).where(MfgLotRow.id.in_(
        [r[2] for r in roots if r[1] == "lot"]))).scalars() if any(r[1] == "lot" for r in roots) else [])}
    open_pos = []
    if src_items:
        for doc, ln, sc in s.execute(select(MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow).join(
                MfgPurchaseLineRow, MfgPurchaseLineRow.doc_id == MfgPurchaseDocRow.id).join(
                MfgPurchaseScheduleRow, MfgPurchaseScheduleRow.line_id == MfgPurchaseLineRow.id).where(
                MfgPurchaseDocRow.owner_id == home, MfgPurchaseDocRow.doc_type == "po",
                MfgPurchaseDocRow.status.in_(("open", "partially_received")),
                MfgPurchaseLineRow.item_id.in_(sorted(src_items)), MfgPurchaseScheduleRow.closed.is_(False))).all():
            left = round(sc.qty - sc.received_qty, 6)
            if left > EPS:
                open_pos.append({"number": doc.number, "line_no": ln.line_no, "seq": sc.seq, "open_qty": left,
                                 "due": sc.requested_date.isoformat()})
    return {"units": units, "lots": lots, "wos": wos, "shipments": ships,
            "by_customer": sorted(by_customer.values(), key=lambda x: x["customer"]),
            "by_program": sorted(by_program.values(), key=lambda x: x["program"]), "open_pos": open_pos,
            "counts": {"units": len(units), "units_exact": sum(1 for u in units if u["precision"] == "exact"),
                       "lots": len(lots), "wos": len(wos), "shipments": len(ships), "nodes": len(nodes)},
            "truncated": trunc, "computed_ms": int((time.monotonic() - t0) * 1000)}


def _desc(n: Node) -> list[Node]:
    out, stack = [], list(n.children)
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(c.children)
    return out


def recall_record(r: MfgRecallRow) -> dict[str, Any]:
    return {"id": r.id, "number": r.number, "name": r.name, "sources": r.sources, "include_possible":
            r.include_possible, "report": r.report, "quarantined_at": as_utc(r.quarantined_at),
            "row_version": r.row_version, "created_at": as_utc(r.created_at), "updated_at": as_utc(r.updated_at)}


def create_recall(ctx: AppContext, inp: Any) -> dict[str, Any]:
    home = str(current_owner())
    user = actor_id()
    sources = [x.model_dump(exclude_none=True) for x in inp.sources]
    with system_scope(), ctx.db.read() as s:
        report = _report(s, home, sources, inp.include_possible, user)

    def fn(s: Session) -> dict[str, Any]:
        from .. import repo_m2

        number = repo_m2.next_number(s, "RCL", repo_m2.number_taken(s, MfgRecallRow))
        now = utcnow()
        r = MfgRecallRow(id=new_id("rcl_"), number=number, name=inp.name, sources=sources,
                         include_possible=inp.include_possible, report=report, quarantined_at=None, actor_id=user,
                         row_version=1, created_at=now, updated_at=now)
        s.add(r)
        s.flush()
        audit(s, "recall", r.id, "create", {"number": number, "units": report["counts"]["units"]})
        return recall_record(r)

    return run_tx(ctx, fn)


def list_recalls(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    from sqlalchemy import func

    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgRecallRow)).scalar() or 0)
        rows = list(s.execute(select(MfgRecallRow).order_by(MfgRecallRow.created_at.desc(), MfgRecallRow.id)
                              .limit(limit).offset(offset)).scalars())
        return page([{**recall_record(r), "report": {"counts": (r.report or {}).get("counts")}} for r in rows],
                    total, limit, offset)


def get_recall(ctx: AppContext, recall_id: str) -> dict[str, Any]:
    from .. import repo

    with read_tx(ctx) as s:
        return recall_record(repo.get_row(s, MfgRecallRow, recall_id, what="Recall"))


def export_recall(ctx: AppContext, recall_id: str) -> tuple[bytes, str]:
    """xlsx with one sheet per section (units, shipments, lots, WOs, per customer)."""
    from openpyxl import Workbook

    rec = get_recall(ctx, recall_id)
    rep = rec["report"] or {}
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in (("units", rep.get("units", [])), ("shipments", rep.get("shipments", [])),
                       ("lots", rep.get("lots", [])), ("work_orders", rep.get("wos", [])),
                       ("by_customer", rep.get("by_customer", [])), ("by_program", rep.get("by_program", [])),
                       ("open_pos", rep.get("open_pos", []))):
        ws = wb.create_sheet(name)
        cols = sorted({k for r in rows for k in r if k not in ("plant",)}) if rows else ["(none)"]
        ws.append(cols)
        for r in rows:
            ws.append([" > ".join(r[c]) if isinstance(r.get(c), list) else r.get(c) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"{rec['number']}.xlsx"


def quarantine(ctx: AppContext, recall_id: str, inp: Any) -> dict[str, Any]:
    """Move every in-stock affected lot balance (outside quarantine locations) to the quarantine location, one
    `transfer` posting per balance, and put the lots on hold (6.3). Serialized units without lots stay where they
    are (their stock is not lot-addressable; listed in the report)."""
    from ....mfg.model_m2 import TransferLine, TransferPosting
    from .. import repo
    from .inventory import post_in_session

    def fn(s: Session) -> dict[str, Any]:
        r = repo.get_row(s, MfgRecallRow, recall_id, what="Recall", lock=True)
        if inp.location_id:
            q = repo.get_row(s, MfgLocationRow, inp.location_id, what="Location")
        else:
            q = s.execute(select(MfgLocationRow).where(MfgLocationRow.kind == "quarantine",
                                                       MfgLocationRow.active.is_(True))
                          .order_by(MfgLocationRow.code)).scalars().first()
            if q is None:
                raise ApiError(422, "VALIDATION_ERROR", "This plant has no quarantine location; create one first.",
                               {"errors": [{"loc": ["body", "location_id"], "msg": "required", "type": "missing"}]})
        if q.kind != "quarantine":
            raise ApiError(422, "VALIDATION_ERROR", f"{q.code} is not a quarantine location.",
                           {"errors": [{"loc": ["body", "location_id"], "msg": "not quarantine",
                                        "type": "value_error"}]})
        lot_ids = sorted({x["lot_id"] for x in (r.report or {}).get("lots", [])})
        only = set(getattr(inp, "lot_ids", None) or [])
        if only:
            lot_ids = [x for x in lot_ids if x in only]
        postings, moved = [], 0
        lots = {x.id: x for x in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_(lot_ids))
                                           .with_for_update()).scalars()} if lot_ids else {}
        bals = list(s.execute(select(MfgInvBalanceRow).where(MfgInvBalanceRow.lot_id.in_(lot_ids),
                                                             MfgInvBalanceRow.qty_on_hand > EPS)
                              .order_by(MfgInvBalanceRow.item_id, MfgInvBalanceRow.location_id,
                                        MfgInvBalanceRow.lot_key)).scalars()) if lot_ids else []
        locs = {x.id: x for x in s.execute(select(MfgLocationRow)).scalars()}
        for b in bals:
            if b.location_id == q.id or locs[b.location_id].kind == "quarantine":
                continue
            qty = round(b.qty_on_hand - b.qty_reserved, 6)
            if qty <= EPS:
                continue
            lot = lots[b.lot_id]
            row, _w = post_in_session(s, TransferPosting.model_construct(
                type="transfer", txn_date=None, note=f"Recall {r.number} quarantine {inp.note}".strip()[:500],
                reason_code="RECALL", lines=[TransferLine.model_construct(
                    item_id=b.item_id, from_location_id=b.location_id, to_location_id=q.id, qty=qty,
                    lot_code=lot.lot_code)]), system=True)
            postings.append({"id": row.id, "number": row.number})
            moved += 1
        held = 0
        for lot in lots.values():
            if not lot.hold:
                lot.hold = True
                touch(lot)
                held += 1
        r.quarantined_at = utcnow()
        touch(r)
        s.flush()
        audit(s, "recall", r.id, "quarantine", {"postings": len(postings), "lots_on_hold": held,
                                                "location": q.code})
        return {"moved": moved, "lots_on_hold": held, "held_lots": sorted(lots), "postings": postings,
                "location_id": q.id}

    return run_tx(ctx, fn, lock=True)


_ = (UTC, check_version)

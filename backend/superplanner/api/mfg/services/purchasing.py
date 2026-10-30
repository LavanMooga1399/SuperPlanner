"""Purchase requests and orders (M2-DESIGN 3.5, 5, 12.3 #106-125): one document model with lines and staggered
delivery schedule lines; status machines from `mfg.purchasing`; PR -> PO conversion; the delivery board.

Transactional writes (no plant lock). Lock order: the document header (`FOR NO KEY UPDATE`), its schedules
(`FOR UPDATE`), then the number series. Received quantities move only through `po_receipt` postings.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ....mfg import purchasing as PUR
from ....mfg.dataset import ref
from ....mfg.model_m2 import EPS, PurchaseDocInput
from ....mfg.purchasing import RuleError
from ....mfg.units import is_count
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from ...schemas import as_utc
from .. import repo, repo_m2
from ..db_models import MfgItemRow
from ..db_models_m2 import (MfgInvPostingRow, MfgInvTransactionRow, MfgItemSupplierRow, MfgPurchaseDocRow,
                            MfgPurchaseLineRow, MfgPurchaseScheduleRow, MfgSupplierRow)
from .common import audit, check_version, ensure_unique, ilike, read_tx, touch, unknown_ref
from .m2util import (actor_id, iref, is_workspace_owner, items, page, r6, request_hash, rule_error, run_tx, today,
                     user_names)

KIND = {"pr": "PR", "po": "PO"}
WHAT = {"pr": "Purchase request", "po": "Purchase order"}
PATH = {"pr": "requests", "po": "orders"}


# ---------------------------------------------------------------- records


def _load(s: Session, docs: list[MfgPurchaseDocRow]) -> tuple[dict[str, list[MfgPurchaseLineRow]],
                                                               dict[str, list[MfgPurchaseScheduleRow]]]:
    ids = [d.id for d in docs]
    lines: dict[str, list[MfgPurchaseLineRow]] = {i: [] for i in ids}
    scheds: dict[str, list[MfgPurchaseScheduleRow]] = {}
    if not ids:
        return lines, scheds
    lrows = list(s.execute(select(MfgPurchaseLineRow).where(MfgPurchaseLineRow.doc_id.in_(ids))
                           .order_by(MfgPurchaseLineRow.line_no)).scalars())
    for ln in lrows:
        lines[ln.doc_id].append(ln)
    if lrows:
        for sc in s.execute(select(MfgPurchaseScheduleRow).where(
                MfgPurchaseScheduleRow.line_id.in_([x.id for x in lrows])).order_by(MfgPurchaseScheduleRow.seq)
                ).scalars():
            scheds.setdefault(sc.line_id, []).append(sc)
    return lines, scheds


def _line_links(s: Session, lines: list[MfgPurchaseLineRow]) -> tuple[dict[str, dict[str, Any]],
                                                                       dict[str, dict[str, Any]]]:
    """converted_to (PR line -> PO line) and source_pr (PO line -> PR line)."""
    ids = [ln.id for ln in lines]
    src_ids = [ln.source_pr_line_id for ln in lines if ln.source_pr_line_id]
    conv: dict[str, dict[str, Any]] = {}
    src: dict[str, dict[str, Any]] = {}
    if ids:
        for ln, d in s.execute(select(MfgPurchaseLineRow, MfgPurchaseDocRow)
                               .join(MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id)
                               .where(MfgPurchaseLineRow.source_pr_line_id.in_(ids))).all():
            conv[ln.source_pr_line_id] = {"doc_id": d.id, "number": d.number, "line_no": ln.line_no}
    if src_ids:
        for ln, d in s.execute(select(MfgPurchaseLineRow, MfgPurchaseDocRow)
                               .join(MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id)
                               .where(MfgPurchaseLineRow.id.in_(src_ids))).all():
            src[ln.id] = {"doc_id": d.id, "number": d.number, "line_no": ln.line_no}
    return conv, src


def _sched_view(sc: MfgPurchaseScheduleRow, recv_days: int, d: date) -> dict[str, Any]:
    v = PUR.schedule_view(sc.qty, sc.received_qty, sc.closed, sc.requested_date, sc.confirmed_date, recv_days, d)
    return {"id": sc.id, "seq": sc.seq, "requested_date": sc.requested_date, "confirmed_date": sc.confirmed_date,
            "qty": r6(sc.qty), "received_qty": r6(sc.received_qty), "closed": sc.closed, **v}


def _summary_values(lines: list[MfgPurchaseLineRow], scheds: dict[str, list[MfgPurchaseScheduleRow]],
                    its: dict[str, MfgItemRow], d: date) -> dict[str, Any]:
    vals = []
    overdue = 0
    next_dock: date | None = None
    for ln in lines:
        q = sum(x.qty for x in scheds.get(ln.id, []))
        oq = 0.0
        for sc in scheds.get(ln.id, []):
            o = PUR.schedule_open_qty(sc.qty, sc.received_qty, sc.closed) if ln.status == "open" else 0.0
            oq += o
            dk = PUR.dock_date(sc.requested_date, sc.confirmed_date)
            if o > EPS:
                if dk < d:
                    overdue += 1
                next_dock = dk if next_dock is None or dk < next_dock else next_dock
        vals.append((q, ln.unit_price, oq))
    value, open_value = PUR.doc_value(vals)
    return {"value": value, "open_value": open_value, "overdue_count": overdue, "next_dock_date": next_dock}


def doc_records(s: Session, docs: list[MfgPurchaseDocRow], *, full: bool = True) -> list[dict[str, Any]]:
    d = today(s)
    lines, scheds = _load(s, docs)
    all_lines = [ln for v in lines.values() for ln in v]
    its = items(s, [ln.item_id for ln in all_lines])
    sups = {x.id: x for x in s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id.in_(
        sorted({x.supplier_id for x in docs if x.supplier_id})))).scalars()} if any(x.supplier_id for x in docs) else {}
    names = user_names(s, [u for x in docs for u in (x.submitted_by, x.approved_by) if u]) if full else {}
    conv, src = _line_links(s, all_lines) if full else ({}, {})
    out = []
    for doc in docs:
        sv = _summary_values(lines[doc.id], scheds, its, d)
        base = {"id": doc.id, "doc_type": doc.doc_type, "number": doc.number, "status": doc.status,
                "supplier_id": doc.supplier_id,
                "supplier": ref(sups[doc.supplier_id]) if doc.supplier_id in sups else None,
                "currency": doc.currency, "order_date": doc.order_date, "note": doc.note,
                "external_ref": doc.external_ref, "source": doc.source, "source_run_no": doc.source_run_no,
                "value": sv["value"], "open_value": sv["open_value"], "overdue_count": sv["overdue_count"],
                "row_version": doc.row_version, "created_at": as_utc(doc.created_at),
                "updated_at": as_utc(doc.updated_at)}
        if not full:
            base.update(line_count=len(lines[doc.id]), next_dock_date=sv["next_dock_date"])
            base.pop("note"), base.pop("external_ref"), base.pop("supplier_id")
            out.append(base)
            continue
        base.update(submitted_at=as_utc(doc.submitted_at),
                    submitted_by={"id": doc.submitted_by, "name": names.get(doc.submitted_by, doc.submitted_by)}
                    if doc.submitted_by else None,
                    approved_at=as_utc(doc.approved_at),
                    approved_by={"id": doc.approved_by, "name": names.get(doc.approved_by, doc.approved_by)}
                    if doc.approved_by else None,
                    rejected_reason=doc.rejected_reason)
        lrecs = []
        for ln in lines[doc.id]:
            it = its.get(ln.item_id)
            rd = it.receiving_days if it else 0
            ss = [_sched_view(sc, rd, d) for sc in scheds.get(ln.id, [])]
            if ln.status != "open":
                for x in ss:
                    x["open_qty"], x["overdue"], x["overdue_days"] = 0.0, False, 0
            qty = sum(x["qty"] for x in ss)
            rec = sum(x["received_qty"] for x in ss)
            lrecs.append({"id": ln.id, "line_no": ln.line_no, "item_id": ln.item_id, "item": iref(it, ln.item_id),
                          "unit_price": ln.unit_price, "note": ln.note, "status": ln.status, "qty": r6(qty),
                          "received_qty": r6(rec), "open_qty": r6(sum(x["open_qty"] for x in ss)),
                          "converted_to": conv.get(ln.id), "source_pr": src.get(ln.source_pr_line_id or ""),
                          "schedules": ss})
        base["lines"] = lrecs
        out.append(base)
    return out


def doc_record(s: Session, doc: MfgPurchaseDocRow) -> dict[str, Any]:
    return doc_records(s, [doc])[0]


def _get(s: Session, doc_type: str, doc_id: str, lock: bool = False) -> MfgPurchaseDocRow:
    row = repo.get_row(s, MfgPurchaseDocRow, doc_id, what=WHAT[doc_type], lock=lock)
    if row.doc_type != doc_type:
        from ...errors import not_found

        raise not_found(WHAT[doc_type], doc_id)
    return row


def get_doc(ctx: AppContext, doc_type: str, doc_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        rec = doc_record(s, _get(s, doc_type, doc_id))
        if doc_type == "po":
            rec["receipts"] = _receipts(s, doc_id)
        return rec


def _receipts(s: Session, doc_id: str) -> list[dict[str, Any]]:
    sub = select(MfgPurchaseScheduleRow.id).join(MfgPurchaseLineRow,
                                                 MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id) \
        .where(MfgPurchaseLineRow.doc_id == doc_id)
    pids = select(MfgInvTransactionRow.posting_id).where(MfgInvTransactionRow.schedule_id.in_(sub))
    rows = list(s.execute(select(MfgInvPostingRow).where(MfgInvPostingRow.id.in_(pids))
                          .order_by(MfgInvPostingRow.created_at, MfgInvPostingRow.id)).scalars())
    names = user_names(s, [r.actor_id for r in rows])
    return [{"id": r.id, "number": r.number, "type": r.type, "txn_date": r.txn_date, "note": r.note,
             "actor": {"id": r.actor_id, "name": names.get(r.actor_id, r.actor_id)},
             "created_at": as_utc(r.created_at), "reversal_of_id": r.reversal_of_id} for r in rows]


def list_docs(ctx: AppContext, doc_type: str, *, status: list[str] | None, supplier_id: str | None,
              item_id: str | None, overdue: bool | None, q: str | None, source: str | None, sort: str, limit: int,
              offset: int) -> dict[str, Any]:
    D = MfgPurchaseDocRow
    conds: list[Any] = [D.doc_type == doc_type]
    if status:
        conds.append(D.status.in_(status))
    if supplier_id:
        conds.append(D.supplier_id == supplier_id)
    if source:
        conds.append(D.source == source)
    if q:
        conds.append(ilike(D.number, q) | ilike(D.note, q) | ilike(func.coalesce(D.external_ref, ""), q))
    if item_id:
        conds.append(D.id.in_(select(MfgPurchaseLineRow.doc_id).where(MfgPurchaseLineRow.item_id == item_id)))
    with read_tx(ctx) as s:
        d = today(s)
        if overdue is not None:
            dock = func.coalesce(MfgPurchaseScheduleRow.confirmed_date, MfgPurchaseScheduleRow.requested_date)
            late = select(MfgPurchaseLineRow.doc_id).join(
                MfgPurchaseScheduleRow, MfgPurchaseScheduleRow.line_id == MfgPurchaseLineRow.id).where(
                MfgPurchaseLineRow.status == "open", MfgPurchaseScheduleRow.closed.is_(False),
                MfgPurchaseScheduleRow.qty - MfgPurchaseScheduleRow.received_qty > EPS, dock < d)
            conds.append(D.id.in_(late) if overdue else D.id.not_in(late))
        stmt = select(D).where(*conds)
        if sort == "number":
            stmt = stmt.order_by(D.number, D.id)
            rows = list(s.execute(stmt.limit(limit).offset(offset)).scalars())
        elif sort == "next_dock_date":
            rows = list(s.execute(stmt).scalars())
        else:
            stmt = stmt.order_by(D.created_at.desc(), D.id.desc())
            rows = list(s.execute(stmt.limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(D).where(*conds)).scalar() or 0)
        recs = doc_records(s, rows, full=False)
        if sort == "next_dock_date":
            recs.sort(key=lambda r: (r["next_dock_date"] is None, r["next_dock_date"] or date.max, r["number"]))
            recs = recs[offset:offset + limit]
        return page(recs, total, limit, offset)


# ---------------------------------------------------------------- write helpers


def _item_rows(s: Session, inp: PurchaseDocInput) -> dict[str, MfgItemRow]:
    its = items(s, [ln.item_id for ln in inp.lines])
    for i, ln in enumerate(inp.lines):
        it = its.get(ln.item_id)
        if it is None:
            raise unknown_ref(["body", "lines", i, "item_id"], ln.item_id, "Item")
        if it.make_buy != "buy":
            raise ApiError(422, "MFG_ITEM_NOT_BUY", f"{it.part_number} is not a buy item.",
                           {"loc": ["body", "lines", i, "item_id"]})
        for j, sc in enumerate(ln.schedules):
            if is_count(it.uom) and abs(sc.qty - round(sc.qty)) > EPS:
                raise ApiError(422, "INV_FRACTIONAL_QTY", f"{it.part_number} is counted in {it.uom}; use whole "
                               "numbers.", {"loc": ["body", "lines", i, "schedules", j, "qty"]})
    return its


def _supplier(s: Session, doc_type: str, inp: PurchaseDocInput) -> MfgSupplierRow | None:
    if inp.supplier_id is None:
        if doc_type == "po":
            raise ApiError(422, "PUR_SUPPLIER_REQUIRED", "A purchase order needs a supplier.",
                           {"loc": ["body", "supplier_id"]})
        return None
    sup = s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id == inp.supplier_id)).scalars().first()
    if sup is None:
        raise unknown_ref(["body", "supplier_id"], inp.supplier_id, "Supplier")
    return sup


def _prices(s: Session, item_ids: Iterable[str], supplier_id: str | None) -> dict[str, float | None]:
    """Item-supplier price: the doc supplier's row, else the preferred active row."""
    ids = sorted(set(item_ids))
    if not ids:
        return {}
    rows = list(s.execute(select(MfgItemSupplierRow).where(MfgItemSupplierRow.item_id.in_(ids))).scalars())
    out: dict[str, float | None] = {}
    for i in ids:
        mine = [r for r in rows if r.item_id == i]
        hit = [r for r in mine if r.supplier_id == supplier_id] or [r for r in mine if r.preferred and r.active]
        out[i] = hit[0].unit_price if hit else None
    return out


def _received(s: Session, sched_ids: list[str]) -> set[str]:
    """Schedules with any receipt transaction."""
    if not sched_ids:
        return set()
    return {r[0] for r in s.execute(select(MfgInvTransactionRow.schedule_id)
                                    .where(MfgInvTransactionRow.schedule_id.in_(sched_ids)).distinct()).all()}


def _write_lines(s: Session, doc: MfgPurchaseDocRow, inp: PurchaseDocInput, its: dict[str, MfgItemRow],
                 creating: bool) -> None:
    now = utcnow()
    old_lines = {ln.id: ln for ln in s.execute(select(MfgPurchaseLineRow).where(MfgPurchaseLineRow.doc_id == doc.id)
                                               .with_for_update()).scalars()} if not creating else {}
    old_scheds: dict[str, MfgPurchaseScheduleRow] = {}
    if old_lines:
        for sc in repo_m2.lock_children_of(s, MfgPurchaseScheduleRow, "line_id", old_lines):
            old_scheds[sc.id] = sc
    with_txn = _received(s, sorted(old_scheds))
    prices = _prices(s, [ln.item_id for ln in inp.lines if ln.unit_price is None], doc.supplier_id)
    keep_lines: set[str] = set()
    keep_scheds: set[str] = set()
    used_nos = [ln.line_no for ln in inp.lines if ln.line_no is not None]
    next_no = 10
    for i, li in enumerate(inp.lines):
        if li.id is not None and li.id not in old_lines:
            raise unknown_ref(["body", "lines", i, "id"], li.id, "Line")
        no = li.line_no
        if no is None:
            while next_no in used_nos:
                next_no += 10
            no = next_no
            used_nos.append(no)
            next_no += 10
        if li.id is not None:
            ln = old_lines[li.id]
            has_rec = any(sc.line_id == ln.id and (sc.received_qty > EPS or sc.id in with_txn)
                          for sc in old_scheds.values())
            if has_rec and ln.item_id != li.item_id:
                raise ApiError(422, "PUR_SCHEDULE_HAS_RECEIPTS", "A line with receipts cannot change its item.",
                               {"loc": ["body", "lines", i, "item_id"]})
            ln.line_no, ln.item_id, ln.note = no, li.item_id, li.note
            if li.unit_price is not None or ln.unit_price is None:
                ln.unit_price = li.unit_price if li.unit_price is not None else prices.get(li.item_id)
            touch(ln, now)
        else:
            ln = MfgPurchaseLineRow(id=new_id("pln_"), doc_id=doc.id, line_no=no, item_id=li.item_id,
                                    unit_price=li.unit_price if li.unit_price is not None else prices.get(li.item_id),
                                    status="open", source_pr_line_id=None, note=li.note, row_version=1,
                                    created_at=now, updated_at=now)
            s.add(ln)
        keep_lines.add(ln.id)
        used_seq = [x.seq for x in li.schedules if x.seq is not None]
        nseq = 1
        for j, si in enumerate(li.schedules):
            seq = si.seq
            if seq is None:
                while nseq in used_seq:
                    nseq += 1
                seq = nseq
                used_seq.append(seq)
            if si.id is not None:
                sc = old_scheds.get(si.id)
                if sc is None or sc.line_id != ln.id:
                    raise unknown_ref(["body", "lines", i, "schedules", j, "id"], si.id, "Schedule")
                if si.qty < sc.received_qty - EPS:
                    raise ApiError(422, "PUR_QTY_BELOW_RECEIVED", f"The quantity cannot go below the "
                                   f"{sc.received_qty:g} already received.",
                                   {"loc": ["body", "lines", i, "schedules", j, "qty"]})
                sc.seq, sc.requested_date, sc.confirmed_date, sc.qty = seq, si.requested_date, si.confirmed_date, si.qty
                touch(sc, now)
            else:
                sc = MfgPurchaseScheduleRow(id=new_id("psc_"), line_id=ln.id, seq=seq,
                                            requested_date=si.requested_date, confirmed_date=si.confirmed_date,
                                            qty=si.qty, received_qty=0.0, closed=False, row_version=1, created_at=now,
                                            updated_at=now)
                s.add(sc)
            keep_scheds.add(sc.id)
    for sc in old_scheds.values():
        if sc.id not in keep_scheds and (sc.received_qty > EPS or sc.id in with_txn):
            raise ApiError(422, "PUR_SCHEDULE_HAS_RECEIPTS", "A schedule with receipts cannot be removed.",
                           {"schedule_id": sc.id})
    gone_s = [x for x in old_scheds if x not in keep_scheds]
    gone_l = [x for x in old_lines if x not in keep_lines]
    if gone_s:
        s.execute(delete(MfgPurchaseScheduleRow).where(MfgPurchaseScheduleRow.id.in_(gone_s))
                  .execution_options(synchronize_session=False))
        for x in gone_s:
            obj = old_scheds[x]
            if obj in s:
                s.expunge(obj)
    if gone_l:
        s.execute(delete(MfgPurchaseLineRow).where(MfgPurchaseLineRow.id.in_(gone_l))
                  .execution_options(synchronize_session=False))
        for x in gone_l:
            if old_lines[x] in s:
                s.expunge(old_lines[x])
    _flush_renumbered(s, list(old_lines.values()), list(old_scheds.values()))


def _flush_renumbered(s: Session, lines: list[MfgPurchaseLineRow], scheds: list[MfgPurchaseScheduleRow]) -> None:
    """Flush with unique (doc, line_no) / (line, seq) re-numbering: park changed numbers on negative values
    first so swaps never collide."""
    moved_l = [(ln, ln.line_no) for ln in lines if ln in s and s.is_modified(ln)]
    moved_s = [(sc, sc.seq) for sc in scheds if sc in s and s.is_modified(sc)]
    new = [o for o in s.new]
    for o in new:
        s.expunge(o)
    for k, (ln, _n) in enumerate(moved_l):
        ln.line_no = -(k + 1)
    for k, (sc, _n) in enumerate(moved_s):
        sc.seq = -(k + 1)
    s.flush()
    for ln, n in moved_l:
        ln.line_no = n
    for sc, n in moved_s:
        sc.seq = n
    s.flush()
    lines_new = [o for o in new if isinstance(o, MfgPurchaseLineRow)]
    s.add_all(lines_new)
    s.flush()
    s.add_all([o for o in new if not isinstance(o, MfgPurchaseLineRow)])
    s.flush()


def _derive(s: Session, doc: MfgPurchaseDocRow) -> None:
    if doc.doc_type != "po":
        return
    scs = list(s.execute(select(MfgPurchaseScheduleRow).join(
        MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id).where(
        MfgPurchaseLineRow.doc_id == doc.id)).scalars())
    doc.status = PUR.derive_po_status(doc.status, [PUR.SchedState(x.qty, x.received_qty, x.closed) for x in scs])


def _header(s: Session, doc_type: str, doc: MfgPurchaseDocRow, inp: PurchaseDocInput,
            sup: MfgSupplierRow | None) -> None:
    if inp.external_ref is not None:
        ensure_unique(s, MfgPurchaseDocRow, WHAT[doc_type], {"doc_type": doc_type, "external_ref": inp.external_ref},
                      exclude_id=doc.id)
    doc.supplier_id = sup.id if sup else None
    doc.currency = inp.currency if inp.currency is not None else (sup.currency if sup else "")
    doc.order_date, doc.note, doc.external_ref = inp.order_date, inp.note, inp.external_ref


def create_doc(ctx: AppContext, doc_type: str, inp: PurchaseDocInput, *, source: str = "manual") -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        its = _item_rows(s, inp)
        sup = _supplier(s, doc_type, inp)
        if inp.number is not None:
            ensure_unique(s, MfgPurchaseDocRow, WHAT[doc_type], {"doc_type": doc_type, "number": inp.number})
            number = inp.number
        else:
            number = repo_m2.next_number(s, KIND[doc_type], repo_m2.number_taken(s, MfgPurchaseDocRow,
                                                                                  doc_type=doc_type))
        now = utcnow()
        doc = MfgPurchaseDocRow(id=new_id("pdc_"), doc_type=doc_type, number=number, status="draft", source=source,
                                source_run_no=None, submitted_at=None, submitted_by=None, approved_at=None,
                                approved_by=None, rejected_reason="", idempotency_key=None, row_version=1,
                                created_at=now, updated_at=now, supplier_id=None, currency="", order_date=None,
                                note="", external_ref=None)
        _header(s, doc_type, doc, inp, sup)
        s.add(doc)
        s.flush()
        _write_lines(s, doc, inp, its, True)
        audit(s, "purchase_doc", doc.id, "create", {"doc_type": doc_type, "number": number,
                                                     "lines": len(inp.lines)})
        return doc_record(s, doc)

    return run_tx(ctx, fn)


def update_doc(ctx: AppContext, doc_type: str, doc_id: str, inp: PurchaseDocInput, if_match: str | None
               ) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        doc = _get(s, doc_type, doc_id, lock=True)
        check_version(doc, if_match)
        try:
            PUR.check_editable(doc_type, doc.status)
        except RuleError as e:
            raise rule_error(e) from None
        its = _item_rows(s, inp)
        sup = _supplier(s, doc_type, inp)
        if inp.number is not None and inp.number != doc.number:
            ensure_unique(s, MfgPurchaseDocRow, WHAT[doc_type], {"doc_type": doc_type, "number": inp.number},
                          exclude_id=doc.id)
            doc.number = inp.number
        _header(s, doc_type, doc, inp, sup)
        _write_lines(s, doc, inp, its, False)
        _derive(s, doc)
        touch(doc)
        s.flush()
        audit(s, "purchase_doc", doc.id, "update", {"number": doc.number, "version": doc.row_version})
        return doc_record(s, doc)

    return run_tx(ctx, fn)


def delete_doc(ctx: AppContext, doc_type: str, doc_id: str, if_match: str | None) -> None:
    def fn(s: Session) -> None:
        doc = _get(s, doc_type, doc_id, lock=True)
        check_version(doc, if_match)
        sids = [r[0] for r in s.execute(select(MfgPurchaseScheduleRow.id).join(
            MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id).where(
            MfgPurchaseLineRow.doc_id == doc.id)).all()]
        try:
            PUR.check_deletable(doc_type, doc.status, doc.source, bool(_received(s, sids)))
        except RuleError as e:
            raise rule_error(e) from None
        if _received(s, sids):
            raise ApiError(409, "MFG_IN_USE", "This document has stock transactions.", {"references":
                                                                                         {"transactions": 1}})
        audit(s, "purchase_doc", doc.id, "delete", {"number": doc.number, "doc_type": doc_type})
        s.delete(doc)
        s.flush()

    run_tx(ctx, fn)


def action(ctx: AppContext, doc_type: str, doc_id: str, act: str, if_match: str | None,
           reason: str | None = None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        doc = _get(s, doc_type, doc_id, lock=True)
        check_version(doc, if_match)
        now = datetime.now(UTC)
        actor = actor_id()
        try:
            target = PUR.check_action(doc_type, doc.status, act)
            if act == "approve":
                PUR.check_self_approval(doc.submitted_by, actor, is_workspace_owner())
            if doc_type == "po" and act == "cancel":
                sids = [r[0] for r in s.execute(select(MfgPurchaseScheduleRow.id).join(
                    MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id).where(
                    MfgPurchaseLineRow.doc_id == doc.id)).all()]
                PUR.check_po_cancel(doc.status, bool(_received(s, sids)))
        except RuleError as e:
            raise rule_error(e) from None
        lines = list(s.execute(select(MfgPurchaseLineRow).where(MfgPurchaseLineRow.doc_id == doc.id)
                               .with_for_update()).scalars())
        if act == "submit":
            doc.submitted_at, doc.submitted_by, doc.rejected_reason = now, actor, ""
        elif act == "approve":
            doc.approved_at, doc.approved_by = now, actor
        elif act == "reject":
            doc.rejected_reason = reason or ""
        elif act == "revise":
            doc.submitted_at = doc.submitted_by = doc.approved_at = doc.approved_by = None
        elif act == "cancel":
            for ln in lines:
                if ln.status == "open":
                    ln.status = "cancelled"
                    touch(ln, now)
        elif act == "close":
            scs = repo_m2.lock_children_of(s, MfgPurchaseScheduleRow, "line_id", [ln.id for ln in lines])
            for sc in scs:
                if not sc.closed and sc.qty - sc.received_qty > EPS:
                    sc.closed = True
                    touch(sc, now)
            for ln in lines:
                if ln.status == "open":
                    ln.status = "closed"
                    touch(ln, now)
        doc.status = target or doc.status
        touch(doc, now)
        s.flush()
        audit(s, "purchase_doc", doc.id, act, {"number": doc.number, "status": doc.status,
                                               **({"reason": reason} if reason else {})})
        return doc_record(s, doc)

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- PR -> PO (5.4)


def _convert_replay(s: Session, key: str, h: str) -> dict[str, Any] | None:
    from ...db.models import AuditEventRow

    po = s.execute(select(MfgPurchaseDocRow).where(MfgPurchaseDocRow.idempotency_key == key,
                                                   MfgPurchaseDocRow.doc_type == "po",
                                                   MfgPurchaseDocRow.created_at > utcnow() - timedelta(hours=24))
                   ).scalars().first()
    if po is None:
        return None
    ev = s.execute(select(AuditEventRow.details).where(AuditEventRow.entity_type == "mfg_purchase_doc",
                                                       AuditEventRow.action == "convert",
                                                       AuditEventRow.entity_id == po.id)).scalars().first()
    if ev is None or ev.get("request_hash") != h:
        raise ApiError(409, "INV_IDEMPOTENCY_CONFLICT", "This Idempotency-Key was already used for another "
                       "request.", {"po_id": po.id})
    pr = s.execute(select(MfgPurchaseDocRow).where(MfgPurchaseDocRow.id == ev.get("pr_id"))).scalars().first()
    return {"pr": doc_record(s, pr) if pr else None, "po": doc_record(s, po)}


def convert_pr(ctx: AppContext, pr_id: str, body: Any, if_match: str | None, idem: str | None
               ) -> tuple[dict[str, Any], bool]:
    h = request_hash({"pr": pr_id, **body.model_dump(mode="json")})
    if idem:
        with read_tx(ctx) as s:
            out = _convert_replay(s, idem, h)
            if out is not None:
                return out, True

    def fn(s: Session) -> tuple[dict[str, Any], bool]:
        pr = _get(s, "pr", pr_id, lock=True)
        check_version(pr, if_match)
        if idem:
            out = _convert_replay(s, idem, h)
            if out is not None:
                return out, True
        try:
            PUR.check_action("pr", pr.status, "convert")
        except RuleError as e:
            raise rule_error(e) from None
        lines = list(s.execute(select(MfgPurchaseLineRow).where(MfgPurchaseLineRow.doc_id == pr.id)
                               .order_by(MfgPurchaseLineRow.line_no).with_for_update()).scalars())
        if body.line_ids is None:
            sel = [ln for ln in lines if ln.status == "open"]
        else:
            by_id = {ln.id: ln for ln in lines}
            sel = []
            for i, lid in enumerate(body.line_ids):
                ln = by_id.get(lid)
                if ln is None:
                    raise unknown_ref(["body", "line_ids", i], lid, "Line")
                if ln.status != "open":
                    raise ApiError(422, "PUR_LINE_CONVERTED", f"Line {ln.line_no} is {ln.status} already.",
                                   {"loc": ["body", "line_ids", i]})
                sel.append(ln)
        if not sel:
            raise ApiError(422, "PUR_LINE_CONVERTED", "There is no open line to convert.", {})
        sup_id = body.supplier_id or pr.supplier_id
        if sup_id is None:
            prefs = {r.item_id: r.supplier_id for r in s.execute(select(MfgItemSupplierRow).where(
                MfgItemSupplierRow.item_id.in_([ln.item_id for ln in sel]), MfgItemSupplierRow.preferred.is_(True),
                MfgItemSupplierRow.active.is_(True))).scalars()}
            ids = {prefs.get(ln.item_id) for ln in sel}
            sup_id = ids.pop() if len(ids) == 1 else None
        if sup_id is None:
            raise ApiError(422, "PUR_SUPPLIER_REQUIRED", "Choose the supplier for the purchase order.",
                           {"loc": ["body", "supplier_id"]})
        sup = s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id == sup_id)).scalars().first()
        if sup is None:
            raise unknown_ref(["body", "supplier_id"], sup_id, "Supplier")
        if body.number is not None:
            ensure_unique(s, MfgPurchaseDocRow, WHAT["po"], {"doc_type": "po", "number": body.number})
        scheds = repo_m2.lock_children_of(s, MfgPurchaseScheduleRow, "line_id", [ln.id for ln in sel])
        number = body.number or repo_m2.next_number(s, "PO", repo_m2.number_taken(s, MfgPurchaseDocRow,
                                                                                    doc_type="po"))
        now = utcnow()
        po = MfgPurchaseDocRow(id=new_id("pdc_"), doc_type="po", number=number, status="open" if body.issue else
                               "draft", supplier_id=sup.id, currency=sup.currency or pr.currency, order_date=today(s),
                               note=f"From {pr.number}", source="manual", source_run_no=pr.source_run_no,
                               submitted_at=None, submitted_by=None, approved_at=None, approved_by=None,
                               rejected_reason="", external_ref=None, idempotency_key=idem, row_version=1,
                               created_at=now, updated_at=now)
        s.add(po)
        s.flush()
        prices = _prices(s, [ln.item_id for ln in sel], sup.id)
        new_lines = []
        new_scheds = []
        for k, ln in enumerate(sel):
            pl = MfgPurchaseLineRow(id=new_id("pln_"), doc_id=po.id, line_no=10 * (k + 1), item_id=ln.item_id,
                                    unit_price=prices.get(ln.item_id) if prices.get(ln.item_id) is not None
                                    else ln.unit_price, status="open", source_pr_line_id=ln.id, note=ln.note,
                                    row_version=1, created_at=now, updated_at=now)
            new_lines.append(pl)
            for sc in sorted((x for x in scheds if x.line_id == ln.id), key=lambda x: x.seq):
                new_scheds.append(MfgPurchaseScheduleRow(
                    id=new_id("psc_"), line_id=pl.id, seq=sc.seq, requested_date=sc.requested_date,
                    confirmed_date=sc.confirmed_date, qty=sc.qty, received_qty=0.0, closed=False, row_version=1,
                    created_at=now, updated_at=now))
            ln.status = "converted"
            touch(ln, now)
        s.add_all(new_lines)
        s.flush()
        s.add_all(new_scheds)
        pr.status = PUR.derive_pr_status(pr.status, [ln.status for ln in lines])
        touch(pr, now)
        s.flush()
        audit(s, "purchase_doc", po.id, "convert", {"pr_id": pr.id, "pr_number": pr.number, "po_number": number,
                                                    "lines": len(sel), "idempotency_key": idem,
                                                    "request_hash": h})
        return {"pr": doc_record(s, pr), "po": doc_record(s, po)}, False

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- delivery board (#125)


def schedule_board(ctx: AppContext, *, d0: date | None, d1: date | None, supplier_id: str | None,
                   item_id: str | None, doc_type: str | None, overdue_only: bool, limit: int, offset: int
                   ) -> dict[str, Any]:
    S, Ln, D = MfgPurchaseScheduleRow, MfgPurchaseLineRow, MfgPurchaseDocRow
    dock = func.coalesce(S.confirmed_date, S.requested_date)
    conds: list[Any] = [S.closed.is_(False), S.qty - S.received_qty > EPS, Ln.status == "open",
                        or_((D.doc_type == "po") & D.status.in_(PUR.PO_SUPPLY_STATUSES),
                            (D.doc_type == "pr") & D.status.in_(PUR.PR_SUPPLY_STATUSES))]
    if d0:
        conds.append(dock >= d0)
    if d1:
        conds.append(dock <= d1)
    if supplier_id:
        conds.append(D.supplier_id == supplier_id)
    if item_id:
        conds.append(Ln.item_id == item_id)
    if doc_type:
        conds.append(D.doc_type == doc_type)
    with read_tx(ctx) as s:
        d = today(s)
        if overdue_only:
            conds.append(dock < d)
        base = select(S, Ln, D).join(Ln, Ln.id == S.line_id).join(D, D.id == Ln.doc_id).where(*conds)
        rows = s.execute(base.order_by(dock, D.number, Ln.line_no, S.seq).limit(limit).offset(offset)).all()
        total = int(s.execute(select(func.count()).select_from(S).join(Ln, Ln.id == S.line_id)
                              .join(D, D.id == Ln.doc_id).where(*conds)).scalar() or 0)
        return page(schedule_rows(s, rows, d), total, limit, offset)


def schedule_rows(s: Session, rows: list[Any], d: date) -> list[dict[str, Any]]:
    its = items(s, [r[1].item_id for r in rows])
    sids = sorted({r[2].supplier_id for r in rows if r[2].supplier_id})
    sups = {x.id: x for x in s.execute(select(MfgSupplierRow).where(MfgSupplierRow.id.in_(sids))).scalars()} \
        if sids else {}
    out = []
    for sc, ln, doc in rows:
        it = its.get(ln.item_id)
        v = PUR.schedule_view(sc.qty, sc.received_qty, sc.closed, sc.requested_date, sc.confirmed_date,
                              it.receiving_days if it else 0, d)
        out.append({"schedule_id": sc.id, "seq": sc.seq,
                    "doc": {"id": doc.id, "doc_type": doc.doc_type, "number": doc.number, "status": doc.status},
                    "line_no": ln.line_no, "item": iref(it, ln.item_id),
                    "supplier": ref(sups[doc.supplier_id]) if doc.supplier_id in sups else None,
                    "requested_date": sc.requested_date, "confirmed_date": sc.confirmed_date, "qty": r6(sc.qty),
                    "received_qty": r6(sc.received_qty), **v,
                    "link": f"/mfg/purchasing/{PATH[doc.doc_type]}/{doc.id}?schedule={sc.id}"})
    return out

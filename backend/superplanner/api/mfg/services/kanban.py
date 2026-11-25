"""Kanban service (M8-DESIGN 6.2, 11 K1-K6): loops and cards, scan signals, posting hooks.

- A loop owns `cards` card rows (`KB:<card id>` codes). Changing `cards` adds full cards / removes the highest
  numbered full cards (409 `KANBAN_CARDS_IN_USE` when not enough full cards can be removed).
- Scan (`trigger scan`) or consumption (`trigger consumption`: every `container_qty` issued from the loop location
  empties a card) creates the signal: `buy` -> a submitted PR (preferred supplier, qty = container, requested =
  today + lead); `make` -> a planned WO `kind kanban` (qty = container, due = today + lead). The card keeps the
  document link.
- A receipt of the item at the loop location (PO / WO / misc receipt) refills the oldest empty card (one card per
  container received, at least one) - interpretation: receipts are matched to cards by item and location, not by
  document (a PR is converted into a PO and may be merged).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....mfg import kanban as K
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow, MfgLineRow
from ..db_models_m2 import MfgLocationRow, MfgPurchaseDocRow, MfgSupplierRow, MfgWorkOrderRow
from ..db_models_m8 import MfgKanbanCardRow, MfgKanbanLoopRow
from . import m8_examples
from .common import audit, check_version, read_tx, touch, unknown_ref, write_tx
from .m8common import iref, next_number, page, today

RECEIPTS = ("po_receipt", "wo_receipt", "receipt_misc", "transfer_receipt")
ISSUES = ("wo_issue", "issue_misc", "backflush")


def _card_record(c: MfgKanbanCardRow, numbers: dict[str, str] | None = None) -> dict[str, Any]:
    return {"id": c.id, "loop_id": c.loop_id, "card_no": c.card_no, "code": K.card_code(c.id), "state": c.state,
            "doc_type": c.doc_type, "doc_id": c.doc_id, "doc_number": (numbers or {}).get(c.doc_id or ""),
            "changed_at": c.changed_at}


def _daily_demand(s: Session, item_id: str) -> float:
    """Average daily requirement over the next 28 days from the latest live MRP run (0 without one)."""
    try:
        from ..db_models_m2 import MfgMrpItemResultRow
        from .mrp import latest_live

        run = latest_live(s)
        if run is None:
            return 0.0
        row = s.execute(select(MfgMrpItemResultRow).where(MfgMrpItemResultRow.run_id == run.id,
                                                          MfgMrpItemResultRow.item_id == item_id)).scalars().first()
        if row is None:
            return 0.0
        gross = getattr(row, "gross_qty", None)
        horizon = max(int(run.horizon_days or 28), 1)
        return float(gross or 0.0) / horizon
    except Exception:  # pragma: no cover - sizing is advisory
        return 0.0


def _loop_record(s: Session, lp: MfgKanbanLoopRow) -> dict[str, Any]:
    counts = {"full": 0, "empty": 0, "in_process": 0}
    for st, n in s.execute(select(MfgKanbanCardRow.state, func.count()).where(MfgKanbanCardRow.loop_id == lp.id)
                           .group_by(MfgKanbanCardRow.state)):
        counts[st] = int(n)
    it = s.get(MfgItemRow, lp.item_id)
    loc = s.get(MfgLocationRow, lp.location_id)
    d = _daily_demand(s, lp.item_id)
    return {"id": lp.id, "number": lp.number, "item_id": lp.item_id, "location_id": lp.location_id,
            "source": lp.source, "supplier_id": lp.supplier_id, "line_id": lp.line_id, "cards": lp.cards,
            "container_qty": lp.container_qty, "lead_time_days": lp.lead_time_days, "trigger": lp.trigger,
            "status": lp.status, "item": iref(it, lp.item_id), "location_code": loc.code if loc else None,
            "card_counts": counts, "consumed_since_signal": lp.consumed,
            "sizing": {"daily_demand": round(d, 6),
                       "suggested_cards": K.suggested_cards(d, lp.lead_time_days, lp.container_qty),
                       "undersized": K.undersized(d, lp.lead_time_days, lp.cards, lp.container_qty)},
            "row_version": lp.row_version, "created_at": lp.created_at, "updated_at": lp.updated_at}


def list_loops(ctx: AppContext, item_id: str | None, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        q = select(MfgKanbanLoopRow)
        if item_id:
            q = q.where(MfgKanbanLoopRow.item_id == item_id)
        n = int(s.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)
        rows = s.execute(q.order_by(MfgKanbanLoopRow.number).limit(limit).offset(offset)).scalars()
        return page([_loop_record(s, r) for r in rows], n, limit, offset)


def get_loop(ctx: AppContext, loop_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _loop_record(s, repo.get_row(s, MfgKanbanLoopRow, loop_id, what="Kanban loop"))


def _check_refs(s: Session, body: Any) -> None:
    it = s.get(MfgItemRow, body.item_id)
    if it is None:
        raise unknown_ref(["body", "item_id"], body.item_id, "Item")
    if s.get(MfgLocationRow, body.location_id) is None:
        raise unknown_ref(["body", "location_id"], body.location_id, "Location")
    if body.source == "buy":
        if it.make_buy != "buy":
            raise ApiError(422, "VALIDATION_ERROR", "A buy loop needs a bought item.",
                           {"errors": [{"loc": ["body", "source"], "msg": "make item", "type": "value_error"}]})
        if body.supplier_id is not None and s.get(MfgSupplierRow, body.supplier_id) is None:
            raise unknown_ref(["body", "supplier_id"], body.supplier_id, "Supplier")
    else:
        if it.make_buy != "make":
            raise ApiError(422, "VALIDATION_ERROR", "A make loop needs a made item.",
                           {"errors": [{"loc": ["body", "source"], "msg": "buy item", "type": "value_error"}]})
        if body.line_id is not None and s.get(MfgLineRow, body.line_id) is None:
            raise unknown_ref(["body", "line_id"], body.line_id, "Line")


def _sync_cards(s: Session, lp: MfgKanbanLoopRow, n: int) -> None:
    cards = list(s.execute(select(MfgKanbanCardRow).where(MfgKanbanCardRow.loop_id == lp.id)
                           .order_by(MfgKanbanCardRow.card_no)).scalars())
    now = utcnow()
    if n > len(cards):
        top = max((c.card_no for c in cards), default=0)
        for k in range(n - len(cards)):
            s.add(MfgKanbanCardRow(id=new_id("kbc_"), loop_id=lp.id, card_no=top + k + 1, state="full", doc_type=None,
                                   doc_id=None, changed_at=now))
    elif n < len(cards):
        drop = [c for c in reversed(cards) if c.state == "full"][:len(cards) - n]
        if len(drop) < len(cards) - n:
            raise ApiError(409, "KANBAN_CARDS_IN_USE", "Cards that are in replenishment cannot be removed; wait until "
                           "they are full.", {"full": sum(1 for c in cards if c.state == "full")})
        for c in drop:
            s.delete(c)
    s.flush()


def create_loop(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        _check_refs(s, body)
        dup = s.execute(select(MfgKanbanLoopRow.id).where(MfgKanbanLoopRow.item_id == body.item_id,
                                                          MfgKanbanLoopRow.location_id == body.location_id)).scalar()
        if dup:
            raise ApiError(409, "MFG_DUPLICATE_KEY", "A kanban loop for this item and location already exists.",
                           {"existing_id": dup})
        now = utcnow()
        lp = MfgKanbanLoopRow(id=new_id("kbl_"), number=next_number(s, "KB", MfgKanbanLoopRow), consumed=0.0,
                              row_version=1, created_at=now, updated_at=now, **body.model_dump())
        s.add(lp)
        s.flush()
        _sync_cards(s, lp, body.cards)
        audit(s, "kanban_loop", lp.id, "create", {"number": lp.number, **body.model_dump(mode="json")})
        return _loop_record(s, lp)


def update_loop(ctx: AppContext, a: Any, loop_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        lp = repo.get_row(s, MfgKanbanLoopRow, loop_id, what="Kanban loop", lock=True)
        check_version(lp, if_match)
        if (body.item_id, body.location_id) != (lp.item_id, lp.location_id):
            raise ApiError(422, "VALIDATION_ERROR", "Item and location of a loop cannot change; create a new loop.",
                           {"errors": [{"loc": ["body", "item_id"], "msg": "fixed", "type": "value_error"}]})
        _check_refs(s, body)
        before = {k: getattr(lp, k) for k in body.model_dump()}
        for k, v in body.model_dump().items():
            setattr(lp, k, v)
        _sync_cards(s, lp, body.cards)
        touch(lp)
        s.flush()
        audit(s, "kanban_loop", lp.id, "update", {"version": lp.row_version}, before=before, after=body.model_dump())
        return _loop_record(s, lp)


def _numbers(s: Session, cards: list[MfgKanbanCardRow]) -> dict[str, str]:
    pr = [c.doc_id for c in cards if c.doc_type == "pr" and c.doc_id]
    wo = [c.doc_id for c in cards if c.doc_type == "wo" and c.doc_id]
    out: dict[str, str] = {}
    if pr:
        out.update(dict(s.execute(select(MfgPurchaseDocRow.id, MfgPurchaseDocRow.number)
                                  .where(MfgPurchaseDocRow.id.in_(pr))).all()))
    if wo:
        out.update(dict(s.execute(select(MfgWorkOrderRow.id, MfgWorkOrderRow.number)
                                  .where(MfgWorkOrderRow.id.in_(wo))).all()))
    return out


def list_cards(ctx: AppContext, loop_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        lp = repo.get_row(s, MfgKanbanLoopRow, loop_id, what="Kanban loop")
        cards = list(s.execute(select(MfgKanbanCardRow).where(MfgKanbanCardRow.loop_id == lp.id)
                               .order_by(MfgKanbanCardRow.card_no)).scalars())
        nums = _numbers(s, cards)
        return {"items": [_card_record(c, nums) for c in cards]}


# ---------------------------------------------------------------- signals

def _signal(s: Session, lp: MfgKanbanLoopRow, card: MfgKanbanCardRow, actor: str) -> dict[str, Any]:
    d = today(s)
    due = d + timedelta(days=lp.lead_time_days)
    if lp.source == "buy":
        from ....mfg.model_m2 import PurchaseDocInput
        from . import purchasing as PUR

        sup_id = lp.supplier_id
        if sup_id is None:
            from ..db_models_m2 import MfgItemSupplierRow

            sup_id = s.execute(select(MfgItemSupplierRow.supplier_id).where(
                MfgItemSupplierRow.item_id == lp.item_id, MfgItemSupplierRow.active.is_(True))
                .order_by(MfgItemSupplierRow.preferred.desc(), MfgItemSupplierRow.id)).scalars().first()
        inp = PurchaseDocInput.model_validate({
            "supplier_id": sup_id, "note": f"Kanban {lp.number} card {card.card_no}",
            "lines": [{"item_id": lp.item_id, "schedules": [{"requested_date": due.isoformat(),
                                                             "qty": lp.container_qty}]}]})
        its = PUR._item_rows(s, inp)
        sup = PUR._supplier(s, "pr", inp)
        from .. import repo_m2

        now = utcnow()
        doc = MfgPurchaseDocRow(id=new_id("pdc_"), doc_type="pr", number=repo_m2.next_number(
            s, "PR", repo_m2.number_taken(s, MfgPurchaseDocRow, doc_type="pr")), status="submitted",
            source="kanban", source_run_no=None, submitted_at=now, submitted_by=actor, approved_at=None,
            approved_by=None, rejected_reason="", idempotency_key=None, row_version=1, created_at=now, updated_at=now,
            supplier_id=None, currency="", order_date=None, note="", external_ref=None)
        PUR._header(s, "pr", doc, inp, sup)
        s.add(doc)
        s.flush()
        PUR._write_lines(s, doc, inp, its, True)
        audit(s, "purchase_doc", doc.id, "create", {"doc_type": "pr", "number": doc.number, "kanban": lp.number})
        card.doc_type, card.doc_id = "pr", doc.id
        return {"doc_type": "pr", "doc_id": doc.id, "number": doc.number, "qty": lp.container_qty}
    from ....mfg.model_m2 import WorkOrderInput
    from .. import repo as R
    from . import workorders as WO

    ds = R.load_dataset(s)
    w, _warn = WO.new_wo(s, ds, WorkOrderInput(item_id=lp.item_id, qty=lp.container_qty, due_date=due,
                                               note=f"Kanban {lp.number} card {card.card_no}",
                                               receipt_location_id=lp.location_id), source="kanban")
    w.kind = "kanban"
    audit(s, "work_order", w.id, "create", {"number": w.number, "kanban": lp.number})
    card.doc_type, card.doc_id = "wo", w.id
    return {"doc_type": "wo", "doc_id": w.id, "number": w.number, "qty": lp.container_qty}


def _empty(s: Session, lp: MfgKanbanLoopRow, card: MfgKanbanCardRow, actor: str) -> dict[str, Any]:
    card.state = K.transition(card.state, "empty")
    card.changed_at = utcnow()
    sig = _signal(s, lp, card, actor)
    audit(s, "kanban_card", card.id, "empty", {"loop": lp.number, "card_no": card.card_no, **sig})
    return sig


def scan(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    card_id = K.parse_code(body.code)
    if card_id is None:
        raise ApiError(422, "KANBAN_CODE_INVALID", "This is not a kanban card code (KB:...).", {"code": body.code[:80]})
    with write_tx(ctx) as (s, _):
        card = repo.get_row(s, MfgKanbanCardRow, card_id, what="Kanban card", lock=True)
        lp = repo.get_row(s, MfgKanbanLoopRow, card.loop_id, what="Kanban loop", lock=True)
        if lp.status != "active":
            raise ApiError(409, "KANBAN_LOOP_INACTIVE", "This kanban loop is inactive.", {"loop_id": lp.id})
        if card.state != "full":
            raise ApiError(409, "KANBAN_CARD_STATE", f"Card {card.card_no} of {lp.number} is already {card.state}.",
                           {"state": card.state})
        sig = _empty(s, lp, card, a.user_id)
        s.flush()
        return {"card": _card_record(card, {sig["doc_id"]: sig["number"]}), "loop_id": lp.id, "signal": sig}


def on_posting(s: Session, posting: Any) -> None:
    """Posting hook (same transaction): receipts refill empty cards; issues count consumption."""
    from ..db_models_m2 import MfgInvTransactionRow

    if s.execute(select(MfgKanbanLoopRow.id).where(MfgKanbanLoopRow.status == "active").limit(1)).first() is None:
        return
    txns = list(s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id == posting.id))
                .scalars())
    for t in txns:
        lp = s.execute(select(MfgKanbanLoopRow).where(MfgKanbanLoopRow.item_id == t.item_id,
                                                      MfgKanbanLoopRow.location_id == t.location_id,
                                                      MfgKanbanLoopRow.status == "active")
                       .with_for_update()).scalars().first()
        if lp is None:
            continue
        if t.txn_type in RECEIPTS and t.qty > 0:
            n = max(1, int(t.qty // lp.container_qty + 1e-9))
            for c in s.execute(select(MfgKanbanCardRow).where(MfgKanbanCardRow.loop_id == lp.id,
                                                              MfgKanbanCardRow.state != "full")
                               .order_by(MfgKanbanCardRow.changed_at, MfgKanbanCardRow.card_no)
                               .limit(n).with_for_update()).scalars():
                c.state, c.changed_at, c.doc_type, c.doc_id = "full", utcnow(), None, None
                audit(s, "kanban_card", c.id, "full", {"loop": lp.number, "posting": posting.number})
        elif lp.trigger == "consumption" and t.qty < 0 and t.txn_type not in RECEIPTS:
            res = K.consume(lp.consumed, -t.qty, lp.container_qty)
            lp.consumed = res.counter
            if res.cards_to_empty:
                for c in s.execute(select(MfgKanbanCardRow).where(MfgKanbanCardRow.loop_id == lp.id,
                                                                  MfgKanbanCardRow.state == "full")
                                   .order_by(MfgKanbanCardRow.card_no).limit(res.cards_to_empty)
                                   .with_for_update()).scalars():
                    _empty(s, lp, c, posting.actor_id)
    s.flush()


__getattr__ = m8_examples.module_getattr(__name__)

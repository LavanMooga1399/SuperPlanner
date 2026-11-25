"""Floor action "issue component lot" (demo finding): scan a lot at an operation -> choose the operation's
component of that item -> quantity (default: the component's remaining requirement, capped by the lot's usable
stock) -> one `wo_issue` posting through the M2 ledger. The ledger enforces expiry and holds (incl. M7 inspection,
NCR, recall and field action holds: 422 `INV_LOT_ON_HOLD`); quarantine locations are never picked (409
`FLR_LOT_QUARANTINED` when the lot's only stock is there)."""

from __future__ import annotations

from typing import Any

from pydantic import Field, StringConstraints, model_validator
from sqlalchemy import func, select
from typing_extensions import Annotated

from ....mfg.model import EntityId, MfgModel
from ...context import AppContext
from ...errors import ApiError
from .. import repo
from ..db_models_m2 import MfgInvBalanceRow, MfgLocationRow, MfgLotRow, MfgWoComponentRow, MfgWorkOrderRow
from ..db_models_m4 import MfgWoOperationRow
from .common import write_tx

EPS = 1e-6


class IssueLotInput(MfgModel):
    wo_operation_id: EntityId
    lot_id: EntityId | None = None
    scan: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    wo_component_id: EntityId | None = None
    qty: Annotated[float, Field(gt=0, le=1_000_000)] | None = None
    location_id: EntityId | None = None
    client_event_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:\-]{1,64}$")] | None = None

    @model_validator(mode="after")
    def _one(self) -> "IssueLotInput":
        if (self.lot_id is None) == (self.scan is None):
            raise ValueError("give lot_id or scan")
        return self


def _lot_from_scan(s: Any, code: str, item_ids: set[str]) -> MfgLotRow | None:
    from ....mfg import scan as SCAN

    for lk in SCAN.parse(code):
        if lk.type == "lot":                               # L:<part>:<lot>
            pn, lc = lk.key
            from ..db_models import MfgItemRow

            r = s.execute(select(MfgLotRow).join(MfgItemRow, MfgItemRow.id == MfgLotRow.item_id).where(
                func.upper(MfgItemRow.part_number) == pn.upper(), MfgLotRow.lot_code == lc)).scalars().first()
            if r is not None:
                return r
        if lk.type == "lot_code":
            hits = list(s.execute(select(MfgLotRow).where(MfgLotRow.lot_code == lk.key[0],
                                                          MfgLotRow.item_id.in_(sorted(item_ids)))).scalars())
            if len(hits) == 1:
                return hits[0]
    return None


def issue_lot(ctx: AppContext, p: Any, inp: IssueLotInput) -> dict[str, Any]:
    from ....mfg.model_m2 import WoIssueLine, WoIssuePosting
    from .floor import _op_components, lock_wo, wo_rows
    from .inventory import post_in_session, posting_record

    with write_tx(ctx, lock=False) as (s, _):
        op = repo.get_row(s, MfgWoOperationRow, inp.wo_operation_id, what="Operation")
        wo = lock_wo(s, op.wo_id)
        if wo.status not in ("released", "in_progress"):
            raise ApiError(409, "MFG_INVALID_STATE", f"{wo.number} is {wo.status}.", {"status": wo.status})
        rows = wo_rows(s, wo.id)
        comps = _op_components(s, wo, rows, op)
        lot = s.get(MfgLotRow, inp.lot_id) if inp.lot_id else _lot_from_scan(s, inp.scan or "",
                                                                             {c.item_id for c in comps})
        if lot is None:
            raise ApiError(404, "FLR_SCAN_UNKNOWN", "That lot was not found.", {"scan": inp.scan})
        cands = [c for c in comps if c.item_id == lot.item_id]
        if inp.wo_component_id:
            cands = [c for c in cands if c.id == inp.wo_component_id]
        if not cands:
            raise ApiError(422, "FLR_LOT_NOT_A_COMPONENT", f"Lot {lot.lot_code} is not a component of operation "
                           f"{op.seq} of {wo.number}.", {"lot_id": lot.id, "components": [
                               {"id": c.id, "item_id": c.item_id} for c in comps]})
        if len(cands) > 1:
            raise ApiError(422, "FLR_CHOOSE_COMPONENT", "Choose the component (several lines use this item).",
                           {"components": [{"id": c.id, "find_number": c.find_number,
                                            "remaining": round(max(0.0, c.required_qty - c.issued_qty), 6)}
                                           for c in cands]})
        cpt = cands[0]
        locs = {x.id: x for x in s.execute(select(MfgLocationRow)).scalars()}
        bals = [b for b in s.execute(select(MfgInvBalanceRow).where(MfgInvBalanceRow.lot_id == lot.id,
                                                                    MfgInvBalanceRow.qty_on_hand > EPS)
                                     .order_by(MfgInvBalanceRow.qty_on_hand.desc())).scalars()]
        if inp.location_id:
            bals = [b for b in bals if b.location_id == inp.location_id]
        usable = [b for b in bals if locs[b.location_id].kind != "quarantine" and locs[b.location_id].active]
        if not usable:
            if bals:
                raise ApiError(409, "FLR_LOT_QUARANTINED", f"Lot {lot.lot_code} is only in quarantine.",
                               {"lot_id": lot.id})
            raise ApiError(422, "INV_INSUFFICIENT_STOCK", f"Lot {lot.lot_code} has no stock here.",
                           {"lot_id": lot.id})
        b = usable[0]
        remaining = max(0.0, cpt.required_qty - cpt.issued_qty)
        qty = inp.qty if inp.qty is not None else min(remaining or b.qty_on_hand, b.qty_on_hand - b.qty_reserved
                                                       if b.qty_on_hand - b.qty_reserved > EPS else b.qty_on_hand)
        qty = round(qty, 6)
        if qty <= EPS:
            raise ApiError(422, "VALIDATION_ERROR", "Nothing to issue.", {"errors": [
                {"loc": ["body", "qty"], "msg": "zero", "type": "value_error"}]})
        posting = WoIssuePosting.model_construct(
            type="wo_issue", txn_date=None, note=f"Floor issue {wo.number}/{op.seq}", reason_code=None,
            lines=[WoIssueLine.model_construct(wo_component_id=cpt.id, location_id=b.location_id,
                                               lot_code=lot.lot_code, qty=qty, over_issue=qty > remaining + EPS)])
        row, warnings = post_in_session(s, posting)
        s.refresh(cpt)
        return {"posting": posting_record(s, row, warnings), "component": {
            "id": cpt.id, "item_id": cpt.item_id, "required_qty": cpt.required_qty, "issued_qty": cpt.issued_qty,
            "remaining": round(max(0.0, cpt.required_qty - cpt.issued_qty), 6)},
            "lot": {"id": lot.id, "lot_code": lot.lot_code, "expires_on": lot.expires_on},
            "location_id": b.location_id, "qty": qty}


__all__ = ["IssueLotInput", "issue_lot"]
del MfgWorkOrderRow, MfgWoComponentRow

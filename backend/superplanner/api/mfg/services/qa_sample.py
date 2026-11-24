"""Applies `mfg.samples.meddev_m7` (M7-DESIGN 12) in the sample load transaction, after the meddev history: schemes
and plans (approved), 12 equipment items, 20 inspection lots (17 decided, 3 open with one overdue), 3 NCRs (scrap
approved, rework proposed, use-as-is closed), a CAPA in implementation, 2 complaints, a field action (draft) from a
recall of a resin supplier lot, and the sample's QC release holds as hold rows (final inspection lots for items
with a final plan). No ledger postings; Part 11 mode stays off (the sample is unsigned data)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....mfg.samples import meddev_m7 as D
from ...db.models import new_id, utcnow
from ..db_models import MfgItemRow, MfgLineRow
from ..db_models_m2 import MfgLotRow, MfgSupplierRow
from ..db_models_m7 import (MfgLotHoldRow, QaCapaActionRow, QaCapaRow, QaCharacteristicRow, QaComplaintRow,
                            QaEquipmentRow, QaInspectionPlanRow, QaNcrDispositionRow, QaResultRow,
                            QaSamplingSchemeRow)

MARKER = "EXAMPLE-TABLE"


def _item(s: Session, pn: str) -> MfgItemRow:
    return s.execute(select(MfgItemRow).where(MfgItemRow.part_number == pn)).scalars().one()


def apply(s: Session, anchor: date, actor: str) -> dict[str, Any]:
    if s.execute(select(QaSamplingSchemeRow.id).where(QaSamplingSchemeRow.code == MARKER)).first() is not None:
        return {"skipped": True}
    from .qa_inspection import create_lot_in, lot_content

    now = utcnow()
    d0 = min(anchor, date.today())
    schemes = {}
    for x in D.SCHEMES:
        r = QaSamplingSchemeRow(id=new_id("ssc_"), code=x["code"], name=x["name"], kind=x["kind"],
                                fixed_n=x.get("fixed_n"), percent=None, table=x.get("table"),
                                switching=x["switching"], status="approved", approved_at=now, author_id=actor,
                                note=x["note"], row_version=1, created_at=now, updated_at=now)
        s.add(r)
        schemes[x["code"]] = r
    s.flush()
    from .qa_common import next_number

    plans = {}
    for key, name, pn, scope, sch, seq, sup, cust, chars in D.PLANS:
        it = _item(s, pn)
        sup_id = s.execute(select(MfgSupplierRow.id).where(MfgSupplierRow.code == sup)).scalar() if sup else None
        p = QaInspectionPlanRow(id=new_id("ipl_"), number=next_number(s, "IP", QaInspectionPlanRow), version=1,
                                name=name, item_id=it.id, scope=scope, operation_seq=seq, supplier_id=sup_id,
                                customer=cust, scheme_id=schemes[sch].id, inspection_level="II", aql=dict(D.AQL),
                                status="approved", effective_from=d0 - timedelta(days=120), supersedes_id=None,
                                approved_at=now, author_id=actor, note="", row_version=1, created_at=now,
                                updated_at=now)
        s.add(p)
        s.flush()
        for c in chars:
            s.add(QaCharacteristicRow(id=new_id("ich_"), plan_id=p.id, owner_id=p.owner_id, method="",
                                      sample_override=None, **{"unit": None, "nominal": None, "lsl": None, "usl": None,
                                                               "equipment_class": None, "destructive": False, **c}))
        plans[key] = p
    s.flush()
    lines = {ln.code: ln.id for ln in s.execute(select(MfgLineRow)).scalars()}
    eqs = {}
    td = date.today()                                  # due states are relative to the real day (UI)
    for code, name, kind, cls, line, due, interval in D.EQUIPMENT:
        e = QaEquipmentRow(id=new_id("eqp_"), code=code, name=name, kind=kind, equipment_class=cls,
                           line_id=lines.get(line) if line else None, tool_pool_id=None, serial_no=f"SN-{code}",
                           manufacturer="Fictional Instruments", location="QC lab" if not line else line,
                           status="active", calibration_required=True, interval_days=interval, grace_days=0,
                           last_calibrated_on=td + timedelta(days=due - interval), due_on=td + timedelta(days=due),
                           failed_on=None, procedure_ref="CAL-SOP-007", provider="external", note="", row_version=1,
                           created_at=now, updated_at=now)
        s.add(e)
        eqs[code] = e
    s.flush()

    # ---- inspection history: 20 lots on the incoming / final plans (manual history, no stock moved)
    seq_plans = [plans["INC-STP"], plans["INC-GLS"], plans["FIN-SYR"], plans["FIN-PFS"]]
    gauge = {"CALIPER": eqs["CAL-0001"].id, "FORCE": eqs["FG-0001"].id}
    lots = []
    for k in range(20):
        p = seq_plans[k % 4]
        lot = create_lot_in(s, p, lot_size=[3200, 400, 60000, 5000][k % 4], source="manual", actor=actor,
                            supplier_id=p.supplier_id, customer=p.customer, note=f"History {k + 1}")
        lots.append(lot)
        if k >= 17:                                   # 3 open lots (one overdue)
            if k == 19:
                lot.due_at = now - timedelta(hours=6)
            continue
        reject = k in (5, 9, 13)
        chars = list(s.execute(select(QaCharacteristicRow).where(QaCharacteristicRow.plan_id == p.id)
                               .order_by(QaCharacteristicRow.seq)).scalars())
        for c in chars:
            sp = lot.sampling[c.id]
            n = min(int(sp["n"]), 50) if not reject else int(sp["re"])
            for i in range(1, n + 1):
                bad = reject and c is chars[0]
                val = None
                if c.kind == "variable":
                    val = (c.lsl - 0.5 if c.lsl is not None else 0.0) if bad else (
                        c.nominal if c.nominal is not None else (c.lsl or 0) + 1)
                s.add(QaResultRow(id=new_id("irs_"), inspection_lot_id=lot.id, characteristic_id=c.id,
                                  sample_no=i, value=val, passed=not bad, defects=1 if bad else 0,
                                  equipment_id=gauge.get(c.equipment_class or ""), note="", reason=None,
                                  entered_by=actor, entered_at=now, corrects_result_id=None, superseded=False,
                                  client_batch_id=f"sample-{k}", owner_id=lot.owner_id))
            if not reject and int(sp["n"]) > 50:         # sampled history: record the entered sample as complete
                lot.sampling = {**lot.sampling, c.id: {**sp, "n": 50}}
        s.flush()
        from .qa_inspection import _verdict

        lot.verdict = _verdict(s, lot)
        lot.status = "rejected" if reject else "accepted"
        lot.decision = "reject" if reject else "accept"
        lot.decided_by, lot.decided_at = actor, now
    s.flush()

    # ---- NCRs from the three rejected lots: scrap (approved), rework (proposed), use as is (closed)
    from .qa_ncr import create_from_inspection

    ncrs = []
    for k, kind, status in ((5, "scrap", "approved"), (9, "rework", "proposed"), (13, "use_as_is", "closed")):
        lot = lots[k]
        n = create_from_inspection(s, lot, s.get(QaInspectionPlanRow, lot.plan_id), actor)
        lot.ncr_id = n.id
        n.title = {"scrap": "Stopper OD out of tolerance", "rework": "Glass barrel chips at flange",
                   "use_as_is": "Graduation print faint"}[kind]
        n.capa_required = kind == "scrap"
        s.add(QaNcrDispositionRow(id=new_id("ncd_"), ncr_id=n.id, line_no=1, kind=kind, qty=n.qty_nc,
                                  location_id=None, rework_routing_id=None, rework_to_seq=None, instructions="",
                                  justification="Legibility verified on 100 % of a 200-unit sample; within "
                                  "customer agreement CA-17." if kind == "use_as_is" else "",
                                  implemented_at=now if status == "closed" else None, refs={}, owner_id=n.owner_id,
                                  row_version=1, created_at=now, updated_at=now))
        n.status = status
        if status == "closed":
            n.closed_at = now
        ncrs.append(n)
    s.flush()

    # ---- CAPA in implementation, linked to the scrap NCR
    from .qa_common import add_link

    cap = QaCapaRow(id=new_id("cap_"), number=next_number(s, "CAPA", QaCapaRow),
                    title="Stopper moulding cavity wear", kind="corrective",
                    problem="Repeated OD rejects on incoming stoppers from one cavity.",
                    risk={"severity": 3, "occurrence": 3, "level": "medium"}, owner_user_id=actor,
                    due_on=d0 + timedelta(days=30), root_cause={"method": "5_why", "text": "Cavity 7 worn."},
                    effectiveness={"criteria": "No OD rejects in 10 lots", "check_due_on": None, "result": None,
                                   "evidence": ""}, status="implementation", author_id=actor, closed_at=None,
                    external_ref=None, row_version=1, created_at=now, updated_at=now)
    s.add(cap)
    s.flush()
    for i, (desc, st) in enumerate((("Supplier replaces cavity 7 insert", "done"),
                                    ("Add OD to supplier CoA", "open")), start=1):
        s.add(QaCapaActionRow(id=new_id("cpa_"), capa_id=cap.id, seq=i, kind="corrective", description=desc,
                              owner_user_id=actor, due_on=d0 + timedelta(days=14 * i), status=st,
                              done_at=now if st == "done" else None, evidence="", eco_id=None, owner_id=cap.owner_id,
                              row_version=1, created_at=now, updated_at=now))
    add_link(s, "ncr", ncrs[0].id, "capa", cap.id, actor)

    # ---- complaints
    for k, (cust, ev, status) in enumerate((("Hospital network North (fictional)", "malfunction", "investigation"),
                                            ("Provincial health authority East (fictional)", "other", "closed")),
                                           start=1):
        s.add(QaComplaintRow(id=new_id("cmp_"), number=next_number(s, "CMP", QaComplaintRow),
                             received_on=d0 - timedelta(days=12 * k), aware_on=d0 - timedelta(days=12 * k),
                             channel="email", customer=cust, country="CA", item_id=_item(s, "MDV-SYR-03").id,
                             lots=[], serials=[], qty_affected=float(k * 3),
                             description="Plunger stiff on first stroke." if k == 1 else "Carton label smudged.",
                             event_type=ev, reportability={"assessed": status == "closed", "reportable": False if
                                                           status == "closed" else None, "regimes": ["hc_mdpr"],
                                                           "report_ref": None},
                             investigation="", status=status, author_id=actor,
                             closed_at=now if status == "closed" else None, external_ref=None, row_version=1,
                             created_at=now, updated_at=now))
    s.flush()

    # ---- field action (draft) from a recall of the history resin lot
    fa = _field_action(s, actor)
    held = _qc_holds(s, plans, actor)
    del lot_content
    return {"schemes": len(schemes), "plans": len(plans), "equipment": len(eqs), "inspection_lots": len(lots),
            "ncrs": len(ncrs), "field_action": fa, "qc_holds": held}


def _field_action(s: Session, actor: str) -> str | None:
    from ..db_models_m5 import MfgRecallRow
    from ..db_models_m7 import QaFieldActionRow
    from ..repo_m2 import next_number as series, number_taken
    from .qa_common import next_number
    from .qa_field_actions import _scope_units
    from .trace import _report

    lot = s.execute(select(MfgLotRow).join(MfgItemRow, MfgItemRow.id == MfgLotRow.item_id)
                    .where(MfgItemRow.part_number == "MDV-RES-PP").order_by(MfgLotRow.lot_code).limit(1)
                    ).scalars().first()
    if lot is None:
        return None
    owner = lot.owner_id
    rep = _report(s, owner, [{"kind": "lot", "id": lot.id}], True, actor)
    now = utcnow()
    rc = MfgRecallRow(id=new_id("rcl_"), number=series(s, "RCL", number_taken(s, MfgRecallRow)),
                      name=f"Resin lot {lot.supplier_lot or lot.lot_code}",
                      sources=[{"kind": "lot", "id": lot.id}], include_possible=True, report=rep,
                      quarantined_at=None, actor_id=actor, row_version=1, created_at=now, updated_at=now)
    s.add(rc)
    s.flush()
    fa = QaFieldActionRow(id=new_id("fac_"), number=next_number(s, "FA", QaFieldActionRow),
                          title=f"Field correction: resin lot {lot.supplier_lot or lot.lot_code}", kind="correction",
                          class_="II", regimes=["hc_mdpr"], strategy="Notify affected customers; inspect stock.",
                          recall_id=rc.id, status="draft", complete_reason=None, author_id=actor, closed_at=None,
                          row_version=1, created_at=now, updated_at=now)
    s.add(fa)
    s.flush()
    _scope_units(s, fa, rep)
    return fa.number


def _qc_holds(s: Session, plans: dict[str, Any], actor: str) -> int:
    """Lots the sample put on QC release hold get hold rows: a final inspection lot with an `inspection` hold where
    the item has a final plan, else a `manual` hold (released through PUT /lots or the Holds page)."""
    from .qa_inspection import create_lot_in

    finals = {p.item_id: p for p in plans.values() if p.scope == "final"}
    n = 0
    for lot in list(s.execute(select(MfgLotRow).where(MfgLotRow.hold.is_(True))).scalars()):
        if s.execute(select(MfgLotHoldRow.id).where(MfgLotHoldRow.lot_id == lot.id,
                                                    MfgLotHoldRow.released_at.is_(None)).limit(1)).first():
            continue
        p = finals.get(lot.item_id)
        if p is not None:
            from .m2util import r6

            from ..db_models_m2 import MfgInvBalanceRow

            qty = float(sum(b.qty_on_hand for b in s.execute(select(MfgInvBalanceRow).where(
                MfgInvBalanceRow.lot_id == lot.id)).scalars()) or 1.0)
            create_lot_in(s, p, lot_size=r6(qty), source="manual", actor=actor, lot_id=lot.id, hold=True,
                          note="QC release")
        else:
            from .qa_holds import place

            place(s, source="manual", reason="QC release hold (sample)", actor=actor, lot_id=lot.id)
        n += 1
    return n

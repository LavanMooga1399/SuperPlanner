"""M9 trade service (M9-DESIGN 8; T1-T8 in the network workspace, P1-P5 in plants).

Tables (tariffs, FX, milestones, country risk) belong to the organisation's network workspace; plant routes read
them in system scope through the plant's organisation (`network_tables`). COO capture at receipts is the posting
hook `after_post`; lot content is rolled up on read (and stored on the lot for the default rule) and by the
`content_rollup` job; the milestone report is the `tariff_report` job.
"""

from __future__ import annotations

import io
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....mfg.network.build import key_of
from ....mfg.network.model import NET_SETTINGS_DEFAULTS
from ....mfg.sop.demand import add_months, months_between
from ....mfg.trade import content as CT
from ....mfg.trade import milestones as MS
from ....mfg.trade import risk as RK
from ....mfg.trade.fx import FxTable
from ....mfg.trade.landed import SupplierTerms, Tariff, landed
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...db.ownership import current_owner, owner_scope, system_scope
from ...errors import ApiError
from .. import repo
from ..db_models import MfgItemRow, MfgPlantRow
from ..db_models_m2 import MfgItemSupplierRow, MfgLotRow, MfgSupplierRow
from ..db_models_m9 import (MfgCountryRiskRow, MfgFxRateRow, MfgItemTradeRow, MfgMpsTargetRow, MfgTariffMilestoneRow,
                            MfgTariffRateRow, MfgTariffReportRow)
from . import m9_examples
from .common import audit, check_version, jsonable, read_tx, write_tx
from .m8common import next_number, page, start_job, today


# ---------------------------------------------------------------- network tables (system scope)

def network_owner(s: Session, owner: str | None = None) -> str | None:
    from ..db_models_m5 import OrgPlantRow

    owner = owner or str(current_owner())
    with system_scope():
        org = s.execute(select(OrgPlantRow.org_id).where(OrgPlantRow.plant_owner_id == owner)).scalar()
        if org is None:
            return None
        owners = list(s.execute(select(OrgPlantRow.plant_owner_id).where(OrgPlantRow.org_id == org)).scalars())
        return s.execute(select(MfgPlantRow.owner_id).where(MfgPlantRow.owner_id.in_(owners),
                                                            MfgPlantRow.kind == "network")).scalar()


def network_tables(s: Session, net: str | None = None) -> dict[str, Any]:
    net = net or network_owner(s)
    out: dict[str, Any] = {"settings": dict(NET_SETTINGS_DEFAULTS), "fx": FxTable(), "tariffs": [], "risk": {},
                           "milestones": []}
    if net is None:
        return out
    with system_scope():
        raw = s.execute(select(MfgPlantRow.planning_settings).where(MfgPlantRow.owner_id == net)).scalar() or {}
        out["settings"] = {k: raw.get(k, v) for k, v in NET_SETTINGS_DEFAULTS.items()}
        out["fx"] = FxTable([(r.from_ccy, r.to_ccy, r.month, r.rate) for r in s.execute(
            select(MfgFxRateRow).where(MfgFxRateRow.owner_id == net)).scalars()])
        out["tariffs"] = [Tariff(r.dest_country, r.hts_prefix, r.coo, r.layer, r.rate_pct, r.per_unit,
                                 r.per_unit_currency, r.valid_from, r.valid_to)
                          for r in s.execute(select(MfgTariffRateRow).where(MfgTariffRateRow.owner_id == net)).scalars()]
        out["risk"] = dict(s.execute(select(MfgCountryRiskRow.country, MfgCountryRiskRow.score).where(
            MfgCountryRiskRow.owner_id == net)).all())
        out["milestones"] = [_milestone(r) for r in s.execute(select(MfgTariffMilestoneRow).where(
            MfgTariffMilestoneRow.owner_id == net).order_by(MfgTariffMilestoneRow.code)).scalars()]
    return out


def _plant_country(s: Session) -> tuple[str | None, str]:
    """(explicit plant country, currency). Review M4: trade never derives the country from the currency or the time
    zone - without the plant attribute `country` the COO of made lots is missing and landed cost has no total."""
    p = s.execute(select(MfgPlantRow)).scalars().first()
    if p is None:
        return None, "USD"
    c = (p.attributes or {}).get("country")
    return (c.upper() if isinstance(c, str) and len(c) == 2 else None), p.currency or "USD"


# ---------------------------------------------------------------- T1-T4 tables

def _tariff(r: MfgTariffRateRow) -> dict[str, Any]:
    return {"id": r.id, "dest_country": r.dest_country, "hts_prefix": r.hts_prefix, "coo": r.coo, "layer": r.layer,
            "rate_pct": r.rate_pct, "per_unit": r.per_unit, "per_unit_currency": r.per_unit_currency,
            "valid_from": r.valid_from, "valid_to": r.valid_to, "note": r.note}


def _require_net(s: Session) -> None:
    from .network import require_network

    require_network(s)


def get_tariffs(ctx: AppContext, dest: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        _require_net(s)
        q = select(MfgTariffRateRow)
        if dest:
            q = q.where(MfgTariffRateRow.dest_country == dest.upper())
        return {"items": [_tariff(r) for r in s.execute(q.order_by(
            MfgTariffRateRow.dest_country, MfgTariffRateRow.hts_prefix, MfgTariffRateRow.coo, MfgTariffRateRow.layer,
            MfgTariffRateRow.valid_from)).scalars()]}


def _bulk(s: Session, model: Any, rows: list[Any], key: tuple[str, ...], prefix: str, replace: bool,
          entity: str) -> dict[str, int]:
    old = {tuple(getattr(r, k) for k in key): r for r in s.execute(select(model)).scalars()}
    ins = upd = 0
    seen = set()
    for x in rows:
        d = x.model_dump()
        k = tuple(d[f] for f in key)
        if k in seen:
            raise ApiError(422, "MFG_DUPLICATE_KEY", "A row appears twice.", {"key": [str(v) for v in k]})
        seen.add(k)
        r = old.get(k)
        if r is None:
            s.add(model(id=new_id(prefix), **d))
            ins += 1
        elif any(getattr(r, f) != v for f, v in d.items()):
            for f, v in d.items():
                setattr(r, f, v)
            upd += 1
    dele = 0
    if replace:
        for k, r in old.items():
            if k not in seen:
                s.delete(r)
                dele += 1
    s.flush()
    audit(s, entity, None, "bulk", {"inserted": ins, "updated": upd, "deleted": dele})
    return {"inserted": ins, "updated": upd, "deleted": dele}


def put_tariffs(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        _require_net(s)
        return _bulk(s, MfgTariffRateRow, body.rows, ("dest_country", "hts_prefix", "coo", "layer", "valid_from"),
                     "trf_", body.replace, "tariff_rates")


def get_fx(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        _require_net(s)
        return {"items": [{"id": r.id, "from_ccy": r.from_ccy, "to_ccy": r.to_ccy, "month": r.month, "rate": r.rate,
                           "source": r.source} for r in s.execute(select(MfgFxRateRow).order_by(
                               MfgFxRateRow.from_ccy, MfgFxRateRow.to_ccy, MfgFxRateRow.month)).scalars()]}


def put_fx(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        _require_net(s)
        return _bulk(s, MfgFxRateRow, body.rows, ("from_ccy", "to_ccy", "month"), "fxr_", body.replace, "fx_rates")


def _milestone(r: MfgTariffMilestoneRow) -> dict[str, Any]:
    return {"id": r.id, "code": r.code, "name": r.name, "dest_country": r.dest_country, "family": r.family,
            "hts_prefix": r.hts_prefix, "rule": r.rule, "effective": r.effective, "note": r.note}


def get_milestones(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        _require_net(s)
        return {"items": [_milestone(r) for r in s.execute(select(MfgTariffMilestoneRow).order_by(
            MfgTariffMilestoneRow.code)).scalars()]}


def put_milestones(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        _require_net(s)
        old = {r.code: r for r in s.execute(select(MfgTariffMilestoneRow)).scalars()}
        ins = upd = 0
        now = utcnow()
        codes = [x.code for x in body.rows]
        if len(codes) != len(set(codes)):
            raise ApiError(422, "MFG_DUPLICATE_KEY", "Milestone codes are unique.", {})
        for x in body.rows:
            d = x.model_dump(mode="python")
            d["rule"] = x.rule.model_dump(mode="json")
            r = old.pop(x.code, None)
            if r is None:
                s.add(MfgTariffMilestoneRow(id=new_id("tms_"), **d, row_version=1, created_at=now, updated_at=now))
                ins += 1
            else:
                for f, v in d.items():
                    setattr(r, f, v)
                r.row_version, r.updated_at = r.row_version + 1, now
                upd += 1
        for r in old.values():
            s.delete(r)
        s.flush()
        audit(s, "tariff_milestones", None, "replace", {"codes": codes})
        return {"inserted": ins, "updated": upd, "deleted": len(old)}


def get_country_risk(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        _require_net(s)
        return {"items": [{"id": r.id, "country": r.country, "score": r.score, "note": r.note} for r in s.execute(
            select(MfgCountryRiskRow).order_by(MfgCountryRiskRow.country)).scalars()]}


def put_country_risk(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        _require_net(s)
        return _bulk(s, MfgCountryRiskRow, body.rows, ("country",), "ckr_", True, "country_risk")


# ---------------------------------------------------------------- P1 item trade

def _item_trade(item_id: str, r: MfgItemTradeRow | None) -> dict[str, Any]:
    return {"item_id": item_id, "hts_code": r.hts_code if r else None, "coo": r.coo if r else None,
            "material_class": r.material_class if r else None, "unit_weight_kg": r.unit_weight_kg if r else None,
            "row_version": r.row_version if r else 0}


def get_item_trade(ctx: AppContext, item_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        it = repo.get_row(s, MfgItemRow, item_id, what="Item")
        r = s.execute(select(MfgItemTradeRow).where(MfgItemTradeRow.item_id == it.id)).scalars().first()
        return _item_trade(it.id, r)


def put_item_trade(ctx: AppContext, a: Any, item_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    with write_tx(ctx) as (s, _):
        it = repo.get_row(s, MfgItemRow, item_id, what="Item")
        r = s.execute(select(MfgItemTradeRow).where(MfgItemTradeRow.item_id == it.id).with_for_update()
                      ).scalars().first()
        before = _item_trade(it.id, r)
        if r is None:
            if if_match not in (None, '"0"', "0"):
                check_version(type("X", (), {"row_version": 0})(), if_match)
            now = utcnow()
            r = MfgItemTradeRow(id=new_id("itr_"), item_id=it.id, **body.model_dump(), row_version=1, created_at=now,
                                updated_at=now)
            s.add(r)
        else:
            if if_match is not None:
                check_version(r, if_match)
            for f, v in body.model_dump().items():
                setattr(r, f, v)
            r.row_version, r.updated_at = r.row_version + 1, utcnow()
        s.flush()
        audit(s, "item_trade", it.id, "update", None, before=before, after=_item_trade(it.id, r))
        return _item_trade(it.id, r)


# ---------------------------------------------------------------- P2 landed cost

def landed_of_rows(s: Session, rows: list[MfgItemSupplierRow], month: date | None = None) -> list[dict[str, Any]]:
    """Landed cost per item-supplier row (bound plant; tables of its organisation's network)."""
    t = network_tables(s)
    country, ccy = _plant_country(s)
    month = (month or today(s)).replace(day=1)
    trade = {r.item_id: r for r in s.execute(select(MfgItemTradeRow).where(
        MfgItemTradeRow.item_id.in_({r.item_id for r in rows}))).scalars()} if rows else {}
    out = []
    for r in rows:
        tr = trade.get(r.item_id)
        out.append(landed(SupplierTerms(r.unit_price, r.currency or ccy, r.units_per_purchase_unit or 1.0, r.coo,
                                        r.hts_code, r.freight_per_unit), country, ccy, month, t["fx"], t["tariffs"],
                          duty_base=t["settings"]["duty_base"], other_cost_pct=float(t["settings"]["other_cost_pct"]),
                          item_hts=tr.hts_code if tr else None, item_coo=tr.coo if tr else None))
    return out


def landed_rows(ctx: AppContext, item_id: str, month: date | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        it = repo.get_row(s, MfgItemRow, item_id, what="Item")
        rows = list(s.execute(select(MfgItemSupplierRow).where(MfgItemSupplierRow.item_id == it.id).order_by(
            MfgItemSupplierRow.preferred.desc(), MfgItemSupplierRow.id)).scalars())
        sups = {x.id: x for x in s.execute(select(MfgSupplierRow)).scalars()}
        lcs = landed_of_rows(s, rows, month)
        return {"items": [{"item_supplier_id": r.id, "supplier_code": sups[r.supplier_id].code if r.supplier_id in sups
                           else "", "supplier_name": sups[r.supplier_id].name if r.supplier_id in sups else "",
                           "coo": r.coo, "hts_code": r.hts_code, "incoterm": r.incoterm, "preferred": r.preferred,
                           "landed": lc} for r, lc in zip(rows, lcs)]}


# ---------------------------------------------------------------- COO capture (8.1)

def after_post(s: Session, posting: Any, inp: Any) -> None:
    """Receipt hook: lot COO (request > item-supplier > item trade > plant country for made lots > none with
    `TRADE_COO_MISSING`), `coo_source`, `unit_value` (plant currency at receipt); transfer receipts copy COO, value
    and domestic shares from the source lot. Only the first receipt of a lot sets them."""
    from ..db_models_m2 import (MfgInvTransactionRow, MfgPurchaseDocRow, MfgPurchaseLineRow,
                                MfgPurchaseScheduleRow)

    if posting.type not in ("po_receipt", "wo_receipt", "transfer_receipt"):
        return
    txns = list(s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id == posting.id,
                                                             MfgInvTransactionRow.lot_id.is_not(None))).scalars())
    if not txns:
        return
    lots = {r.id: r for r in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_({t.lot_id for t in txns}))
                                       .with_for_update()).scalars()}
    country, ccy = _plant_country(s)
    lines_in = list(getattr(inp, "lines", []))          # review m10: keyed by the 1-based receipt line
    req = {i + 1: getattr(ln, "coo", None) for i, ln in enumerate(lines_in)}
    warn = []
    tables = None
    for t in txns:
        lot = lots.get(t.lot_id)
        if lot is None:
            continue
        if lot.coo_source is not None:                    # later receipt into a lot: keep, warn on a conflict
            asked = req.get(t.line_no) if posting.type == "po_receipt" else None
            if asked and lot.coo and asked != lot.coo:
                warn.append({"code": "TRADE_COO_CONFLICT", "lot_id": lot.id, "coo": lot.coo, "requested": asked})
            continue
        if posting.type == "wo_receipt":
            it = s.get(MfgItemRow, t.item_id)
            lot.coo, lot.coo_source = country, ("plant" if country else None)
            lot.unit_value = it.standard_cost if it else None
            if not country:
                warn.append({"code": "TRADE_COO_MISSING", "lot_id": lot.id, "detail": "COUNTRY_MISSING"})
        elif posting.type == "po_receipt":
            sched = s.get(MfgPurchaseScheduleRow, t.schedule_id) if t.schedule_id else None
            line = s.get(MfgPurchaseLineRow, sched.line_id) if sched else None
            doc = s.get(MfgPurchaseDocRow, line.doc_id) if line else None
            isp = s.execute(select(MfgItemSupplierRow).where(MfgItemSupplierRow.item_id == t.item_id,
                                                             MfgItemSupplierRow.supplier_id == doc.supplier_id)
                            ).scalars().first() if doc and doc.supplier_id else None
            tr = s.execute(select(MfgItemTradeRow).where(MfgItemTradeRow.item_id == t.item_id)).scalars().first()
            coo, src = req.get(t.line_no), "receipt"
            if not coo and isp is not None and isp.coo:
                coo, src = isp.coo, "supplier"
            if not coo and tr is not None and tr.coo:
                coo, src = tr.coo, "item"
            lot.coo, lot.coo_source = coo, (src if coo else None)
            if not coo:
                warn.append({"code": "TRADE_COO_MISSING", "lot_id": lot.id})
            price = t.unit_cost if t.unit_cost is not None else (line.unit_price if line else None)
            if price is not None and doc is not None:
                if (doc.currency or ccy) == ccy:
                    lot.unit_value = price
                else:
                    tables = tables or network_tables(s)
                    lot.unit_value, _f = tables["fx"].convert(price, doc.currency, ccy, t.txn_date)
                    if lot.unit_value is None:
                        warn.append({"code": "FX_MISSING", "lot_id": lot.id, "from": doc.currency, "to": ccy})
        else:
            src_lot = _source_lot(s, t)
            if src_lot is not None:
                lot.coo, lot.coo_source = src_lot["coo"], "transfer"
                lot.dom_share_value, lot.dom_share_weight = src_lot["dv"], src_lot["dw"]
                lot.dom_estimated = src_lot["est"]
                v = src_lot["unit_value"]
                if v is not None and src_lot["currency"] != ccy:
                    tables = tables or network_tables(s)
                    v, _f = tables["fx"].convert(v, src_lot["currency"], ccy, t.txn_date)
                    if v is None:
                        warn.append({"code": "FX_MISSING", "lot_id": lot.id, "from": src_lot["currency"], "to": ccy})
                lot.unit_value = v
    if warn:
        s.info.setdefault("sp_trade_warnings", []).extend(warn)


def _source_lot(s: Session, t: Any) -> dict[str, Any] | None:
    from ..db_models_m5 import MfgTransferLineRow

    with system_scope():
        dl = s.get(MfgTransferLineRow, t.transfer_line_id) if t.transfer_line_id else None
        sl = s.get(MfgTransferLineRow, dl.mirror_line_id) if dl and dl.mirror_line_id else None
        mine = s.get(MfgLotRow, t.lot_id)
        if sl is None or mine is None:
            return None
        src = s.execute(select(MfgLotRow).where(MfgLotRow.owner_id == sl.owner_id, MfgLotRow.item_id == sl.item_id,
                                                MfgLotRow.lot_code == mine.lot_code)).scalars().first()
        if src is None:
            return None
        ccy = s.execute(select(MfgPlantRow.currency).where(MfgPlantRow.owner_id == sl.owner_id)).scalar() or "USD"
        return {"coo": src.coo, "dv": src.dom_share_value, "dw": src.dom_share_weight, "est": src.dom_estimated,
                "unit_value": src.unit_value, "currency": ccy}


def put_lot_coo(ctx: AppContext, a: Any, lot_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    """8.1: change a received lot's COO - always with a reason (audited as the change reason, also outside
    Part 11 mode); the lot's stored domestic shares are cleared and the plant's roll-up is queued."""
    with write_tx(ctx) as (s, _):
        lot = repo.get_row(s, MfgLotRow, lot_id, what="Lot", lock=True)
        if if_match is not None:
            check_version(lot, if_match)
        before = {"coo": lot.coo, "coo_source": lot.coo_source}
        lot.coo = body.coo
        lot.coo_source = lot.coo_source or "receipt"
        lot.dom_share_value = lot.dom_share_weight = lot.dom_estimated = lot.dom_computed_at = None
        lot.row_version += 1
        lot.updated_at = utcnow()
        audit(s, "lot", lot.id, "coo_change", {"lot_code": lot.lot_code}, before=before,
              after={"coo": lot.coo, "coo_source": lot.coo_source}, reason=body.reason)
        from .inventory import lot_record

        rec = lot_record(s, lot)
    queue_rollup(ctx)
    return rec


# ---------------------------------------------------------------- lot content (8.2; T7, P4)

def load_graph(s: Session, lot_id: str) -> CT.Graph:
    """The genealogy subgraph under a lot (bound plant), breadth-first, depth <= 30."""
    from ..db_models_m5 import MfgTraceEdgeRow

    lots: dict[str, CT.LotT] = {}
    wo_inputs: dict[str, list[CT.EdgeT]] = {}
    item_ids: set[str] = set()
    todo, depth = [lot_id], 0
    while todo and depth <= CT.MAX_DEPTH:
        rows = {r.id: r for r in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_(todo))).scalars()}
        made = defaultdict(list)
        for e in s.execute(select(MfgTraceEdgeRow).where(MfgTraceEdgeRow.to_kind == "lot",
                                                         MfgTraceEdgeRow.to_id.in_(todo),
                                                         MfgTraceEdgeRow.from_kind == "wo")).scalars():
            made[e.to_id].append(e)
        wos = {e.from_id for es in made.values() for e in es}
        outs: dict[str, float] = defaultdict(float)
        if wos:
            for e in s.execute(select(MfgTraceEdgeRow).where(MfgTraceEdgeRow.from_kind == "wo",
                                                             MfgTraceEdgeRow.from_id.in_(wos))).scalars():
                outs[e.from_id] += float(e.qty or 0)
            for e in s.execute(select(MfgTraceEdgeRow).where(MfgTraceEdgeRow.to_kind == "wo",
                                                             MfgTraceEdgeRow.to_id.in_(wos))).scalars():
                if e.from_kind not in ("lot", "item_stock"):
                    continue
                wo_inputs.setdefault(e.to_id, []).append(CT.EdgeT("lot" if e.from_kind == "lot" else "stock",
                                                                  e.from_id if e.from_kind == "lot" else None,
                                                                  e.from_item_id or "", float(e.qty or 0)))
        nxt = []
        for lid in todo:
            r = rows.get(lid)
            if r is None:
                continue
            item_ids.add(r.item_id)
            es = made.get(lid, [])
            wo = es[0].from_id if es else None
            q = sum(float(e.qty or 0) for e in es)
            ts = (r.dom_share_value, r.dom_share_weight) if r.coo_source == "transfer" else None
            lots[lid] = CT.LotT(r.id, r.lot_code, r.item_id, r.coo, r.unit_value, wo,
                                (q / outs[wo]) if wo and outs.get(wo) else 1.0, q, ts)
            if wo:
                for e in wo_inputs.get(wo, []):
                    item_ids.add(e.item_id)
                    if e.lot_id and e.lot_id not in lots:
                        nxt.append(e.lot_id)
        todo, depth = sorted(set(nxt)), depth + 1
    items = {}
    trade = {r.item_id: r for r in s.execute(select(MfgItemTradeRow).where(MfgItemTradeRow.item_id.in_(item_ids))
                                             ).scalars()} if item_ids else {}
    for it in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(item_ids))).scalars() if item_ids else []:
        tr = trade.get(it.id)
        items[it.id] = CT.ItemT(it.id, key_of(it), it.description, it.uom, float(it.standard_cost or 0.0),
                                tr.unit_weight_kg if tr else None, tr.coo if tr else None,
                                tr.material_class if tr else None)
    return CT.Graph(items, lots, wo_inputs)


def _rule(ms: dict[str, Any] | None, settings: dict[str, Any], plant_country: str | None) -> CT.Rule:
    if ms is None:
        return CT.Rule(settings.get("domestic_country", "US"), None, False, plant_country)
    r = ms["rule"]
    return CT.Rule(r.get("domestic_country", "US"), frozenset(r["material_classes"]) if r.get("material_classes")
                   else None, bool(r.get("include_conversion")), plant_country)


def _content(s: Session, lot_id: str, milestone_id: str | None, store: bool = True) -> dict[str, Any]:
    lot = repo.get_row(s, MfgLotRow, lot_id, what="Lot")
    t = network_tables(s)
    ms = None
    if milestone_id:
        ms = next((m for m in t["milestones"] if m["id"] == milestone_id), None)
        if ms is None:
            raise ApiError(404, "NOT_FOUND", "Milestone not found.", {"id": milestone_id})
    country, ccy = _plant_country(s)
    g = load_graph(s, lot.id)
    out = CT.rollup(g, lot.id, _rule(ms, t["settings"], country))
    now = utcnow()
    if store and ms is None and lot.coo_source != "transfer" and g.lots[lot.id].wo_id:    # job only (m9)
        lot.dom_share_value, lot.dom_share_weight = out["share_value"], out["share_weight"]
        lot.dom_estimated, lot.dom_computed_at = out["estimated"], now
    it = g.items.get(lot.item_id)
    return {"lot_id": lot.id, "lot_code": lot.lot_code, "item_key": it.key if it else "", "coo": lot.coo,
            "coo_source": lot.coo_source, "share_value": out["share_value"], "share_weight": out["share_weight"],
            "estimated": out["estimated"], "computed_at": now, "milestone_id": milestone_id, "currency": ccy,
            "tree": out["tree"]}


def lot_content(ctx: AppContext, lot_id: str, milestone_id: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:                          # review m9: computed on read, never stored by a GET
        return _content(s, lot_id, milestone_id, store=False)


def network_lot_content(ctx: AppContext, a: Any, plant: str, lot_id: str, milestone_id: str | None
                        ) -> dict[str, Any]:
    from .network import org_nodes

    with read_tx(ctx) as s:
        nodes = {n["owner_id"]: n for n in org_nodes(s, a.user_id)}
        n = nodes.get(plant) or next((x for x in nodes.values() if x["code"] == plant), None)
        if n is None or not n["member"]:
            from ...errors import not_found

            raise not_found("Lot", lot_id)          # same answer as an unknown lot of a member plant
    with owner_scope(n["owner_id"]), read_tx(ctx) as s:
        return _content(s, lot_id, milestone_id, store=False)


def rollup_lots(s: Session, since: date) -> int:
    """Default-rule roll-up of the plant's made lots received since `since` (job `content_rollup`)."""
    from ..db_models_m2 import MfgInvTransactionRow

    ids = sorted(set(s.execute(select(MfgInvTransactionRow.lot_id).where(
        MfgInvTransactionRow.txn_type == "wo_receipt", MfgInvTransactionRow.txn_date >= since,
        MfgInvTransactionRow.lot_id.is_not(None))).scalars()))
    changed = 0
    for lid in ids:
        before = s.execute(select(MfgLotRow.dom_share_value, MfgLotRow.dom_share_weight).where(
            MfgLotRow.id == lid)).first()
        out = _content(s, lid, None)
        if before is None or (before[0], before[1]) != (out["share_value"], out["share_weight"]):
            changed += 1
            audit(s, "lot", lid, "content_rollup", {"share_value": out["share_value"],
                                                    "share_weight": out["share_weight"],
                                                    "estimated": out["estimated"]})
    return len(ids)


ROLLUP_DEBOUNCE_S = 300


def queue_rollup(ctx: AppContext) -> str | None:
    """After a `wo_receipt`: one `content_rollup` duty run per plant, debounced - none is queued while one is queued
    or running; the queue executor claims it 5 minutes later (`run_after`), the inline executor runs it at once."""
    from ....integration.jobs import active_run, new_run

    owner = str(current_owner())
    with write_tx(ctx, lock=False) as (s, _):
        if active_run(s, "content_rollup", owner):
            return None
        rid, job = new_run(s, ctx, "content_rollup", owner, {"days": 30})
        if hasattr(job, "run_after") and job.run_after is not None:
            job.run_after = job.run_after + timedelta(seconds=ROLLUP_DEBOUNCE_S)
    ctx.jobs.dispatch(job)
    return rid


def rollup_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        n = rollup_lots(s, today(s) - timedelta(days=int(info["params"].get("days", 30))))
    return {"lots": n}


# ---------------------------------------------------------------- T5-T6 milestone reports (8.3)

def _report(r: MfgTariffReportRow) -> dict[str, Any]:
    return {"id": r.id, "number": r.number, "params": r.params, "status": r.status, "result": r.result,
            "error": r.error, "actor_id": r.actor_id, "started_at": r.started_at, "finished_at": r.finished_at,
            "created_at": r.created_at}


def list_reports(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        _require_net(s)
        n = int(s.execute(select(func.count()).select_from(MfgTariffReportRow)).scalar() or 0)
        rows = s.execute(select(MfgTariffReportRow).order_by(MfgTariffReportRow.created_at.desc()).limit(limit)
                         .offset(offset)).scalars()
        return page([_report(r) for r in rows], n, limit, offset)


def create_report(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        _require_net(s)
        known = {r for r in s.execute(select(MfgTariffMilestoneRow.id)).scalars()}
        for m in body.milestone_ids:
            if m not in known:
                raise ApiError(404, "NOT_FOUND", "Milestone not found.", {"id": m})
        r = MfgTariffReportRow(id=new_id("trp_"), number=next_number(s, "TR", MfgTariffReportRow),
                               params=body.model_dump(mode="json", by_alias=True), status="queued", result=None,
                               error=None, actor_id=a.user_id, created_at=utcnow(), started_at=None, finished_at=None)
        s.add(r)
        s.flush()
        _rid, job = start_job(s, ctx, "tariff_report", r.owner_id, {"report_id": r.id})
        audit(s, "tariff_report", r.id, "create", r.params)
        rec = _report(r)
    ctx.jobs.dispatch(job)
    return rec


def get_report(ctx: AppContext, report_id: str, fmt: str) -> Any:
    with read_tx(ctx) as s:
        r = repo.get_row(s, MfgTariffReportRow, report_id, what="Tariff report")
        rec = _report(r)
    if fmt != "xlsx":
        return rec
    return _xlsx(rec), f"{rec['number']}.xlsx"


def _xlsx(rec: dict[str, Any]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Milestones"
    ws.append(["Milestone", "Group", "Month", "Share %", "Status", "Projected", "Lots", "Lots below", "Qty below %",
               "Estimated %"])
    for m in (rec.get("result") or {}).get("milestones", []):
        for g in m["groups"]:
            for c in g["cells"]:
                ws.append([m["code"], g["label"], str(c["month"]), c["share_pct"], c["status"], c["projected"],
                           c["lots"], c["lots_below"], c["qty_below_pct"], c["estimated_pct"]])
    lots = wb.create_sheet("Lots below minimum")
    lots.append(["Milestone", "Plant", "Lot", "Item", "Month", "Qty", "Share %", "Estimated"])
    for m in (rec.get("result") or {}).get("milestones", []):
        for x in m["lots_below"]:
            lots.append([m["code"], x["plant_owner_id"], x["lot_code"], x["item_key"], str(x["month"]), x["qty"],
                         x["share_pct"], x["estimated"]])
    for sh in wb.worksheets:                 # review m8: text is an explicit string cell (as mfg/io/export.py)
        for row in sh.iter_rows():
            for c in row:
                if isinstance(c.value, str):
                    c.data_type = "s"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def compute_report(ctx: AppContext, report_id: str) -> dict[str, Any]:
    from ..db_models_m2 import MfgInvTransactionRow
    from .network import org_nodes

    t0 = time.monotonic()
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MfgTariffReportRow, report_id, with_for_update=True)
        r.status, r.started_at = "running", utcnow()
        params = dict(r.params)
        net = r.owner_id
    with read_tx(ctx) as s:
        tables = network_tables(s, net)
        nodes = [n for n in org_nodes(s) if n["kind"] == "plant"]
    if params.get("nodes"):
        nodes = [n for n in nodes if n["owner_id"] in params["nodes"]]
    mss = [m for m in tables["milestones"] if m["id"] in params["milestone_ids"]]
    splits = _scenario_splits(ctx, net, (params.get("projection") or {}).get("scenario_id"), nodes)
    m_from, m_to = date.fromisoformat(params["from"]).replace(day=1), date.fromisoformat(params["to"]).replace(day=1)
    months = months_between(m_from, m_to)
    cur = date.today().replace(day=1)
    by = params.get("group_by", "family")
    result_ms = []
    shares_proj: dict[str, dict[str, float]] = {}
    for ms in mss:
        cells: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
        below: list[dict[str, Any]] = []
        proj_num: dict[str, float] = defaultdict(float)
        proj_den: dict[str, float] = defaultdict(float)
        for n in nodes:
            with owner_scope(n["owner_id"]), write_tx(ctx, lock=False) as (s, _):
                items = [it for it in s.execute(select(MfgItemRow).where(MfgItemRow.active.is_(True))).scalars()]
                trade = {x.item_id: x for x in s.execute(select(MfgItemTradeRow)).scalars()}
                scope = {it.id: it for it in items if (ms["family"] and it.family == ms["family"]) or (
                    ms["hts_prefix"] and trade.get(it.id) and (trade[it.id].hts_code or "").startswith(
                        ms["hts_prefix"]))}
                if not scope:
                    continue
                country, _ccy = _plant_country(s)
                rule = _rule(ms, tables["settings"], country)
                memo: dict[str, Any] = {}
                txs = s.execute(select(MfgInvTransactionRow.lot_id, MfgInvTransactionRow.item_id,
                                       MfgInvTransactionRow.txn_date, MfgInvTransactionRow.qty).where(
                    MfgInvTransactionRow.txn_type == "wo_receipt", MfgInvTransactionRow.lot_id.is_not(None),
                    MfgInvTransactionRow.item_id.in_(list(scope)), MfgInvTransactionRow.txn_date >= m_from,
                    MfgInvTransactionRow.txn_date < add_months(m_to, 1))).all()
                per_lot: dict[str, list[Any]] = {}
                for lid, iid, d, q in txs:
                    x = per_lot.setdefault(lid, [iid, d, 0.0])
                    x[2] += float(q)
                for lid, (iid, d, q) in sorted(per_lot.items()):
                    g = load_graph(s, lid)
                    out = CT.rollup(g, lid, rule, memo)
                    tree = out["tree"]
                    basis = ms["rule"].get("basis", "value")
                    share = out["share_value"] if basis == "value" else out["share_weight"]
                    denom = (tree["value"] if basis == "value" else tree["weight_kg"]) or 0.0
                    it = scope[iid]
                    gkey = it.family if by == "family" else key_of(it)
                    m = d.replace(day=1)
                    cells[(gkey, m)].append({"share": share, "denom": denom, "qty": q, "estimated": out["estimated"]})
                    if share is not None and share * 100 < float(ms["rule"]["min_pct"]) - 1e-9:
                        lot = s.get(MfgLotRow, lid)
                        below.append({"plant_owner_id": n["owner_id"], "lot_id": lid, "lot_code": lot.lot_code,
                                      "item_key": key_of(it), "month": m, "qty": q,
                                      "share_pct": round(share * 100, 2), "estimated": out["estimated"]})
                # projection: BOM share per item, bought components split by preferred / active supplier COO
                bom = _bom_map(s)
                ct_items = {it.id: CT.ItemT(it.id, key_of(it), it.description, it.uom, float(it.standard_cost or 0),
                                            trade[it.id].unit_weight_kg if it.id in trade else None,
                                            trade[it.id].coo if it.id in trade else None,
                                            trade[it.id].material_class if it.id in trade else None) for it in items}
                buy_coo = _buy_coo(s, trade, splits.get(n["owner_id"]), items)
                for iid, it in scope.items():
                    if iid not in bom:
                        continue
                    num, den = CT.bom_share(iid, bom, ct_items, buy_coo, rule, ms["rule"].get("basis", "value"))
                    gkey = it.family if by == "family" else key_of(it)
                    if den > 0:
                        proj_num[gkey] += num / den
                        proj_den[gkey] += 1.0
        groups = sorted({g for g, _m in cells} | set(proj_den))
        gout = []
        first_missed = None
        eff = ms["effective"] if isinstance(ms["effective"], date) else date.fromisoformat(str(ms["effective"]))
        for gk in groups:
            row = []
            for m in months:
                if m > cur and gk in proj_den:
                    pct = round(proj_num[gk] / proj_den[gk] * 100, 2)
                    cell = MS.projected_cell(pct, float(ms["rule"]["min_pct"]), m, eff)
                else:
                    cell = MS.month_cell(cells.get((gk, m), []), float(ms["rule"]["min_pct"]), m, eff)
                if cell["status"] == "missed" and (first_missed is None or m < first_missed):
                    first_missed = m
                row.append(cell)
            gout.append({"key": gk, "label": gk, "cells": row})
        result_ms.append({"milestone_id": ms["id"], "code": ms["code"], "name": ms["name"],
                          "min_pct": float(ms["rule"]["min_pct"]), "effective": eff,
                          "basis": ms["rule"].get("basis", "value"), "groups": gout, "first_missed_month": first_missed,
                          "lots_below": sorted(below, key=lambda x: (x["month"], x["lot_code"]))[:500]})
        shares_proj[ms["code"]] = {k: proj_num[k] / proj_den[k] for k in proj_den}
    scen = (params.get("projection") or {}).get("scenario_id")
    result = {"months": months, "projection_from": add_months(cur, 1) if add_months(cur, 1) <= m_to else None,
              "projection_source": scen or "bom", "milestones": result_ms}
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.get(MfgTariffReportRow, report_id, with_for_update=True)
        r.status, r.result, r.finished_at = "completed", jsonable(result), utcnow()
    return {"status": "completed", "duration_s": round(time.monotonic() - t0, 3)}


def _bom_map(s: Session) -> dict[str, list[tuple[str, float]]]:
    from .. import repo as _repo

    ds = _repo.load_dataset(s)
    out = {}
    for iid, bs in ds.boms_by_item.items():
        live = [b for b in bs if b.status == "released"] or bs
        if live:
            out[iid] = [(ln.child_item_id, float(ln.qty_per)) for ln in live[-1].lines]
    return out


def _scenario_splits(ctx: AppContext, net: str, scenario_id: str | None, nodes: list[dict[str, Any]]
                     ) -> dict[str, dict[str, dict[str, float]]]:
    """node owner -> family -> supplier code -> share, from the scenario's `supplier_allocation` changes and the
    supplier rows of `sourcing` changes (share = mean of min / max share)."""
    from ..db_models_m9 import MfgSopScenarioRow

    if not scenario_id:
        return {}
    with read_tx(ctx) as s:
        sc = s.execute(select(MfgSopScenarioRow).where(MfgSopScenarioRow.id == scenario_id,
                                                       MfgSopScenarioRow.owner_id == net)).scalars().first()
        changes = list(sc.changes or []) if sc else []
    if sc is None:
        raise ApiError(404, "NOT_FOUND", "Scenario not found.", {"id": scenario_id})
    by_ref = {n["owner_id"]: n["owner_id"] for n in nodes} | {n["code"]: n["owner_id"] for n in nodes}
    out: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for ch in changes:
        if ch["kind"] == "supplier_allocation":
            node, rows = by_ref.get(ch["node"]), ch["suppliers"]
        elif ch["kind"] == "sourcing":
            node, rows = by_ref.get(ch["dest_node"]), [r for r in ch["sources"] if r.get("supplier_code")]
        else:
            continue
        if node is None or not rows:
            continue
        out[node][ch["family"]] = {(r.get("code") or r.get("supplier_code")): (float(r.get("min_share", 0)) + float(
            r.get("max_share", 1))) / 2 for r in rows}
    return out


def _buy_coo(s: Session, trade: dict[str, Any], splits: dict[str, dict[str, float]] | None = None,
             items: list[Any] | None = None) -> dict[str, list[tuple[str | None, float]]]:
    """Bought item -> [(COO, share)]: the scenario's split for the item's family when given, else the preferred
    (else every active) supplier."""
    out: dict[str, list[tuple[str | None, float]]] = defaultdict(list)
    rows = list(s.execute(select(MfgItemSupplierRow).where(MfgItemSupplierRow.active.is_(True))).scalars())
    codes = dict(s.execute(select(MfgSupplierRow.id, MfgSupplierRow.code)).all())
    fam = {it.id: it.family for it in items or []}
    pref = {r.item_id for r in rows if r.preferred}
    for r in rows:
        tr = trade.get(r.item_id)
        coo = r.coo or (tr.coo if tr else None)
        split = (splits or {}).get(fam.get(r.item_id) or "")
        if split is not None:
            share = split.get(codes.get(r.supplier_id, ""))
            if share:
                out[r.item_id].append((coo, share))
            continue
        if r.item_id in pref and not r.preferred:
            continue
        out[r.item_id].append((coo, 1.0))
    return out


def report_job_body(ctx: AppContext, info: dict[str, Any]) -> dict[str, Any]:
    rid = info["params"]["report_id"]
    try:
        return compute_report(ctx, rid)
    except Exception as exc:
        with ctx.write_guard(), ctx.db.write() as s:
            r = s.get(MfgTariffReportRow, rid, with_for_update=True)
            if r is not None:
                r.status, r.error, r.finished_at = "failed", f"{exc.__class__.__name__}: {exc}"[:2000], utcnow()
        raise


# ---------------------------------------------------------------- T8 / P3 supplier risk

def _plant_risk_rows(s: Session, node: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    from ..db_models_m2 import MfgInvTransactionRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow

    since = today(s) - timedelta(days=365)
    items = {i.id: i for i in s.execute(select(MfgItemRow)).scalars()}
    sups = {x.id: x for x in s.execute(select(MfgSupplierRow)).scalars()}
    rows = list(s.execute(select(MfgItemSupplierRow).where(MfgItemSupplierRow.active.is_(True))).scalars())
    lcs = landed_of_rows(s, rows)
    trade = {x.item_id: x for x in s.execute(select(MfgItemTradeRow)).scalars()}
    from ..db_models_m2 import MfgPurchaseDocRow

    rec = s.execute(select(MfgInvTransactionRow.item_id, MfgPurchaseDocRow.supplier_id, MfgInvTransactionRow.qty,
                           MfgInvTransactionRow.unit_cost, MfgPurchaseLineRow.unit_price, MfgInvTransactionRow.txn_date,
                           MfgPurchaseScheduleRow.confirmed_date, MfgPurchaseScheduleRow.requested_date)
                    .join(MfgPurchaseScheduleRow, MfgPurchaseScheduleRow.id == MfgInvTransactionRow.schedule_id)
                    .join(MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id)
                    .join(MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id)
                    .where(MfgInvTransactionRow.txn_type == "po_receipt", MfgInvTransactionRow.txn_date >= since)
                    ).all()
    spend: dict[tuple[str, str], float] = defaultdict(float)
    otd: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for iid, sid, q, uc, up, d, cd, rd in rec:
        k = (iid, sid)
        spend[k] += float(q or 0) * float(uc if uc is not None else (up or 0))
        otd[k][1] += 1
        otd[k][0] += 1 if d <= (cd or rd) else 0
    n_by_item: dict[str, list[MfgItemSupplierRow]] = defaultdict(list)
    for r in rows:
        n_by_item[r.item_id].append(r)
    _country, ccy = _plant_country(s)
    out = []
    ms_fams = {m["family"] for m in tables["milestones"] if m.get("family")}
    dom = tables["settings"].get("domestic_country", "US")
    for r, lc in zip(rows, lcs):
        it = items.get(r.item_id)
        if it is None:
            continue
        tr = trade.get(r.item_id)
        coo = r.coo or (tr.coo if tr else None)
        o = otd.get((r.item_id, r.supplier_id))
        lead = r.lead_time_days if r.lead_time_days is not None else (sups[r.supplier_id].lead_time_days
                                                                      if r.supplier_id in sups else None)
        if lead is None:
            lead = it.lead_time_days
        duty = sum(d["amount"] or 0 for d in lc["duty"])
        row = {"node_owner_id": node, "item_id": it.id, "item_key": key_of(it), "part_number": it.part_number,
               "description": it.description, "family": it.family,
               "supplier_code": sups[r.supplier_id].code if r.supplier_id in sups else "",
               "supplier_name": sups[r.supplier_id].name if r.supplier_id in sups else "", "coo": coo,
               "spend_12m": round(spend.get((r.item_id, r.supplier_id), 0.0), 2), "currency": ccy,
               "otd_pct": round(o[0] / o[1] * 100, 1) if o and o[1] else None, "lead_days": lead,
               "duty_pct": round(duty / lc["customs_value"] * 100, 2) if lc["customs_value"] else None,
               "hts": r.hts_code or (tr.hts_code if tr else None), "landed": lc["total"]}
        peers = n_by_item[r.item_id]
        sc = RK.score(row, n_suppliers=len(peers), countries={(p.coo or (tr.coo if tr else None)) for p in peers},
                      country_risk=tables["risk"], domestic=dom, milestone_families=ms_fams)
        row.update(score=sc["score"], parts=sc["parts"], flags=sc["flags"], suggestions=[])
        out.append(row)
    return out


def risk(ctx: AppContext, a: Any, node: str | None, min_score: int) -> dict[str, Any]:
    from .network import org_nodes

    with read_tx(ctx) as s:
        kind = s.execute(select(MfgPlantRow.kind)).scalar() or "plant"
        if kind == "network":
            tables = network_tables(s, str(current_owner()))
            nodes = [n["owner_id"] for n in org_nodes(s) if not node or n["owner_id"] == node]
        else:
            tables = network_tables(s)
            nodes = [str(current_owner())]
    rows: list[dict[str, Any]] = []
    for n in nodes:
        with owner_scope(n), read_tx(ctx) as s:
            rows += _plant_risk_rows(s, n, tables)
    top = RK.top_spend(rows)
    for i, r in enumerate(rows):
        if r["score"] >= 50 and i in top:
            r["suggestions"] = RK.suggestions(r, rows)
    out = [{k: v for k, v in r.items() if k not in ("hts", "landed")} for r in rows if r["score"] >= min_score]
    out.sort(key=lambda r: (-r["score"], -r["spend_12m"], r["part_number"]))
    return {"items": out}


# ---------------------------------------------------------------- P5 MPS targets

def mps_targets(ctx: AppContext, family: str | None, from_: date | None, to: date | None) -> dict[str, Any]:
    from ..db_models_m2 import MfgInvTransactionRow

    with read_tx(ctx) as s:
        q = select(MfgMpsTargetRow)
        if family:
            q = q.where(MfgMpsTargetRow.family == family)
        if from_:
            q = q.where(MfgMpsTargetRow.month >= from_.replace(day=1))
        if to:
            q = q.where(MfgMpsTargetRow.month <= to)
        rows = list(s.execute(q.order_by(MfgMpsTargetRow.month, MfgMpsTargetRow.family)).scalars())
        actual: dict[tuple[str, date], float] = defaultdict(float)
        if rows:
            fam = dict(s.execute(select(MfgItemRow.id, MfgItemRow.family)).all())
            lo = min(r.month for r in rows)
            for iid, d, q2 in s.execute(select(MfgInvTransactionRow.item_id, MfgInvTransactionRow.txn_date,
                                               MfgInvTransactionRow.qty).where(
                    MfgInvTransactionRow.txn_type == "wo_receipt", MfgInvTransactionRow.txn_date >= lo)):
                if fam.get(iid):
                    actual[(fam[iid], d.replace(day=1))] += float(q2)
        return {"items": [{"id": r.id, "cycle_id": r.cycle_id, "cycle_number": r.cycle_number, "family": r.family,
                           "month": r.month, "qty_target": r.qty_target, "hours": r.hours,
                           "actual_qty": round(actual.get((r.family, r.month), 0.0), 6),
                           "attainment": round(actual.get((r.family, r.month), 0.0) / r.qty_target, 4)
                           if r.qty_target else None} for r in rows]}


__getattr__ = m9_examples.module_getattr(__name__)

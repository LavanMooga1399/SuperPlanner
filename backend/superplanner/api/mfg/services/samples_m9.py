"""Organisation sample `meddev_m9` (M9-DESIGN 12.1; `manage.py load-org-sample meddev_m9 --org <slug> --email
<org admin> --replace`). Fictional data only.

Nodes: `QC` Quebec City (CA, CAD; the `meddev_m8` sample), `US1` (US, USD; needles on flow lines NA-01 / NA-02,
cannula steel from KTUBE (US) and ATUBE (CN)), DC `DCUS` (US; customer orders for syringes and needles) and the
network workspace `NET`. Lanes QC -> DCUS road 3 d, US1 -> DCUS road 2 d, US1 -> QC road 4 d. Sourcing: DCUS
syringes from QC, DCUS needles from US1, QC needles 70 % US1 / 30 % external supplier NDLX. Trade: HTS on the items,
fictional tariffs (one `s301` CN layer, one `surtax` CA layer), 24 months of USD / CAD FX, country risk, milestone
`NDL-US-STEEL` (steel only, value basis, min 100 %, effective 2027-07-01); finished needle lots mix KTUBE and
ATUBE steel, so some miss. Then one published network run, the previous month's cycle published and this month's
cycle at `pre_sop` with a baseline, an expansion ("US1 line NA-03", STD26, capex 45 M USD) and a dual-source
scenario ("Dual-source cannula 60/40 KTUBE").

Sample shortcut (documented): the previous month's cycle is set to `approved` without signatures before it is
published, so the sample needs no enrolled signers; the current cycle stops before the signed approval.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from ...db.models import new_id, utcnow
from ...db.ownership import owner_scope, system_scope
from ...errors import ApiError

STEEL_PER_NEEDLE = 0.0003     # kg


class _Act:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.p = SimpleNamespace(user_id=user_id, roles=("plant_admin",), has=lambda _x: True)
        self.session_ref = None
        self.client_ip = None


def _bundle_us1(anchor: date) -> dict[str, Any]:
    from ....mfg.samples.common import Builder, op, shift
    from ....mfg.samples.common import line as bl

    days = ["mon", "tue", "wed", "thu", "fri"]
    b = Builder()
    b.plant("US plant 1 (sample)", utc_offset="-06:00", horizon=180, currency="USD")
    b.template("2X8", "Two shifts", [shift("A", days, "06:00", "14:00"), shift("B", days, "14:00", "22:00")])
    b.group("NA", "Needle assembly", kind="line")
    b.line("NA-01", "NA", "Needle line 1")
    b.line("NA-02", "NA", "Needle line 2")
    b.assign("2X8", "group", "NA")
    b.item("MDV-CAN-STL", "buy", "Cannula steel (kg)", uom="KG", family="CANSTEEL", lead_time_days=75,
           lot_controlled=True, standard_cost=12.0, min_order_qty=10.0)
    b.item("MDV-NDL-25", "make", "Hypodermic needle 25G", family="NEEDLE", lead_time_days=7, lot_controlled=True,
           standard_cost=0.06, order_multiple=10000.0)
    b.item("MDV-NDL-23", "make", "Hypodermic needle 23G", family="NEEDLE", lead_time_days=7, lot_controlled=True,
           standard_cost=0.06, order_multiple=10000.0)
    for pn in ("MDV-NDL-25", "MDV-NDL-23"):
        b.bom(pn, [bl(10, "MDV-CAN-STL", STEEL_PER_NEEDLE)])
        b.routing(pn, [op(10, "Assemble", "NA", setup_minutes=0, run_minutes=0.0075)])
    bd = b.canonical()
    bd["locations"] = [{"code": "STORES", "name": "Stores", "kind": "stores"},
                       {"code": "FG", "name": "Finished goods", "kind": "stores", "receipt_default": True}]
    bd["suppliers"] = [{"code": "KTUBE", "name": "K-Tube (fictional)", "currency": "USD", "lead_time_days": 30},
                       {"code": "ATUBE", "name": "A-Tube (fictional)", "currency": "USD", "lead_time_days": 75}]
    bd["item_suppliers"] = [
        {"part_number": "MDV-CAN-STL", "supplier_code": "KTUBE", "unit_price": 14.0, "currency": "USD",
         "preferred": True},
        {"part_number": "MDV-CAN-STL", "supplier_code": "ATUBE", "unit_price": 9.5, "currency": "USD"}]
    return bd


def _bundle_dc(anchor: date, rng: random.Random) -> dict[str, Any]:
    from ....mfg.samples.common import Builder

    b = Builder()
    b.plant("DC United States (sample)", utc_offset="-06:00", horizon=180, currency="USD")
    for pn, fam, d in (("MDV-SYR-03", "SYRINGE", "Syringe 3 mL"), ("MDV-SYR-10", "SYRINGE", "Syringe 10 mL"),
                       ("MDV-NDL-25", "NEEDLE", "Hypodermic needle 25G")):
        b.item(pn, "buy", d, family=fam, lead_time_days=7, safety_stock=20000.0 if fam == "SYRINGE" else 50000.0)
    bd = b.canonical()
    bd["locations"] = [{"code": "FG", "name": "Finished goods", "kind": "stores", "receipt_default": True}]
    orders, lines = [], []
    for o in range(16):
        no = f"SO-DC-{o + 1:04d}"
        orders.append({"number": no, "demand_type": "customer", "customer": f"Hospital group {o % 5 + 1}",
                       "program": None, "priority": 3 if o % 4 else 2, "status": "open"})
        for j, pn in enumerate(("MDV-SYR-03", "MDV-SYR-10", "MDV-NDL-25")):
            lines.append({"number": no, "line_no": 10 * (j + 1), "part_number": pn,
                          "qty": float(rng.choice((10000, 20000, 40000)) * (5 if pn == "MDV-NDL-25" else 1)),
                          "due_date": anchor + timedelta(days=5 + 4 * o)})
    bd["demand_orders"], bd["demand_lines"] = orders, lines
    return bd


def _apply(db: Any, owner: str, bd: dict[str, Any], anchor: date) -> None:
    from ....mfg.dataset import MfgDataset
    from ....mfg.io.plan import ImportOptions, plan_import
    from ....mfg.model import PlantRecord
    from .. import repo, writer
    from .samples import delete_all

    plan = plan_import(bd, MfgDataset(plant=PlantRecord()), ImportOptions(release=True, today=anchor),
                       id_factory=new_id)
    if not plan.ok:
        raise ValueError(f"meddev_m9 bundle has errors: {plan.row_errors[:5]}")
    with owner_scope(owner), db.write() as s:
        plant = repo.lock_plant(s)
        kind, country = plant.kind, (plant.attributes or {}).get("country")
        delete_all(s)
        plant = repo.lock_plant(s)
        writer.apply(s, plan, plant, stock_date=anchor - timedelta(days=1))
        plant = repo.lock_plant(s)
        plant.kind = kind
        plant.attributes = {**(plant.attributes or {}), "country": country}


def _us1_history(db: Any, owner: str, anchor: date) -> None:
    """Steel lots of both suppliers (COO captured) and needle WOs consuming them: N25-1 all US steel, N25-2 and
    N25-3 a mix (below the 100 % US-steel milestone)."""
    from ....mfg.model_m2 import (ReceiptMiscLine, ReceiptMiscPosting, WoIssueLine, WoIssuePosting, WoReceiptLine,
                                  WoReceiptPosting, WorkOrderInput)
    from .. import repo
    from ..db_models import MfgItemRow, MfgLineRow
    from ..db_models_m2 import MfgLocationRow, MfgLotRow, MfgWoComponentRow
    from ..db_models_m8 import MfgLineRateRow
    from .inventory import post_in_session
    from .workorders import new_wo

    with owner_scope(owner), db.write() as s:
        now = utcnow()
        for ln in s.execute(select(MfgLineRow)).scalars():
            ln.planning, ln.oee = "flow", 0.85
            s.add(MfgLineRateRow(id=new_id("lrt_"), line_id=ln.id, item_id=None, item_family="NEEDLE",
                                 units_per_hour=9000.0, oee=None, row_version=1, created_at=now, updated_at=now))
        locs = {x.code: x for x in s.execute(select(MfgLocationRow)).scalars()}
        it = {x.part_number: x for x in s.execute(select(MfgItemRow)).scalars()}
        steel = it["MDV-CAN-STL"]
        for code, coo, d in (("KT-2611-1", "US", 40), ("AT-2611-1", "CN", 38), ("KT-2611-2", "US", 20)):
            post_in_session(s, ReceiptMiscPosting.model_construct(
                type="receipt_misc", txn_date=None, note="Steel receipt (sample)", reason_code="SAMPLE",
                lines=[ReceiptMiscLine.model_construct(item_id=steel.id, location_id=locs["STORES"].id, qty=20.0,
                                                       lot_code=code, expires_on=None, supplier_lot=code,
                                                       unit_cost=None)]),
                system=True, txn_date=anchor - timedelta(days=d), note_audit=False)
            lot = s.execute(select(MfgLotRow).where(MfgLotRow.lot_code == code)).scalars().one()
            lot.coo, lot.coo_source, lot.unit_value = coo, "receipt", 14.0 if coo == "US" else 9.5
        ds = repo.load_dataset(s)
        for k, (mix, d) in enumerate((({"KT-2611-1": 3.0}, 30), ({"KT-2611-1": 1.5, "AT-2611-1": 1.5}, 20),
                                      ({"AT-2611-1": 2.0, "KT-2611-2": 1.0}, 10)), start=1):
            qty = 10000.0
            w, _x = new_wo(s, ds, WorkOrderInput(number=f"WO-NDL-{k:03d}", item_id=it["MDV-NDL-25"].id, qty=qty,
                                                 due_date=anchor - timedelta(days=d - 2),
                                                 start_date=anchor - timedelta(days=d), priority=3,
                                                 note="Sample history"))
            w.status, w.released_at = "released", now
            s.flush()
            comp = s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == w.id)).scalars().one()
            for lot, q in mix.items():
                post_in_session(s, WoIssuePosting.model_construct(
                    type="wo_issue", txn_date=None, note="Issue (sample)", reason_code=None,
                    lines=[WoIssueLine.model_construct(wo_component_id=comp.id, location_id=locs["STORES"].id, qty=q,
                                                       lot_code=lot, over_issue=True)]),
                    system=True, txn_date=anchor - timedelta(days=d), note_audit=False)
            post_in_session(s, WoReceiptPosting.model_construct(
                type="wo_receipt", txn_date=None, note="Receipt (sample)", reason_code=None,
                lines=[WoReceiptLine.model_construct(wo_id=w.id, location_id=locs["FG"].id, qty=qty, scrap_qty=0,
                                                     lot_code=f"N25-{k}", expires_on=None)]),
                system=True, txn_date=anchor - timedelta(days=d - 2), note_audit=False)


def _trade(db: Any, owners: dict[str, str], net: str, anchor: date) -> None:
    from ..db_models import MfgItemRow
    from ..db_models_m2 import MfgItemSupplierRow, MfgSupplierRow
    from ..db_models_m9 import (MfgCountryRiskRow, MfgFxRateRow, MfgItemTradeRow, MfgTariffMilestoneRow,
                                MfgTariffRateRow)
    from ....mfg.sop.demand import add_months

    hts = {"SYRINGE": "901831", "NEEDLE": "901832", "CANNULA": "901832", "CANSTEEL": "730411"}
    now = utcnow()
    for code, owner in owners.items():
        with owner_scope(owner), db.write() as s:
            for it in s.execute(select(MfgItemRow)).scalars():
                h = hts.get(it.family or "")
                if h is None:
                    continue
                s.add(MfgItemTradeRow(id=new_id("itr_"), item_id=it.id, hts_code=h,
                                      coo=None if it.make_buy == "buy" else None,
                                      material_class="steel" if it.family == "CANSTEEL" else None,
                                      unit_weight_kg=1.0 if it.family == "CANSTEEL" else 0.0012, row_version=1,
                                      created_at=now, updated_at=now))
            if code == "US1":
                sups = {x.code: x.id for x in s.execute(select(MfgSupplierRow)).scalars()}
                for r in s.execute(select(MfgItemSupplierRow)).scalars():
                    if r.supplier_id == sups.get("KTUBE"):
                        r.coo, r.hts_code, r.freight_per_unit, r.cap_per_month = "US", "730411", 0.05, None
                    elif r.supplier_id == sups.get("ATUBE"):
                        r.coo, r.hts_code, r.freight_per_unit, r.cap_per_month = "CN", "730411", 0.4, 400.0
    with owner_scope(net), db.write() as s:
        y0 = date(2020, 1, 1)
        rows = [("US", "9018", "*", "mfn", 0.0), ("US", "7304", "*", "mfn", 0.0), ("US", "7304", "CN", "s301", 25.0),
                ("CA", "9018", "*", "mfn", 0.0), ("CA", "9018", "CN", "surtax", 25.0)]
        for dest, pre, coo, layer, rate in rows:
            s.add(MfgTariffRateRow(id=new_id("trf_"), dest_country=dest, hts_prefix=pre, coo=coo, layer=layer,
                                   rate_pct=rate, per_unit=None, per_unit_currency=None, valid_from=y0, valid_to=None,
                                   note="Fictional"))
        m0 = add_months(anchor.replace(day=1), -12)
        for k in range(24):
            s.add(MfgFxRateRow(id=new_id("fxr_"), from_ccy="USD", to_ccy="CAD", month=add_months(m0, k),
                               rate=round(1.36 + 0.004 * (k % 6), 4), source="sample"))
        for c, sc in (("CN", 20), ("US", 0), ("CA", 0), ("JP", 5)):
            s.add(MfgCountryRiskRow(id=new_id("ckr_"), country=c, score=sc, note="Illustrative"))
        s.add(MfgTariffMilestoneRow(id=new_id("tms_"), code="NDL-US-STEEL", name="Needles: US steel",
                                    dest_country="US", family="NEEDLE", hts_prefix=None,
                                    rule={"domestic_country": "US", "basis": "value", "material_classes": ["steel"],
                                          "include_conversion": False, "min_pct": 100.0},
                                    effective=date(2027, 7, 1), note="Illustrative", row_version=1, created_at=now,
                                    updated_at=now))


def load_org_sample(ctx: Any, admin_id: str, org_slug: str, anchor: date | None = None) -> dict[str, Any]:
    from ....mfg.network.model import NetParams
    from ....mfg.sop.model import CycleInput, ScenarioInput
    from ....orgs.model import NetworkIn, OrgPlantIn
    from ....orgs.service import create_network, create_plant
    from ..db_models import MfgPlantRow
    from ..db_models_m5 import OrgPlantRow, OrgRow
    from ..db_models_m9 import (MfgNetLaneRow, MfgNetRunRow, MfgNetSourcingRow, MfgSopCycleRow,
                                MfgSopScenarioRow)
    from . import network as NET
    from . import samples
    from . import sop as SOP
    from .m8common import next_number

    db = ctx.db
    anchor = anchor or date.today()
    with system_scope(), db.read() as s:
        org = s.execute(select(OrgRow.id).where(OrgRow.slug == org_slug)).scalar()
        if org is None:
            raise ApiError(404, "NOT_FOUND", "Organisation not found.", {"slug": org_slug})
        have = {p.code: p.plant_owner_id for p in s.execute(select(OrgPlantRow).where(
            OrgPlantRow.org_id == org)).scalars()}
        for o in have.values():
            if s.execute(select(MfgPlantRow.part11_mode).where(MfgPlantRow.owner_id == o)).scalar():
                raise ApiError(409, "PART11_DELETE_NOT_ALLOWED", "A plant of the organisation runs in Part 11 mode.",
                               {})
    for code, kind, country, ccy, tz in (("QC", "plant", "CA", "CAD", "America/Toronto"),
                                         ("US1", "plant", "US", "USD", "America/Chicago"),
                                         ("DCUS", "dc", "US", "USD", "America/Chicago")):
        if code not in have:
            have[code] = create_plant(ctx, admin_id, org, OrgPlantIn(code=code, name={
                "QC": "Quebec City", "US1": "US plant 1", "DCUS": "DC United States"}[code], kind=kind,
                country=country, currency=ccy, time_zone=tz))["plant_owner_id"]
    net = have.get("NET") or create_network(ctx, admin_id, org, NetworkIn(name="Network"))["owner_id"]
    a = _Act(admin_id)
    # nodes
    with owner_scope(have["QC"]):
        samples.load(ctx, "meddev_m8", True)
    with owner_scope(have["QC"]), db.write() as s:
        p = s.execute(select(MfgPlantRow)).scalars().first()
        p.kind, p.attributes = "plant", {**(p.attributes or {}), "country": "CA"}
    _apply(db, have["US1"], _bundle_us1(anchor), anchor)
    _us1_history(db, have["US1"], anchor)
    _apply(db, have["DCUS"], _bundle_dc(anchor, random.Random(9)), anchor)
    nodes = {k: have[k] for k in ("QC", "US1", "DCUS")}
    _trade(db, nodes, net, anchor)
    # network topology
    now = utcnow()
    with owner_scope(net), db.write() as s:
        for model in (MfgNetSourcingRow, MfgNetLaneRow):
            for r in s.execute(select(model)).scalars():
                s.delete(r)
        s.flush()
        lanes = {}
        for src, dst, days in (("QC", "DCUS", 3), ("US1", "DCUS", 2), ("US1", "QC", 4)):
            ln = MfgNetLaneRow(id=new_id("nln_"), from_owner_id=have[src], to_owner_id=have[dst], mode="road",
                               transit_days=days, freight_per_unit=0.002, freight_per_kg=None, currency="USD",
                               active=True, row_version=1, created_at=now, updated_at=now)
            s.add(ln)
            lanes[(src, dst)] = ln.id
        for dest, fam, kind, src, sup, prio, quota in (("DCUS", "SYRINGE", "plant", "QC", None, 1, None),
                                                       ("DCUS", "NEEDLE", "plant", "US1", None, 1, None),
                                                       ("QC", "NEEDLE", "plant", "US1", None, 1, 70.0),
                                                       ("QC", "NEEDLE", "supplier", None, "NDLX", 2, 30.0)):
            s.add(MfgNetSourcingRow(id=new_id("nsg_"), dest_owner_id=have[dest], item_key=None, family=fam,
                                    source_kind=kind, source_owner_id=have[src] if src else None, supplier_code=sup,
                                    priority=prio, quota_pct=quota,
                                    lane_id=lanes.get((src, dest)) if src else None, valid_from=None, valid_to=None,
                                    active=True, row_version=1, created_at=now, updated_at=now))
    out: dict[str, Any] = {"org": org_slug, "nodes": {k: v for k, v in have.items()}}
    # network run (synchronous) + publish
    with owner_scope(net):
        with db.write() as s:
            st = NET.net_settings(s)
            r = MfgNetRunRow(id=new_id("nrn_"), number=next_number(s, "NR", MfgNetRunRow), label="Sample",
                             params=NetParams().model_dump(mode="json", exclude={"label"}) | {"_settings": st},
                             status="queued", as_of=SOP.today(s), input_hash=None, summary=None, validator=None,
                             explanations=None, published=False, published_at=None, published_by=None,
                             publish_result=None, error=None, actor_id=admin_id, created_at=utcnow(),
                             started_at=None, finished_at=None, duration_ms=None)
            s.add(r)
            rid = r.id
        NET.compute(ctx, rid)
        run = NET.get_run(ctx, rid)
        out["net_run"] = {"number": run["number"], "status": run["status"],
                          "validator_ok": (run["validator"] or {}).get("ok")}
        if run["status"] == "completed" and (run["validator"] or {}).get("ok"):
            out["net_publish"] = NET.publish(ctx, a, rid)["publish_result"]
        # S&OP: previous month published, this month at pre-S&OP with three scenarios
        cur = anchor.replace(day=1)
        prev = date(cur.year - (cur.month == 1), (cur.month - 2) % 12 + 1, 1)
        with db.write() as s:
            for c in s.execute(select(MfgSopCycleRow).where(MfgSopCycleRow.period.in_([prev, cur]))).scalars():
                c.status = "cancelled"

        def scenario(cycle_id: str, name: str, changes: list[dict[str, Any]], note: str = "") -> str:
            sc = SOP.create_scenario(ctx, a, ScenarioInput.model_validate({"cycle_id": cycle_id, "name": name,
                                                                          "changes": changes, "capex_note": note}))
            SOP.compute(ctx, sc["id"])
            return sc["id"]

        c1 = SOP.create_cycle(ctx, a, CycleInput(period=prev, horizon_months=18))
        b1 = scenario(c1["id"], "Baseline", [])
        with db.write() as s:
            c = s.get(MfgSopCycleRow, c1["id"])
            c.status, c.recommended_scenario_id, c.approved_scenario_id = "approved", b1, b1
            c.recommend_note = "Sample shortcut: approved without signatures"
        out["published_cycle"] = SOP.publish(ctx, a, c1["id"])["number"]
        c2 = SOP.create_cycle(ctx, a, CycleInput(period=cur, horizon_months=18))
        b2 = scenario(c2["id"], "Baseline", [])
        for _k in range(3):
            c2 = SOP.advance(ctx, a, c2["id"], SimpleNamespace(note=""), None)
        exp = scenario(c2["id"], "US1 line NA-03", [{
            "kind": "add_line", "id": "na03", "label": "US1 line NA-03", "node": "US1", "cap_group": "NA",
            "name": "NA-03", "start": "2027-03-01", "hours_per_week": 80, "uph_by_family": {"NEEDLE": 9000},
            "oee": 0.85, "curve": "STD26", "capex": 45_000_000, "capex_currency": "USD",
            "fixed_cost_per_month": 60_000}], "45 M USD, 2027 budget")
        dual = scenario(c2["id"], "Dual-source cannula 60/40 KTUBE", [{
            "kind": "supplier_allocation", "id": "dual", "label": "Dual-source cannula 60/40 KTUBE", "node": "US1",
            "family": "CANSTEEL", "suppliers": [{"code": "KTUBE", "min_share": 0.6, "max_share": 0.6},
                                                {"code": "ATUBE", "min_share": 0.4, "max_share": 0.4}]}])
        with db.read() as s:
            out["scenarios"] = {x.name: x.status for x in s.execute(select(MfgSopScenarioRow).where(
                MfgSopScenarioRow.id.in_([b2, exp, dual]))).scalars()}
        out["cycle"] = SOP.get_cycle(ctx, c2["id"])["status"]
    return out

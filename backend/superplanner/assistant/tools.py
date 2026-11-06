"""Read-only, permission-checked assistant tools (M6-DESIGN 1.3).

Each tool wraps existing services and runs with the asking user's owner / actor binding (M2 10: the ownership filter
serves only this plant's rows). The offered list is filtered by the user's permissions; every run re-resolves the
user's permissions in the plant (a role removed mid-turn takes effect at once) and refuses tools that were not
offered. Results are trimmed: at most 50 rows per list, 20,000 characters, free-text fields cut to 200 characters
and listed under `untrusted_text`, personal fields removed, prices / costs removed unless the tool's name says cost.
Record references are issued by the server (`RefRegistry`) from server-built links.

The only tools that start anything are `run_whatif_mrp` / `run_whatif_aps`: offered only when the conversation's
what-if switch is on (and the plant allows it), they force the run kind `what_if` (never live, never publishable or
convertible). `draft_action` only builds a draft card.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from ..api.errors import ApiError
from ..intake.ai.json_schema import strict_json_schema
from ..mfg.model import MfgModel
from . import drafts as D
from .citations import RefRegistry, safe_link, type_of_link

MAX_ROWS = 50
MAX_CHARS = 20_000
MAX_TEXT = 200
UNTRUSTED_KEYS = frozenset({"description", "name", "note", "notes", "reason", "customer", "title", "comment",
                            "body", "handling_note", "message", "summary", "rejected_reason", "label",
                            "supplier_lot", "external_ref", "program"})
PERSONAL_KEYS = frozenset({"reported_by", "closed_by", "acknowledged_by", "actor", "actor_id", "approved_by",
                           "submitted_by", "rejected_by", "created_by", "email", "published_by", "handled_by",
                           "invited_by", "operator", "operators", "operator_id", "user", "users", "user_id",
                           "display_name", "phone"})
COST_KEY = re.compile(r"(price|cost|amount|value)", re.IGNORECASE)
LABEL_KEYS = ("label", "number", "part_number", "code", "serial", "lot_code", "name")


@dataclass
class ToolContext:
    ctx: Any                                    # AppContext
    user_id: str
    owner_id: str
    permissions: frozenset[str]
    conversation_id: str
    allow_whatif: bool
    refs: RefRegistry
    drafts: list[dict[str, Any]] = field(default_factory=list)
    whatif_runs: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: tests: the permission re-check (default: the membership in the database)
    reload_permissions: Callable[["ToolContext"], frozenset[str]] | None = None


@dataclass
class ToolResult:
    data: Any
    refs: list[tuple[str, str, str, str]] = field(default_factory=list)   # extra (type, id, label, link)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    permissions: tuple[str, ...]                # any of
    run: Callable[[ToolContext, Any], ToolResult]
    whatif: bool = False
    cost: bool = False

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": strict_json_schema(self.args)}

    def allowed(self, perms: frozenset[str], allow_whatif: bool) -> bool:
        if self.whatif and not allow_whatif:
            return False
        return any(p in perms for p in self.permissions)


# ---------------------------------------------------------------- argument models (strict schemas)

class NoArgs(MfgModel):
    pass


class FindArgs(MfgModel):
    query: str = Field(description="part number, order / document number, code or name (part of it is enough)",
                       max_length=100)
    kinds: list[Literal["item", "demand_order", "work_order", "purchase_order", "purchase_request", "supplier",
                        "line", "lot", "serial"]] | None = None


class DemandArgs(MfgModel):
    order: str = Field(description="demand order number (e.g. DO-KV-003) or id; '/10' suffix = line 10",
                       max_length=64)
    line: int | None = Field(default=None, description="line number")


class ExceptionArgs(MfgModel):
    code: str | None = Field(default=None, max_length=40)
    item: str | None = Field(default=None, max_length=64, description="part number or id")
    demand: str | None = Field(default=None, max_length=64, description="demand order number or id")


class ItemPlanArgs(MfgModel):
    item: str = Field(max_length=64, description="part number or id")
    bucket: Literal["day", "week", "month"] = "week"


class PeggingArgs(MfgModel):
    item: str = Field(max_length=64, description="part number or id")
    node: int = Field(default=0, ge=0, description="node number from mrp_item_plan (0 = first requirement)")
    direction: Literal["up", "down"] = "up"


class OrderArgs(MfgModel):
    order: str = Field(max_length=64, description="work order number, planned order (P-n) or demand order number")


class LineArgs(MfgModel):
    line: str | None = Field(default=None, max_length=64, description="line code or id (none = all lines)")


class KpiArgs(MfgModel):
    period: Literal["7d", "4w", "13w"] = "4w"
    dim: Literal["plant", "group", "line"] = "plant"
    dim_id: str | None = Field(default=None, max_length=64)


class SupplierArgs(MfgModel):
    supplier: str = Field(max_length=64, description="supplier code or id")


class TraceArgs(MfgModel):
    kind: Literal["lot", "serial", "wo"]
    id: str = Field(max_length=64, description="record id (use find_records first)")
    direction: Literal["backward", "forward"] = "backward"


class RecallSourceArg(MfgModel):
    kind: Literal["lot", "serial", "wo"]
    id: str = Field(max_length=64)


class RecallArgs(MfgModel):
    sources: list[RecallSourceArg] = Field(min_length=1, max_length=10)


class EcoArgs(MfgModel):
    eco: str = Field(max_length=64, description="change request number or id")


class StockArgs(MfgModel):
    item: str = Field(max_length=64, description="part number or id")


class ExtraDemandArg(MfgModel):
    item: str = Field(max_length=64)
    qty: float = Field(gt=0, le=1_000_000)
    due_date: date


class SupplyDateArg(MfgModel):
    purchase_order: str = Field(max_length=64, description="PO number or id")
    new_date: date


class WhatIfMrpArgs(MfgModel):
    extra_demand: list[ExtraDemandArg] | None = None
    supply_delays: list[SupplyDateArg] | None = None
    label: str | None = Field(default=None, max_length=60)


class LineBreakdownArg(MfgModel):
    line_id: str = Field(max_length=64)
    start: datetime
    end: datetime


class WhatIfApsArgs(MfgModel):
    open_shifts: list[D.OpenShiftArg] | None = Field(default=None, description="optional shift windows to open "
                                                     "(from overtime_options)")
    overtime: Literal["off", "suggest", "allow"] | None = None
    line_breakdowns: list[LineBreakdownArg] | None = None
    label: str | None = Field(default=None, max_length=60)


class DraftActionArgs(MfgModel):
    kind: Literal["expedite_po_schedule", "release_planned_orders", "open_overtime", "schedule_edit", "create_pr",
                  "raise_priority", "whatif_run"]
    args: D.DraftArgs


# ---------------------------------------------------------------- helpers

def _is_id(v: str) -> bool:
    return bool(re.fullmatch(r"[a-z]{3}_[0-9a-f]{32}", v or ""))


def _latest_mrp(tctx: ToolContext) -> str:
    from sqlalchemy import select

    from ..api.mfg.db_models_m2 import MfgMrpRunRow

    with tctx.ctx.db.read() as s:
        rid = s.execute(select(MfgMrpRunRow.id).where(MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed")
                        .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalar()
    if rid is None:
        raise ApiError(404, "MRP_NO_RUN", "There is no completed live MRP run.", {})
    return str(rid)


def _published(tctx: ToolContext) -> str:
    from sqlalchemy import select

    from ..api.mfg.db_models_m3 import MfgApsRunRow

    with tctx.ctx.db.read() as s:
        rid = s.execute(select(MfgApsRunRow.id).where(MfgApsRunRow.is_published.is_(True)).limit(1)).scalar()
    if rid is None:
        raise ApiError(404, "APS_NO_PUBLISHED_RUN", "There is no published schedule.", {})
    return str(rid)


def _item_id(tctx: ToolContext, ref: str) -> str:
    if _is_id(ref):
        return ref
    from ..api.mfg.services import items

    hits = items.list_items(tctx.ctx, q=ref, make_buy=None, family=None, active=None, has_bom=None,
                            has_routing=None, sort="part_number", limit=20, offset=0)["items"]
    exact = [x for x in hits if x["part_number"].lower() == ref.lower()]
    if len(exact) == 1 or len(hits) == 1:
        return (exact or hits)[0]["id"]
    raise ApiError(404, "NOT_FOUND", f"No single item matches {ref!r}.", {"candidates": [x["part_number"]
                                                                                        for x in hits[:10]]})


def _demand_order(tctx: ToolContext, ref: str) -> dict[str, Any]:
    from ..api.mfg.services import demand

    if _is_id(ref):
        return demand.get_order(tctx.ctx, ref)
    hits = demand.list_orders(tctx.ctx, status=None, demand_type=None, program=None, item_id=None, due_from=None,
                              due_to=None, late_only=False, q=ref, limit=20, offset=0)["items"]
    exact = [x for x in hits if x["number"].lower() == ref.lower()]
    if len(exact) == 1 or len(hits) == 1:
        return demand.get_order(tctx.ctx, (exact or hits)[0]["id"])
    raise ApiError(404, "NOT_FOUND", f"No single demand order matches {ref!r}.",
                   {"candidates": [x["number"] for x in hits[:10]]})


def _page(d: Any) -> list[Any]:
    return list(d.get("items") or []) if isinstance(d, dict) else list(d or [])


# ---------------------------------------------------------------- tool bodies

def t_find(tctx: ToolContext, a: FindArgs) -> ToolResult:
    from ..api.mfg.services import (demand, inventory, items, plant, purchasing, serials, suppliers, workorders)

    q = a.query.strip()
    kinds = set(a.kinds or ["item", "demand_order", "work_order", "purchase_order", "purchase_request", "supplier",
                            "line", "lot", "serial"])
    ctx = tctx.ctx
    out: dict[str, Any] = {}
    refs: list[tuple[str, str, str, str]] = []
    if "item" in kinds:
        rows = items.list_items(ctx, q=q, make_buy=None, family=None, active=None, has_bom=None, has_routing=None,
                                sort="part_number", limit=10, offset=0)["items"]
        out["items"] = [{"id": x["id"], "part_number": x["part_number"], "description": x.get("description"),
                         "make_buy": x.get("make_buy")} for x in rows]
        refs += [("item", x["id"], x["part_number"], f"/mfg/items/{x['id']}") for x in rows]
    if "demand_order" in kinds:
        out["demand_orders"] = _page(demand.list_orders(ctx, status=None, demand_type=None, program=None, item_id=None,
                                                        due_from=None, due_to=None, late_only=False, q=q, limit=10,
                                                        offset=0))
        refs += [("demand_order", x["id"], x["number"], f"/mfg/demand/{x['id']}") for x in out["demand_orders"]]
    if "work_order" in kinds:
        out["work_orders"] = _page(workorders.list_wos(ctx, status=None, item_id=None, q=q, start_from=None,
                                                       start_to=None, source=None, sort="number", limit=10, offset=0))
    for dt, key in (("po", "purchase_order"), ("pr", "purchase_request")):
        if key in kinds:
            out[key + "s"] = _page(purchasing.list_docs(ctx, dt, status=None, supplier_id=None, item_id=None,
                                                        overdue=None, q=q, source=None, sort="number", limit=10,
                                                        offset=0))
    if "supplier" in kinds:
        out["suppliers"] = _page(suppliers.list_suppliers(ctx, q, None))[:10]
        refs += [("supplier", x["id"], x["code"], f"/mfg/suppliers/{x['id']}") for x in out["suppliers"]]
    if "line" in kinds:
        out["lines"] = [{"id": x["id"], "code": x["code"], "name": x.get("name")}
                        for x in _page(plant.list_lines(ctx, None, q, None))[:10]]
        refs += [("line", x["id"], x["code"], f"/mfg/floor?line={x['id']}") for x in out["lines"]]
    if "lot" in kinds:
        out["lots"] = _page(inventory.list_lots(ctx, item_id=None, q=q, expiring_before=None, hold=None, limit=10,
                                                offset=0))
    if "serial" in kinds:
        out["serials"] = _page(serials.list_serials(ctx, item_id=None, q=q, status=None, wo_id=None, limit=10,
                                                    offset=0))
    return ToolResult({k: v for k, v in out.items() if v}, refs)


def t_demand_status(tctx: ToolContext, a: DemandArgs) -> ToolResult:
    from ..api.mfg.services import aps, mrp

    ref, line = a.order, a.line
    if "/" in ref and line is None:
        ref, _, ln = ref.partition("/")
        line = int(ln) if ln.isdigit() else None
    order = _demand_order(tctx, ref)
    lines = [x for x in order.get("lines") or [] if line is None or x["line_no"] == line]
    out: dict[str, Any] = {"order": {k: order.get(k) for k in ("id", "number", "status", "priority", "customer",
                                                               "program", "demand_type")},
                           "lines": [{k: x.get(k) for k in ("id", "line_no", "item", "qty", "due_date", "open_qty",
                                                            "priority", "projection")} for x in lines]}
    refs = [("demand_order", order["id"], order["number"], f"/mfg/demand/{order['id']}")]
    refs += [("demand_line", x["id"], f"{order['number']}/{x['line_no']}", f"/mfg/demand/{order['id']}?line={x['id']}")
             for x in lines]
    try:
        run = _latest_mrp(tctx)
        rows = _page(mrp.list_demand(tctx.ctx, run, status=None, program=None, order_id=order["id"],
                                     late_only=False, sort="due_date", limit=50, offset=0))
        sel = [r for r in rows if line is None or r.get("line_no") == line]
        out["mrp"] = {"run_id": run, "lines": sel}
    except ApiError as exc:
        out["mrp"] = {"error": exc.code}
    try:
        prun = _published(tctx)
        dem = aps.demand(tctx.ctx, prun, late_only=False, program=None)
        out["schedule"] = {"run_id": prun, "lines": [d for d in dem["items"]
                                                     if d.get("order_number") == order["number"]
                                                     or d.get("order_id") == order["id"]
                                                     or (d.get("order") or {}).get("id") == order["id"]][:20]}
    except ApiError as exc:
        out["schedule"] = {"error": exc.code}
    return ToolResult(out, refs)


def t_mrp_exceptions(tctx: ToolContext, a: ExceptionArgs) -> ToolResult:
    from ..api.mfg.services import mrp

    run = _latest_mrp(tctx)
    item_id = _item_id(tctx, a.item) if a.item else None
    dl = None
    if a.demand:
        o = _demand_order(tctx, a.demand.partition("/")[0])
        dl = None if "/" not in a.demand else next((x["id"] for x in o["lines"]
                                                    if str(x["line_no"]) == a.demand.partition("/")[2]), None)
    out = mrp.list_exceptions(tctx.ctx, run, code=[a.code] if a.code else None, severity=None, item_id=item_id,
                              demand_line_id=dl, q=None, limit=MAX_ROWS, offset=0)
    return ToolResult({"run_id": run, **out})


def t_mrp_item_plan(tctx: ToolContext, a: ItemPlanArgs) -> ToolResult:
    from ..api.mfg.services import mrp

    run = _latest_mrp(tctx)
    iid = _item_id(tctx, a.item)
    out = mrp.item_plan(tctx.ctx, run, iid, a.bucket, None, None)
    if isinstance(out, dict):
        for k in ("timeline", "events", "nodes"):
            if isinstance(out.get(k), list) and len(out[k]) > 20:
                out[k] = out[k][:20]
                out[f"{k}_truncated"] = True
    return ToolResult({"run_id": run, **out}, [("mrp_item", iid, a.item, f"/mfg/mrp/runs/{run}/items/{iid}")])


def t_mrp_pegging(tctx: ToolContext, a: PeggingArgs) -> ToolResult:
    from ..api.mfg.services import mrp

    run = _latest_mrp(tctx)
    out = mrp.pegging(tctx.ctx, run, _item_id(tctx, a.item), a.node, "requirement", a.direction, 6)
    return ToolResult({"run_id": run, **out})


def t_schedule_order(tctx: ToolContext, a: OrderArgs) -> ToolResult:
    from ..api.mfg.services import aps

    run = _published(tctx)
    orders = aps.orders(tctx.ctx, run, late_only=False, order_type=None, q=a.order, sort="-late_minutes", limit=5,
                        offset=0)
    ops: list[Any] = []
    for o in _page(orders)[:2]:
        oid = o.get("id") or o.get("order_id")
        if oid:
            ops += _page(aps.operations(tctx.ctx, run, line_id=None, group_id=None, order_id=oid, status=None,
                                        late_only=False, frozen=None, frm=None, to=None, sort="start", limit=30,
                                        offset=0))
    return ToolResult({"run_id": run, "orders": _page(orders), "operations": ops},
                      [("aps_run", run, "published schedule", f"/mfg/schedule/runs/{run}")])


def t_bottlenecks(tctx: ToolContext, a: NoArgs) -> ToolResult:
    from ..api.mfg.services import aps

    run = _published(tctx)
    out = aps.bottlenecks(tctx.ctx, run)
    refs = [("aps_bottleneck", b["group_id"], f"stage {(b.get('group') or {}).get('code', '')}",
             f"/mfg/schedule/runs/{run}?view=load&group={b['group_id']}") for b in out["items"][:20]
            if b.get("group_id")]
    return ToolResult({"run_id": run, **out}, refs)


def t_overtime(tctx: ToolContext, a: NoArgs) -> ToolResult:
    from ..api.mfg.services import aps

    run = _published(tctx)
    out = aps.overtime(tctx.ctx, run, status="suggested")
    refs = []
    for x in out["items"][:20]:
        key = f"{x.get('line_id')}:{x.get('start') or x.get('start_at')}"
        refs.append(("overtime_suggestion", hashlib.sha1(key.encode()).hexdigest()[:24],
                     f"overtime {(x.get('line') or {}).get('code', '')} {x.get('start') or x.get('start_at')}",
                     f"/mfg/schedule/runs/{run}?view=overtime"))
    return ToolResult({"run_id": run, **out}, refs)


def t_line_status(tctx: ToolContext, a: LineArgs) -> ToolResult:
    from ..api.mfg.services import downtime, plant, replan

    lines = _page(plant.list_lines(tctx.ctx, None, None, True))
    if a.line:
        lines = [x for x in lines if a.line in (x["id"], x["code"])]
    ids = {x["id"] for x in lines}
    dts = [d for d in _page(downtime.list_downtime(tctx.ctx, line_id=None, open_=True, from_=None, to=None,
                                                   limit=200, offset=0)) if d["line"]["id"] in ids]
    trig = _page(replan.list_triggers(tctx.ctx, status="open", kind=None, limit=50, offset=0))
    out = {"lines": [{"id": x["id"], "code": x["code"], "name": x.get("name"),
                      "down": any(d["line"]["id"] == x["id"] for d in dts)} for x in lines[:MAX_ROWS]],
           "open_downtime": dts, "open_triggers": trig}
    refs = [("line", x["id"], x["code"], f"/mfg/floor?line={x['id']}") for x in lines[:MAX_ROWS]]
    return ToolResult(out, refs)


def t_kpis(tctx: ToolContext, a: KpiArgs) -> ToolResult:
    from ..api.mfg.services import kpi

    days = {"7d": 7, "4w": 28, "13w": 91}[a.period]
    out = kpi.kpis(tctx.ctx, None, None, a.dim, a.dim_id, "week") if a.period == "4w" else None
    if out is None:
        from ..api.mfg.services.m2util import today
        from ..api.mfg.services.common import read_tx

        with read_tx(tctx.ctx) as s:
            to = today(s) + timedelta(days=1)
        out = kpi.kpis(tctx.ctx, to - timedelta(days=days), to, a.dim, a.dim_id, "week")
    return ToolResult(out, [("kpis", f"{a.dim}:{a.dim_id or ''}", f"KPIs {a.period}", "/mfg/kpis")])


def t_supplier(tctx: ToolContext, a: SupplierArgs) -> ToolResult:
    from ..api.mfg.services import purchasing, suppliers

    sid = a.supplier
    if not _is_id(sid):
        hits = [x for x in _page(suppliers.list_suppliers(tctx.ctx, sid, None)) if x["code"].lower() == sid.lower()]
        if len(hits) != 1:
            raise ApiError(404, "NOT_FOUND", f"No supplier {a.supplier!r}.", {})
        sid = hits[0]["id"]
    sup = suppliers.get_supplier(tctx.ctx, sid)
    board = purchasing.schedule_board(tctx.ctx, d0=None, d1=None, supplier_id=sid, item_id=None, doc_type="po",
                                      overdue_only=False, limit=MAX_ROWS, offset=0)
    from ..api.mfg.services import dashboard as dash

    hist = dash.supplier_lateness(tctx.ctx, sid)
    return ToolResult({"supplier": sup, "open_schedules": _page(board), "lateness_12m": hist},
                      [("supplier", sid, str(sup.get("code") or a.supplier), f"/mfg/suppliers/{sid}")])


def t_trace(tctx: ToolContext, a: TraceArgs) -> ToolResult:
    from ..api.mfg.services import trace

    return ToolResult(trace.trace(tctx.ctx, a.kind, a.id, a.direction, 6, True))


def t_recall_scope(tctx: ToolContext, a: RecallArgs) -> ToolResult:
    from ..api.db.ownership import current_owner, system_scope
    from ..api.mfg.services import trace

    home = str(current_owner())
    with system_scope(), tctx.ctx.db.read() as s:
        rep = trace._report(s, home, [x.model_dump() for x in a.sources], True, tctx.user_id)
    return ToolResult({"preview": True, "counts": rep.get("counts"), "by_customer": rep.get("by_customer"),
                       "by_program": rep.get("by_program"), "lots": (rep.get("lots") or [])[:MAX_ROWS],
                       "truncated": rep.get("truncated")})


def t_eco_impact(tctx: ToolContext, a: EcoArgs) -> ToolResult:
    from ..api.mfg.services import eco

    cid = a.eco
    if not _is_id(cid):
        hits = [x for x in _page(eco.list_(tctx.ctx, None, cid, 20, 0)) if x["number"].lower() == cid.lower()]
        if len(hits) != 1:
            raise ApiError(404, "NOT_FOUND", f"No change request {a.eco!r}.", {})
        cid = hits[0]["id"]
    return ToolResult(eco.impact(tctx.ctx, cid), [("eco", cid, a.eco, f"/mfg/eco/{cid}")])


def t_stock(tctx: ToolContext, a: StockArgs) -> ToolResult:
    from ..api.mfg.services import inventory

    iid = _item_id(tctx, a.item)
    return ToolResult(inventory.item_stock(tctx.ctx, iid), [("item", iid, a.item, f"/mfg/items/{iid}")])


def t_whatif_mrp(tctx: ToolContext, a: WhatIfMrpArgs) -> ToolResult:
    from ..api.mfg.services import mrp, purchasing
    from ..mfg.mrp.model import MrpParams

    extra = [{"item_id": _item_id(tctx, x.item), "qty": x.qty, "due_date": x.due_date.isoformat()}
             for x in (a.extra_demand or [])][:20]
    overrides = []
    for x in (a.supply_delays or [])[:20]:
        pid = x.purchase_order if _is_id(x.purchase_order) else next(
            (d["id"] for d in _page(purchasing.list_docs(tctx.ctx, "po", status=None, supplier_id=None, item_id=None,
                                                         overdue=None, q=x.purchase_order, source=None, sort="number",
                                                         limit=5, offset=0)) if d["number"] == x.purchase_order), None)
        if pid is None:
            raise ApiError(404, "NOT_FOUND", f"No purchase order {x.purchase_order!r}.", {})
        doc = purchasing.get_doc(tctx.ctx, "po", pid)
        for ln in doc["lines"]:
            for sc in ln["schedules"]:
                if (sc.get("open_qty") or 0) > 0:
                    overrides.append({"schedule_id": sc["id"], "date": x.new_date.isoformat()})
    try:
        params = MrpParams.model_validate({"label": f"Assistant what-if {a.label or ''}".strip()[:100],
                                           "extra_demand": extra, "supply_date_overrides": overrides})
    except ValidationError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "The what-if parameters are not valid.",
                       {"errors": [e["msg"] for e in exc.errors()[:5]]}) from None
    rec = mrp.create_run(tctx.ctx, params, force_what_if=True)
    tctx.whatif_runs.append({"kind": "mrp", "id": rec["id"]})
    return ToolResult({"run": {k: rec.get(k) for k in ("id", "run_no", "kind", "status", "label", "summary")}},
                      [("mrp_run", rec["id"], f"MRP what-if {rec.get('run_no')}", f"/mfg/mrp/runs/{rec['id']}")])


def t_whatif_aps(tctx: ToolContext, a: WhatIfApsArgs) -> ToolResult:
    from ..api.mfg.services import aps
    from ..mfg.aps.model import ApsParams

    label = f"Assistant what-if {a.label or ''}".strip()[:100]
    if a.open_shifts:
        body: dict[str, Any] = {"copy_of": _published(tctx), "label": label,
                                "open_shifts": [x.model_dump(mode="json") for x in a.open_shifts[:20]]}
        if a.overtime:
            body["overtime"] = a.overtime
    else:
        body = {"label": label, "overtime": a.overtime,
                "line_breakdowns": [x.model_dump(mode="json") for x in (a.line_breakdowns or [])[:20]]}
    try:
        params = ApsParams.model_validate({k: v for k, v in body.items() if v is not None})
    except ValidationError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "The what-if parameters are not valid.",
                       {"errors": [e["msg"] for e in exc.errors()[:5]]}) from None
    rec, _ = aps.create_run(tctx.ctx, params, None, force_what_if=True)
    tctx.whatif_runs.append({"kind": "aps", "id": rec["id"]})
    deadline = time.monotonic() + WHATIF_APS_WAIT_SECONDS
    while rec.get("status") in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.5)
        rec = aps.get_run(tctx.ctx, rec["id"])
    out = {"run": {k: rec.get(k) for k in ("id", "run_no", "kind", "status", "label", "summary", "score")}}
    if rec.get("status") == "completed":
        out["late_demand"] = aps.demand(tctx.ctx, rec["id"], late_only=True, program=None)
        out["overtime"] = aps.overtime(tctx.ctx, rec["id"], status=None)["totals"]
    return ToolResult(out, [("aps_run", rec["id"], f"schedule what-if {rec.get('run_no')}",
                             f"/mfg/schedule/runs/{rec['id']}")])


WHATIF_APS_WAIT_SECONDS = 120.0


def t_draft(tctx: ToolContext, a: DraftActionArgs) -> ToolResult:
    try:
        card = D.build(tctx, a.kind, a.args)
    except D.DraftInvalid as exc:
        tctx.notes.append(f"A {a.kind} draft was dropped: {exc.note}")
        return ToolResult({"draft": None, "dropped": True, "reason": exc.note[:300]})
    if len(tctx.drafts) >= 5:
        return ToolResult({"draft": None, "dropped": True, "reason": "at most 5 drafts per answer"})
    tctx.drafts.append(card)
    return ToolResult({"draft": {"draft_id": card["draft_id"], "kind": card["kind"], "summary": card["summary"],
                                 "required_permission": card["required_permission"],
                                 "user_may_apply": card["allowed"]},
                       "note": "Draft prepared for the user to review; nothing has been changed."})


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("find_records", "Search items, demand orders, work orders, purchase orders / requests, suppliers, lines, "
         "lots and serials by number, code or name.", FindArgs, ("view",), t_find),
    Tool("demand_status", "Status of a demand order (line): MRP projection of the latest live run with the limiting "
         "path, and the published schedule's view (projected completion, late chain).", DemandArgs, ("view",),
         t_demand_status),
    Tool("mrp_exceptions", "MRP exceptions of the latest live run, filtered by code, item or demand.",
         ExceptionArgs, ("view",), t_mrp_exceptions),
    Tool("mrp_item_plan", "Time-phased MRP plan of one item (latest live run).", ItemPlanArgs, ("view",),
         t_mrp_item_plan),
    Tool("mrp_pegging", "Pegging of an item's requirement or supply up to demand or down to components.",
         PeggingArgs, ("view",), t_mrp_pegging),
    Tool("schedule_order", "Operations of an order in the published schedule with start reasons and lateness.",
         OrderArgs, ("view",), t_schedule_order),
    Tool("schedule_bottlenecks", "Bottleneck stages of the published schedule.", NoArgs, ("view",), t_bottlenecks),
    Tool("overtime_options", "Suggested overtime windows of the published schedule with the tardiness they save.",
         NoArgs, ("view",), t_overtime),
    Tool("line_status", "Shop floor: lines, open downtime and open replan triggers.", LineArgs, ("floor_view",),
         t_line_status),
    Tool("kpis", "Plant / stage / line KPIs (OTD, adherence, OEE-lite, FPY, scrap).", KpiArgs, ("view",), t_kpis),
    Tool("supplier_performance", "A supplier's open and late schedules and 12-month lateness.", SupplierArgs,
         ("view",), t_supplier),
    Tool("trace", "Genealogy of a lot, serial or work order (backward or forward).", TraceArgs, ("trace_view",),
         t_trace),
    Tool("recall_scope", "Preview the scope of a recall from lots / serials / work orders (nothing is saved).",
         RecallArgs, ("trace_view",), t_recall_scope),
    Tool("eco_impact", "Impact of an engineering change request.", EcoArgs, ("eco_edit", "eco_approve"),
         t_eco_impact),
    Tool("stock", "On-hand stock of an item by location and lot.", StockArgs, ("view",), t_stock),
    Tool("run_whatif_mrp", "Run a what-if MRP (extra demand, supply delays). Creates a what-if run only.",
         WhatIfMrpArgs, ("mrp_run",), t_whatif_mrp, whatif=True),
    Tool("run_whatif_aps", "Run a what-if schedule (open overtime windows, line breakdowns, overtime policy); waits "
         "up to 120 s. Creates a what-if run only (never live or publishable).", WhatIfApsArgs, ("schedule_run",),
         t_whatif_aps, whatif=True),
    Tool("draft_action", "Prepare a draft card for the user to apply (never executed by you): expedite a PO "
         "schedule, release planned orders, open overtime, schedule edits, create a PR, raise a priority, a what-if "
         "run request.", DraftActionArgs, tuple(sorted({"view"})), t_draft),
)}


def offered(perms: frozenset[str], allow_whatif: bool) -> list[Tool]:
    return [t for t in TOOLS.values() if t.allowed(perms, allow_whatif)]


def definitions(tools: list[Tool]) -> list[dict[str, Any]]:
    out = [t.schema() for t in tools]
    if out:
        out[-1] = dict(out[-1], cache_control={"type": "ephemeral"})
    return out


# ---------------------------------------------------------------- trimming and references

def trim(data: Any, *, cost: bool, registry: RefRegistry, extra_refs: list[tuple[str, str, str, str]]
         ) -> tuple[dict[str, Any], int]:
    """-> (tool result payload, row count). Issues references for records with server links."""
    untrusted: list[str] = []
    state = {"rows": 0, "truncated": False}

    def walk(v: Any, path: str, depth: int) -> Any:
        if depth > 12:
            state["truncated"] = True
            return None
        if isinstance(v, dict):
            out: dict[str, Any] = {}
            link = v.get("link")
            for k, x in v.items():
                if k in PERSONAL_KEYS or k == "link":
                    continue
                if not cost and COST_KEY.search(k) and k not in ("qty_value",):
                    continue
                out[k] = walk(x, f"{path}.{k}" if path else k, depth + 1)
            if link is not None and isinstance(v.get("id"), str):
                ok = safe_link(link)
                if ok:
                    label = next((str(v[k]) for k in LABEL_KEYS if isinstance(v.get(k), (str, int)) and v.get(k)),
                                 v["id"])
                    ref = registry.issue(type_of_link(ok), v["id"], label, ok)
                    if ref:
                        out["ref"] = ref
            return out
        if isinstance(v, (list, tuple)):
            if len(v) > MAX_ROWS:
                state["truncated"] = True
            items = [walk(x, f"{path}[{i}]", depth + 1) for i, x in enumerate(list(v)[:MAX_ROWS])]
            state["rows"] = max(state["rows"], len(items))
            return items
        if isinstance(v, str):
            last = path.rsplit(".", 1)[-1].split("[")[0]
            if last in UNTRUSTED_KEYS:
                if len(untrusted) < 200:
                    untrusted.append(path)
                return v[:MAX_TEXT]
            return v[:MAX_TEXT] if len(v) > MAX_TEXT else v
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        return v

    body = walk(_jsonable(data), "", 0)
    refs_out = []
    for t, i, label, link in extra_refs:
        ref = registry.issue(t, i, label, link)
        if ref:
            refs_out.append({"ref": ref, "type": t, "label": str(label)[:120]})
    payload: dict[str, Any] = {"data": body, "refs": refs_out, "untrusted_text": untrusted,
                               "truncated": state["truncated"]}
    text = json.dumps(payload, default=str)
    if len(text) > MAX_CHARS:
        payload = {"data": text[:MAX_CHARS - 500], "refs": refs_out, "untrusted_text": untrusted, "truncated": True,
                   "note": "result cut to 20,000 characters (JSON text)"}
    return payload, state["rows"]


def _jsonable(v: Any) -> Any:
    from ..api.mfg.services.common import jsonable

    return jsonable(v)


# ---------------------------------------------------------------- running a tool call

def current_permissions(tctx: ToolContext) -> frozenset[str]:
    if tctx.reload_permissions is not None:
        return tctx.reload_permissions(tctx)
    from ..api.mfg.access import ROLE_PERMISSIONS, _membership, permissions_of

    if tctx.owner_id == tctx.user_id:
        return ROLE_PERMISSIONS["owner"]
    roles = _membership(tctx.ctx, tctx.owner_id, tctx.user_id)
    return permissions_of(list(roles)) if roles else frozenset()


def run_call(tctx: ToolContext, name: str, args: Any, offered_names: set[str]) -> tuple[dict[str, Any], bool, int]:
    """-> (tool_result payload, ok, rows). Never raises for tool problems (they become error payloads)."""
    tool = TOOLS.get(name)
    if tool is None or name not in offered_names:
        return {"error": "permission_denied", "message": f"The tool {name!r} is not available to this user here."}, \
            False, 0
    perms = current_permissions(tctx)
    tctx.permissions = perms
    if not tool.allowed(perms, tctx.allow_whatif):
        return {"error": "permission_denied", "message": f"The tool {name!r} is not available to this user here."}, \
            False, 0
    try:
        parsed = tool.args.model_validate(args if isinstance(args, dict) else {})
    except ValidationError as exc:
        return {"error": "invalid_arguments", "details": [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                                                           for e in exc.errors()[:5]]}, False, 0
    from . import cache

    ck = None
    if name in cache.CACHEABLE:
        with tctx.ctx.db.read() as s:
            ck = cache.key(tctx.owner_id, name, parsed.model_dump(mode="json"), cache.data_token(s))
        hit = cache.get(ck)
        if hit is not None:
            data, refs = hit
            payload, rows = trim(data, cost=tool.cost, registry=tctx.refs, extra_refs=refs)
            return payload, True, rows
    try:
        res = tool.run(tctx, parsed)
    except ApiError as exc:
        return {"error": exc.code, "message": exc.message[:300]}, False, 0
    if ck is not None:
        cache.put(ck, (res.data, res.refs))
    payload, rows = trim(res.data, cost=tool.cost, registry=tctx.refs, extra_refs=res.refs)
    return payload, True, rows


def args_digest(args: Any) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]


def summary_of(name: str, args: Any) -> str:
    """Short step label (no free text beyond record numbers)."""
    a = args if isinstance(args, dict) else {}
    key = next((str(a[k]) for k in ("order", "item", "supplier", "eco", "line", "query", "kind") if a.get(k)), "")
    key = re.sub(r"[^A-Za-z0-9_./\- ]", "", key)[:40]
    return f"tool: {name}" + (f" ({key})" if key else "")

"""Draft cards (M6-DESIGN 1.4): the assistant never changes anything; `draft_action` builds an exact API request
(method, path, body) the user applies in the UI with their own session, CSRF, If-Match and permissions.

Every card is checked against an allow-list of (method, path template) and the target endpoint's input model;
anything else is dropped with a note. Cards are built from fresh server reads (current documents), never from
model-supplied bodies: the model only names the record and the change."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..api.db import new_id
from ..api.errors import ApiError
from ..mfg.model import MfgModel

V1 = "/api/v1"
ID = r"[A-Za-z0-9_\-]{1,64}"


def _models() -> dict[str, type[BaseModel]]:
    from ..api.mfg.schemas_m2 import ConvertPlannedRequest
    from ..mfg.aps.model import ApsParams, EditsRequest
    from ..mfg.model_m2 import DemandOrderInput, PurchaseDocInput
    from ..mfg.mrp.model import MrpParams

    return {"po_put": PurchaseDocInput, "pr_post": PurchaseDocInput, "convert": ConvertPlannedRequest,
            "aps_post": ApsParams, "edits": EditsRequest, "demand_put": DemandOrderInput, "mrp_post": MrpParams}


#: (method, path regex, input model key, permission) - the only requests a card may describe
ALLOW_LIST: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    ("PUT", re.compile(rf"^{V1}/mfg/purchase-orders/{ID}$"), "po_put", "po_edit"),
    ("POST", re.compile(rf"^{V1}/mfg/purchase-requests$"), "pr_post", "pr_edit"),
    ("POST", re.compile(rf"^{V1}/mfg/mrp/runs/{ID}/planned-orders/convert$"), "convert", "mrp_run"),
    ("POST", re.compile(rf"^{V1}/mfg/aps/runs$"), "aps_post", "schedule_run"),
    ("POST", re.compile(rf"^{V1}/mfg/aps/runs/{ID}/edits$"), "edits", "schedule_run"),
    ("PUT", re.compile(rf"^{V1}/mfg/demand-orders/{ID}$"), "demand_put", "demand_edit"),
    ("POST", re.compile(rf"^{V1}/mfg/mrp/runs$"), "mrp_post", "mrp_run"),
)


class DraftInvalid(Exception):
    def __init__(self, note: str):
        super().__init__(note)
        self.note = note


class OpenShiftArg(MfgModel):
    line_id: str
    start: datetime
    end: datetime


class EditArg(MfgModel):
    kind: Literal["move", "lock", "unlock", "resequence"]
    op_no: int | None = None
    line_id: str | None = None
    start: datetime | None = None
    op_nos: list[int] | None = None


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
    open_shifts: list[OpenShiftArg] | None = Field(default=None, description="optional shift windows to open "
                                                     "(from overtime_options)")
    overtime: Literal["off", "suggest", "allow"] | None = None
    line_breakdowns: list[LineBreakdownArg] | None = None
    label: str | None = Field(default=None, max_length=60)


class DraftArgs(MfgModel):
    """Flat arguments of `draft_action` (every field nullable; each kind uses its own)."""
    purchase_order: str | None = None          # PO id or number (expedite)
    schedule_id: str | None = None             # PO schedule id (expedite; default: the first open schedule)
    needed_date: date | None = None            # expedite / create_pr
    planned_order_ids: list[str] | None = None  # release_planned_orders
    release_mode: Literal["firm", "release"] | None = None
    open_shifts: list[OpenShiftArg] | None = None   # open_overtime
    run_id: str | None = None                  # schedule_edit / open_overtime (default: published run)
    edits: list[EditArg] | None = None         # schedule_edit
    item: str | None = None                    # create_pr: item id or part number
    qty: float | None = None
    supplier_id: str | None = None
    demand_order: str | None = None            # raise_priority: order id or number
    line_no: int | None = None
    priority: int | None = None
    target: Literal["mrp", "aps"] | None = None    # whatif_run (typed, extra=forbid; body built by the server)
    whatif_mrp: WhatIfMrpArgs | None = None
    whatif_aps: WhatIfApsArgs | None = None
    summary: str | None = None                 # the model's one-line rationale (shown, truncated)


def check(method: str, path: str, body: dict[str, Any]) -> tuple[str, BaseModel]:
    """(permission, validated body) or DraftInvalid."""
    models = _models()
    for m, rx, key, perm in ALLOW_LIST:
        if m == method and rx.match(path):
            try:
                return perm, models[key].model_validate(body)
            except ValidationError as exc:
                errs = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
                raise DraftInvalid(f"the request body is not valid ({errs[:300]})") from None
    raise DraftInvalid(f"{method} {path[:120]} is not an allowed draft target")


def _resolve(svc_list: Any, ref: str, key: str = "number") -> str:
    """An id, or a number found through the list service (exact match)."""
    if re.fullmatch(r"[a-z]{3}_[0-9a-f]{32}", ref or ""):
        return ref
    from ..api.mfg.services.common import jsonable

    items = jsonable(svc_list(ref))
    hit = [x for x in items if str(x.get(key, "")).lower() == (ref or "").lower()]
    if len(hit) != 1:
        raise DraftInvalid(f"{ref!r} was not found")
    return hit[0]["id"]


def build(tctx: Any, kind: str, args: DraftArgs) -> dict[str, Any]:
    """A validated draft card (dict of `model.DraftCard`) or DraftInvalid."""
    ctx = tctx.ctx
    if_match_of = None
    summary = ""
    try:
        if kind == "expedite_po_schedule":
            from ..api.mfg.services import purchasing

            if not args.purchase_order or not args.needed_date:
                raise DraftInvalid("expedite needs purchase_order and needed_date")
            po_id = _resolve(lambda q: purchasing.list_docs(ctx, "po", status=None, supplier_id=None, item_id=None,
                                                            overdue=None, q=q, source=None, sort="number", limit=20,
                                                            offset=0)["items"], args.purchase_order)
            doc = purchasing.get_doc(ctx, "po", po_id)
            body, sched, line = _po_body(doc, args.schedule_id, args.needed_date)
            method, path = "PUT", f"{V1}/mfg/purchase-orders/{doc['id']}"
            if_match_of = {"type": "purchase_order", "id": doc["id"], "row_version": doc["row_version"]}
            summary = (f"Ask the supplier to pull {doc['number']} line {line['line_no']} forward from "
                       f"{sched['requested_date']} to {args.needed_date.isoformat()}.")
        elif kind == "release_planned_orders":
            run = _latest_mrp(tctx)
            ids = list(args.planned_order_ids or [])[:200]
            if not ids:
                raise DraftInvalid("release needs planned_order_ids")
            body = {"mode": args.release_mode or "firm", "orders": [{"id": i} for i in ids]}
            method, path = "POST", f"{V1}/mfg/mrp/runs/{run}/planned-orders/convert"
            summary = f"{'Release' if body['mode'] == 'release' else 'Firm'} {len(ids)} planned order(s) of the latest MRP run."
        elif kind == "open_overtime":
            run = args.run_id or _published_aps(tctx)
            shifts = [{"line_id": x.line_id, "start": x.start.isoformat(), "end": x.end.isoformat()}
                      for x in (args.open_shifts or [])][:20]
            if not shifts:
                raise DraftInvalid("open_overtime needs open_shifts")
            body = {"copy_of": run, "open_shifts": shifts}
            method, path = "POST", f"{V1}/mfg/aps/runs"
            summary = f"Re-run the schedule with {len(shifts)} overtime window(s) opened."
        elif kind == "schedule_edit":
            run = args.run_id or _published_aps(tctx)
            edits = [e.model_dump(mode="json", exclude_none=True) for e in (args.edits or [])][:50]
            body = {"edits": edits}
            method, path = "POST", f"{V1}/mfg/aps/runs/{run}/edits"
            summary = f"Apply {len(edits)} manual schedule edit(s) (creates an edited copy of the run)."
        elif kind == "create_pr":
            if not args.item or not args.qty or not args.needed_date:
                raise DraftInvalid("create_pr needs item, qty and needed_date")
            from ..api.mfg.services import items as items_svc

            item_id = _resolve(lambda q: items_svc.list_items(ctx, q=q, make_buy=None, family=None, active=None,
                                                              has_bom=None, has_routing=None, sort="part_number",
                                                              limit=20, offset=0)["items"], args.item, "part_number")
            body = {"supplier_id": args.supplier_id, "note": "Assistant draft",
                    "lines": [{"item_id": item_id, "schedules": [{"requested_date": args.needed_date.isoformat(),
                                                                  "qty": args.qty}]}]}
            method, path = "POST", f"{V1}/mfg/purchase-requests"
            summary = f"Create a purchase request for {args.qty:g} of {args.item} needed {args.needed_date}."
        elif kind == "raise_priority":
            from ..api.mfg.services import demand

            if not args.demand_order or args.priority is None:
                raise DraftInvalid("raise_priority needs demand_order and priority")
            oid = _resolve(lambda q: demand.list_orders(ctx, status=None, demand_type=None, program=None,
                                                         item_id=None, due_from=None, due_to=None, late_only=False,
                                                         q=q, limit=20, offset=0)["items"], args.demand_order)
            order = demand.get_order(ctx, oid)
            body = _demand_body(order, args.line_no, args.priority)
            method, path = "PUT", f"{V1}/mfg/demand-orders/{order['id']}"
            if_match_of = {"type": "demand_order", "id": order["id"], "row_version": order["row_version"]}
            summary = (f"Set the priority of {order['number']}" + (f" line {args.line_no}" if args.line_no else "")
                       + f" to {args.priority}.")
        elif kind == "whatif_run":
            # M6 review M2: no free parameters - the body is built by the server and always says what_if
            from . import tools as T

            if args.target == "aps":
                body = T.whatif_aps_body(tctx, args.whatif_aps or WhatIfApsArgs())
                method, path = "POST", f"{V1}/mfg/aps/runs"
            else:
                body = T.whatif_mrp_body(tctx, args.whatif_mrp or WhatIfMrpArgs())
                method, path = "POST", f"{V1}/mfg/mrp/runs"
            summary = f"Start a what-if {'schedule' if args.target == 'aps' else 'MRP'} run (never live)."
        else:
            raise DraftInvalid(f"unknown draft kind {kind!r}")
    except ApiError as exc:
        raise DraftInvalid(f"{exc.code}: {exc.message}"[:300]) from None
    perm, validated = check(method, path, body)
    if kind == "whatif_run" and getattr(validated, "what_if", False) is not True:
        raise DraftInvalid("a what-if draft must request a what-if run")
    if args.summary:
        summary = f"{summary} {args.summary.strip()[:300]}".strip()
    return {"draft_id": new_id("drf_"), "kind": kind, "summary": summary[:600], "method": method, "path": path,
            "body": body, "if_match_of": if_match_of, "required_permission": perm,
            "allowed": perm in tctx.permissions, "applied_at": None, "applied_status": None, "response_ref": None}


def _po_body(doc: dict[str, Any], schedule_id: str | None, needed: date) -> tuple[dict[str, Any], dict[str, Any],
                                                                                    dict[str, Any]]:
    if doc.get("status") not in ("draft", "open", "partially_received"):
        raise DraftInvalid(f"{doc['number']} is {doc.get('status')}")
    target = None
    lines = []
    for ln in doc.get("lines") or []:
        scheds = []
        for sc in ln.get("schedules") or []:
            sd = {"id": sc["id"], "seq": sc["seq"], "requested_date": str(sc["requested_date"])[:10],
                  "confirmed_date": str(sc["confirmed_date"])[:10] if sc.get("confirmed_date") else None,
                  "qty": sc["qty"]}
            hit = (sc["id"] == schedule_id) if schedule_id else (target is None and (sc.get("open_qty") or 0) > 0)
            if hit:
                target = (dict(sd), ln)
                sd["requested_date"] = needed.isoformat()
                sd["confirmed_date"] = None
            scheds.append(sd)
        lines.append({"id": ln["id"], "line_no": ln["line_no"], "item_id": ln["item_id"],
                      "unit_price": ln.get("unit_price"), "note": ln.get("note") or "", "schedules": scheds})
    if target is None:
        raise DraftInvalid("no open schedule to expedite on this purchase order")
    note = (doc.get("note") or "")
    add = f"Expedite requested to {needed.isoformat()} - agree with the supplier."
    body = {"number": doc["number"], "supplier_id": doc.get("supplier_id"), "currency": doc.get("currency") or None,
            "order_date": str(doc["order_date"])[:10] if doc.get("order_date") else None,
            "note": (f"{note} {add}".strip())[:500], "external_ref": doc.get("external_ref"), "lines": lines}
    return body, target[0], target[1]


def _demand_body(order: dict[str, Any], line_no: int | None, priority: int) -> dict[str, Any]:
    lines = []
    for ln in order.get("lines") or []:
        pr = ln.get("priority")
        if line_no is not None and ln["line_no"] == line_no:
            pr = priority
        lines.append({"id": ln["id"], "line_no": ln["line_no"], "item_id": ln["item_id"], "qty": ln["qty"],
                      "due_date": str(ln["due_date"])[:10], "serial_from": ln.get("serial_from"),
                      "serial_to": ln.get("serial_to"), "priority": pr, "note": ln.get("note") or ""})
    body = {"number": order["number"], "demand_type": order["demand_type"], "customer": order.get("customer") or "",
            "program": order.get("program"), "priority": order["priority"] if line_no is not None else priority,
            "note": order.get("note") or "", "external_ref": order.get("external_ref"), "lines": lines}
    return body


def _latest_mrp(tctx: Any) -> str:
    from ..api.mfg.db_models_m2 import MfgMrpRunRow
    from sqlalchemy import select

    with tctx.ctx.db.read() as s:
        rid = s.execute(select(MfgMrpRunRow.id).where(MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed")
                        .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalar()
    if rid is None:
        raise DraftInvalid("there is no completed live MRP run")
    return str(rid)


def _published_aps(tctx: Any) -> str:
    from ..api.mfg.db_models_m3 import MfgApsRunRow
    from sqlalchemy import select

    with tctx.ctx.db.read() as s:
        rid = s.execute(select(MfgApsRunRow.id).where(MfgApsRunRow.is_published.is_(True)).limit(1)).scalar()
    if rid is None:
        raise DraftInvalid("there is no published schedule")
    return str(rid)

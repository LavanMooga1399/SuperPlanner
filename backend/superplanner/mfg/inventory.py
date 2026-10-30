"""Inventory posting rules (M2-DESIGN 4): validation of every posting type, FEFO lot picking, balance deltas,
reservation effects and document deltas. Pure: the service loads and locks the context (4.5 lock order), calls
`plan_posting` / `plan_reversal` and applies the returned `PostingPlan` (balance `balance_after` values are computed
while applying, under the row locks).

Errors are raised as `purchasing.RuleError` (422 unless stated): `INV_LOT_REQUIRED`, `INV_LOT_NOT_ALLOWED`,
`INV_LOT_EXPIRED`, `INV_LOT_ON_HOLD`, `INV_FRACTIONAL_QTY`, `INV_BACKDATE_LIMIT`, `INV_SAME_LOCATION`,
`INV_LOCATION_INACTIVE`, `INV_LOCATION_REQUIRED`, `INV_REASON_REQUIRED`, 409 `INV_INSUFFICIENT_STOCK`,
409 `PUR_OVER_RECEIPT`, 409 `MFG_INVALID_STATE`, `WO_OVER_ISSUE`, `WO_RETURN_ABOVE_ISSUED`, `DEM_OVER_SHIPMENT`.
`loc` of a line error is `["body", "lines", i, field]`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .limits import INV_MAX_BACKDATE_DAYS
from .model_m2 import EPS
from .purchasing import RuleError, invalid_state, receipt_limit, schedule_open_qty
from .units import is_count

BalKey = tuple[str, str, str]          # (item_id, location_id, lot_key)
#: transactions that set `last_receipt_on` when positive (4.3)
RECEIPT_TYPES = ("receipt_misc", "po_receipt", "wo_receipt", "transfer", "adjust")
INBOUND_FIELDS = {"receipt_misc": "location_id", "adjust": "location_id", "count": "location_id",
                  "po_receipt": "location_id", "wo_return": "location_id", "wo_receipt": "location_id"}


# ---------------------------------------------------------------- context


@dataclass
class ItemInfo:
    id: str
    part_number: str
    uom: str
    lot_controlled: bool = False
    shelf_life_days: int | None = None
    standard_cost: float | None = None
    make_buy: str = "buy"


@dataclass
class LocInfo:
    id: str
    code: str
    kind: str
    active: bool = True
    receipt_default: bool = False
    name: str = ""


@dataclass
class LotInfo:
    item_id: str
    lot_code: str
    id: str | None = None
    expires_on: date | None = None
    hold: bool = False
    received_on: date | None = None
    supplier_lot: str = ""


@dataclass
class BalInfo:
    item_id: str
    location_id: str
    lot_key: str
    qty_on_hand: float = 0.0
    qty_reserved: float = 0.0
    id: str | None = None
    last_receipt_on: date | None = None

    @property
    def key(self) -> BalKey:
        return (self.item_id, self.location_id, self.lot_key)

    @property
    def available(self) -> float:
        return self.qty_on_hand - self.qty_reserved


@dataclass
class ResInfo:
    id: str
    wo_component_id: str
    balance_key: BalKey
    qty: float
    order: Any = 0              # oldest first (created_at, id)


@dataclass
class SchedInfo:
    id: str
    seq: int
    qty: float
    received_qty: float
    closed: bool
    line_id: str
    line_no: int
    item_id: str
    unit_price: float | None
    doc_id: str
    doc_number: str
    doc_type: str
    doc_status: str
    line_status: str = "open"


@dataclass
class CompInfo:
    id: str
    wo_id: str
    item_id: str
    required_qty: float
    issued_qty: float


@dataclass
class WoInfo:
    id: str
    number: str
    status: str
    item_id: str
    qty: float
    qty_completed: float
    qty_scrapped: float = 0.0


@dataclass
class DemLineInfo:
    id: str
    order_id: str
    order_number: str
    order_status: str
    line_no: int
    item_id: str
    qty: float
    shipped_qty: float


@dataclass
class PostingContext:
    today: date
    items: dict[str, ItemInfo]
    locations: dict[str, LocInfo]
    lots: dict[tuple[str, str], LotInfo] = field(default_factory=dict)
    balances: dict[BalKey, BalInfo] = field(default_factory=dict)
    reservations: list[ResInfo] = field(default_factory=list)
    schedules: dict[str, SchedInfo] = field(default_factory=dict)
    components: dict[str, CompInfo] = field(default_factory=dict)
    work_orders: dict[str, WoInfo] = field(default_factory=dict)
    demand_lines: dict[str, DemLineInfo] = field(default_factory=dict)
    over_receipt_pct: float = 0.0
    #: imports and sample loads: no backdate/future limit, no reason requirement
    system: bool = False


# ---------------------------------------------------------------- plan


@dataclass
class TxnPlan:
    line_no: int                # 1-based input line
    txn_type: str
    item_id: str
    location_id: str
    lot_code: str | None
    qty: float                  # signed
    unit_cost: float | None = None
    schedule_id: str | None = None
    wo_id: str | None = None
    wo_component_id: str | None = None
    demand_line_id: str | None = None
    set_last_receipt: date | None = None     # value for last_receipt_on (receipts / transfer in)
    scrap_qty: float | None = None           # wo_receipt: scrap recorded with the line (signed on reversals)

    @property
    def key(self) -> BalKey:
        return (self.item_id, self.location_id, self.lot_code or "")


@dataclass
class NewLot:
    item_id: str
    lot_code: str
    expires_on: date | None
    received_on: date
    supplier_lot: str = ""


@dataclass
class PostingPlan:
    type: str
    txn_date: date
    transactions: list[TxnPlan] = field(default_factory=list)
    new_lots: list[NewLot] = field(default_factory=list)
    reservation_qty: dict[str, float] = field(default_factory=dict)   # reservation id -> new qty (0 = delete)
    schedule_received: dict[str, float] = field(default_factory=dict)  # deltas
    component_issued: dict[str, float] = field(default_factory=dict)
    wo_completed: dict[str, float] = field(default_factory=dict)
    wo_scrapped: dict[str, float] = field(default_factory=dict)
    wo_touched: set[str] = field(default_factory=set)
    demand_shipped: dict[str, float] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def balance_keys(self) -> list[BalKey]:
        return sorted({t.key for t in self.transactions})


def _err(code: str, message: str, loc: list[Any] | None = None, status: int = 422, **details: Any) -> RuleError:
    d = dict(details)
    if loc is not None:
        d["loc"] = loc
    return RuleError(status, code, message, d)


def _fmt(x: float) -> str:
    return f"{x:,.6f}".rstrip("0").rstrip(".")


class _Planner:
    def __init__(self, ptype: str, ctx: PostingContext, txn_date: date):
        self.ctx = ctx
        self.plan = PostingPlan(ptype, txn_date)
        self.d = txn_date
        self.bal = {k: BalInfo(b.item_id, b.location_id, b.lot_key, b.qty_on_hand, b.qty_reserved, b.id,
                               b.last_receipt_on) for k, b in ctx.balances.items()}
        self.res = {r.id: ResInfo(r.id, r.wo_component_id, r.balance_key, r.qty, r.order) for r in ctx.reservations}
        self.new_lots: dict[tuple[str, str], NewLot] = {}
        self.issued = {k: c.issued_qty for k, c in ctx.components.items()}
        self.received = {k: s.received_qty for k, s in ctx.schedules.items()}
        self.completed = {k: w.qty_completed for k, w in ctx.work_orders.items()}
        self.shipped = {k: x.shipped_qty for k, x in ctx.demand_lines.items()}

    # -------------------------------------------------------- lookups
    def item(self, item_id: str, loc: list[Any]) -> ItemInfo:
        it = self.ctx.items.get(item_id)
        if it is None:
            raise _err("MFG_UNKNOWN_REFERENCE", f"Item {item_id!r} was not found.", loc, id=item_id)
        return it

    def location(self, loc_id: str, loc: list[Any], *, inbound: bool) -> LocInfo:
        lc = self.ctx.locations.get(loc_id)
        if lc is None:
            raise _err("MFG_UNKNOWN_REFERENCE", f"Location {loc_id!r} was not found.", loc, id=loc_id)
        if inbound and not lc.active:
            raise _err("INV_LOCATION_INACTIVE", f"Location {lc.code} is inactive; nothing can be posted into it.", loc)
        return lc

    def balance(self, key: BalKey) -> BalInfo:
        b = self.bal.get(key)
        if b is None:
            b = self.bal[key] = BalInfo(*key)
        return b

    def lot(self, item_id: str, code: str) -> LotInfo | None:
        lot = self.ctx.lots.get((item_id, code))
        if lot is not None:
            return lot
        nl = self.new_lots.get((item_id, code))
        return LotInfo(item_id, code, None, nl.expires_on) if nl else None

    # -------------------------------------------------------- checks
    def whole(self, it: ItemInfo, qty: float, loc: list[Any]) -> None:
        if is_count(it.uom) and abs(qty - round(qty)) > EPS:
            raise _err("INV_FRACTIONAL_QTY", f"{it.part_number} is counted in {it.uom}; use a whole number "
                       f"(not {_fmt(qty)}).", loc)

    def lot_rules(self, it: ItemInfo, code: str | None, loc: list[Any], *, required: bool) -> None:
        if code is not None and not it.lot_controlled:
            raise _err("INV_LOT_NOT_ALLOWED", f"{it.part_number} is not lot-controlled; leave the lot empty.", loc)
        if code is None and it.lot_controlled and required:
            raise _err("INV_LOT_REQUIRED", f"{it.part_number} is lot-controlled; enter the lot code.", loc)

    def lot_usable(self, it: ItemInfo, code: str, loc: list[Any], *, to_quarantine: bool = False) -> None:
        lot = self.lot(it.id, code)
        if lot is None or to_quarantine:
            return
        if lot.hold:
            raise _err("INV_LOT_ON_HOLD", f"Lot {code} of {it.part_number} is on hold.", loc)
        if lot.expires_on is not None and lot.expires_on <= self.d:
            raise _err("INV_LOT_EXPIRED", f"Lot {code} of {it.part_number} expired on {lot.expires_on.isoformat()}.",
                       loc)

    def ensure_lot(self, it: ItemInfo, code: str | None, expires_on: date | None, supplier_lot: str) -> None:
        if code is None or (it.id, code) in self.ctx.lots or (it.id, code) in self.new_lots:
            return
        exp = expires_on
        if exp is None and it.shelf_life_days:
            exp = self.d + timedelta(days=int(it.shelf_life_days))
        nl = NewLot(it.id, code, exp, self.d, supplier_lot or "")
        self.new_lots[(it.id, code)] = nl
        self.plan.new_lots.append(nl)

    def insufficient(self, it: ItemInfo, lc: LocInfo, code: str | None, b: BalInfo | None, req: float,
                     line: int, extra_available: float = 0.0) -> RuleError:
        on = b.qty_on_hand if b else 0.0
        rs = b.qty_reserved if b else 0.0
        av = max(0.0, on - rs + extra_available)
        lot = f" (lot {code})" if code else ""
        return RuleError(409, "INV_INSUFFICIENT_STOCK",
                         f"Only {_fmt(av)} of {it.part_number}{lot} are available in {lc.code} ({_fmt(on)} on hand, "
                         f"{_fmt(rs)} reserved); {_fmt(req)} requested.",
                         {"item_id": it.id, "location_id": lc.id, "lot_code": code, "on_hand": round(on, 6),
                          "reserved": round(rs, 6), "available": round(av, 6), "requested": round(req, 6),
                          "line": line})

    # -------------------------------------------------------- movements
    def inbound(self, line: int, ttype: str, it: ItemInfo, lc: LocInfo, code: str | None, qty: float,
                last: date | None, **refs: Any) -> None:
        b = self.balance((it.id, lc.id, code or ""))
        b.qty_on_hand += qty
        lr = last if ttype in RECEIPT_TYPES and qty > 0 else None
        if lr is not None:
            b.last_receipt_on = max(b.last_receipt_on or lr, lr)
        self.plan.transactions.append(TxnPlan(line, ttype, it.id, lc.id, code, round(qty, 6),
                                              set_last_receipt=lr, **refs))

    def outbound(self, line: int, ttype: str, it: ItemInfo, lc: LocInfo, code: str | None, qty: float,
                 *, component_id: str | None = None, to_quarantine: bool = False, idx: int = 0,
                 **refs: Any) -> list[tuple[str | None, float]]:
        """Take `qty` out of (item, location[, lot]); lot-controlled without a lot code: FEFO over that location's
        usable lots. `component_id`: its reservations on the balance are consumed first (wo_issue)."""
        picks: list[tuple[str | None, float]]
        if it.lot_controlled and code is None:
            picks = self.pick(it, lc, qty, component_id, to_quarantine, idx)
        else:
            if code is not None:
                self.lot_usable(it, code, ["body", "lines", idx, "lot_code"], to_quarantine=to_quarantine)
            b = self.bal.get((it.id, lc.id, code or ""))
            own = self.own_reserved(component_id, (it.id, lc.id, code or ""))
            if b is None or b.available + own < qty - EPS:
                raise self.insufficient(it, lc, code, b, qty, idx, own)
            picks = [(code, qty)]
        for c, q in picks:
            key = (it.id, lc.id, c or "")
            b = self.bal[key]
            if component_id is not None:
                self.consume_reservation(component_id, key, q)
            b.qty_on_hand -= q
            self.plan.transactions.append(TxnPlan(line, ttype, it.id, lc.id, c, round(-q, 6), **refs))
        return picks

    def own_reserved(self, component_id: str | None, key: BalKey) -> float:
        if component_id is None:
            return 0.0
        return sum(r.qty for r in self.res.values() if r.wo_component_id == component_id and r.balance_key == key)

    def consume_reservation(self, component_id: str, key: BalKey, q: float) -> None:
        rest = q
        b = self.bal[key]
        for r in sorted((r for r in self.res.values() if r.wo_component_id == component_id and r.balance_key == key),
                        key=lambda r: (r.order, r.id)):
            take = min(r.qty, rest)
            if take <= EPS:
                continue
            r.qty -= take
            b.qty_reserved -= take
            rest -= take
            self.plan.reservation_qty[r.id] = round(max(0.0, r.qty), 6)
            if rest <= EPS:
                break

    def trim_reservations(self, component_id: str, open_qty: float) -> None:
        """m5 / 4.4: a component's reservations never exceed its open qty (required - issued); the excess is
        released newest first (the reservations' balances are in the posting's lock set)."""
        rs = [r for r in self.res.values() if r.wo_component_id == component_id and r.qty > EPS]
        excess = sum(r.qty for r in rs) - max(0.0, open_qty)
        for r in sorted(rs, key=lambda r: (r.order, r.id), reverse=True):
            if excess <= EPS:
                break
            take = min(r.qty, excess)
            r.qty -= take
            if r.balance_key in self.bal:
                self.bal[r.balance_key].qty_reserved -= take
            excess -= take
            self.plan.reservation_qty[r.id] = round(max(0.0, r.qty), 6)

    def release_reservations(self, comp_ids: set[str]) -> None:
        for r in self.res.values():
            if r.wo_component_id in comp_ids and r.qty > EPS:
                if r.balance_key in self.bal:
                    self.bal[r.balance_key].qty_reserved -= r.qty
                r.qty = 0.0
                self.plan.reservation_qty[r.id] = 0.0

    def pick(self, it: ItemInfo, lc: LocInfo, qty: float, component_id: str | None, to_quarantine: bool,
             idx: int) -> list[tuple[str | None, float]]:
        """FEFO: earliest `expires_on` (nulls last), then lot code; expired/held lots are skipped (unless the
        destination is quarantine)."""
        cands = []
        for (item_id, loc_id, lk), b in self.bal.items():
            if item_id != it.id or loc_id != lc.id or not lk:
                continue
            lot = self.lot(it.id, lk)
            exp = lot.expires_on if lot else None
            if not to_quarantine and lot is not None and (lot.hold or (exp is not None and exp <= self.d)):
                continue
            av = b.available + self.own_reserved(component_id, b.key)
            if av > EPS:
                cands.append((exp is None, exp or date.max, lk, av))
        cands.sort()
        out: list[tuple[str | None, float]] = []
        rest = qty
        for _n, _e, lk, av in cands:
            take = min(av, rest)
            out.append((lk, round(take, 6)))
            rest -= take
            if rest <= EPS:
                break
        if rest > EPS:
            total = sum(c[3] for c in cands)
            b = BalInfo(it.id, lc.id, "", total, 0.0)
            raise self.insufficient(it, lc, None, b, qty, idx)
        return out

    # -------------------------------------------------------- per type
    def run(self, inp: Any) -> PostingPlan:
        t = inp.type
        if t in ("issue_misc", "adjust") and not inp.reason_code and not self.ctx.system:
            raise _err("INV_REASON_REQUIRED", "Enter a reason code for this posting (e.g. SCRAP, SAMPLE).",
                       ["body", "reason_code"])
        for i, ln in enumerate(inp.lines):
            getattr(self, f"_{t}")(i, ln)
        return self.plan

    def _receipt_misc(self, i: int, ln: Any) -> None:
        it = self.item(ln.item_id, ["body", "lines", i, "item_id"])
        lc = self.location(ln.location_id, ["body", "lines", i, "location_id"], inbound=True)
        self.whole(it, ln.qty, ["body", "lines", i, "qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=True)
        self.ensure_lot(it, ln.lot_code, ln.expires_on, ln.supplier_lot)
        cost = ln.unit_cost if ln.unit_cost is not None else it.standard_cost
        self.inbound(i + 1, "receipt_misc", it, lc, ln.lot_code, ln.qty, self.d, unit_cost=cost)

    def _issue_misc(self, i: int, ln: Any) -> None:
        it = self.item(ln.item_id, ["body", "lines", i, "item_id"])
        lc = self.location(ln.location_id, ["body", "lines", i, "location_id"], inbound=False)
        self.whole(it, ln.qty, ["body", "lines", i, "qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=False)
        self.outbound(i + 1, "issue_misc", it, lc, ln.lot_code, ln.qty, idx=i, unit_cost=it.standard_cost)

    def _adjust(self, i: int, ln: Any) -> None:
        it = self.item(ln.item_id, ["body", "lines", i, "item_id"])
        lc = self.location(ln.location_id, ["body", "lines", i, "location_id"], inbound=ln.qty > 0)
        self.whole(it, abs(ln.qty), ["body", "lines", i, "qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=True)
        if ln.qty > 0:
            self.ensure_lot(it, ln.lot_code, ln.expires_on, "")
            self.inbound(i + 1, "adjust", it, lc, ln.lot_code, ln.qty, self.d, unit_cost=it.standard_cost)
        else:
            key = (it.id, lc.id, ln.lot_code or "")
            b = self.bal.get(key)
            if b is None or b.available < -ln.qty - EPS:
                raise self.insufficient(it, lc, ln.lot_code, b, -ln.qty, i)
            b.qty_on_hand += ln.qty
            self.plan.transactions.append(TxnPlan(i + 1, "adjust", it.id, lc.id, ln.lot_code, round(ln.qty, 6),
                                                  unit_cost=it.standard_cost))

    def _count(self, i: int, ln: Any) -> None:
        it = self.item(ln.item_id, ["body", "lines", i, "item_id"])
        lc = self.location(ln.location_id, ["body", "lines", i, "location_id"], inbound=True)
        self.whole(it, ln.counted_qty, ["body", "lines", i, "counted_qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=True)
        key = (it.id, lc.id, ln.lot_code or "")
        b = self.balance(key)
        delta = round(ln.counted_qty - b.qty_on_hand, 6)
        if abs(delta) <= EPS:
            return
        if delta > 0:
            self.ensure_lot(it, ln.lot_code, ln.expires_on, "")
            self.inbound(i + 1, "adjust", it, lc, ln.lot_code, delta, self.d, unit_cost=it.standard_cost)
            return
        if ln.counted_qty < b.qty_reserved - EPS:          # release reservations, oldest first
            excess = b.qty_reserved - ln.counted_qty
            for r in sorted((r for r in self.res.values() if r.balance_key == key and r.qty > EPS),
                            key=lambda r: (r.order, r.id)):
                take = min(r.qty, excess)
                r.qty -= take
                b.qty_reserved -= take
                excess -= take
                self.plan.reservation_qty[r.id] = round(max(0.0, r.qty), 6)
                if excess <= EPS:
                    break
            self.plan.warnings.append({"code": "INV_RESERVATION_REDUCED",
                                       "message": f"Line {i + 1}: the count of {it.part_number} in {lc.code} is below "
                                                  "the reserved quantity; reservations were released (oldest first)."})
        b.qty_on_hand += delta
        self.plan.transactions.append(TxnPlan(i + 1, "adjust", it.id, lc.id, ln.lot_code, delta,
                                              unit_cost=it.standard_cost))

    def _transfer(self, i: int, ln: Any) -> None:
        it = self.item(ln.item_id, ["body", "lines", i, "item_id"])
        src = self.location(ln.from_location_id, ["body", "lines", i, "from_location_id"], inbound=False)
        dst = self.location(ln.to_location_id, ["body", "lines", i, "to_location_id"], inbound=True)
        if src.id == dst.id:
            raise _err("INV_SAME_LOCATION", "Choose two different locations for a transfer.",
                       ["body", "lines", i, "to_location_id"])
        self.whole(it, ln.qty, ["body", "lines", i, "qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=False)
        picks = self.outbound(i + 1, "transfer", it, src, ln.lot_code, ln.qty, idx=i,
                              to_quarantine=dst.kind == "quarantine")
        for code, q in picks:
            last = self.bal[(it.id, src.id, code or "")].last_receipt_on or self.d
            b = self.balance((it.id, dst.id, code or ""))
            b.qty_on_hand += q
            b.last_receipt_on = max(b.last_receipt_on or last, last)
            self.plan.transactions.append(TxnPlan(i + 1, "transfer", it.id, dst.id, code, round(q, 6),
                                                  set_last_receipt=last))

    def _po_receipt(self, i: int, ln: Any) -> None:
        loc = ["body", "lines", i, "schedule_id"]
        sc = self.ctx.schedules.get(ln.schedule_id)
        if sc is None:
            raise _err("MFG_UNKNOWN_REFERENCE", f"Schedule {ln.schedule_id!r} was not found.", loc, id=ln.schedule_id)
        if sc.doc_type != "po" or sc.doc_status not in ("open", "partially_received"):
            what = "This purchase order" if sc.doc_type == "po" else "A purchase request"
            raise invalid_state(what, sc.doc_status, "receive", ["open", "partially_received"])
        if sc.closed or sc.line_status != "open":
            raise RuleError(409, "MFG_INVALID_STATE", f"{sc.doc_number} / {sc.line_no} / {sc.seq} is closed.",
                            {"status": "closed", "action": "receive", "allowed_from": ["open"]})
        open_now = schedule_open_qty(sc.qty, self.received[sc.id], sc.closed)
        if ln.qty > receipt_limit(open_now, self.ctx.over_receipt_pct):
            raise RuleError(409, "PUR_OVER_RECEIPT", f"Only {_fmt(open_now)} are still open on {sc.doc_number} / "
                            f"{sc.line_no} / {sc.seq}; {_fmt(ln.qty)} would be received (tolerance "
                            f"{_fmt(self.ctx.over_receipt_pct)}%).",
                            {"open_qty": round(open_now, 6), "requested": ln.qty,
                             "tolerance_pct": self.ctx.over_receipt_pct, "line": i})
        loc_id = ln.location_id
        if loc_id is None:
            d = [x for x in self.ctx.locations.values() if x.receipt_default and x.active]
            if not d:
                raise _err("INV_LOCATION_REQUIRED", "Choose a location: no receipt-default location is set.",
                           ["body", "lines", i, "location_id"])
            loc_id = d[0].id
        lc = self.location(loc_id, ["body", "lines", i, "location_id"], inbound=True)
        it = self.item(sc.item_id, loc)
        self.whole(it, ln.qty, ["body", "lines", i, "qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=True)
        self.ensure_lot(it, ln.lot_code, ln.expires_on, ln.supplier_lot)
        self.received[sc.id] += ln.qty
        self.plan.schedule_received[sc.id] = round(self.plan.schedule_received.get(sc.id, 0.0) + ln.qty, 6)
        cost = ln.unit_cost if ln.unit_cost is not None else sc.unit_price
        self.inbound(i + 1, "po_receipt", it, lc, ln.lot_code, ln.qty, self.d, unit_cost=cost, schedule_id=sc.id)

    def _component(self, i: int, cid: str, action: str) -> tuple[CompInfo, WoInfo]:
        c = self.ctx.components.get(cid)
        if c is None:
            raise _err("MFG_UNKNOWN_REFERENCE", f"Work-order component {cid!r} was not found.",
                       ["body", "lines", i, "wo_component_id"], id=cid)
        w = self.ctx.work_orders[c.wo_id]
        from .workorders import check_action

        check_action(w.status, action)
        return c, w

    def _wo_issue(self, i: int, ln: Any) -> None:
        c, w = self._component(i, ln.wo_component_id, "issue")
        it = self.item(c.item_id, ["body", "lines", i, "wo_component_id"])
        lc = self.location(ln.location_id, ["body", "lines", i, "location_id"], inbound=False)
        self.whole(it, ln.qty, ["body", "lines", i, "qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=False)
        left = c.required_qty - self.issued[c.id]
        if ln.qty > left + EPS and not ln.over_issue:
            raise _err("WO_OVER_ISSUE", f"Only {_fmt(max(0.0, left))} of {it.part_number} are still to issue to "
                       f"{w.number}; set over_issue to issue more.", ["body", "lines", i, "qty"])
        self.outbound(i + 1, "wo_issue", it, lc, ln.lot_code, ln.qty, component_id=c.id, idx=i,
                      unit_cost=it.standard_cost, wo_id=w.id, wo_component_id=c.id)
        self.issued[c.id] += ln.qty
        self.plan.component_issued[c.id] = round(self.plan.component_issued.get(c.id, 0.0) + ln.qty, 6)
        self.plan.wo_touched.add(w.id)
        self.trim_reservations(c.id, c.required_qty - self.issued[c.id])

    def _wo_return(self, i: int, ln: Any) -> None:
        c, w = self._component(i, ln.wo_component_id, "return")
        it = self.item(c.item_id, ["body", "lines", i, "wo_component_id"])
        lc = self.location(ln.location_id, ["body", "lines", i, "location_id"], inbound=True)
        self.whole(it, ln.qty, ["body", "lines", i, "qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=True)
        if ln.qty > self.issued[c.id] + EPS:
            raise _err("WO_RETURN_ABOVE_ISSUED", f"Only {_fmt(self.issued[c.id])} of {it.part_number} were issued to "
                       f"{w.number}.", ["body", "lines", i, "qty"])
        self.ensure_lot(it, ln.lot_code, None, "")
        self.issued[c.id] -= ln.qty
        self.plan.component_issued[c.id] = round(self.plan.component_issued.get(c.id, 0.0) - ln.qty, 6)
        self.inbound(i + 1, "wo_return", it, lc, ln.lot_code, ln.qty, None, unit_cost=it.standard_cost,
                     wo_id=w.id, wo_component_id=c.id)

    def _wo_receipt(self, i: int, ln: Any) -> None:
        w = self.ctx.work_orders.get(ln.wo_id)
        if w is None:
            raise _err("MFG_UNKNOWN_REFERENCE", f"Work order {ln.wo_id!r} was not found.",
                       ["body", "lines", i, "wo_id"], id=ln.wo_id)
        from .workorders import check_action

        check_action(w.status, "receipt")
        it = self.item(w.item_id, ["body", "lines", i, "wo_id"])
        lc = self.location(ln.location_id, ["body", "lines", i, "location_id"], inbound=True)
        self.whole(it, ln.qty, ["body", "lines", i, "qty"])
        self.whole(it, ln.scrap_qty, ["body", "lines", i, "scrap_qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=ln.qty > EPS)
        if ln.qty > EPS:
            self.ensure_lot(it, ln.lot_code, ln.expires_on, "")
        self.inbound(i + 1, "wo_receipt", it, lc, ln.lot_code, ln.qty, self.d, unit_cost=it.standard_cost,
                     wo_id=w.id, scrap_qty=round(ln.scrap_qty, 6) if ln.scrap_qty > EPS else None)
        self.completed[w.id] += ln.qty
        self.plan.wo_completed[w.id] = round(self.plan.wo_completed.get(w.id, 0.0) + ln.qty, 6)
        if ln.scrap_qty > EPS:
            self.plan.wo_scrapped[w.id] = round(self.plan.wo_scrapped.get(w.id, 0.0) + ln.scrap_qty, 6)
        self.plan.wo_touched.add(w.id)
        if self.completed[w.id] >= w.qty - EPS:
            self.release_reservations({c.id for c in self.ctx.components.values() if c.wo_id == w.id})

    def _ship(self, i: int, ln: Any) -> None:
        dl = self.ctx.demand_lines.get(ln.demand_line_id)
        if dl is None:
            raise _err("MFG_UNKNOWN_REFERENCE", f"Demand line {ln.demand_line_id!r} was not found.",
                       ["body", "lines", i, "demand_line_id"], id=ln.demand_line_id)
        if dl.order_status != "open":
            raise invalid_state("This demand order", dl.order_status, "ship", ["open"])
        it = self.item(dl.item_id, ["body", "lines", i, "demand_line_id"])
        lc = self.location(ln.location_id, ["body", "lines", i, "location_id"], inbound=False)
        self.whole(it, ln.qty, ["body", "lines", i, "qty"])
        self.lot_rules(it, ln.lot_code, ["body", "lines", i, "lot_code"], required=False)
        left = dl.qty - self.shipped[dl.id]
        if ln.qty > left + EPS:
            raise _err("DEM_OVER_SHIPMENT", f"Only {_fmt(max(0.0, left))} are still open on {dl.order_number} / "
                       f"{dl.line_no}.", ["body", "lines", i, "qty"])
        self.outbound(i + 1, "ship", it, lc, ln.lot_code, ln.qty, idx=i, unit_cost=it.standard_cost,
                      demand_line_id=dl.id)
        self.shipped[dl.id] += ln.qty
        self.plan.demand_shipped[dl.id] = round(self.plan.demand_shipped.get(dl.id, 0.0) + ln.qty, 6)


def resolve_txn_date(txn_date: date | None, today: date, *, system: bool = False) -> date:
    d = txn_date or today
    if not system and not (today - timedelta(days=INV_MAX_BACKDATE_DAYS) <= d <= today):
        raise _err("INV_BACKDATE_LIMIT", f"The posting date must be between "
                   f"{(today - timedelta(days=INV_MAX_BACKDATE_DAYS)).isoformat()} and {today.isoformat()}.",
                   ["body", "txn_date"])
    return d


def plan_posting(inp: Any, ctx: PostingContext) -> PostingPlan:
    """The whole effect of one posting (raises `RuleError` on the first problem; nothing is applied)."""
    d = resolve_txn_date(inp.txn_date, ctx.today, system=ctx.system)
    return _Planner(inp.type, ctx, d).run(inp)


def validate_posting(inp: Any, ctx: PostingContext) -> list[dict[str, Any]]:
    """`[]` if the posting would succeed, else the first error as `{status, code, message, details}`."""
    try:
        plan_posting(inp, ctx)
    except RuleError as e:
        return [{"status": e.status, "code": e.code, "message": e.message, "details": e.details}]
    return []


def pick_fefo(balances: Iterable[tuple[BalKey, float, date | None, bool]], qty: float, txn_date: date
              ) -> list[tuple[BalKey, float]]:
    """FEFO over `(key, available, expires_on, hold)` candidates (one item and location): earliest expiry (nulls
    last), then lot code; expired (`expires_on <= txn_date`) and held lots skipped. Short -> as much as possible."""
    cands = sorted(((e is None, e or date.max, k[2], k, av) for k, av, e, h in balances
                    if av > EPS and not h and (e is None or e > txn_date)))
    out = []
    rest = qty
    for *_x, k, av in cands:
        if rest <= EPS:
            break
        take = min(av, rest)
        out.append((k, round(take, 6)))
        rest -= take
    return out


# ---------------------------------------------------------------- reversal (4.2)


@dataclass
class OrigTxn:
    line_no: int
    txn_type: str
    item_id: str
    location_id: str
    lot_code: str | None
    qty: float
    unit_cost: float | None = None
    schedule_id: str | None = None
    wo_id: str | None = None
    wo_component_id: str | None = None
    demand_line_id: str | None = None
    scrap_qty: float | None = None


def plan_reversal(ptype: str, original: Iterable[OrigTxn], ctx: PostingContext, txn_date: date) -> PostingPlan:
    """The exact inverse of a posting (same type, every transaction negated) under the same stock rule: a negative
    inverse transaction needs that much available stock (409 `INV_INSUFFICIENT_STOCK`). Document quantities move
    back (received / issued / completed / shipped); the service re-derives statuses."""
    p = _Planner(ptype, ctx, txn_date)
    for o in original:
        it = ctx.items[o.item_id]
        lc = ctx.locations[o.location_id]
        q = -o.qty
        key = (o.item_id, o.location_id, o.lot_code or "")
        if q < 0:
            b = p.bal.get(key)
            if b is None or b.available < -q - EPS:
                raise p.insufficient(it, lc, o.lot_code, b, -q, o.line_no - 1)
            b.qty_on_hand += q
        else:
            p.balance(key).qty_on_hand += q
        p.plan.transactions.append(TxnPlan(o.line_no, o.txn_type, o.item_id, o.location_id, o.lot_code, round(q, 6),
                                           o.unit_cost, o.schedule_id, o.wo_id, o.wo_component_id, o.demand_line_id,
                                           scrap_qty=-o.scrap_qty if o.scrap_qty else None))
        if o.txn_type == "po_receipt" and o.schedule_id:
            p.plan.schedule_received[o.schedule_id] = round(p.plan.schedule_received.get(o.schedule_id, 0) + q, 6)
        elif o.txn_type in ("wo_issue", "wo_return") and o.wo_component_id:
            p.plan.component_issued[o.wo_component_id] = round(
                p.plan.component_issued.get(o.wo_component_id, 0) - q, 6)
            if o.wo_id:
                p.plan.wo_touched.add(o.wo_id)
        elif o.txn_type == "wo_receipt" and o.wo_id:
            p.plan.wo_completed[o.wo_id] = round(p.plan.wo_completed.get(o.wo_id, 0) + q, 6)
            if o.scrap_qty:
                p.plan.wo_scrapped[o.wo_id] = round(p.plan.wo_scrapped.get(o.wo_id, 0) - o.scrap_qty, 6)
            p.plan.wo_touched.add(o.wo_id)
        elif o.txn_type == "ship" and o.demand_line_id:
            p.plan.demand_shipped[o.demand_line_id] = round(p.plan.demand_shipped.get(o.demand_line_id, 0) - q, 6)
    for sid, dq in p.plan.schedule_received.items():
        if ctx.schedules[sid].received_qty + dq < -EPS:
            raise RuleError(409, "MFG_INVALID_STATE", "The receipt cannot be reversed: the schedule would go below "
                            "zero received.", {"status": "received", "action": "reverse", "allowed_from": []})
    return p.plan


__all__ = ["BalInfo", "CompInfo", "DemLineInfo", "ItemInfo", "LocInfo", "LotInfo", "NewLot", "OrigTxn",
           "PostingContext", "PostingPlan", "ResInfo", "SchedInfo", "TxnPlan", "WoInfo", "pick_fefo", "plan_posting",
           "plan_reversal", "resolve_txn_date", "validate_posting"]

"""Import planning of the M2 sheets (M2-DESIGN 11), called by `plan._Planner.run`.

Master sheets (`locations`, `suppliers`, `item_suppliers`) behave like M1 sheets (upsert by key, unchanged
detection). Transactional sheets are diffed against `ds.txn` (empty when not loaded):

- `stock` (`stock_mode` `set` | `add`): `set` changes become one `count` posting (reason `IMPORT`), `add` rows one
  `receipt_misc` posting; Change rows of table `stock` (`id` = (item id, location id, lot code)). A `set` below the
  reserved quantity -> `IMP_BELOW_RESERVED`. Balances not in the file are untouched.
- documents (purchase, demand, WO) upsert by number; `status` and the create-only quantities (`received_qty`,
  `shipped_qty`, `qty_completed`, `issued_qty`) apply only on create; read-only documents -> `IMP_READONLY_STATUS`;
  `replace_children` removes children missing from the file unless they carry receipts/shipments/issues
  (`IMP_IN_USE`). WOs without `wo_components` rows get generated components (7.2).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError

from ..bundle import SHEETS_BY_NAME
from ..dataset import TxnData
from ..model_m2 import EPS, ItemSupplierInput, LocationInput, SupplierInput
from ..units import is_count
from . import messages as msg

PR_STATUSES = ("draft", "submitted", "approved", "rejected", "ordered", "cancelled")
PO_STATUSES = ("draft", "open", "partially_received", "received", "closed", "cancelled")
READONLY = {"pr": ("submitted", "approved", "ordered", "cancelled"), "po": ("received", "closed", "cancelled"),
            "demand": ("closed", "cancelled"), "wo": ("completed", "closed", "cancelled")}
WO_STATUSES = ("planned", "released", "in_progress", "completed", "closed", "cancelled")


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


class M2Planner:
    def __init__(self, P: Any):
        from .plan import _data, _Ent

        self.P = P
        self.Ent = _Ent
        ds = P.ds
        self.locations = {x.code: _Ent(x.id, _data(x), False) for x in ds.locations.values()}
        self.suppliers = {x.code: _Ent(x.id, _data(x), False) for x in ds.suppliers.values()}
        self.txn: TxnData = ds.txn or TxnData()
        self.today: date | None = getattr(P.o, "today", None)

    # ------------------------------------------------------------ master
    def run(self) -> None:
        P = self.P
        P.simple("locations", LocationInput, self.locations, "locations", "loc_", P.ds.locations)
        defaults = [c for c, e in self.locations.items() if e.data.get("receipt_default") and e.data.get("active")]
        if len(defaults) > 1:
            for row, src in P.rows("locations"):
                if _s(row.get("code")) in defaults[1:]:
                    P.err("locations", src, "receipt_default", "IMP_BAD_VALUE",
                          "Only one active location can be the receipt default.")
        P.simple("suppliers", SupplierInput, self.suppliers, "suppliers", "sup_", P.ds.suppliers)
        self.item_suppliers()
        self.stock()
        self.purchase_docs()
        self.demand()
        self.work_orders()

    def item_suppliers(self) -> None:
        P = self.P
        from .plan import _data

        existing = {(r.item_id, r.supplier_id): (r.id, _data(r)) for r in P.ds.item_suppliers.values()}
        spec = SHEETS_BY_NAME["item_suppliers"]
        seen: dict[Any, int] = {}
        for row, src in P.rows("item_suppliers"):
            it = P.resolve("item_suppliers", src, "part_number", P.items, row.get("part_number"), "Part")
            sp = P.resolve("item_suppliers", src, "supplier_code", self.suppliers, row.get("supplier_code"),
                           "Supplier")
            if it is None or sp is None:
                if _blank(row.get("part_number")) or _blank(row.get("supplier_code")):
                    P.required("item_suppliers", row, src, True)
                continue
            if it.data.get("make_buy") != "buy":
                P.err("item_suppliers", src, "part_number", "IMP_BAD_VALUE",
                      f"{_s(row.get('part_number'))} is not a buy item.")
                continue
            key = (it.id, sp.id)
            if not P.dedupe("item_suppliers", src, seen, key, f"{_s(row.get('part_number'))} / "
                                                                  f"{_s(row.get('supplier_code'))}"):
                continue
            ex = existing.get(key)
            creating = ex is None
            base = dict(ex[1]) if ex else {}
            fields = [f for f in spec.fields if f not in ("part_number", "supplier_code")]
            d = P.merge(base, row, ItemSupplierInput, creating, fields)
            d.update(item_id=it.id, supplier_id=sp.id)
            inp = P.validate("item_suppliers", src, ItemSupplierInput, d)
            if inp is None:
                continue
            if is_count(it.data.get("uom", "EA")) and abs(inp.units_per_purchase_unit -
                                                          round(inp.units_per_purchase_unit)) > 1e-9:
                P.err("item_suppliers", src, "units_per_purchase_unit", "IMP_BAD_VALUE",
                      "A pack of a counted item must hold a whole number of units.")
                continue
            new = inp.model_dump()
            k = {"part_number": _s(row.get("part_number")), "supplier_code": _s(row.get("supplier_code"))}
            if creating:
                P.add("item_suppliers", "create", P.nid("isu_"), new)
                P.note("item_suppliers", "create", k)
            else:
                ch = P.diff(ex[1], new, ItemSupplierInput.model_fields)
                if ch:
                    P.add("item_suppliers", "update", ex[0], {f: new[f] for f in ch})
                P.note("item_suppliers", "update" if ch else "unchanged", k, ch)

    # ------------------------------------------------------------ helpers
    def item(self, sheet: str, src: Any, row: dict[str, Any], f: str = "part_number") -> Any:
        if _blank(row.get(f)):
            self.P.err(sheet, src, f, "IMP_REQUIRED", msg.required(f))
            return None
        return self.P.resolve(sheet, src, f, self.P.items, row.get(f), "Part")

    def num(self, sheet: str, src: Any, row: dict[str, Any], f: str, *, default: Any = None, positive: bool = False,
            item: Any = None, integer: bool = False) -> Any:
        v = row.get(f)
        if _blank(v):
            return default
        try:
            x = float(v)
        except (TypeError, ValueError):
            self.P.err(sheet, src, f, "IMP_BAD_NUMBER", f"{msg.label(f)}: not a number.")
            return None
        if x < 0 or (positive and x <= 0):
            self.P.err(sheet, src, f, "IMP_BAD_VALUE", f"{msg.label(f)} must be {'greater than' if positive else 'at least'} 0.")
            return None
        if integer:
            return int(x)
        if item is not None and is_count(item.data.get("uom", "EA")) and abs(x - round(x)) > EPS:
            self.P.err(sheet, src, f, "IMP_BAD_VALUE", f"{msg.label(f)}: {item.data.get('part_number')} is counted "
                       "in whole units.")
            return None
        return x

    def need(self, sheet: str, src: Any, row: dict[str, Any], f: str) -> bool:
        if _blank(row.get(f)):
            self.P.err(sheet, src, f, "IMP_REQUIRED", msg.required(f))
            return False
        return True

    def readonly(self, plan: Any, sheet: str, src: Any, number: str, status: str) -> None:
        """A document in a read-only status may appear unchanged in the file (round trip); any change ->
        `IMP_READONLY_STATUS`."""
        P = self.P
        n_changes, n_errors = len(P.changes), len(P.errors)
        plan()
        if len(P.changes) > n_changes or len(P.errors) > n_errors:
            del P.changes[n_changes:]
            del P.errors[n_errors:]
            P.err(sheet, src, "status", "IMP_READONLY_STATUS",
                  f"{number} is {status.replace('_', ' ')} and cannot be changed by an import.")

    # ------------------------------------------------------------ stock
    def stock(self) -> None:
        P = self.P
        mode = getattr(P.o, "stock_mode", "set")
        bal = {(b.item_id, b.location_id, b.lot_key): b for b in self.txn.balances.values()}
        lots = {(x.item_id, x.lot_code): x for x in self.txn.lots.values()}
        seen: dict[Any, int] = {}
        for row, src in P.rows("stock"):
            it = self.item("stock", src, row)
            if not self.need("stock", src, row, "location_code"):
                continue
            loc = P.resolve("stock", src, "location_code", self.locations, row.get("location_code"), "Location")
            if it is None or loc is None:
                continue
            lot = None if _blank(row.get("lot_code")) else _s(row.get("lot_code"))
            if it.data.get("lot_controlled") and lot is None:
                P.err("stock", src, "lot_code", "IMP_REQUIRED", f"{it.data['part_number']} is lot-controlled; enter "
                      "the lot code.")
                continue
            if not it.data.get("lot_controlled") and lot is not None:
                P.err("stock", src, "lot_code", "IMP_BAD_VALUE", f"{it.data['part_number']} is not lot-controlled.")
                continue
            key = (it.id, loc.id, lot or "")
            if not P.dedupe("stock", src, seen, key, f"{it.data['part_number']} / {_s(row.get('location_code'))}"
                                                    f"{' / ' + lot if lot else ''}"):
                continue
            if not self.need("stock", src, row, "qty"):
                continue
            qty = self.num("stock", src, row, "qty", item=it)
            if qty is None:
                continue
            b = bal.get(key)
            on, rs = (b.qty_on_hand, b.qty_reserved) if b else (0.0, 0.0)
            vals = {"item_id": it.id, "location_id": loc.id, "lot_code": lot, "expires_on": row.get("expires_on"),
                    "supplier_lot": _s(row.get("supplier_lot")), "qty": qty}
            k = {"part_number": it.data["part_number"], "location_code": _s(row.get("location_code")),
                 "lot_code": lot}
            if mode == "add":
                if qty <= EPS:
                    P.note("stock", "unchanged", k)
                    continue
                P.add("stock", "add", key, vals)
                P.note("stock", "update" if b else "create", k, {"qty": (on, on + qty)})
                continue
            if qty < rs - EPS:
                P.err("stock", src, "qty", "IMP_BELOW_RESERVED", f"{_s(qty)} is below the {rs:g} reserved; release "
                      "reservations first.")
                continue
            if abs(qty - on) <= EPS:
                P.note("stock", "unchanged", k)
                continue
            if lot and (it.id, lot) in lots and row.get("expires_on") is not None and \
                    lots[(it.id, lot)].expires_on != row.get("expires_on"):
                vals["expires_on"] = row.get("expires_on")
            P.add("stock", "set", key, vals)
            P.note("stock", "update" if b else "create", k, {"qty": (on, qty)})

    # ------------------------------------------------------------ purchase documents
    def purchase_docs(self) -> None:
        P = self.P
        docs = {(d.doc_type, d.number): d for d in self.txn.purchase_docs.values()}
        heads: dict[tuple[str, str], tuple[dict[str, Any], Any]] = {}
        seen: dict[Any, int] = {}
        for row, src in P.rows("purchase_docs"):
            if not (self.need("purchase_docs", src, row, "doc_type") and self.need("purchase_docs", src, row,
                                                                                     "number")):
                continue
            k = (_s(row["doc_type"]), _s(row["number"]))
            if P.dedupe("purchase_docs", src, seen, k, f"{k[0]} {k[1]}"):
                heads[k] = (row, src)
        lines: dict[tuple[str, str], list[tuple[dict[str, Any], Any]]] = {}
        for row, src in P.rows("purchase_lines"):
            if all(self.need("purchase_lines", src, row, f) for f in ("doc_type", "number", "line_no")):
                lines.setdefault((_s(row["doc_type"]), _s(row["number"])), []).append((row, src))
        scheds: dict[tuple[str, str, int], list[tuple[dict[str, Any], Any]]] = {}
        for row, src in P.rows("purchase_schedules"):
            if all(self.need("purchase_schedules", src, row, f) for f in ("doc_type", "number", "line_no", "seq")):
                scheds.setdefault((_s(row["doc_type"]), _s(row["number"]), int(row["line_no"])), []).append((row, src))
        for k in list(lines) + [x[:2] for x in scheds]:
            if k not in heads and k not in docs:
                src = (lines.get(k) or [(None, None)])[0][1] or next(v for kk, v in scheds.items() if kk[:2] == k)[0][1]
                sheet = "purchase_lines" if k in lines else "purchase_schedules"
                P.err(sheet, src, "number", "IMP_UNKNOWN_REFERENCE", msg.unknown_reference("Document", k[1]))
        for k in sorted(set(heads) | {x for x in set(lines) | {y[:2] for y in scheds} if x in docs}):
            self.plan_doc(k, heads.get(k), docs.get(k), lines.get(k, []), scheds)

    def plan_doc(self, k: tuple[str, str], head: Any, ex: Any, lrows: list[Any],
                 scheds: dict[tuple[str, str, int], list[Any]]) -> None:
        P = self.P
        dt, number = k
        if dt not in ("pr", "po"):
            return
        row, src = head if head else ({}, None)
        creating = ex is None
        if not creating and ex.status in READONLY[dt]:
            s0 = src or (lrows[0][1] if lrows else next(v for kk, v in scheds.items() if kk[:2] == k)[0][1])
            self.readonly(lambda: self.plan_doc(k, head, _Writable(ex), lrows, scheds),
                          "purchase_docs" if src else "purchase_lines", s0, number, ex.status)
            return
        if creating and src is None:
            return
        statuses = PR_STATUSES if dt == "pr" else PO_STATUSES
        status = _s(row.get("status")) or "draft"
        if creating and status not in statuses:
            P.err("purchase_docs", src, "status", "IMP_BAD_VALUE", f"{status!r} is not a {dt.upper()} status.")
            return
        sup = None
        if not _blank(row.get("supplier_code")):
            sup = P.resolve("purchase_docs", src, "supplier_code", self.suppliers, row.get("supplier_code"),
                            "Supplier")
            if sup is None:
                return
        sup_id = sup.id if sup else (ex.supplier_id if ex else None)
        if dt == "po" and sup_id is None:
            P.err("purchase_docs", src, "supplier_code", "IMP_REQUIRED", "A purchase order needs a supplier.")
            return
        hdr = {"supplier_id": sup_id,
               "currency": _s(row.get("currency")) if "currency" in row else (ex.currency if ex else
                                                                            (sup.data.get("currency", "") if sup else "")),
               "order_date": row.get("order_date") if "order_date" in row else (ex.order_date if ex else None),
               "note": _s(row.get("note")) if "note" in row else (ex.note if ex else ""),
               "external_ref": (None if _blank(row.get("external_ref")) else _s(row.get("external_ref")))
               if "external_ref" in row else (ex.external_ref if ex else None)}
        doc_id = ex.id if ex else P.nid("pdc_")
        key = {"doc_type": dt, "number": number}
        if creating:
            P.add("purchase_docs", "create", doc_id, {"doc_type": dt, "number": number, "status": status,
                                                      "source": "import", "source_run_no": None,
                                                      "rejected_reason": "", **hdr})
            P.note("purchase_docs", "create", key)
        elif head:
            old = {"supplier_id": ex.supplier_id, "currency": ex.currency, "order_date": ex.order_date,
                   "note": ex.note, "external_ref": ex.external_ref}
            ch = P.diff(old, hdr, hdr.keys())
            if ch:
                P.add("purchase_docs", "update", doc_id, {f: hdr[f] for f in ch})
            P.note("purchase_docs", "update" if ch else "unchanged", key, ch)
        old_lines = {ln.line_no: ln for ln in (ex.lines if ex else [])}
        line_seen: set[int] = set()
        for lrow, lsrc in lrows:
            ln_no = self.num("purchase_lines", lsrc, lrow, "line_no", integer=True)
            if ln_no is None or ln_no in line_seen:
                if ln_no is not None:
                    P.err("purchase_lines", lsrc, "line_no", "IMP_DUPLICATE_KEY", f"Line {ln_no} appears twice.")
                continue
            line_seen.add(ln_no)
            old = old_lines.get(ln_no)
            it = self.item("purchase_lines", lsrc, lrow) if ("part_number" in lrow or old is None) else None
            if it is None and old is None:
                continue
            if it is not None and it.data.get("make_buy") != "buy":
                P.err("purchase_lines", lsrc, "part_number", "IMP_BAD_VALUE", f"{it.data['part_number']} is not a "
                      "buy item.")
                continue
            item_id = it.id if it else old.item_id
            vals = {"line_no": ln_no, "item_id": item_id,
                    "unit_price": self.num("purchase_lines", lsrc, lrow, "unit_price") if "unit_price" in lrow
                    else (old.unit_price if old else None),
                    "note": _s(lrow.get("note")) if "note" in lrow else (old.note if old else "")}
            lk = {**key, "line_no": ln_no}
            if old is None:
                lid = P.nid("pln_")
                P.add("purchase_lines", "create", lid, {"doc_id": doc_id, "status": self._line_status(dt, status),
                                                        "source_pr_line_id": None, **vals})
                P.note("purchase_lines", "create", lk)
            else:
                lid = old.id
                if old.item_id != item_id and any(sc.received_qty > EPS for sc in old.schedules):
                    P.err("purchase_lines", lsrc, "part_number", "IMP_IN_USE", "A line with receipts cannot change "
                          "its item.")
                    continue
                oldv = {"line_no": old.line_no, "item_id": old.item_id, "unit_price": old.unit_price,
                        "note": old.note}
                ch = P.diff(oldv, vals, vals.keys())
                if ch:
                    P.add("purchase_lines", "update", lid, {f: vals[f] for f in ch})
                P.note("purchase_lines", "update" if ch else "unchanged", lk, ch)
            self.plan_scheds(k, ln_no, lid, old, scheds.get((dt, number, ln_no), []), creating, it or
                             P.items.get(P.item_by_id.get(item_id, "")))
        if P.o.replace_children and "purchase_lines" in P.b and old_lines:
            for no, old in old_lines.items():
                if no in line_seen:
                    continue
                if any(sc.received_qty > EPS or sc.id in self.txn.in_ledger for sc in old.schedules):
                    P.err("purchase_docs", src or lrows[0][1] if (src or lrows) else None, "number", "IMP_IN_USE",
                          f"{number} line {no} has receipts and cannot be removed.")
                    continue
                for sc in old.schedules:
                    P.add("purchase_schedules", "delete", sc.id)
                P.add("purchase_lines", "delete", old.id)
                P.count("purchase_lines", "delete")
        for (dt2, no2, ln2), rows in scheds.items():
            if (dt2, no2) == k and ln2 not in line_seen and ln2 not in old_lines:
                P.err("purchase_schedules", rows[0][1], "line_no", "IMP_UNKNOWN_REFERENCE",
                      msg.unknown_reference("Line", ln2))

    def _line_status(self, dt: str, status: str) -> str:
        return {"cancelled": "cancelled", "ordered": "converted", "closed": "closed"}.get(status, "open")

    def plan_scheds(self, k: tuple[str, str], ln_no: int, line_id: str, old_line: Any, rows: list[Any],
                    creating_doc: bool, it: Any) -> None:
        P = self.P
        old = {sc.seq: sc for sc in (old_line.schedules if old_line else [])}
        seen: set[int] = set()
        for row, src in rows:
            seq = self.num("purchase_schedules", src, row, "seq", integer=True)
            if seq is None or seq in seen:
                if seq is not None:
                    P.err("purchase_schedules", src, "seq", "IMP_DUPLICATE_KEY", f"Schedule {seq} appears twice.")
                continue
            seen.add(seq)
            o = old.get(seq)
            if o is None and not (self.need("purchase_schedules", src, row, "requested_date")
                                  and self.need("purchase_schedules", src, row, "qty")):
                continue
            qty = self.num("purchase_schedules", src, row, "qty", positive=True, item=it) if "qty" in row and \
                not _blank(row.get("qty")) else (o.qty if o else None)
            if qty is None:
                continue
            vals = {"seq": seq, "requested_date": row.get("requested_date") or (o.requested_date if o else None),
                    "confirmed_date": row.get("confirmed_date") if "confirmed_date" in row else
                    (o.confirmed_date if o else None), "qty": qty}
            sk = {"doc_type": k[0], "number": k[1], "line_no": ln_no, "seq": seq}
            if o is None:
                rec = self.num("purchase_schedules", src, row, "received_qty", default=0.0, item=it) \
                    if creating_doc or old_line is None else 0.0
                if rec is None:
                    continue
                P.add("purchase_schedules", "create", P.nid("psc_"), {"line_id": line_id, "received_qty": rec,
                                                                      "closed": False, **vals})
                P.note("purchase_schedules", "create", sk)
            else:
                if qty < o.received_qty - EPS:
                    P.err("purchase_schedules", src, "qty", "IMP_IN_USE", f"The quantity cannot go below the "
                          f"{o.received_qty:g} received.")
                    continue
                oldv = {"seq": o.seq, "requested_date": o.requested_date, "confirmed_date": o.confirmed_date,
                        "qty": o.qty}
                ch = P.diff(oldv, vals, vals.keys())
                if ch:
                    P.add("purchase_schedules", "update", o.id, {f: vals[f] for f in ch})
                P.note("purchase_schedules", "update" if ch else "unchanged", sk, ch)
        if P.o.replace_children and rows and old:
            for seq, o in old.items():
                if seq not in seen:
                    if o.received_qty > EPS or o.id in self.txn.in_ledger:
                        P.err("purchase_schedules", rows[0][1], "seq", "IMP_IN_USE",
                              f"Schedule {seq} has receipts and cannot be removed.")
                        continue
                    P.add("purchase_schedules", "delete", o.id)
                    P.count("purchase_schedules", "delete")

    # ------------------------------------------------------------ demand
    def demand(self) -> None:
        P = self.P
        orders = {o.number: o for o in self.txn.demand_orders.values()}
        heads: dict[str, Any] = {}
        seen: dict[Any, int] = {}
        for row, src in P.rows("demand_orders"):
            if self.need("demand_orders", src, row, "number") and \
                    P.dedupe("demand_orders", src, seen, _s(row["number"]), _s(row["number"])):
                heads[_s(row["number"])] = (row, src)
        lines: dict[str, list[Any]] = {}
        for row, src in P.rows("demand_lines"):
            if self.need("demand_lines", src, row, "number") and self.need("demand_lines", src, row, "line_no"):
                no = _s(row["number"])
                if no not in heads and no not in orders:
                    P.err("demand_lines", src, "number", "IMP_UNKNOWN_REFERENCE", msg.unknown_reference("Order", no))
                    continue
                lines.setdefault(no, []).append((row, src))
        for no in sorted(set(heads) | set(lines)):
            self.plan_order(no, heads.get(no), orders.get(no), lines.get(no, []))

    def plan_order(self, number: str, head: Any, ex: Any, lrows: list[Any]) -> None:
        P = self.P
        row, src = head if head else ({}, None)
        creating = ex is None
        if creating and src is None:
            return
        if not creating and ex.status in READONLY["demand"]:
            self.readonly(lambda: self.plan_order(number, head, _Writable(ex), lrows),
                          "demand_orders" if src else "demand_lines", src or lrows[0][1], number, ex.status)
            return
        if creating and not self.need("demand_orders", src, row, "demand_type"):
            return
        status = _s(row.get("status")) or "draft"
        if creating and status not in ("draft", "open", "closed", "cancelled"):
            P.err("demand_orders", src, "status", "IMP_BAD_VALUE", f"{status!r} is not a demand-order status.")
            return
        prio = self.num("demand_orders", src, row, "priority", integer=True) if "priority" in row and \
            not _blank(row.get("priority")) else (ex.priority if ex else 5)
        if prio is None or not 1 <= prio <= 9:
            P.err("demand_orders", src, "priority", "IMP_BAD_VALUE", "Priority must be 1..9.")
            return
        hdr = {"demand_type": _s(row.get("demand_type")) or (ex.demand_type if ex else ""),
               "customer": _s(row.get("customer")) if "customer" in row else (ex.customer if ex else ""),
               "program": (None if _blank(row.get("program")) else _s(row.get("program"))) if "program" in row
               else (ex.program if ex else None),
               "priority": prio, "note": _s(row.get("note")) if "note" in row else (ex.note if ex else ""),
               "external_ref": (None if _blank(row.get("external_ref")) else _s(row.get("external_ref")))
               if "external_ref" in row else (ex.external_ref if ex else None)}
        oid = ex.id if ex else P.nid("dmo_")
        key = {"number": number}
        if creating:
            P.add("demand_orders", "create", oid, {"number": number, "status": status, **hdr})
            P.note("demand_orders", "create", key)
        elif head:
            old = {f: getattr(ex, f) for f in hdr}
            ch = P.diff(old, hdr, hdr.keys())
            if ch:
                P.add("demand_orders", "update", oid, {f: hdr[f] for f in ch})
            P.note("demand_orders", "update" if ch else "unchanged", key, ch)
        old_lines = {ln.line_no: ln for ln in (ex.lines if ex else [])}
        seen: set[int] = set()
        for lrow, lsrc in lrows:
            ln_no = self.num("demand_lines", lsrc, lrow, "line_no", integer=True)
            if ln_no is None or ln_no in seen:
                if ln_no is not None:
                    P.err("demand_lines", lsrc, "line_no", "IMP_DUPLICATE_KEY", f"Line {ln_no} appears twice.")
                continue
            seen.add(ln_no)
            o = old_lines.get(ln_no)
            it = self.item("demand_lines", lsrc, lrow) if ("part_number" in lrow or o is None) else None
            if it is None and o is None:
                continue
            if it is not None and (not it.data.get("active", True) or it.data.get("make_buy") == "phantom"):
                P.err("demand_lines", lsrc, "part_number", "IMP_BAD_VALUE", f"{it.data['part_number']} cannot be "
                      "planned (inactive or phantom).")
                continue
            item_id = it.id if it else o.item_id
            iit = it or P.items.get(P.item_by_id.get(item_id, ""))
            if o is None and not (self.need("demand_lines", lsrc, lrow, "qty")
                                  and self.need("demand_lines", lsrc, lrow, "due_date")):
                continue
            qty = self.num("demand_lines", lsrc, lrow, "qty", positive=True, item=iit) if not _blank(lrow.get("qty")) \
                else (o.qty if o else None)
            if qty is None:
                continue
            sf = self.num("demand_lines", lsrc, lrow, "serial_from", integer=True) if "serial_from" in lrow else \
                (o.serial_from if o else None)
            st = self.num("demand_lines", lsrc, lrow, "serial_to", integer=True) if "serial_to" in lrow else \
                (o.serial_to if o else None)
            if (sf is None) != (st is None) or (sf is not None and (not (iit and iit.data.get("serialized"))
                                                                    or st - sf + 1 != round(qty))):
                P.err("demand_lines", lsrc, "serial_from", "IMP_BAD_VALUE", "The serial range must match the quantity "
                      "of a serialized item.")
                continue
            lp = self.num("demand_lines", lsrc, lrow, "priority", integer=True) if "priority" in lrow else \
                (o.priority if o else None)
            vals = {"line_no": ln_no, "item_id": item_id, "qty": qty,
                    "due_date": lrow.get("due_date") or (o.due_date if o else None), "serial_from": sf,
                    "serial_to": st, "priority": lp,
                    "note": _s(lrow.get("note")) if "note" in lrow else (o.note if o else "")}
            lk = {"number": number, "line_no": ln_no}
            if o is None:
                shipped = self.num("demand_lines", lsrc, lrow, "shipped_qty", default=0.0, item=iit) if creating \
                    else 0.0
                if shipped is None or shipped > qty + EPS:
                    P.err("demand_lines", lsrc, "shipped_qty", "IMP_BAD_VALUE", "shipped_qty cannot exceed qty.")
                    continue
                P.add("demand_lines", "create", P.nid("dml_"), {"order_id": oid, "shipped_qty": shipped, **vals})
                P.note("demand_lines", "create", lk)
            else:
                if qty < o.shipped_qty - EPS:
                    P.err("demand_lines", lsrc, "qty", "IMP_IN_USE", f"The quantity cannot go below the "
                          f"{o.shipped_qty:g} shipped.")
                    continue
                oldv = {f: getattr(o, f) for f in vals}
                ch = P.diff(oldv, vals, vals.keys())
                if ch:
                    P.add("demand_lines", "update", o.id, {f: vals[f] for f in ch})
                P.note("demand_lines", "update" if ch else "unchanged", lk, ch)
        if P.o.replace_children and lrows and old_lines:
            for no, o in old_lines.items():
                if no not in seen:
                    if o.shipped_qty > EPS or o.id in self.txn.in_ledger:
                        P.err("demand_lines", lrows[0][1], "line_no", "IMP_IN_USE", f"Line {no} has shipments and "
                              "cannot be removed.")
                        continue
                    P.add("demand_lines", "delete", o.id)
                    P.count("demand_lines", "delete")

    # ------------------------------------------------------------ work orders
    def work_orders(self) -> None:
        P = self.P
        wos = {w.number: w for w in self.txn.work_orders.values()}
        heads: dict[str, Any] = {}
        seen: dict[Any, int] = {}
        for row, src in P.rows("work_orders"):
            if self.need("work_orders", src, row, "number") and \
                    P.dedupe("work_orders", src, seen, _s(row["number"]), _s(row["number"])):
                heads[_s(row["number"])] = (row, src)
        comps: dict[str, list[Any]] = {}
        for row, src in P.rows("wo_components"):
            if self.need("wo_components", src, row, "wo_number"):
                no = _s(row["wo_number"])
                if no not in heads and no not in wos:
                    P.err("wo_components", src, "wo_number", "IMP_UNKNOWN_REFERENCE",
                          msg.unknown_reference("Work order", no))
                    continue
                comps.setdefault(no, []).append((row, src))
        if not heads and not comps:
            return
        planned = None
        for no in sorted(set(heads) | set(comps)):
            if no not in wos and planned is None:
                planned = P.planned_dataset()
            self.plan_wo(no, heads.get(no), wos.get(no), comps.get(no), planned)

    def plan_wo(self, number: str, head: Any, ex: Any, crows: list[Any] | None, planned: Any) -> None:
        P = self.P
        row, src = head if head else ({}, None)
        creating = ex is None
        if creating and src is None:
            return
        if not creating and ex.status in READONLY["wo"]:
            self.readonly(lambda: self.plan_wo(number, head, _Writable(ex), crows, planned),
                          "work_orders" if src else "wo_components", src or crows[0][1], number, ex.status)
            return
        key = {"number": number}
        if creating:
            if not all(self.need("work_orders", src, row, f) for f in ("part_number", "qty", "due_date")):
                return
            it = self.item("work_orders", src, row)
            if it is None:
                return
            if it.data.get("make_buy") != "make":
                P.err("work_orders", src, "part_number", "IMP_BAD_VALUE", f"{it.data['part_number']} is not a make "
                      "item.")
                return
            qty = self.num("work_orders", src, row, "qty", positive=True, item=it)
            done = self.num("work_orders", src, row, "qty_completed", default=0.0, item=it)
            prio = self.num("work_orders", src, row, "priority", integer=True, default=5)
            status = _s(row.get("status")) or "planned"
            if qty is None or done is None or prio is None:
                return
            if status not in WO_STATUSES or not 1 <= prio <= 9:
                P.err("work_orders", src, "status", "IMP_BAD_VALUE", "Unknown work-order status or priority.")
                return
            sf = self.num("work_orders", src, row, "serial_from", integer=True)
            st = self.num("work_orders", src, row, "serial_to", integer=True)
            if (sf is None) != (st is None) or (sf is not None and (not it.data.get("serialized")
                                                                    or st - sf + 1 != round(qty))):
                P.err("work_orders", src, "serial_from", "IMP_BAD_VALUE", "The serial range must match the quantity "
                      "of a serialized item.")
                return
            due = row.get("due_date")
            from .. import workorders as W
            from ..workdays import WorkCalendar

            start = row.get("start_date")
            if start is None:
                start = W.default_start_date(planned, it.id, qty, due, WorkCalendar(planned.plant.mrp_workdays,
                                                                                    W.plant_holidays(planned)),
                                             on=due, serial=sf)
            if start > due:
                P.err("work_orders", src, "start_date", "IMP_BAD_VALUE", "start_date must not be after due_date.")
                return
            expl = W.generate_components(planned, it.id, qty, on=max(start, self.today or start), serial=sf)
            wid = P.nid("wko_")
            P.add("work_orders", "create", wid, {
                "number": number, "item_id": it.id, "qty": qty, "qty_completed": done, "qty_scrapped": 0.0,
                "start_date": start, "due_date": due, "status": status, "priority": prio, "serial_from": sf,
                "serial_to": st, "bom_id": expl.bom_id, "routing_id": expl.routing_id, "demand_line_id": None,
                "source": "import", "source_run_no": None, "source_planned_no": None,
                "note": _s(row.get("note")), "external_ref": None if _blank(row.get("external_ref"))
                else _s(row.get("external_ref"))})
            P.note("work_orders", "create", key)
            if crows is None:
                for c in expl.components:
                    P.add("wo_components", "create", P.nid("woc_"), {
                        "wo_id": wid, "item_id": c.item_id, "required_qty": c.qty, "issued_qty": 0.0,
                        "operation_seq": c.operation_seq, "find_number": c.find_number, "alt_group": c.alt_group,
                        "bom_line_id": c.bom_line_id, "note": ""})
                P.count("wo_components", "create", len(expl.components))
            else:
                self.plan_comps(number, wid, [], crows, True, expl)
            return
        vals: dict[str, Any] = {}
        for f in ("start_date", "due_date"):
            if f in row and row[f] is not None:
                vals[f] = row[f]
        if "priority" in row and not _blank(row.get("priority")):
            vals["priority"] = self.num("work_orders", src, row, "priority", integer=True)
        if "qty" in row and not _blank(row.get("qty")):
            q = self.num("work_orders", src, row, "qty", positive=True)
            if q is not None and q < ex.qty_completed - EPS:
                P.err("work_orders", src, "qty", "IMP_IN_USE", "The quantity cannot go below the completed quantity.")
                return
            vals["qty"] = q
        if "note" in row:
            vals["note"] = _s(row.get("note"))
        if head:
            old = {f: getattr(ex, f) for f in vals}
            ch = P.diff(old, vals, vals.keys())
            if ch:
                P.add("work_orders", "update", ex.id, {f: vals[f] for f in ch})
            P.note("work_orders", "update" if ch else "unchanged", key, ch)
        if crows is not None:
            self.plan_comps(number, ex.id, ex.components, crows, False, None)

    def plan_comps(self, number: str, wo_id: str, old: list[Any], rows: list[Any], creating: bool, expl: Any
                   ) -> None:
        P = self.P
        oldk = {(c.item_id, c.find_number): c for c in old}
        seen: set[Any] = set()
        for row, src in rows:
            it = self.item("wo_components", src, row)
            if it is None:
                continue
            if it.data.get("make_buy") == "phantom":
                P.err("wo_components", src, "part_number", "IMP_BAD_VALUE", "A phantom is not a WO component.")
                continue
            fn = None if _blank(row.get("find_number")) else _s(row.get("find_number"))
            k = (it.id, fn)
            if k in seen:
                P.err("wo_components", src, "part_number", "IMP_DUPLICATE_KEY", "This component appears twice.")
                continue
            seen.add(k)
            o = oldk.get(k)
            if o is None and not self.need("wo_components", src, row, "required_qty"):
                continue
            req = self.num("wo_components", src, row, "required_qty", item=it) if not _blank(row.get("required_qty")) \
                else o.required_qty
            if req is None:
                continue
            ck = {"wo_number": number, "part_number": it.data["part_number"], "find_number": fn}
            vals = {"required_qty": req, "operation_seq": self.num("wo_components", src, row, "operation_seq",
                                                                   integer=True) if "operation_seq" in row
                    else (o.operation_seq if o else None),
                    "note": _s(row.get("note")) if "note" in row else (o.note if o else "")}
            if o is None:
                iss = self.num("wo_components", src, row, "issued_qty", default=0.0, item=it) if creating else 0.0
                if iss is None:
                    continue
                m = next((c for c in (expl.components if expl else ()) if c.item_id == it.id and c.find_number == fn),
                         None)
                P.add("wo_components", "create", P.nid("woc_"), {
                    "wo_id": wo_id, "item_id": it.id, "find_number": fn, "issued_qty": iss,
                    "alt_group": m.alt_group if m else None, "bom_line_id": m.bom_line_id if m else None, **vals})
                P.note("wo_components", "create", ck)
            else:
                if req < o.issued_qty - EPS:
                    P.err("wo_components", src, "required_qty", "IMP_IN_USE", "The required quantity cannot go below "
                          "the issued quantity.")
                    continue
                oldv = {f: getattr(o, f) for f in vals}
                ch = P.diff(oldv, vals, vals.keys())
                if ch:
                    P.add("wo_components", "update", o.id, {f: vals[f] for f in ch})
                P.note("wo_components", "update" if ch else "unchanged", ck, ch)
        if P.o.replace_children and old:
            for k, o in oldk.items():
                if k not in seen:
                    if o.issued_qty > EPS or o.id in self.txn.in_ledger:
                        P.err("wo_components", rows[0][1], "part_number", "IMP_IN_USE", "A component with issues "
                              "or transactions cannot be removed.")
                        continue
                    P.add("wo_components", "delete", o.id)
                    P.count("wo_components", "delete")


class _Writable:
    """A read-only document viewed as editable (to detect whether an import would change it)."""

    def __init__(self, ex: Any):
        self.__dict__.update(ex.__dict__)
        self.status = "draft" if hasattr(ex, "doc_type") or hasattr(ex, "demand_type") else "planned"


def _unused() -> None:  # pragma: no cover
    _ = ValidationError

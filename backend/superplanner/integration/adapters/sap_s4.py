"""`sap_s4` adapter (M8-DESIGN 9): SAP S/4HANA OData JSON (v2 `d.results`, v4 `value`) <-> `superplanner.v1`.

- `inbound(raw, filename)`: `raw` = `{"entity": <sap entity>, ...OData response...}` (or a list of them, or a
  file named `<sap entity>.json`) -> v1 batches (`upsert`); M8 extras (packaging levels, demand history) are kept on
  `self.extras` for the sync to apply.
- `outbound(event)`: `purchase_request.submitted` -> purchase requisition, `work_order.created` -> planned order
  (OData POST bodies; `Delivery.kind = "odata"`, the path in header `X-SAP-Path`); other events are not sent.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from ...mfg.model_m8 import SapSettings
from ..contract import V1Batch, V1Event
from ..sap import mapping as M
from ..sap.odata import page_of
from .base import Delivery

V1_ENTITY = {"item": "item", "supplier": "supplier", "item_supplier": "item_supplier", "stock_snapshot":
             "stock_snapshot", "purchase_order": "purchase_order", "demand_order": "demand_order", "bom": "bom",
             "routing": "routing"}


class SapS4:
    name = "sap_s4"

    def __init__(self, profile: SapSettings | None = None):
        self.profile = profile or SapSettings()
        self.extras: dict[str, list[dict[str, Any]]] = {}

    def map_page(self, entity: str, recs: list[dict[str, Any]]) -> list[V1Batch]:
        out = M.ENTITIES[entity][2](recs, self.profile)
        batches = []
        for key, rows in out.items():
            if not rows:
                continue
            if key in V1_ENTITY:
                batches.append(V1Batch.model_validate({"schema": "superplanner.v1", "entity": V1_ENTITY[key],
                                                       "mode": "upsert", "records": rows}))
            else:
                self.extras.setdefault(key, []).extend(rows)
        return batches

    def inbound(self, raw: bytes | dict[str, Any], filename: str | None) -> list[V1Batch]:
        data = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
        docs = data if isinstance(data, list) else [data]
        out: list[V1Batch] = []
        for doc in docs:
            entity = doc.get("entity") or (filename or "").rsplit("/", 1)[-1].split(".")[0]
            if entity not in M.ENTITIES:
                raise ValueError(f"unknown SAP entity {entity!r}")
            recs, _next = page_of({k: v for k, v in doc.items() if k != "entity"})
            out += self.map_page(entity, recs)
        return out

    def outbound(self, event: V1Event) -> list[Delivery]:
        d = event.data
        if event.type == "purchase_request.submitted":
            lines = d.get("lines") or []
            out = []
            for ln in lines:
                for sc in ln.get("schedules") or []:
                    path, body = M.planned_order_out({"kind": "buy", "part_number": (ln.get("item") or {}).get(
                        "part_number") or ln.get("item_id"), "qty": sc.get("qty"), "need_date": sc.get(
                        "requested_date"), "start_date": sc.get("requested_date"), "ref": d.get("number", "")},
                        self.profile)
                    out.append(Delivery("odata", json.dumps(body).encode(), {"X-SAP-Path": path}))
            return out
        if event.type == "work_order.created":
            path, body = M.planned_order_out({"kind": "make", "part_number": (d.get("item") or {}).get(
                "part_number") or d.get("item_id"), "qty": d.get("qty"), "need_date": d.get("due_date"),
                "start_date": d.get("start_date") or d.get("due_date"), "ref": d.get("number", "")}, self.profile)
            return [Delivery("odata", json.dumps(body).encode(), {"X-SAP-Path": path})]
        return []

    def snapshot(self, entity: str) -> Iterable[Any] | None:
        return None                  # pulled by the `sap_sync` job (services/sap.py)

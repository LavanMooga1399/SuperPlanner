"""A fake S/4HANA OData server (httpx MockTransport) over the recorded payloads: paging (`__next`), CSRF token
fetch / expiry, POST capture, errors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

import superplanner.integration.sap as sap_pkg

FIX = Path(sap_pkg.__file__).resolve().parent / "fixtures"
BASE = "https://localhost/sap/opu/odata/sap/"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIX / name).read_text())


class FakeS4:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.gets: list[str] = []
        self.token = "tok-1"
        self.expire_next_post = False
        self.fail: dict[str, int] = {}
        self.counter = 0
        self.prefer: list[str] = []
        self.foreign_next = False
        self.fail_posts_after: int | None = None

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "GET" and req.headers.get("x-csrf-token") == "fetch":
            return httpx.Response(200, headers={"x-csrf-token": self.token, "set-cookie": "SAP_SESSIONID=abc; path=/"})
        if req.method == "GET":
            self.gets.append(str(req.url))
            self.prefer.append(req.headers.get("prefer", ""))
            if "$top" in str(req.url) or "%24top" in str(req.url):      # a real server: $top = client limit, no
                body = load("product_v2_page1.json")                     # next link (review 4)
                body["d"]["results"] = body["d"]["results"][:1]
                body["d"].pop("__next", None)
                return httpx.Response(200, json=body)
            if self.foreign_next and path.endswith("/A_Product"):
                body = load("product_v2_page1.json")
                body["d"]["__next"] = "https://evil.example.net/steal?x=1"
                return httpx.Response(200, json=body)
            for frag, code in self.fail.items():
                if frag in path:
                    return httpx.Response(code, json={"error": {"code": "X", "message": {"value": "Boom secret"}}})
            if path.endswith("/A_Product"):
                page2 = "skiptoken" in str(req.url)
                return httpx.Response(200, json=load("product_v2_page2.json" if page2 else "product_v2_page1.json"))
            name = {"A_Supplier": "supplier_v2.json", "A_PurchasingInfoRecord": "info_record_v2.json",
                    "A_MatlStkInAcctMod": "stock_v2.json", "A_PurchaseOrder": "purchase_order_v2.json",
                    "A_SalesOrder": "sales_order_v4.json", "A_BillingDocumentItem": "billing_v2.json",
                    "MaterialBOM": "bom_v2.json"}[path.rsplit("/", 1)[-1]]
            return httpx.Response(200, json=load(name))
        if req.method == "POST":
            if self.fail_posts_after is not None and len(self.posts) >= self.fail_posts_after:
                return httpx.Response(500, json={"error": {"code": "SY/530", "message": {"value": "dump secret"}}})
            if req.headers.get("x-csrf-token") != self.token or self.expire_next_post:
                self.expire_next_post = False
                self.token = f"tok-{len(self.posts) + 2}"
                return httpx.Response(403, headers={"x-csrf-token": "Required"},
                                      json={"error": {"message": {"value": "CSRF token validation failed"}}})
            body = json.loads(req.content)
            self.posts.append((path, body, dict(req.headers)))
            self.counter += 1
            key = "PlannedOrder" if "PlannedOrder" in path else "PurchaseRequisition"
            return httpx.Response(201, json={"d": {key: f"{10000000 + self.counter}"}})
        return httpx.Response(405)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

"""M6 test helpers: a Kavach world in accounts mode (owner / planner / viewer) with a live MRP run and a published
schedule, and a swappable fake model client (never the real API)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, sign_up
from superplanner.assistant.fake import FakeClient


class Holder:
    def __init__(self) -> None:
        self.client: Any = FakeClient([])

    def factory(self) -> Any:
        return self.client


@dataclass
class World:
    app: Any
    holder: Holder
    owner: TestClient
    planner: TestClient
    viewer: TestClient
    owner_id: str
    run_id: str

    def api(self, who: str = "owner") -> Api:
        c = getattr(self, who)
        return Api(c) if who == "owner" else Api(c).at(self.owner_id)

    def script(self, script: Any) -> FakeClient:
        self.holder.client = FakeClient(script)
        return self.holder.client


def wait_aps(api: Api, run_id: str, timeout: float = 180) -> dict[str, Any]:
    t = time.monotonic()
    while (r := api.get(f"/aps/runs/{run_id}"))["status"] in ("queued", "running"):
        assert time.monotonic() - t < timeout, r["status"]
        time.sleep(0.2)
    return r


def build_world(db_url: str, **settings: Any) -> World:
    holder = Holder()
    settings.setdefault("assistant_ai_enabled", True)
    app = acc_app(db_url, assistant_ai_client_factory=holder.factory, **settings)
    owner = sign_up(app, "owner@kv.example")
    planner = sign_up(app, "planner@kv.example")
    viewer = sign_up(app, "viewer@kv.example")
    oid = owner.get(f"{V1}/auth/session").json()["user"]["id"]
    api = Api(owner)
    api.post("/members", {"email": "planner@kv.example", "roles": ["planner"]})
    api.post("/members", {"email": "viewer@kv.example", "roles": ["viewer"]})
    api.load("kavach")
    api.post("/mrp/runs", {})
    run = wait_aps(api, api.post("/aps/runs", {"improve_seconds": 0, "overtime": "suggest"}, status=202)["id"])
    assert run["status"] == "completed", run
    api.post(f"/aps/runs/{run['id']}/publish", {}, status=200, version=run["row_version"])
    return World(app, holder, owner, planner, viewer, oid, run["id"])


def ask(api: Api, text: str, *, context: dict[str, Any] | None = None, allow_whatif: bool = False,
        conversation: str | None = None, timeout: float = 200) -> dict[str, Any]:
    conv = conversation or api.post("/assistant/conversations", {})["id"]
    acc = api.post(f"/assistant/conversations/{conv}/turns", {"text": text, "context": context,
                                                               "allow_whatif": allow_whatif}, status=202)
    t = time.monotonic()
    while (turn := api.get(f"/assistant/turns/{acc['turn_id']}"))["status"] in ("queued", "running"):
        assert time.monotonic() - t < timeout
        time.sleep(0.05)
    return turn


def late_demand_line(api: Api) -> dict[str, Any]:
    run = api.get("/mrp/runs/latest")
    rows = api.get(f"/mrp/runs/{run['id']}/demand", late_only=True, limit=50)["items"]
    assert rows, "the Kavach sample has late demand"
    return rows[0]

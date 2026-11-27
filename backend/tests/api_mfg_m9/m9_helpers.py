"""An organisation world for M9 tests: plants QC (CA, CAD) and US1 (US, USD), DC DCUS (US, USD), the network
workspace NET; the org admin is plant admin everywhere."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, sign_up


@dataclass
class World:
    app: Any
    admin: TestClient
    org: dict[str, Any]
    plants: dict[str, dict[str, Any]] = field(default_factory=dict)   # code -> org plant record
    net_owner: str = ""

    def api(self, code: str) -> Api:
        return Api(self.admin, self.net_owner if code == "NET" else self.plants[code]["plant_owner_id"])

    @property
    def net(self) -> Api:
        return self.api("NET")

    def owner(self, code: str) -> str:
        return self.net_owner if code == "NET" else self.plants[code]["plant_owner_id"]

    def person(self, email: str, roles: dict[str, list[str]]) -> TestClient:
        """A second person, member of the org, with plant roles per code."""
        c = sign_up(self.app, email)
        uid = c.get(f"{V1}/auth/session").json()["user"]["id"]
        r = self.admin.post(f"{V1}/orgs/{self.org['id']}/members", json={"email": email})
        assert r.status_code == 201, r.text
        assert c.post(f"{V1}/orgs/{self.org['id']}/accept").status_code == 200
        for code, rs in roles.items():
            plant = "NET" if code == "NET" else self.plants[code]["id"]
            if code == "NET":
                plant = self.net_owner
            r = self.admin.post(f"{V1}/orgs/{self.org['id']}/plants/{plant}/roles", json={"user_id": uid, "roles": rs})
            assert r.status_code == 200, r.text
        c.user_id = uid   # type: ignore[attr-defined]
        return c


def make_world(app: Any, slug: str = "demo", email: str = "admin@demo.example", network: bool = True) -> World:
    admin = sign_up(app, email)
    r = admin.post(f"{V1}/orgs", json={"name": slug.title(), "slug": slug})
    assert r.status_code == 201, r.text
    w = World(app, admin, r.json())
    for code, name, kind, country, ccy, tz in (("QC", "Quebec City", "plant", "CA", "CAD", "America/Toronto"),
                                              ("US1", "US plant 1", "plant", "US", "USD", "America/Chicago"),
                                              ("DCUS", "DC United States", "dc", "US", "USD", "America/Chicago")):
        r = admin.post(f"{V1}/orgs/{w.org['id']}/plants", json={"code": code, "name": name, "kind": kind,
                                                               "country": country, "currency": ccy, "time_zone": tz})
        assert r.status_code == 201, r.text
        w.plants[code] = r.json()
    if network:
        r = admin.post(f"{V1}/orgs/{w.org['id']}/network", json={"name": "Network"})
        assert r.status_code == 201, r.text
        w.net_owner = r.json()["owner_id"]
    return w


def app_for(db_url: str) -> Any:
    return acc_app(db_url, org_self_service=True)

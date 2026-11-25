"""Helpers for tests/api_mfg_m7: an accounts-mode plant with QA members, enrolment, TOTP and signing."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from apimfgm2_helpers import PASSWORD, V1, Api, acc_app, sign_up
from superplanner.identity import totp

KEY = Fernet.generate_key().decode()


@dataclass
class Person:
    email: str
    client: TestClient
    api: Api
    user_id: str
    totp_secret: str | None = None
    _step: int = field(default=0)

    def code(self) -> str:
        """A TOTP code of a step not used yet (WINDOW = 1: now-1 .. now+1; each step once)."""
        assert self.totp_secret is not None
        now = int(time.time() // 30)
        self._step = max(self._step + 1, now - 1)
        assert self._step <= now + 1, "out of TOTP steps in this 30 s window"
        return totp.code_at(self.totp_secret, self._step * 30 + 1)


class World:
    def __init__(self, db_url: str, **settings: Any):
        settings.setdefault("secrets_keys", [KEY])
        self.app = acc_app(db_url, **settings)
        self.tc = TestClient(self.app)
        self.tc.__enter__()
        self.owner = self._person("owner@m7.example", None)
        self.oid = self.owner.user_id
        self.people: dict[str, Person] = {"owner": self.owner}

    def close(self) -> None:
        self.tc.__exit__(None, None, None)

    def _person(self, email: str, workspace: str | None) -> Person:
        c = sign_up(self.app, email)
        uid = c.get(f"{V1}/auth/session").json()["user"]["id"]
        return Person(email, c, Api(c, workspace), uid)

    def member(self, name: str, roles: list[str], enroll: bool = True, with_totp: bool = False) -> Person:
        p = self._person(f"{name}@m7.example", self.oid)
        self.owner.api.post("/members", {"email": p.email, "roles": roles})
        if with_totp:
            self.totp(p)
        if enroll:
            self.enroll(p, name.title() + " Tremblay")
        self.people[name] = p
        return p

    def enroll(self, p: Person, legal: str) -> dict[str, Any]:
        r = p.client.post(f"{V1}/auth/esig/enroll", json={"legal_name": legal, "password": PASSWORD,
                                                          "acknowledgement": True})
        assert r.status_code == 200, r.text
        return r.json()

    def totp(self, p: Person) -> None:
        r = p.client.post(f"{V1}/auth/totp/setup", json={})
        assert r.status_code == 200, r.text
        p.totp_secret = r.json()["secret"]
        r = p.client.post(f"{V1}/auth/totp/enable", json={"code": p.code()})
        assert r.status_code == 200, r.text

    def part11_on(self) -> dict[str, Any]:
        o = self.owner
        if o.totp_secret is None:
            self.totp(o)
        if o.client.get(f"{V1}/auth/esig/status").json()["enrolled"] is False:
            self.enroll(o, "Olivier Owner")
        sig = signature(o, "plant", "plant", "part11_on", "approved", totp_code=o.code())
        return o.api.req("PUT", "/plant/part11", 200, json={"enabled": True, "signature": sig}).json()


def preview(p: Person, record_type: str, record_id: str, action: str, decision: str | None = None) -> dict[str, Any]:
    params = {"record_type": record_type, "record_id": record_id, "action": action}
    if decision:
        params["decision"] = decision
    return p.api.get("/esig/preview", **params)


def signature(p: Person, record_type: str, record_id: str, action: str, meaning: str, *, password: str = PASSWORD,
              totp_code: str | None = None, decision: str | None = None, content_hash: str | None = None,
              comment: str = "Reviewed") -> dict[str, Any]:
    h = content_hash or preview(p, record_type, record_id, action, decision)["content_hash"]
    out: dict[str, Any] = {"meaning": meaning, "content_hash": h, "username": p.email, "password": password,
                           "comment": comment}
    if totp_code is not None:
        out["totp_code"] = totp_code
    return out


__all__ = ["KEY", "PASSWORD", "Person", "World", "preview", "signature"]

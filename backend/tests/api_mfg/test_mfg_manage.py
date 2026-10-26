"""B3-7: `manage.py reassign-owner` refuses a target that owns mfg rows (M1-DESIGN 14.1)."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from apimfg_helpers import API, MFG, PASSWORD, Mfg, acc_app, make_app, row_counts
from superplanner import manage


def run(url: str, *argv: str, stdin: str = "") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = manage.main(["--url", url, *argv], out=out, err=err, stdin=io.StringIO(stdin))
    return code, out.getvalue(), err.getvalue()


def _sign_in(c: TestClient, email: str) -> None:
    r = c.post(f"{API}/auth/sign-in", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]


def test_reassign_owner_guard_and_move(db_url):
    with TestClient(make_app(db_url)) as c:                       # single_user data, owned by usr_local
        Mfg(c).load("small")
    for email in ("busy@example.com", "empty@example.com"):
        assert run(db_url, "create-user", "--email", email, "--password-stdin", stdin=PASSWORD)[0] == 0
    app = acc_app(db_url)
    with TestClient(app) as c:
        _sign_in(c, "busy@example.com")
        assert c.post(f"{MFG}/items", json={"part_number": "MINE", "make_buy": "buy"}).status_code == 201
        before = row_counts(app)
        for extra in ((), ("--dry-run",)):
            code, out, err = run(db_url, "reassign-owner", "--from", "usr_local", "--to-email", "busy@example.com",
                                 *extra)
            assert code == 1, (out, err)
            assert "already has manufacturing data" in err and "mfg_items: 1" in err and "mfg_plant: 1" in err
        assert row_counts(app) == before
        assert len(c.get(f"{MFG}/items").json()["items"]) == 1
        # a target that only looked at the Manufacturing area is not blocked
        e = TestClient(app)
        _sign_in(e, "empty@example.com")
        assert e.get(f"{MFG}/summary").status_code == 200 and e.get(f"{MFG}/plant").json()["id"] is None
        code, out, err = run(db_url, "reassign-owner", "--from", "usr_local", "--to-email", "empty@example.com")
        assert code == 0, err
        assert "mfg_items: 10" in out and "mfg_bom_lines: 9" in out
        assert e.get(f"{MFG}/summary").json()["counts"]["items"] == 10
        assert e.get(f"{MFG}/health", params={"as_of": "2026-11-02"}).json()["ok"] is True

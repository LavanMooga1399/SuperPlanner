"""S0 (M6-DESIGN 8): the frozen contract examples validate against the M6 models and are reproducible; the new
routes answer with their permissions; settings defaults (assistant off, push / SMTP off)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from apimfgm2_helpers import Api, acc_app, make_app, sign_up
from superplanner.api.config import Settings
from superplanner.api.mfg.access import ROLE_PERMISSIONS, roles_allowed
from superplanner.assistant import model as A
from superplanner.mfg import model_m4 as M4
from superplanner.mfg import model_m6 as M
from superplanner.push import model as P

FIX = Path(__file__).resolve().parents[2] / "superplanner" / "assistant" / "fixtures" / "example_m6.json"
V1 = "/api/v1"


def test_fixture_validates_and_is_reproducible(tmp_path):
    fx = json.loads(FIX.read_text(encoding="utf-8"))
    pairs = {"assistant_status": A.AssistantStatus, "assistant_status_unavailable": A.AssistantStatus,
             "conversation": A.ConversationRecord, "conversation_detail": A.ConversationDetail,
             "turn_input": A.TurnInput, "turn_accepted": A.TurnAccepted, "turn_running": A.TurnRecord,
             "turn_completed": A.TurnRecord, "turn_failed": A.TurnRecord, "draft_applied": A.DraftApplied,
             "quick_why_late": A.QuickExplanation, "vapid_public_key": P.VapidPublicKey,
             "push_subscription_input": P.PushSubscriptionInput, "push_subscription": P.PushSubscriptionRecord,
             "push_payload": P.PushPayload, "dashboard": M.Dashboard, "org_dashboard": M.OrgDashboard,
             "thresholds_input": M.ThresholdsInput, "digest_input": M.DigestInput, "digest": M.DigestRecord,
             "approvals": M.Approvals, "downtime_acknowledged": M4.DowntimeRecord}
    for key, model in pairs.items():
        model.model_validate(fx[key])
    turn = fx["turn_completed"]
    assert len(turn["drafts"]) == 2 and {c["ref"] for c in turn["citations"]} == {"R1", "R2", "R3", "R4"}
    assert [s["kind"] for s in turn["steps"]].count("tool") >= 3
    assert set(fx["dashboard"]["tiles"]) == set(M.TILE_NAMES)
    before = FIX.read_bytes()
    subprocess.run([sys.executable, str(FIX.with_name("build_example.py"))], check=True, capture_output=True)
    assert FIX.read_bytes() == before


def test_defaults_are_off():
    s = Settings(database_url="postgresql+psycopg://u:p@localhost/x", sp_env="development")
    assert s.assistant_ai_enabled is False and s.push_enabled is False and s.smtp_enabled is False
    assert s.database_read_url is None and s.assistant_daily_tokens_per_user == 400_000
    assert roles_allowed("assistant_use") == ["owner", "plant_admin", "planner", "purchaser", "store_keeper",
                                              "approver", "viewer", "supervisor"]
    assert "assistant_use" not in ROLE_PERMISSIONS["operator"]


def test_routes_answer(db_url):
    with TestClient(make_app(db_url)) as c:
        api = Api(c)
        st = api.get("/assistant/status")
        assert st["available"] is False and st["code"] == "AI_DISABLED" and st["privacy_notice"].startswith(
            "The assistant sends")
        conv = api.post("/assistant/conversations", {})
        e = api.err("POST", f"/assistant/conversations/{conv['id']}/turns", 422, "AI_DISABLED",
                    json={"text": "why late"})
        assert e["details"]["code"] == "AI_DISABLED"
        assert api.get("/assistant/conversations")["total"] == 1
        assert api.get(f"/assistant/conversations/{conv['id']}")["history"] == []
        api.err("GET", "/assistant/turns/ast_" + "0" * 32, 404, "NOT_FOUND")
        q = api.get("/assistant/quick", kind="limits")
        assert q["kind"] == "limits" and q["empty_message"]
        assert api.put("/plant/assistant", {"assistant_enabled": False, "assistant_allow_whatif": False}, 0)[
            "assistant_enabled"] is False
        assert api.get("/approvals") == {"items": [], "counts": {"pr": 0, "eco": 0, "replan_proposal": 0,
                                                                  "overtime": 0}}
        assert set(api.get("/dashboard")["tiles"]) == set(M.TILE_NAMES)
        r = c.get(f"{V1}/push/vapid-public-key")
        assert r.status_code == 200 and r.json()["enabled"] is False
        r = c.post(f"{V1}/push/subscriptions", json=json.loads(FIX.read_text())["push_subscription_input"])
        assert r.status_code == 422 and r.json()["error"]["code"] == "PUSH_DISABLED"
        r = c.post(f"{V1}/digests", json={"scope": "plant", "scope_id": "usr_local"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "DIGEST_NO_SMTP"
        assert c.get(f"{V1}/digests").json() == {"items": [], "smtp_enabled": False}
        api.delete(f"/assistant/conversations/{conv['id']}")


def test_operator_cannot_use_the_assistant(db_url):
    app = acc_app(db_url)
    owner = sign_up(app, "owner@m6.example")
    op = sign_up(app, "op@m6.example")
    oid = owner.get(f"{V1}/auth/session").json()["user"]["id"]
    Api(owner).post("/members", {"email": "op@m6.example", "roles": ["operator"]})
    a = Api(op).at(oid)
    e = a.err("GET", "/assistant/status", 403, "MFG_FORBIDDEN")
    assert e["details"]["permission"] == "assistant_use"
    a.err("PUT", "/plant/assistant", 403, "MFG_FORBIDDEN", json={"assistant_enabled": False})
    assert a.get("/assistant/quick", kind="changes")["kind"] == "changes"     # quick explanations: view

"""Builds `example_m6.json` (M6 S0 contract examples, validated by the M6 models):
`python superplanner/assistant/fixtures/build_example.py`."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from superplanner.assistant import model as A  # noqa: E402
from superplanner.mfg import model_m4 as M4  # noqa: E402
from superplanner.mfg import model_m6 as M  # noqa: E402
from superplanner.push import model as P  # noqa: E402

T0 = datetime(2026, 11, 6, 4, 30, tzinfo=timezone.utc)
V1 = "/api/v1"


def iid(p, n):
    return f"{p}_{n:032x}"


def J(model, d):
    return json.loads(model.model_validate(d).model_dump_json(by_alias=True))


def t(sec):
    return (T0 + timedelta(seconds=sec)).isoformat()


conv_id, turn_id = iid("asc", 1), iid("ast", 1)
run_live, line_smt = iid("apr", 12), iid("lin", 3)
po_id, dl_id = iid("pdc", 7), iid("dln", 10)
citations = [
    {"ref": "R1", "type": "demand_line", "id": dl_id, "label": "DO-KV-003/10 (KV-TPU-1000 x 40, due 2026-11-20)",
     "link": f"/mfg/demand/{iid('dor', 3)}?line={dl_id}"},
    {"ref": "R2", "type": "mrp_exception", "id": "mrx_42", "label": "KV-FPGA-7A short 120 on 2026-11-12",
     "link": f"/mfg/mrp/runs/{iid('mrr', 5)}/exceptions?item={iid('itm', 22)}"},
    {"ref": "R3", "type": "purchase_order", "id": po_id, "label": "PO-000231 line 1 (KV-FPGA-7A, dock 2026-11-18)",
     "link": f"/mfg/purchasing/orders/{po_id}"},
    {"ref": "R4", "type": "aps_bottleneck", "id": line_smt, "label": "SMT-1 load 112% week 47",
     "link": f"/mfg/schedule/runs/{run_live}?view=load&line={line_smt}"},
]
drafts = [
    {"draft_id": iid("drf", 1), "kind": "open_overtime",
     "summary": "Re-run schedule 12 with the suggested Saturday shift on SMT-1 (2026-11-14 06:00-14:00) opened: saves "
                "2.5 days of tardiness on DO-KV-003/10 [R4].",
     "method": "POST", "path": f"{V1}/mfg/aps/runs",
     "body": {"copy_of": run_live, "open_shifts": [{"line_id": line_smt, "start": "2026-11-14T06:00:00+05:30",
                                                    "end": "2026-11-14T14:00:00+05:30"}]},
     "required_permission": "schedule_run", "allowed": True},
    {"draft_id": iid("drf", 2), "kind": "expedite_po_schedule",
     "summary": "Ask the supplier to pull PO-000231 line 1 forward from 2026-11-18 to 2026-11-11 (needed date) [R3].",
     "method": "PUT", "path": f"{V1}/mfg/purchase-orders/{po_id}",
     "body": {"supplier_id": iid("sup", 2), "currency": "INR", "order_date": "2026-10-20",
              "note": "Assistant draft: expedite schedule 1 of line 1 to 2026-11-11 for DO-KV-003/10 - agree with "
                      "the supplier before saving.",
              "lines": [{"id": iid("pln", 1), "line_no": 1, "item_id": iid("itm", 22), "unit_price": 5400.0,
                         "note": "", "schedules": [{"id": iid("psc", 1), "seq": 1, "requested_date": "2026-11-11",
                                                    "confirmed_date": None, "qty": 120}]}]},
     "if_match_of": {"type": "purchase_order", "id": po_id, "row_version": 4},
     "required_permission": "po_edit", "allowed": False},
]
steps = [
    {"at": t(0), "kind": "thinking", "summary": "thinking"},
    {"at": t(4), "kind": "tool", "name": "demand_status", "summary": "tool: demand_status (DO-KV-003/10)"},
    {"at": t(9), "kind": "tool", "name": "mrp_pegging", "summary": "tool: mrp_pegging (KV-FPGA-7A)"},
    {"at": t(13), "kind": "tool", "name": "overtime_options", "summary": "tool: overtime_options"},
    {"at": t(14), "kind": "tool", "name": "draft_action", "summary": "tool: draft_action (open_overtime)"},
    {"at": t(15), "kind": "tool", "name": "draft_action", "summary": "tool: draft_action (expedite_po_schedule)"},
    {"at": t(21), "kind": "answer", "summary": "answer"},
]
answer = ("**DO-KV-003/10 is projected 6 days late** [R1]. Two causes:\n\n"
          "1. **Material**: KV-FPGA-7A is short 120 on 2026-11-12 [R2]; the covering PO-000231 docks on 2026-11-18 "
          "[R3].\n2. **Capacity**: SMT-1 is loaded 112% in week 47 [R4].\n\n"
          "Options (drafts below, nothing has been changed):\n\n- open the suggested Saturday shift on SMT-1 "
          "(saves 2.5 days);\n- ask the supplier to expedite PO-000231 to 2026-11-11.")
turn_done = {"id": turn_id, "conversation_id": conv_id, "status": "completed",
             "user_text": "Why is DO-KV-003/10 late and what can I do?",
             "context": {"type": "demand_line", "id": dl_id}, "allow_whatif": False, "steps": steps,
             "answer": answer, "citations": citations, "drafts": drafts, "model": "claude-opus-5-5",
             "fallback_code": None, "tokens": {"input": 18400, "output": 910, "cache_read": 12000}, "rounds": 3,
             "created_at": t(0), "started_at": t(0), "finished_at": t(21)}
turn_running = dict(turn_done, id=iid("ast", 2), status="running", steps=steps[:3], answer=None, citations=[],
                    drafts=[], finished_at=None, tokens={"input": 9100, "output": 240, "cache_read": 6000}, rounds=2)
turn_failed = dict(turn_done, id=iid("ast", 3), status="failed", steps=steps[:1], answer=None, citations=[],
                   drafts=[], error={"code": "AI_CONNECTION_ERROR", "message": "The AI service could not be reached. "
                                     "Use the quick explanations, or try again later."},
                   tokens={"input": 0, "output": 0, "cache_read": 0}, rounds=0)
conv = {"id": conv_id, "title": "Why is DO-KV-003/10 late", "allow_whatif": False, "created_at": t(0),
        "updated_at": t(21), "turns": 1}
status_ok = {"available": True, "code": None, "message": "", "budget_left": {"user": 381600, "plant": 1963000},
             "plant": {"assistant_enabled": True, "assistant_allow_whatif": True}, "model": "claude-opus-5-5"}
quick = {"kind": "why_late", "title": "Why is DO-KV-003/10 late?",
         "subject": {"type": "demand_line", "id": dl_id, "label": "DO-KV-003/10"},
         "sections": [{"title": "Material (latest MRP run 5)", "items": [
             {"text": "Projected 2026-11-26, 6 days after the due date 2026-11-20.", "refs": ["Q1"]},
             {"text": "Limiting path: KV-FPGA-7A short 120, covered by PO-000231 docking 2026-11-18.",
              "refs": ["Q2", "Q3"]}]},
                      {"title": "Schedule (published run 12)", "items": [
             {"text": "Late chain: SMT-1 op 20 waits for capacity (load 112% week 47).", "refs": ["Q4"]}]}],
         "citations": [dict(c, ref=c["ref"].replace("R", "Q")) for c in citations],
         "sources": ["GET /mfg/mrp/runs/{id}/demand", "GET /mfg/aps/runs/{id}/demand"]}


def tile(value, unit, status, drill, **kw):
    return {"value": value, "unit": unit, "status": status, "drill": drill, **kw}


tiles = {
    "otd": tile(0.91, "%", "watch", [{"label": "Demand lines of the week", "path": "/mfg/demand?due_week=2026-W45"}],
                trend=[{"period": "2026-W42", "value": 0.88}, {"period": "2026-W43", "value": 0.93},
                       {"period": "2026-W44", "value": 0.9}, {"period": "2026-W45", "value": 0.91}],
                thresholds={"alert_below": 0.85, "watch_below": 0.95}, details={"wo_on_time": 0.87}),
    "backlog": tile(1.04, "%", "watch", [{"label": "Load view", "path": f"/mfg/schedule/runs/{run_live}?view=load"}],
                    details={"weeks_4": {"required_h": 1460.0, "capacity_h": 1400.0, "load": 1.04},
                             "weeks_8": {"required_h": 2310.0, "capacity_h": 2800.0, "load": 0.83},
                             "by_stage": [{"stage": "SMT", "load_4w": 1.12, "load_8w": 0.9}],
                             "beyond_horizon_h": 120.0}),
    "material_risk": tile(7, "count", "watch", [{"label": "Short items", "path": "/mfg/mrp?short_only=1"}],
                          details={"items_short_4w": 7, "value_short_4w": 182400.0, "currency": "INR",
                                   "late_lines_material": 3, "risk_lines_below_80": 2}),
    "execution": tile(0.82, "%", "ok", [{"label": "KPIs", "path": "/mfg/kpis"}],
                      details={"adherence": 0.82, "oee": 0.71, "fpy": 0.985, "scrap_rate": 0.006}),
    "inventory": tile(12650000.0, "INR", "ok", [{"label": "Stock by family", "path": "/mfg/inventory?by=family"}],
                      details={"turns": None, "turns_note": "n/a until 3 monthly snapshots exist",
                               "by_family": [{"family": "FPGA", "value": 4200000.0}]}),
    "late_pos": tile(4, "count", "watch", [{"label": "Delivery board", "path": "/mfg/purchasing/schedule?overdue=1"}],
                     details={"by_supplier": [{"supplier": {"id": iid("sup", 2), "code": "AVN", "name": "Avnet"},
                                               "open_overdue": 2, "lateness_12m": 0.18}]}),
    "quality": tile(1, "count", "alert", [{"label": "Recalls", "path": "/mfg/recalls"}],
                    details={"open_recalls": 1, "ecos_by_status": {"submitted": 2, "approved": 1},
                             "top_scrap_reasons": [{"reason": "SOLDER_BRIDGE", "qty": 14}]}),
    "integration": tile(0, "count", "ok", [{"label": "Integration console", "path": "/integration"}],
                        details={"dead_deliveries": 0, "failed_batches_7d": 0, "stale_reconciliation": False}),
}
plant = {"owner_id": "usr_" + "1" * 32, "name": "Kavach Hyderabad", "currency": "INR", "time_zone": "Asia/Kolkata"}
dashboard = {"as_of": t(0), "period": "13w", "plant": plant, "tiles": tiles, "source": "primary", "computed_ms": 412}
org_dash = {"as_of": t(0), "period": "13w", "org": {"id": iid("org", 1), "name": "HBL"},
            "plants": [{"plant": {"owner_id": plant["owner_id"], "code": "HYD", "name": plant["name"]},
                        "tiles": tiles}],
            "totals": {"otd": tile(0.91, "%", "watch", [], details={"weights": "due demand lines per plant"})},
            "computed_ms": 990}
fx = {
    "_doc": "M6 S0 contract examples (M6-DESIGN 5). Ids are synthetic; the turn is the scripted 'why late' turn.",
    "assistant_status": J(A.AssistantStatus, status_ok),
    "assistant_status_unavailable": J(A.AssistantStatus, dict(status_ok, available=False, code="AI_DISABLED",
                                                              message="The assistant is switched off on this server.")),
    "assistant_settings": J(A.AssistantPlantSettings, {"assistant_enabled": True, "assistant_allow_whatif": False}),
    "conversation_input": J(A.ConversationInput, {"title": "", "allow_whatif": False}),
    "conversation": J(A.ConversationRecord, conv),
    "conversation_detail": J(A.ConversationDetail, dict(conv, history=[turn_done])),
    "turn_input": J(A.TurnInput, {"text": "Why is DO-KV-003/10 late and what can I do?",
                                  "context": {"type": "demand_line", "id": dl_id}, "allow_whatif": False}),
    "turn_accepted": J(A.TurnAccepted, {"turn_id": turn_id, "conversation_id": conv_id, "status": "queued"}),
    "turn_running": J(A.TurnRecord, turn_running),
    "turn_completed": J(A.TurnRecord, turn_done),
    "turn_failed": J(A.TurnRecord, turn_failed),
    "draft_applied": J(A.DraftApplied, {"status": "succeeded", "response_ref": iid("apr", 13)}),
    "quick_why_late": J(A.QuickExplanation, quick),
    "errors": {
        "turn_running_409": {"error": {"code": "AI_TURN_RUNNING", "message": "Your previous question is still being "
                                       "answered.", "details": {"turn_id": iid("ast", 2)}}},
        "plant_opted_out_422": {"error": {"code": "AI_PLANT_OPTED_OUT", "message": "The assistant is switched off "
                                          "for this plant.", "details": {"code": "AI_PLANT_OPTED_OUT"}}},
        "budget_422": {"error": {"code": "AI_BUDGET_EXCEEDED", "message": "The daily assistant budget is used up.",
                                 "details": {"code": "AI_BUDGET_EXCEEDED", "budget_left": {"user": 1000,
                                                                                           "plant": 900000}}}},
        "whatif_422": {"error": {"code": "AI_WHATIF_NOT_ALLOWED", "message": "What-if runs by the assistant are "
                                 "not allowed in this plant.", "details": {"code": "AI_WHATIF_NOT_ALLOWED"}}},
        "digest_no_smtp_422": {"error": {"code": "DIGEST_NO_SMTP", "message": "E-mail digests need an SMTP server; "
                                         "ask your administrator.", "details": {}}},
        "push_disabled_422": {"error": {"code": "PUSH_DISABLED", "message": "Push notifications are not set up on "
                                        "this server.", "details": {}}},
        "db_unavailable_503": {"error": {"code": "DB_UNAVAILABLE", "message": "The database is switching over; try "
                                         "again in a few seconds.", "details": {"retry_after": 5}}},
    },
    "vapid_public_key": J(P.VapidPublicKey, {"enabled": True, "public_key": "B" + "A" * 86}),
    "push_subscription_input": J(P.PushSubscriptionInput, {
        "endpoint": "https://fcm.googleapis.com/fcm/send/dXq3...", "keys": {
            "p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
            "auth": "BTBZMqHH6r4Tts7J_aSIgg"}, "topics": ["critical_alerts", "approvals"]}),
    "push_subscription": J(P.PushSubscriptionRecord, {"id": iid("psb", 1), "endpoint_host": "fcm.googleapis.com",
                                                      "topics": ["critical_alerts", "approvals"],
                                                      "user_agent": "Chrome/131 Android", "created_at": t(0)}),
    "push_payload": J(P.PushPayload, {"title": "SMT-1 is down", "body": "Downtime reported 10:12 (feeder jam).",
                                      "link": "/m/lines/" + line_smt, "topic": "critical_alerts"}),
    "dashboard": J(M.Dashboard, dashboard),
    "org_dashboard": J(M.OrgDashboard, org_dash),
    "thresholds_input": J(M.ThresholdsInput, {"thresholds": {"otd": {"alert_below": 0.8, "watch_below": 0.9}}}),
    "digest_input": J(M.DigestInput, {"scope": "plant", "scope_id": plant["owner_id"], "frequency": "weekly",
                                      "local_time": "07:30", "weekday": 0}),
    "digest": J(M.DigestRecord, {"id": iid("dgs", 1), "scope": "plant", "scope_id": plant["owner_id"],
                                 "scope_label": plant["name"], "frequency": "weekly", "local_time": "07:30",
                                 "weekday": 0, "time_zone": "Asia/Kolkata", "created_at": t(0)}),
    "approvals": J(M.Approvals, {"items": [
        {"kind": "pr", "id": iid("pdc", 9), "number": "PR-000044", "title": "PR-000044 (Avnet, 3 lines)",
         "summary": "INR 648,000", "waiting_since": t(-7200), "permission": "pr_approve", "row_version": 3,
         "actions": [{"label": "Approve", "method": "POST", "path": f"{V1}/mfg/purchase-requests/{iid('pdc', 9)}"
                      "/approve", "body": {}},
                     {"label": "Reject", "method": "POST", "path": f"{V1}/mfg/purchase-requests/{iid('pdc', 9)}"
                      "/reject", "body": {"reason": ""}}], "link": f"/mfg/purchasing/requests/{iid('pdc', 9)}"},
        {"kind": "overtime", "id": f"{run_live}:{line_smt}:2026-11-14T00:30:00Z", "number": "12",
         "title": "Saturday shift on SMT-1 (2026-11-14 06:00-14:00)", "summary": "saves 2.5 days of tardiness",
         "permission": "schedule_run", "actions": [{"label": "Accept", "method": "POST", "path": f"{V1}/mfg/aps/runs",
                                                    "body": {"copy_of": run_live, "open_shifts": [
                                                        {"line_id": line_smt, "start": "2026-11-14T00:30:00Z",
                                                         "end": "2026-11-14T08:30:00Z"}]}}],
         "link": f"/mfg/schedule/runs/{run_live}?view=overtime"}],
        "counts": {"pr": 1, "eco": 0, "replan_proposal": 0, "overtime": 1}}),
    "downtime_acknowledged": J(M4.DowntimeRecord, {
        "id": iid("dtm", 1), "row_version": 2, "created_at": t(-600), "updated_at": t(0),
        "line": {"id": line_smt, "code": "SMT-1", "name": "SMT line 1"}, "kind": "breakdown", "planned": False,
        "start_at": t(-600), "open": True, "reason": "Feeder jam", "note": "",
        "acknowledged_by": {"id": "usr_" + "2" * 32, "code": "", "name": "Ravi (supervisor)"},
        "acknowledged_at": t(0)}),
}
out = Path(__file__).with_name("example_m6.json")
out.write_text(json.dumps(fx, indent=1, sort_keys=False) + "\n", encoding="utf-8")
print(f"wrote {out}")

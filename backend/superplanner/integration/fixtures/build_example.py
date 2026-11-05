"""Builds `example_m5.json` (M5 S0 contract examples, validated by the M5 models):
`python superplanner/integration/fixtures/build_example.py`."""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from superplanner.identity import schemas as I  # noqa: E402
from superplanner.integration import contract as C  # noqa: E402
from superplanner.integration import model as IM  # noqa: E402
from superplanner.mfg import model_m5 as M  # noqa: E402
from superplanner.orgs import model as O  # noqa: E402

T0 = datetime(2026, 11, 5, 3, 30, tzinfo=timezone.utc)


def iid(p, n):
    return f"{p}_{n:032x}"


def J(model, d):
    return json.loads(model.model_validate(d).model_dump_json(by_alias=True))


st = {"row_version": 1, "created_at": T0.isoformat(), "updated_at": T0.isoformat()}
item = {"id": iid("itm", 1), "part_number": "KV-TPU-1000", "revision": "A", "description": "TPU", "uom": "EA",
        "make_buy": "make", "active": True}
lot = {"id": iid("lot", 1), "part_number": "KV-CAP-100N", "lot_code": "SUPP-2611"}
tree = J(M.TraceNode, {"kind": "serial", "id": iid("ser", 1), "item": item, "label": "TPU-26-0001", "qty": 1,
                       "precision": "exact", "at": T0.isoformat(), "status": "shipped",
                       "link": f"/mfg/serials/{iid('ser', 1)}", "depth": 0, "children": [
    {"kind": "wo", "id": iid("wko", 1), "label": "WO-000150", "qty": 3, "precision": "exact", "depth": 1,
     "link": f"/mfg/work-orders/{iid('wko', 1)}", "children": [
        {"kind": "lot", "id": lot["id"], "label": "KV-CAP-100N lot SUPP-2611", "qty": 120, "precision": "possible",
         "depth": 2, "children": []},
        {"kind": "serial", "id": iid("ser", 2), "label": "PCB-26-0417", "qty": 1, "precision": "exact",
         "depth": 2, "children": []}]}]})
fx = {
    "_doc": "M5 S0 contract examples (M5-DESIGN 9). Ids are synthetic.",
    "auth_config": J(I.AuthConfig, {"mode": "accounts", "sso_enabled": True, "sso_label": "HBL sign-in",
                                    "sso_required_domains": ["hbl.example"], "password_login": True}),
    "totp_setup": J(I.TotpSetupOut, {"secret": "JBSWY3DPEHPK3PXP", "otpauth_uri":
                                     "otpauth://totp/SuperPlanner:ana%40hbl.example?secret=JBSWY3DPEHPK3PXP"}),
    "totp_2fa_required_403": {"error": {"code": "AUTH_2FA_REQUIRED", "message": "Enter the code from your "
                                        "authenticator app.", "details": {"pending_token": "x" * 43,
                                                                          "setup_required": False}}},
    "token_created": J(I.TokenCreated, {"id": iid("tok", 1), "kind": "personal", "name": "ERP middleware",
                                        "prefix": "spt_Ab12Cd34", "scopes": ["integration.read", "integration.write"],
                                        "workspace_owner_id": "usr_" + "0" * 32, "expires_at": (T0 + timedelta(
                                            days=90)).isoformat(), "created_at": T0.isoformat(),
                                        "token": "spt_" + "A" * 43}),
    "org": J(O.OrgRecord, {"id": iid("org", 1), "name": "HBL", "slug": "hbl", "require_2fa": True,
                           "my_role": "org_admin", "plants": 2, "members": 14, "row_version": 1,
                           "created_at": T0.isoformat()}),
    "org_plant": J(O.OrgPlantRecord, {"id": iid("orp", 1), "code": "HYD", "name": "Hyderabad",
                                      "plant_owner_id": "usr_" + "1" * 32, "my_roles": ["plant_admin"],
                                      "row_version": 1, "created_at": T0.isoformat()}),
    "org_overview": J(O.OrgOverview, {"org": {"id": iid("org", 1), "name": "HBL"}, "plants": [
        {"plant": {"code": "HYD", "owner_id": "usr_" + "1" * 32}, "visible": True,
         "kpis": {"otd": 0.92, "oee": 0.71}, "late_demand": 2, "open_triggers": 3,
         "integration": {"enabled": True, "dead_deliveries": 0, "last_batch_at": T0.isoformat()}}]}),
    "integration_settings": J(IM.SettingsRecord, {"enabled": True, "adapter": "generic_v1", "plant_code": "HYD",
                                                  "sor": dict(IM.SOR_DEFAULTS), "goods_receipts_owner": "superplanner",
                                                  "filedrop_enabled": True, "export_enabled": False,
                                                  "export_interval_minutes": 15, "row_version": 3}),
    "batch_body": {"schema": "superplanner.v1", "entity": "item", "mode": "upsert", "records": [
        J(C.ItemV1, {"ref": "MAT-100045", "part_number": "KV-CAP-100N", "description": "Capacitor 100n",
                     "uom": "NOS"})]},
    "batch_result": J(C.BatchResult, {"id": iid("inb", 1), "entity": "item", "mode": "upsert", "status": "completed",
                                      "counts": {"created": 1, "rejected": 1}, "received_at": T0.isoformat(),
                                      "results": [{"ref": "MAT-100045", "status": "created", "id": iid("itm", 9)},
                                                  {"ref": "MAT-100046", "status": "rejected",
                                                   "errors": [{"code": "INT_UNMAPPED_VALUE", "message":
                                                               "Unit 'BOX' has no value map."}]}]}),
    "event": J(C.V1Event, {"schema": "superplanner.v1", "id": 1042, "type": "work_order.released",
                           "occurred_at": T0.isoformat(), "plant": {"code": "HYD", "owner_id": "usr_" + "1" * 32},
                           "actor": "usr_" + "2" * 32, "data": {"id": iid("wko", 1), "number": "WO-000150"}}),
    "events_page": {"items": [], "next_after": 1042},
    "endpoint": J(IM.EndpointRecord, {"id": iid("iep", 1), "name": "ERP middleware", "url":
                                      "https://erp-mw.hbl.example/sp", "event_types": [], "active": True,
                                      "cursor": 1041, "pending": 1, "dead": 0, "row_version": 1,
                                      "created_at": T0.isoformat()}),
    "delivery": J(IM.DeliveryRecord, {"id": iid("dlv", 1), "endpoint_id": iid("iep", 1), "event_seq": 1042,
                                      "event_type": "work_order.released", "status": "pending", "attempts": 2,
                                      "next_attempt_at": (T0 + timedelta(minutes=1)).isoformat(),
                                      "last_error": "HTTP 503", "last_status_code": 503,
                                      "created_at": T0.isoformat()}),
    "reconciliation": J(IM.ReconciliationRecord, {"id": iid("irc", 1), "entities": ["stock"], "status": "completed",
                                                  "summary": {"stock": {"different": 1, "missing_in_sp": 0,
                                                                        "missing_in_erp": 0, "sor_conflicts": 0}},
                                                  "results": {"stock": {"different": [{"item": "KV-CAP-100N",
                                                                                       "location": "STORES",
                                                                                       "lot": "", "sp_qty": 98,
                                                                                       "erp_qty": 100,
                                                                                       "delta": 2}]}},
                                                  "created_at": T0.isoformat(), "finished_at": T0.isoformat()}),
    "trace": J(M.TraceResult, {"root": tree, "direction": "backward", "depth": 30, "nodes": 4}),
    "where_used": {"items": [{"kind": "wo", "id": iid("wko", 1), "label": "WO-000150", "precision": "exact"}],
                   "truncated": False},
    "recall_body": {"name": "Capacitor lot SUPP-2611", "sources": [{"item_id": iid("itm", 5),
                                                                    "supplier_lot": "SUPP-2611"}]},
    "recall": J(M.RecallRecord, {"id": iid("rcl", 1), "number": "RCL-000001", "name": "Capacitor lot SUPP-2611",
                                 "sources": [{"item_id": iid("itm", 5), "supplier_lot": "SUPP-2611"}],
                                 "include_possible": True, **st, "report": {
        "units": [{"serial": "TPU-26-0001", "item": "KV-TPU-1000", "status": "shipped", "precision": "possible",
                   "customer": "Railway zone A", "demand_order": "DO-KV-003", "shipped_on": "2026-11-03",
                   "path": ["SUPP-2611", "WO-000150", "TPU-26-0001"]}],
        "lots": [{"lot_code": "SUPP-2611", "item": "KV-CAP-100N", "on_hand": 380, "location": "STORES"}],
        "wos": [{"number": "WO-000150", "status": "completed"}],
        "by_customer": [{"customer": "Railway zone A", "units": 1}], "by_program": [], "open_pos": []}}),
    "eco_body": {"title": "Replace C14 capacitor", "reason": "Supplier EOL", "effectivity": {"mode": "date",
                                                                                           "date": "2027-01-01"}},
    "eco": J(M.ChangeRequestRecord, {"id": iid("ecr", 1), "number": "ECO-000001", "title": "Replace C14 capacitor",
                                     "reason": "Supplier EOL", "kind": "eco", "source": "manual", "status": "draft",
                                     "priority": 5, "effectivity": {"mode": "date", "date": "2027-01-01"},
                                     "note": "", **st, "items": [{"id": iid("eci", 1), "doc_type": "bom",
                                                                  "doc_id": iid("bom", 2),
                                                                  "supersedes_doc_id": iid("bom", 1),
                                                                  "disposition": {"open_wos": "flag",
                                                                                  "open_pos": "flag_cancel",
                                                                                  "stock": "use_up"}}]}),
    "eco_impact": J(M.ImpactResult, {"cr_id": iid("ecr", 1), "effectivity": {"mode": "date", "date": "2027-01-01"},
                                     "explosion_delta": [{"parent": "KV-PCB-CPU", "removed": ["KV-CAP-100N"],
                                                          "added": ["KV-CAP-100N-B"], "changed": []}],
                                     "open_wos": [{"number": "WO-000150", "component": "KV-CAP-100N", "qty": 30}],
                                     "phase_out_stock": [{"item": "KV-CAP-100N", "on_hand": 380, "on_order": 1000,
                                                          "value": 1140.0}],
                                     "use_up_date": "2027-02-14", "computed_ms": 2100}),
    "transfer_body": {"dest_plant_owner_id": "usr_" + "3" * 32, "lines": [
        {"item_id": iid("itm", 5), "qty": 100, "ship_date": "2026-11-10", "receive_date": "2026-11-12"}]},
    "transfer": J(M.TransferOrderRecord, {"id": iid("tro", 1), "number": "TO-000001", "direction": "out",
                                          "status": "open", "source_plant": {"owner_id": "usr_" + "1" * 32,
                                                                             "code": "HYD"},
                                          "dest_plant": {"owner_id": "usr_" + "3" * 32, "code": "BLR"}, **st,
                                          "lines": [{"id": iid("trl", 1), "line_no": 1, "item_id": iid("itm", 5),
                                                     "qty": 100, "shipped_qty": 0, "received_qty": 0,
                                                     "ship_date": "2026-11-10", "receive_date": "2026-11-12"}]}),
    "audit_event": J(M.AuditEventRecord, {"id": 1, "entity_type": "mfg_item", "entity_id": iid("itm", 1),
                                          "action": "create", "details": {}, "actor_id": "usr_local",
                                          "owner_id": "usr_local", "created_at": T0.isoformat(),
                                          "chain_hash": "0" * 64}),
}
if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "example_m5.json"
    out.write_text(json.dumps(fx, indent=1) + "\n")
    print("written", out)

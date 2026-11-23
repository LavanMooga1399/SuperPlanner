"""Build and validate `example_m7.json` (M7-DESIGN 11 S0): one typed example per M7 record and input, validated
against `esig.model` / `qa.model`. The UI's `contractExamplesM7.ts` mirrors this file.

    python -m superplanner.qa.fixtures.build_example        # rewrite example_m7.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...esig import model as E
from .. import model as Q

OUT = Path(__file__).resolve().parent / "example_m7.json"
TS = "2026-11-23T19:05:12.000000Z"
TS2 = "2026-11-23T19:40:02.000000Z"


def _id(prefix: str, n: int) -> str:
    return f"{prefix}{n:032x}"


ITEM = {"id": _id("itm_", 1), "part_number": "SYR-3ML-LL", "revision": "A", "name": "Syringe 3 mL Luer lock"}
USER_A, USER_B = _id("usr_", 1), _id("usr_", 2)
STAMP = {"row_version": 1, "created_at": TS, "updated_at": TS}
MANIFEST = {"id": _id("esg_", 1), "meaning": "approved", "meaning_label": "Approved",
            "signer_legal_name": "Marie Tremblay", "signer_username": "mtremblay@example.com", "signed_at": TS,
            "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)", "auth_method": "password", "action": "approve",
            "step": 1, "status": "valid", "record_version": 3, "comment": "", "content_matches_current": True}
SIGNATURE_INPUT = {"meaning": "approved", "content_hash": "a" * 64, "username": "mtremblay@example.com",
                   "password": "correct horse battery staple", "comment": "Reviewed against drawing rev C"}
CHAR = {"id": _id("ich_", 1), "seq": 10, "code": "PULL", "name": "Needle pull force", "kind": "variable",
        "severity": "critical", "unit": "N", "nominal": 40.0, "lsl": 22.0, "usl": None, "method": "ISO 7864 pull test",
        "equipment_class": "FORCE", "sample_override": None, "destructive": True}
CHAR2 = {"id": _id("ich_", 2), "seq": 20, "code": "VIS", "name": "Visual: no particles", "kind": "attribute",
         "severity": "major", "unit": None, "nominal": None, "lsl": None, "usl": None, "method": "Visual, 2x",
         "equipment_class": None, "sample_override": None, "destructive": False}
VERDICT = {"verdict": "pending", "characteristics": [
    {"characteristic_id": CHAR["id"], "code": "PULL", "n": 13, "ac": 0, "re": 1, "entered": 2, "defective": 0,
     "verdict": "pending"},
    {"characteristic_id": CHAR2["id"], "code": "VIS", "n": 125, "ac": 2, "re": 3, "entered": 0, "defective": 0,
     "verdict": "pending"}]}
RESULT = {"id": _id("irs_", 1), "characteristic_id": CHAR["id"], "sample_no": 1, "value": 41.7, "passed": True,
          "defects": 0, "equipment_id": _id("eqp_", 1), "note": "", "reason": None, "entered_by": USER_A,
          "entered_at": TS, "corrects_result_id": None, "superseded": False}
TABLE = {"levels": ["S-4", "II"], "lot_size_ranges": [
    {"min": 1, "max": 1200, "letters": {"S-4": "E", "II": "J"}},
    {"min": 1201, "max": 3200, "letters": {"S-4": "G", "II": "K"}},
    {"min": 3201, "max": None, "letters": {"S-4": "H", "II": "L"}}],
    "plans": {"normal": {"E": {"0.65": {"n": 13, "ac": 0, "re": 1}}, "G": {"0.65": {"n": 32, "ac": 0, "re": 1}},
                         "H": {"0.65": {"n": 50, "ac": 1, "re": 2}}, "J": {"0.65": {"n": 80, "ac": 1, "re": 2}},
                         "K": {"0.65": {"n": 125, "ac": 2, "re": 3}}, "L": {"0.65": {"n": 200, "ac": 3, "re": 4}}},
              "tightened": {"E": {"0.65": {"n": 20, "ac": 0, "re": 1}}, "G": {"0.65": {"n": 50, "ac": 0, "re": 1}},
                            "H": {"0.65": {"n": 80, "ac": 1, "re": 2}}, "J": {"0.65": {"n": 125, "ac": 1, "re": 2}},
                            "K": {"0.65": {"n": 200, "ac": 1, "re": 2}}, "L": {"0.65": {"n": 315, "ac": 2, "re": 3}}}},
    "switching": {"to_tightened": {"rejected": 2, "of_last": 5}, "to_normal": {"consecutive_accepted": 5}}}
NEXT_STEP = {"step": 2, "meanings": ["approved"], "roles": ["qa_approver"], "auth": "password", "can_sign": True,
             "blocked_reason": None}
POLICY = {"id": _id("esp_", 1), "record_type": "ncr", "action": "approve",
          "steps": [{"meaning": "reviewed", "roles": ["qa_engineer"]}, {"meaning": "approved", "roles": ["qa_approver"]}],
          "auth": "password", "distinct_signers": True, "exclude_author": True, "version": 1, "fixed": False,
          "row_version": 1, "updated_at": TS, "signatures": []}


def examples() -> dict[str, tuple[Any, dict[str, Any]]]:
    """name -> (model, example)."""
    lot = {**STAMP, "id": _id("ilt_", 1), "number": "IL-000001", "plan_id": _id("ipl_", 1), "plan_number": "IP-000001",
           "plan_version": 1, "scope": "incoming", "item_id": ITEM["id"], "item": ITEM, "lot_id": _id("lot_", 1),
           "lot_code": "L2611-07", "wo_id": None, "wo_number": None, "wo_operation_id": None, "operation_seq": None,
           "posting_id": _id("pst_", 1), "supplier_id": _id("sup_", 1), "customer": None, "lot_size": 3200,
           "sampling": {CHAR["id"]: {"n": 13, "ac": 0, "re": 1, "severity_state": "normal", "aql": "0.065"},
                        CHAR2["id"]: {"n": 125, "ac": 2, "re": 3, "severity_state": "normal", "aql": "0.65"}},
           "status": "in_progress", "verdict": VERDICT, "decision": None, "decided_by": None, "decided_at": None,
           "decision_note": "", "ncr_id": None, "hold": True, "source": "po_receipt", "due_at": TS2, "overdue": False,
           "characteristics": [CHAR, CHAR2], "results": [RESULT], "signatures": [], "links": [], "attachments": []}
    ncr = {**STAMP, "id": _id("ncr_", 1), "number": "NCR-000001", "title": "Pull force below LSL", "source": "inspection",
           "severity": "critical", "item_id": ITEM["id"], "item": ITEM, "lot_id": _id("lot_", 1),
           "lot_code": "L2611-07", "serial_ids": [], "supplier_id": _id("sup_", 1), "wo_id": None,
           "wo_operation_id": None, "operation_seq": None, "inspection_lot_id": lot["id"], "complaint_id": None,
           "place": "stock", "location_id": _id("loc_", 1), "qty_nc": 3200, "defect_codes": ["PULL-LOW"],
           "description": "2 of 13 samples below 22 N.", "containment": "Lot on hold in MRB.", "investigation": "",
           "status": "proposed", "capa_required": True, "author_id": USER_A, "closed_at": None, "external_ref": None,
           "dispositions": [
               {"id": _id("ncd_", 1), "line_no": 1, "kind": "scrap", "qty": 100, "location_id": _id("loc_", 1),
                "rework_routing_id": None, "rework_to_seq": None, "instructions": "", "justification": "",
                "implemented_at": None, "refs": {}},
               {"id": _id("ncd_", 2), "line_no": 2, "kind": "rework", "qty": 200, "location_id": _id("loc_", 1),
                "rework_routing_id": _id("rtg_", 1), "rework_to_seq": None, "instructions": "Re-bond needles",
                "justification": "", "implemented_at": None, "refs": {}},
               {"id": _id("ncd_", 3), "line_no": 3, "kind": "use_as_is", "qty": 2900, "location_id": _id("loc_", 1),
                "rework_routing_id": None, "rework_to_seq": None, "instructions": "",
                "justification": "Remaining units tested 100 %, all >= 30 N.", "implemented_at": None, "refs": {}}],
           "rework_wos": [], "next_actions": ["approve"], "signatures": [{**MANIFEST, "meaning": "reviewed",
                                                                          "meaning_label": "Reviewed"}],
           "links": [], "attachments": []}
    capa = {**STAMP, "id": _id("cap_", 1), "number": "CAPA-000001", "title": "Needle bonding process drift",
            "kind": "corrective", "problem": "Pull force failures on two lots.",
            "risk": {"severity": 4, "occurrence": 2, "level": "medium"}, "owner_user_id": USER_A,
            "due_on": "2027-01-15", "root_cause": {"method": "5_why", "text": "UV lamp intensity below spec."},
            "effectiveness": {"criteria": "No pull force rejects in 10 lots", "check_due_on": "2027-03-01",
                              "result": None, "evidence": ""},
            "status": "implementation", "author_id": USER_A, "closed_at": None, "external_ref": None,
            "sor": "superplanner", "overdue": False,
            "actions": [{"id": _id("cpa_", 1), "seq": 1, "kind": "corrective",
                         "description": "Add UV intensity check to start-up", "owner_user_id": USER_B,
                         "due_on": "2026-12-15", "status": "open", "done_at": None, "evidence": "", "eco_id": None,
                         "row_version": 1}],
            "signatures": [MANIFEST], "links": [{"id": _id("qlk_", 1), "from_type": "ncr", "from_id": ncr["id"],
                                                 "to_type": "capa", "to_id": _id("cap_", 1), "label": "NCR-000001",
                                                 "created_by": USER_A, "created_at": TS}], "attachments": []}
    complaint = {**STAMP, "id": _id("cmp_", 1), "number": "CMP-000001", "received_on": "2026-11-20",
                 "aware_on": "2026-11-20", "channel": "email", "customer": "CHU de Québec", "country": "CA",
                 "item_id": ITEM["id"], "lots": [{"code": "L2611-07", "lot_id": _id("lot_", 1)},
                                                 {"code": "X-UNKNOWN", "lot_id": None}],
                 "serials": [], "warnings": ["Lot X-UNKNOWN was not found; kept as text."], "qty_affected": 3,
                 "description": "Needle detached during injection.", "event_type": "malfunction",
                 "reportability": {"assessed": True, "reportable": None, "regimes": ["hc_mdpr"], "report_ref": None},
                 "reporting_due": [{"regime": "hc_mdpr", "days": 30, "due_on": "2026-12-20", "overdue": False}],
                 "investigation": "", "status": "investigation", "author_id": USER_A, "closed_at": None,
                 "external_ref": None, "sor": "superplanner", "signatures": [], "links": [], "attachments": []}
    fa = {**STAMP, "id": _id("fac_", 1), "number": "FA-000001", "title": "Recall SYR-3ML-LL lot L2611-07",
          "kind": "recall", "class": "II", "regimes": ["hc_mdpr", "fda_mdr"], "strategy": "Notify hospitals; return.",
          "recall_id": _id("rcl_", 1), "recall_number": "RCL-000001", "status": "in_progress", "complete_reason": None,
          "author_id": USER_A, "closed_at": None, "units_total": 2,
          "effectiveness": {"overall": {"done": 1, "total": 2, "pct": 50.0},
                            "by_customer": [{"customer": "CHU de Québec", "done": 1, "total": 2, "pct": 50.0}]},
          "signatures": [MANIFEST], "links": [], "attachments": []}
    equipment = {**STAMP, "id": _id("eqp_", 1), "code": "EQ-0042", "name": "Force gauge 50 N", "kind": "gauge",
                 "equipment_class": "FORCE", "line_id": None, "tool_pool_id": None, "serial_no": "FG50-1187",
                 "manufacturer": "Mark-10", "location": "QC lab", "status": "active", "calibration_required": True,
                 "interval_days": 365, "grace_days": 0, "last_calibrated_on": "2025-11-20", "due_on": "2026-11-20",
                 "failed_on": None, "procedure_ref": "CAL-SOP-007", "provider": "external", "note": "", "valid": False,
                 "due_state": "overdue", "signatures": [], "links": [], "attachments": []}
    return {
        # ---- esig
        "signature_input": (E.SignatureInput, SIGNATURE_INPUT),
        "signature_manifest": (E.SignatureManifest, MANIFEST),
        "policy": (E.PolicyRecord, POLICY),
        "policy_update": (E.PolicyUpdate, {"steps": POLICY["steps"], "auth": "password_totp",
                                            "distinct_signers": True, "exclude_author": True,
                                            "signature": SIGNATURE_INPUT}),
        "preview": (E.PreviewResult, {
            "record_type": "ncr", "record_id": ncr["id"], "action": "approve", "record_version": 3,
            "content_hash": "a" * 64, "content": {"number": "NCR-000001", "qty_nc": 3200},
            "summary": [{"label": "NCR", "value": "NCR-000001"}, {"label": "Dispositions",
                                                                 "value": "scrap 100, rework 200, use as is 2,900"}],
            "required": True, "part11_mode": True, "policy": POLICY, "next_step": NEXT_STEP,
            "signatures": ncr["signatures"],
            "signer": {"legal_name": "Marie Tremblay", "username": "mtremblay@example.com", "methods": ["password"],
                       "enrolled": True, "locked_until": None},
            "legal_statement": E.ACK_TEXT["en"]}),
        "pending": (E.PendingSignatures, {"status": "pending_signatures", "record_type": "ncr",
                                          "record_id": ncr["id"], "signatures": ncr["signatures"],
                                          "next_step": NEXT_STEP}),
        "enroll_input": (E.EnrollInput, {"legal_name": "Marie Tremblay", "password": "correct horse battery staple",
                                         "acknowledgement": True}),
        "esig_status": (E.EsigStatus, {"user_id": USER_A, "username": "mtremblay@example.com", "enrolled": True,
                                       "legal_name": "Marie Tremblay", "enrolled_at": TS, "ack_version": E.ACK_VERSION,
                                       "revoked_at": None, "locked_until": None, "methods": ["password",
                                                                                            "password_totp"],
                                       "totp_enabled": True, "sso_user": False, "local_credentials": False,
                                       "can_sign": True,
                                       "acknowledgement": {"version": E.ACK_VERSION, **E.ACK_TEXT}}),
        "verify": (E.VerifyResult, {"signature_id": MANIFEST["id"], "mac_ok": True, "chain_ok": True,
                                    "content_hash_ok": True, "content_matches_current": False,
                                    "record_version_signed": 3, "record_version_current": 4,
                                    "current_hash": "b" * 64}),
        "audit_record": (E.AuditRecordPage, {"entity_type": "mfg_item", "entity_id": ITEM["id"], "total": 2,
                                             "limit": 100, "offset": 0, "items": [
            {"id": 101, "at": TS, "actor_id": USER_A, "actor_name": "Marie Tremblay", "action": "create",
             "entity_type": "mfg_item", "entity_id": ITEM["id"], "record_version": 1, "reason": None, "changes": [],
             "signature": None, "details": {}},
            {"id": 102, "at": TS2, "actor_id": USER_A, "actor_name": "Marie Tremblay", "action": "update",
             "entity_type": "mfg_item", "entity_id": ITEM["id"], "record_version": 2,
             "reason": "Drawing rev C", "changes": [{"path": "description", "old": "Syringe 3 mL",
                                                     "new": "Syringe 3 mL Luer lock"}],
             "signature": None, "details": {}}]}),
        "part11_mode": (E.Part11ModeRecord, {"enabled": True, "enabled_at": TS, "enabled_by": USER_A,
                                             "signatures": [{**MANIFEST, "action": "part11_on"}],
                                             "esig_enabled": True, "secrets_configured": True, "clock_skew_ms": 3.2,
                                             "max_clock_skew_ms": 2000}),
        "part11_mode_input": (E.Part11ModeInput, {"enabled": True, "signature": SIGNATURE_INPUT}),
        "package": (E.Part11Package, {"record_type": "ncr", "record_id": ncr["id"], "record": {"number": "NCR-000001"},
                                      "signatures": [MANIFEST], "audit": [], "attachments": [
                                          {"id": _id("att_", 1), "filename": "photo.png", "size": 20480,
                                           "sha256": "c" * 64}], "links": [], "generated_at": TS2,
                                      "generated_by": USER_A, "package_sha256": "d" * 64}),
        "export_input": (E.Part11ExportInput, {"from": "2026-01-01", "to": "2026-11-30", "record_types": ["ncr"]}),
        "export": (E.Part11ExportRecord, {"id": _id("p1x_", 1), "params": {"from": "2026-01-01", "to": "2026-11-30",
                                                                           "record_types": ["ncr"]},
                                          "status": "completed", "manifest": {"counts": {"records": 3}},
                                          "sha256": "e" * 64, "error": None, "requested_by": USER_A,
                                          "created_at": TS, "finished_at": TS2,
                                          "download_url": f"/api/v1/mfg/part11/exports/{_id('p1x_', 1)}/download"}),
        "time": (E.TimeInfo, {"app_utc": TS, "db_utc": TS, "skew_ms": 1.4, "max_skew_ms": 2000, "ok": True}),
        # ---- qa settings, schemes, plans
        "qa_settings": (Q.QaSettingsRecord, {**Q.QaSettings().model_dump(mode="json"), "row_version": 4,
                                             "defect_codes": [{"code": "PULL-LOW", "name": "Pull force low",
                                                               "severity": "critical"}]}),
        "scheme_input": (Q.SchemeInput, {"code": "EXAMPLE-TABLE", "name": "Example table (test only)",
                                         "kind": "table", "table": TABLE, "switching": True,
                                         "note": "test only - load your licensed tables"}),
        "scheme": (Q.SchemeRecord, {**STAMP, "id": _id("ssc_", 1), "code": "EXAMPLE-TABLE",
                                    "name": "Example table (test only)", "kind": "table", "fixed_n": None,
                                    "percent": None, "table": TABLE, "switching": True, "status": "approved",
                                    "approved_at": TS, "note": "test only - load your licensed tables",
                                    "signatures": [MANIFEST], "links": [], "attachments": []}),
        "sampling_preview": (Q.SamplingPreview, {"lot_size": 3200, "level": "II", "aql": "0.65", "state": "normal",
                                                 "n": 125, "ac": 2, "re": 3, "full": False}),
        "plan_input": (Q.PlanInput, {"name": "Incoming SYR-3ML-LL", "item_id": ITEM["id"], "scope": "incoming",
                                     "supplier_id": _id("sup_", 1), "scheme_id": _id("ssc_", 1),
                                     "inspection_level": "II", "aql": {"critical": "0.065", "major": "0.65",
                                                                       "minor": "2.5"},
                                     "characteristics": [{k: v for k, v in CHAR.items() if k != "id"}]}),
        "plan": (Q.PlanRecord, {**STAMP, "id": _id("ipl_", 1), "number": "IP-000001", "version": 1,
                                "name": "Incoming SYR-3ML-LL", "item_id": ITEM["id"], "item": ITEM,
                                "scope": "incoming", "operation_seq": None, "supplier_id": _id("sup_", 1),
                                "customer": None, "scheme_id": _id("ssc_", 1), "scheme_code": "EXAMPLE-TABLE",
                                "inspection_level": "II", "aql": {"critical": "0.065", "major": "0.65",
                                                                  "minor": "2.5"},
                                "status": "approved", "effective_from": "2026-11-23", "supersedes_id": None,
                                "approved_at": TS, "note": "", "characteristics": [CHAR, CHAR2],
                                "signatures": [MANIFEST], "links": [], "attachments": []}),
        # ---- inspection lots
        "inspection_lot_input": (Q.InspectionLotInput, {"plan_id": _id("ipl_", 1), "lot_id": _id("lot_", 1),
                                                        "lot_size": 500, "hold": True, "note": "Re-inspection"}),
        "inspection_lot": (Q.InspectionLotRecord, lot),
        "results_batch": (Q.ResultsBatch, {"client_batch_id": "tab-7:000123", "results": [
            {"characteristic_id": CHAR["id"], "sample_no": 1, "value": 41.7, "equipment_id": _id("eqp_", 1)},
            {"characteristic_id": CHAR2["id"], "sample_no": 1, "passed": True, "defects": 0}]}),
        "results_batch_response": (Q.ResultsBatchResponse, {"inspection_lot_id": lot["id"],
                                                            "client_batch_id": "tab-7:000123", "accepted": 1,
                                                            "replayed": False, "results": [RESULT],
                                                            "verdict": VERDICT, "status": "in_progress",
                                                            "row_version": 2}),
        "decision_input": (Q.DecisionInput, {"decision": "accept", "note": "", "signature": {
            **SIGNATURE_INPUT, "meaning": "released"}}),
        # ---- holds
        "hold_input": (Q.HoldInput, {"lot_id": _id("lot_", 1), "reason": "Supplier notice SN-17"}),
        "hold": (Q.HoldRecord, {**STAMP, "id": _id("hld_", 1), "lot_id": _id("lot_", 1), "lot_code": "L2611-07",
                                "serial_id": None, "serial": None, "item_id": ITEM["id"], "item": ITEM,
                                "source": "inspection", "source_id": lot["id"], "source_number": "IL-000001",
                                "reason": "Incoming inspection IL-000001", "placed_by": USER_A, "placed_at": TS,
                                "released_by": None, "released_at": None, "release_signature_id": None,
                                "release_note": "", "open": True, "signatures": [], "links": [], "attachments": []}),
        # ---- NCR
        "ncr_input": (Q.NcrInput, {"title": "Pull force below LSL", "source": "inspection", "severity": "critical",
                                   "item_id": ITEM["id"], "lot_id": _id("lot_", 1), "location_id": _id("loc_", 1),
                                   "qty_nc": 3200, "defect_codes": ["PULL-LOW"], "capa_required": True}),
        "propose_input": (Q.ProposeInput, {"dispositions": [
            {"kind": "scrap", "qty": 100, "location_id": _id("loc_", 1)},
            {"kind": "rework", "qty": 200, "location_id": _id("loc_", 1), "rework_routing_id": _id("rtg_", 1)},
            {"kind": "use_as_is", "qty": 2900, "location_id": _id("loc_", 1),
             "justification": "Remaining units tested 100 %, all >= 30 N."}]}),
        "ncr": (Q.NcrRecord, ncr),
        # ---- CAPA, complaints, field actions
        "capa_input": (Q.CapaInput, {"title": "Needle bonding process drift", "kind": "corrective",
                                     "problem": "Pull force failures on two lots.",
                                     "risk": {"severity": 4, "occurrence": 2}, "due_on": "2027-01-15"}),
        "capa_action_input": (Q.CapaActionInput, {"kind": "corrective",
                                                  "description": "Add UV intensity check to start-up",
                                                  "due_on": "2026-12-15"}),
        "capa_verify_input": (Q.CapaVerifyInput, {"result": "effective", "evidence": "10 lots without reject",
                                                  "signature": {**SIGNATURE_INPUT, "meaning": "verified"}}),
        "capa": (Q.CapaRecord, capa),
        "complaint_input": (Q.ComplaintInput, {"received_on": "2026-11-20", "aware_on": "2026-11-20",
                                               "customer": "CHU de Québec", "country": "CA", "item_id": ITEM["id"],
                                               "lots": ["L2611-07", "X-UNKNOWN"], "qty_affected": 3,
                                               "description": "Needle detached during injection.",
                                               "event_type": "malfunction"}),
        "complaint": (Q.ComplaintRecord, complaint),
        "field_action_input": (Q.FieldActionInput, {"title": "Recall SYR-3ML-LL lot L2611-07", "kind": "recall",
                                                    "class": "II", "regimes": ["hc_mdpr"],
                                                    "recall_id": _id("rcl_", 1)}),
        "field_action": (Q.FieldActionRecord, fa),
        "field_action_unit": (Q.FieldActionUnitRecord, {"id": _id("fau_", 1), "kind": "lot", "serial_id": None,
                                                        "lot_id": _id("lot_", 1), "code": "L2611-07",
                                                        "item_id": ITEM["id"], "customer": "CHU de Québec",
                                                        "demand_line_id": _id("dml_", 1), "qty": 500,
                                                        "in_stock": False, "status": "acknowledged", "note": "",
                                                        "updated_by": USER_A, "updated_at": TS}),
        "units_bulk_input": (Q.UnitsBulkInput, {"items": [{"unit_id": _id("fau_", 1), "status": "returned",
                                                           "note": "RMA 4471"}]}),
        # ---- equipment
        "equipment_input": (Q.EquipmentInput, {"code": "EQ-0042", "name": "Force gauge 50 N", "kind": "gauge",
                                               "equipment_class": "FORCE", "interval_days": 365,
                                               "due_on": "2026-11-20", "provider": "external"}),
        "equipment": (Q.EquipmentRecord, equipment),
        "equipment_status_input": (Q.EquipmentStatusInput, {"status": "active", "reason": "Calibrated, passed",
                                                            "signature": SIGNATURE_INPUT}),
        "calibration_input": (Q.CalibrationInput, {"performed_on": "2026-11-23", "provider_name": "MetroLab inc.",
                                                   "result": "pass", "certificate_ref": "C-2026-8812",
                                                   "signature": {**SIGNATURE_INPUT, "meaning": "performed"}}),
        "calibration": (Q.CalibrationRecord, {**STAMP, "id": _id("cal_", 1), "equipment_id": equipment["id"],
                                              "performed_on": "2026-11-23", "performed_by": USER_B,
                                              "provider_name": "MetroLab inc.", "result": "pass", "as_found": "",
                                              "as_left": "", "certificate_ref": "C-2026-8812",
                                              "next_due_on": "2027-11-23", "signatures": [MANIFEST], "links": [],
                                              "attachments": []}),
        "impact": (Q.ImpactRecord, {"equipment_id": equipment["id"], "since": "2025-11-20", "results": 26,
                                    "inspection_lots": [{"id": lot["id"], "number": "IL-000001",
                                                         "status": "accepted", "decision": "accept",
                                                         "lot_id": _id("lot_", 1), "lot_code": "L2611-07",
                                                         "item_id": ITEM["id"], "results": 13}]}),
        # ---- attachments, links, summary
        "attachment": (Q.AttachmentRecord, {"id": _id("att_", 1), "entity_type": "ncr", "entity_id": ncr["id"],
                                            "filename": "photo.png", "content_type": "image/png", "size": 20480,
                                            "sha256": "c" * 64, "uploaded_by": USER_A, "uploaded_at": TS}),
        "link_input": (Q.LinkInput, {"from_type": "ncr", "from_id": ncr["id"], "to_type": "capa",
                                     "to_id": capa["id"]}),
        "link": (Q.LinkRecord, capa["links"][0]),
        "qa_summary": (Q.QaSummary, {"open_lots": 4, "overdue_lots": 1, "open_ncrs": 3, "overdue_capas": 0,
                                     "equipment_due": 2}),
    }


def build() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, (model, ex) in examples().items():
        model.model_validate(ex)
        out[name] = ex
    return out


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

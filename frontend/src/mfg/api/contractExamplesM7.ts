/**
 * M7 S0 contract examples: `backend/superplanner/qa/fixtures/example_m7.json` verbatim, typed against `typesM7.ts`
 * so the compiler flags drift (inputs as `Partial`: the fixture omits defaulted fields). Regenerate when the fixture changes.
 */
import type {
  AttachmentRef,
  Calibration,
  CalibrationInput,
  Capa,
  CapaActionInput,
  CapaInput,
  Complaint,
  ComplaintInput,
  DecisionInput,
  EnrollInput,
  Equipment,
  EquipmentImpact,
  EquipmentInput,
  EsigPolicy,
  EsigPreview,
  EsigStatus,
  FieldAction,
  FieldActionInput,
  FieldActionUnit,
  Hold,
  InspectionLot,
  InspectionLotInput,
  InspectionPlan,
  MetaTime,
  Ncr,
  NcrInput,
  Part11Export,
  Part11Mode,
  Part11Package,
  PendingSignatures,
  PlanInput,
  PolicyInput,
  QaLink,
  QaSettings,
  QaSummary,
  RecordAuditPage,
  ResultsBatchResponse,
  SamplingPreview,
  SamplingScheme,
  SchemeInput,
  SignatureInput,
  SignatureManifest,
  VerifyResult,
} from "./typesM7";

export const exampleAttachment: AttachmentRef = {
 "content_type": "image/png",
 "entity_id": "ncr_00000000000000000000000000000001",
 "entity_type": "ncr",
 "filename": "photo.png",
 "id": "att_00000000000000000000000000000001",
 "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
 "size": 20480,
 "uploaded_at": "2026-11-23T19:05:12.000000Z",
 "uploaded_by": "usr_00000000000000000000000000000001"
};

export const exampleAuditRecord: RecordAuditPage = {
 "entity_id": "itm_00000000000000000000000000000001",
 "entity_type": "mfg_item",
 "items": [
  {
   "action": "create",
   "actor_id": "usr_00000000000000000000000000000001",
   "actor_name": "Marie Tremblay",
   "at": "2026-11-23T19:05:12.000000Z",
   "changes": [],
   "details": {},
   "entity_id": "itm_00000000000000000000000000000001",
   "entity_type": "mfg_item",
   "id": 101,
   "reason": null,
   "record_version": 1,
   "signature": null
  },
  {
   "action": "update",
   "actor_id": "usr_00000000000000000000000000000001",
   "actor_name": "Marie Tremblay",
   "at": "2026-11-23T19:40:02.000000Z",
   "changes": [
    {
     "new": "Syringe 3 mL Luer lock",
     "old": "Syringe 3 mL",
     "path": "description"
    }
   ],
   "details": {},
   "entity_id": "itm_00000000000000000000000000000001",
   "entity_type": "mfg_item",
   "id": 102,
   "reason": "Drawing rev C",
   "record_version": 2,
   "signature": null
  }
 ],
 "limit": 100,
 "offset": 0,
 "total": 2
};

export const exampleCalibration: Calibration = {
 "as_found": "",
 "as_left": "",
 "attachments": [],
 "certificate_ref": "C-2026-8812",
 "created_at": "2026-11-23T19:05:12.000000Z",
 "equipment_id": "eqp_00000000000000000000000000000001",
 "id": "cal_00000000000000000000000000000001",
 "links": [],
 "next_due_on": "2027-11-23",
 "performed_by": "usr_00000000000000000000000000000002",
 "performed_on": "2026-11-23",
 "provider_name": "MetroLab inc.",
 "result": "pass",
 "row_version": 1,
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "approved",
   "meaning_label": "Approved",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ],
 "updated_at": "2026-11-23T19:05:12.000000Z"
};

export const exampleCalibrationInput: Partial<CalibrationInput> = {
 "certificate_ref": "C-2026-8812",
 "performed_on": "2026-11-23",
 "provider_name": "MetroLab inc.",
 "result": "pass",
 "signature": {
  "comment": "Reviewed against drawing rev C",
  "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "meaning": "performed",
  "password": "correct horse battery staple",
  "username": "mtremblay@example.com"
 }
};

export const exampleCapa: Capa = {
 "actions": [
  {
   "description": "Add UV intensity check to start-up",
   "done_at": null,
   "due_on": "2026-12-15",
   "eco_id": null,
   "evidence": "",
   "id": "cpa_00000000000000000000000000000001",
   "kind": "corrective",
   "owner_user_id": "usr_00000000000000000000000000000002",
   "row_version": 1,
   "seq": 1,
   "status": "open"
  }
 ],
 "attachments": [],
 "author_id": "usr_00000000000000000000000000000001",
 "closed_at": null,
 "created_at": "2026-11-23T19:05:12.000000Z",
 "due_on": "2027-01-15",
 "effectiveness": {
  "check_due_on": "2027-03-01",
  "criteria": "No pull force rejects in 10 lots",
  "evidence": "",
  "result": null
 },
 "external_ref": null,
 "id": "cap_00000000000000000000000000000001",
 "kind": "corrective",
 "links": [
  {
   "created_at": "2026-11-23T19:05:12.000000Z",
   "created_by": "usr_00000000000000000000000000000001",
   "from_id": "ncr_00000000000000000000000000000001",
   "from_type": "ncr",
   "id": "qlk_00000000000000000000000000000001",
   "label": "NCR-000001",
   "to_id": "cap_00000000000000000000000000000001",
   "to_type": "capa"
  }
 ],
 "number": "CAPA-000001",
 "overdue": false,
 "owner_user_id": "usr_00000000000000000000000000000001",
 "problem": "Pull force failures on two lots.",
 "risk": {
  "level": "medium",
  "occurrence": 2,
  "severity": 4
 },
 "root_cause": {
  "method": "5_why",
  "text": "UV lamp intensity below spec."
 },
 "row_version": 1,
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "approved",
   "meaning_label": "Approved",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ],
 "sor": "superplanner",
 "status": "implementation",
 "title": "Needle bonding process drift",
 "updated_at": "2026-11-23T19:05:12.000000Z"
};

export const exampleCapaActionInput: Partial<CapaActionInput> = {
 "description": "Add UV intensity check to start-up",
 "due_on": "2026-12-15",
 "kind": "corrective"
};

export const exampleCapaInput: Partial<CapaInput> = {
 "due_on": "2027-01-15",
 "kind": "corrective",
 "problem": "Pull force failures on two lots.",
 "risk": {
  "occurrence": 2,
  "severity": 4
 },
 "title": "Needle bonding process drift"
};

export const exampleComplaint: Complaint = {
 "attachments": [],
 "author_id": "usr_00000000000000000000000000000001",
 "aware_on": "2026-11-20",
 "channel": "email",
 "closed_at": null,
 "country": "CA",
 "created_at": "2026-11-23T19:05:12.000000Z",
 "customer": "CHU de Québec",
 "description": "Needle detached during injection.",
 "event_type": "malfunction",
 "external_ref": null,
 "id": "cmp_00000000000000000000000000000001",
 "investigation": "",
 "item_id": "itm_00000000000000000000000000000001",
 "links": [],
 "lots": [
  {
   "code": "L2611-07",
   "lot_id": "lot_00000000000000000000000000000001"
  },
  {
   "code": "X-UNKNOWN",
   "lot_id": null
  }
 ],
 "number": "CMP-000001",
 "qty_affected": 3,
 "received_on": "2026-11-20",
 "reportability": {
  "assessed": true,
  "regimes": [
   "hc_mdpr"
  ],
  "report_ref": null,
  "reportable": null
 },
 "reporting_due": [
  {
   "days": 30,
   "due_on": "2026-12-20",
   "overdue": false,
   "regime": "hc_mdpr"
  }
 ],
 "row_version": 1,
 "serials": [],
 "signatures": [],
 "sor": "superplanner",
 "status": "investigation",
 "updated_at": "2026-11-23T19:05:12.000000Z",
 "warnings": [
  "Lot X-UNKNOWN was not found; kept as text."
 ]
};

export const exampleComplaintInput: Partial<ComplaintInput> = {
 "aware_on": "2026-11-20",
 "country": "CA",
 "customer": "CHU de Québec",
 "description": "Needle detached during injection.",
 "event_type": "malfunction",
 "item_id": "itm_00000000000000000000000000000001",
 "lots": [
  "L2611-07",
  "X-UNKNOWN"
 ],
 "qty_affected": 3,
 "received_on": "2026-11-20"
};

export const exampleDecisionInput: Partial<DecisionInput> = {
 "decision": "accept",
 "note": "",
 "signature": {
  "comment": "Reviewed against drawing rev C",
  "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "meaning": "released",
  "password": "correct horse battery staple",
  "username": "mtremblay@example.com"
 }
};

export const exampleEnrollInput: Partial<EnrollInput> = {
 "acknowledgement": true,
 "legal_name": "Marie Tremblay",
 "password": "correct horse battery staple"
};

export const exampleEquipment: Equipment = {
 "attachments": [],
 "calibration_required": true,
 "code": "EQ-0042",
 "created_at": "2026-11-23T19:05:12.000000Z",
 "due_on": "2026-11-20",
 "due_state": "overdue",
 "equipment_class": "FORCE",
 "failed_on": null,
 "grace_days": 0,
 "id": "eqp_00000000000000000000000000000001",
 "interval_days": 365,
 "kind": "gauge",
 "last_calibrated_on": "2025-11-20",
 "line_id": null,
 "links": [],
 "location": "QC lab",
 "manufacturer": "Mark-10",
 "name": "Force gauge 50 N",
 "note": "",
 "procedure_ref": "CAL-SOP-007",
 "provider": "external",
 "row_version": 1,
 "serial_no": "FG50-1187",
 "signatures": [],
 "status": "active",
 "tool_pool_id": null,
 "updated_at": "2026-11-23T19:05:12.000000Z",
 "valid": false
};

export const exampleEquipmentInput: Partial<EquipmentInput> = {
 "code": "EQ-0042",
 "due_on": "2026-11-20",
 "equipment_class": "FORCE",
 "interval_days": 365,
 "kind": "gauge",
 "name": "Force gauge 50 N",
 "provider": "external"
};

export const exampleEsigStatus: EsigStatus = {
 "ack_version": "2026-11",
 "acknowledgement": {
  "en": "I agree that my electronic signature is the legally binding equivalent of my handwritten signature.",
  "fr-CA": "J'accepte que ma signature électronique soit l'équivalent juridiquement contraignant de ma signature manuscrite.",
  "version": "2026-11"
 },
 "can_sign": true,
 "enrolled": true,
 "enrolled_at": "2026-11-23T19:05:12.000000Z",
 "legal_name": "Marie Tremblay",
 "local_credentials": false,
 "locked_until": null,
 "methods": [
  "password",
  "password_totp"
 ],
 "revoked_at": null,
 "sso_user": false,
 "totp_enabled": true,
 "user_id": "usr_00000000000000000000000000000001",
 "username": "mtremblay@example.com"
};

export const exampleExport: Part11Export = {
 "created_at": "2026-11-23T19:05:12.000000Z",
 "download_url": "/api/v1/mfg/part11/exports/p1x_00000000000000000000000000000001/download",
 "error": null,
 "finished_at": "2026-11-23T19:40:02.000000Z",
 "id": "p1x_00000000000000000000000000000001",
 "manifest": {
  "counts": {
   "records": 3
  }
 },
 "params": {
  "from": "2026-01-01",
  "record_types": [
   "ncr"
  ],
  "to": "2026-11-30"
 },
 "requested_by": "usr_00000000000000000000000000000001",
 "sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
 "status": "completed"
};

export const exampleFieldAction: FieldAction = {
 "attachments": [],
 "author_id": "usr_00000000000000000000000000000001",
 "class": "II",
 "closed_at": null,
 "complete_reason": null,
 "created_at": "2026-11-23T19:05:12.000000Z",
 "effectiveness": {
  "by_customer": [
   {
    "customer": "CHU de Québec",
    "done": 1,
    "pct": 50.0,
    "total": 2
   }
  ],
  "overall": {
   "done": 1,
   "pct": 50.0,
   "total": 2
  }
 },
 "id": "fac_00000000000000000000000000000001",
 "kind": "recall",
 "links": [],
 "number": "FA-000001",
 "recall_id": "rcl_00000000000000000000000000000001",
 "recall_number": "RCL-000001",
 "regimes": [
  "hc_mdpr",
  "fda_mdr"
 ],
 "row_version": 1,
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "approved",
   "meaning_label": "Approved",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ],
 "status": "in_progress",
 "strategy": "Notify hospitals; return.",
 "title": "Recall SYR-3ML-LL lot L2611-07",
 "units_total": 2,
 "updated_at": "2026-11-23T19:05:12.000000Z"
};

export const exampleFieldActionInput: Partial<FieldActionInput> = {
 "class": "II",
 "kind": "recall",
 "recall_id": "rcl_00000000000000000000000000000001",
 "regimes": [
  "hc_mdpr"
 ],
 "title": "Recall SYR-3ML-LL lot L2611-07"
};

export const exampleFieldActionUnit: FieldActionUnit = {
 "code": "L2611-07",
 "customer": "CHU de Québec",
 "demand_line_id": "dml_00000000000000000000000000000001",
 "id": "fau_00000000000000000000000000000001",
 "in_stock": false,
 "item_id": "itm_00000000000000000000000000000001",
 "kind": "lot",
 "lot_id": "lot_00000000000000000000000000000001",
 "note": "",
 "qty": 500,
 "serial_id": null,
 "status": "acknowledged",
 "updated_at": "2026-11-23T19:05:12.000000Z",
 "updated_by": "usr_00000000000000000000000000000001"
};

export const exampleHold: Hold = {
 "attachments": [],
 "created_at": "2026-11-23T19:05:12.000000Z",
 "id": "hld_00000000000000000000000000000001",
 "item": {
  "id": "itm_00000000000000000000000000000001",
  "name": "Syringe 3 mL Luer lock",
  "part_number": "SYR-3ML-LL",
  "revision": "A"
 },
 "item_id": "itm_00000000000000000000000000000001",
 "links": [],
 "lot_code": "L2611-07",
 "lot_id": "lot_00000000000000000000000000000001",
 "open": true,
 "placed_at": "2026-11-23T19:05:12.000000Z",
 "placed_by": "usr_00000000000000000000000000000001",
 "reason": "Incoming inspection IL-000001",
 "release_note": "",
 "release_signature_id": null,
 "released_at": null,
 "released_by": null,
 "row_version": 1,
 "serial": null,
 "serial_id": null,
 "signatures": [],
 "source": "inspection",
 "source_id": "ilt_00000000000000000000000000000001",
 "source_number": "IL-000001",
 "updated_at": "2026-11-23T19:05:12.000000Z"
};

export const exampleImpact: EquipmentImpact = {
 "equipment_id": "eqp_00000000000000000000000000000001",
 "inspection_lots": [
  {
   "decision": "accept",
   "id": "ilt_00000000000000000000000000000001",
   "item_id": "itm_00000000000000000000000000000001",
   "lot_code": "L2611-07",
   "lot_id": "lot_00000000000000000000000000000001",
   "number": "IL-000001",
   "results": 13,
   "status": "accepted"
  }
 ],
 "results": 26,
 "since": "2025-11-20"
};

export const exampleInspectionLot: InspectionLot = {
 "attachments": [],
 "characteristics": [
  {
   "code": "PULL",
   "destructive": true,
   "equipment_class": "FORCE",
   "id": "ich_00000000000000000000000000000001",
   "kind": "variable",
   "lsl": 22.0,
   "method": "ISO 7864 pull test",
   "name": "Needle pull force",
   "nominal": 40.0,
   "sample_override": null,
   "seq": 10,
   "severity": "critical",
   "unit": "N",
   "usl": null
  },
  {
   "code": "VIS",
   "destructive": false,
   "equipment_class": null,
   "id": "ich_00000000000000000000000000000002",
   "kind": "attribute",
   "lsl": null,
   "method": "Visual, 2x",
   "name": "Visual: no particles",
   "nominal": null,
   "sample_override": null,
   "seq": 20,
   "severity": "major",
   "unit": null,
   "usl": null
  }
 ],
 "created_at": "2026-11-23T19:05:12.000000Z",
 "customer": null,
 "decided_at": null,
 "decided_by": null,
 "decision": null,
 "decision_note": "",
 "due_at": "2026-11-23T19:40:02.000000Z",
 "hold": true,
 "id": "ilt_00000000000000000000000000000001",
 "item": {
  "id": "itm_00000000000000000000000000000001",
  "name": "Syringe 3 mL Luer lock",
  "part_number": "SYR-3ML-LL",
  "revision": "A"
 },
 "item_id": "itm_00000000000000000000000000000001",
 "links": [],
 "lot_code": "L2611-07",
 "lot_id": "lot_00000000000000000000000000000001",
 "lot_size": 3200,
 "ncr_id": null,
 "number": "IL-000001",
 "operation_seq": null,
 "overdue": false,
 "plan_id": "ipl_00000000000000000000000000000001",
 "plan_number": "IP-000001",
 "plan_version": 1,
 "posting_id": "pst_00000000000000000000000000000001",
 "results": [
  {
   "characteristic_id": "ich_00000000000000000000000000000001",
   "corrects_result_id": null,
   "defects": 0,
   "entered_at": "2026-11-23T19:05:12.000000Z",
   "entered_by": "usr_00000000000000000000000000000001",
   "equipment_id": "eqp_00000000000000000000000000000001",
   "id": "irs_00000000000000000000000000000001",
   "note": "",
   "passed": true,
   "reason": null,
   "sample_no": 1,
   "superseded": false,
   "value": 41.7
  }
 ],
 "row_version": 1,
 "sampling": {
  "ich_00000000000000000000000000000001": {
   "ac": 0,
   "aql": "0.065",
   "n": 13,
   "re": 1,
   "severity_state": "normal"
  },
  "ich_00000000000000000000000000000002": {
   "ac": 2,
   "aql": "0.65",
   "n": 125,
   "re": 3,
   "severity_state": "normal"
  }
 },
 "scope": "incoming",
 "signatures": [],
 "source": "po_receipt",
 "status": "in_progress",
 "supplier_id": "sup_00000000000000000000000000000001",
 "updated_at": "2026-11-23T19:05:12.000000Z",
 "verdict": {
  "characteristics": [
   {
    "ac": 0,
    "characteristic_id": "ich_00000000000000000000000000000001",
    "code": "PULL",
    "defective": 0,
    "entered": 2,
    "n": 13,
    "re": 1,
    "verdict": "pending"
   },
   {
    "ac": 2,
    "characteristic_id": "ich_00000000000000000000000000000002",
    "code": "VIS",
    "defective": 0,
    "entered": 0,
    "n": 125,
    "re": 3,
    "verdict": "pending"
   }
  ],
  "verdict": "pending"
 },
 "wo_id": null,
 "wo_number": null,
 "wo_operation_id": null
};

export const exampleInspectionLotInput: Partial<InspectionLotInput> = {
 "hold": true,
 "lot_id": "lot_00000000000000000000000000000001",
 "lot_size": 500,
 "note": "Re-inspection",
 "plan_id": "ipl_00000000000000000000000000000001"
};

export const exampleLink: QaLink = {
 "created_at": "2026-11-23T19:05:12.000000Z",
 "created_by": "usr_00000000000000000000000000000001",
 "from_id": "ncr_00000000000000000000000000000001",
 "from_type": "ncr",
 "id": "qlk_00000000000000000000000000000001",
 "label": "NCR-000001",
 "to_id": "cap_00000000000000000000000000000001",
 "to_type": "capa"
};

export const exampleNcr: Ncr = {
 "attachments": [],
 "author_id": "usr_00000000000000000000000000000001",
 "capa_required": true,
 "closed_at": null,
 "complaint_id": null,
 "containment": "Lot on hold in MRB.",
 "created_at": "2026-11-23T19:05:12.000000Z",
 "defect_codes": [
  "PULL-LOW"
 ],
 "description": "2 of 13 samples below 22 N.",
 "dispositions": [
  {
   "id": "ncd_00000000000000000000000000000001",
   "implemented_at": null,
   "instructions": "",
   "justification": "",
   "kind": "scrap",
   "line_no": 1,
   "location_id": "loc_00000000000000000000000000000001",
   "qty": 100,
   "refs": {},
   "rework_routing_id": null,
   "rework_to_seq": null
  },
  {
   "id": "ncd_00000000000000000000000000000002",
   "implemented_at": null,
   "instructions": "Re-bond needles",
   "justification": "",
   "kind": "rework",
   "line_no": 2,
   "location_id": "loc_00000000000000000000000000000001",
   "qty": 200,
   "refs": {},
   "rework_routing_id": "rtg_00000000000000000000000000000001",
   "rework_to_seq": null
  },
  {
   "id": "ncd_00000000000000000000000000000003",
   "implemented_at": null,
   "instructions": "",
   "justification": "Remaining units tested 100 %, all >= 30 N.",
   "kind": "use_as_is",
   "line_no": 3,
   "location_id": "loc_00000000000000000000000000000001",
   "qty": 2900,
   "refs": {},
   "rework_routing_id": null,
   "rework_to_seq": null
  }
 ],
 "external_ref": null,
 "id": "ncr_00000000000000000000000000000001",
 "inspection_lot_id": "ilt_00000000000000000000000000000001",
 "investigation": "",
 "item": {
  "id": "itm_00000000000000000000000000000001",
  "name": "Syringe 3 mL Luer lock",
  "part_number": "SYR-3ML-LL",
  "revision": "A"
 },
 "item_id": "itm_00000000000000000000000000000001",
 "links": [],
 "location_id": "loc_00000000000000000000000000000001",
 "lot_code": "L2611-07",
 "lot_id": "lot_00000000000000000000000000000001",
 "next_actions": [
  "approve"
 ],
 "number": "NCR-000001",
 "operation_seq": null,
 "place": "stock",
 "qty_nc": 3200,
 "rework_wos": [],
 "row_version": 1,
 "serial_ids": [],
 "severity": "critical",
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "reviewed",
   "meaning_label": "Reviewed",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ],
 "source": "inspection",
 "status": "proposed",
 "supplier_id": "sup_00000000000000000000000000000001",
 "title": "Pull force below LSL",
 "updated_at": "2026-11-23T19:05:12.000000Z",
 "wo_id": null,
 "wo_operation_id": null
};

export const exampleNcrInput: Partial<NcrInput> = {
 "capa_required": true,
 "defect_codes": [
  "PULL-LOW"
 ],
 "item_id": "itm_00000000000000000000000000000001",
 "location_id": "loc_00000000000000000000000000000001",
 "lot_id": "lot_00000000000000000000000000000001",
 "qty_nc": 3200,
 "severity": "critical",
 "source": "inspection",
 "title": "Pull force below LSL"
};

export const examplePackage: Part11Package = {
 "attachments": [
  {
   "filename": "photo.png",
   "id": "att_00000000000000000000000000000001",
   "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
   "size": 20480
  }
 ],
 "audit": [],
 "generated_at": "2026-11-23T19:40:02.000000Z",
 "generated_by": "usr_00000000000000000000000000000001",
 "links": [],
 "package_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
 "record": {
  "number": "NCR-000001"
 },
 "record_id": "ncr_00000000000000000000000000000001",
 "record_type": "ncr",
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "approved",
   "meaning_label": "Approved",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ]
};

export const examplePart11Mode: Part11Mode = {
 "clock_skew_ms": 3.2,
 "enabled": true,
 "enabled_at": "2026-11-23T19:05:12.000000Z",
 "enabled_by": "usr_00000000000000000000000000000001",
 "esig_enabled": true,
 "max_clock_skew_ms": 2000,
 "secrets_configured": true,
 "signatures": [
  {
   "action": "part11_on",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "approved",
   "meaning_label": "Approved",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ]
};

export const examplePending: PendingSignatures = {
 "next_step": {
  "auth": "password",
  "blocked_reason": null,
  "can_sign": true,
  "meanings": [
   "approved"
  ],
  "roles": [
   "qa_approver"
  ],
  "step": 2
 },
 "record_id": "ncr_00000000000000000000000000000001",
 "record_type": "ncr",
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "reviewed",
   "meaning_label": "Reviewed",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ],
 "status": "pending_signatures"
};

export const examplePlan: InspectionPlan = {
 "approved_at": "2026-11-23T19:05:12.000000Z",
 "aql": {
  "critical": "0.065",
  "major": "0.65",
  "minor": "2.5"
 },
 "attachments": [],
 "characteristics": [
  {
   "code": "PULL",
   "destructive": true,
   "equipment_class": "FORCE",
   "id": "ich_00000000000000000000000000000001",
   "kind": "variable",
   "lsl": 22.0,
   "method": "ISO 7864 pull test",
   "name": "Needle pull force",
   "nominal": 40.0,
   "sample_override": null,
   "seq": 10,
   "severity": "critical",
   "unit": "N",
   "usl": null
  },
  {
   "code": "VIS",
   "destructive": false,
   "equipment_class": null,
   "id": "ich_00000000000000000000000000000002",
   "kind": "attribute",
   "lsl": null,
   "method": "Visual, 2x",
   "name": "Visual: no particles",
   "nominal": null,
   "sample_override": null,
   "seq": 20,
   "severity": "major",
   "unit": null,
   "usl": null
  }
 ],
 "created_at": "2026-11-23T19:05:12.000000Z",
 "customer": null,
 "effective_from": "2026-11-23",
 "id": "ipl_00000000000000000000000000000001",
 "inspection_level": "II",
 "item": {
  "id": "itm_00000000000000000000000000000001",
  "name": "Syringe 3 mL Luer lock",
  "part_number": "SYR-3ML-LL",
  "revision": "A"
 },
 "item_id": "itm_00000000000000000000000000000001",
 "links": [],
 "name": "Incoming SYR-3ML-LL",
 "note": "",
 "number": "IP-000001",
 "operation_seq": null,
 "row_version": 1,
 "scheme_code": "EXAMPLE-TABLE",
 "scheme_id": "ssc_00000000000000000000000000000001",
 "scope": "incoming",
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "approved",
   "meaning_label": "Approved",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ],
 "status": "approved",
 "supersedes_id": null,
 "supplier_id": "sup_00000000000000000000000000000001",
 "updated_at": "2026-11-23T19:05:12.000000Z",
 "version": 1
};

export const examplePlanInput: Partial<PlanInput> = {
 "aql": {
  "critical": "0.065",
  "major": "0.65",
  "minor": "2.5"
 },
 "characteristics": [
  {
   "code": "PULL",
   "destructive": true,
   "equipment_class": "FORCE",
   "kind": "variable",
   "lsl": 22.0,
   "method": "ISO 7864 pull test",
   "name": "Needle pull force",
   "nominal": 40.0,
   "sample_override": null,
   "seq": 10,
   "severity": "critical",
   "unit": "N",
   "usl": null
  }
 ],
 "inspection_level": "II",
 "item_id": "itm_00000000000000000000000000000001",
 "name": "Incoming SYR-3ML-LL",
 "scheme_id": "ssc_00000000000000000000000000000001",
 "scope": "incoming",
 "supplier_id": "sup_00000000000000000000000000000001"
};

export const examplePolicy: EsigPolicy = {
 "action": "approve",
 "auth": "password",
 "distinct_signers": true,
 "exclude_author": true,
 "fixed": false,
 "id": "esp_00000000000000000000000000000001",
 "record_type": "ncr",
 "row_version": 1,
 "signatures": [],
 "steps": [
  {
   "meaning": "reviewed",
   "roles": [
    "qa_engineer"
   ]
  },
  {
   "meaning": "approved",
   "roles": [
    "qa_approver"
   ]
  }
 ],
 "updated_at": "2026-11-23T19:05:12.000000Z",
 "version": 1
};

export const examplePolicyUpdate: PolicyInput = {
 "auth": "password_totp",
 "distinct_signers": true,
 "exclude_author": true,
 "signature": {
  "comment": "Reviewed against drawing rev C",
  "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "meaning": "approved",
  "password": "correct horse battery staple",
  "username": "mtremblay@example.com"
 },
 "steps": [
  {
   "meaning": "reviewed",
   "roles": [
    "qa_engineer"
   ]
  },
  {
   "meaning": "approved",
   "roles": [
    "qa_approver"
   ]
  }
 ]
};

export const examplePreview: EsigPreview = {
 "action": "approve",
 "content": {
  "number": "NCR-000001",
  "qty_nc": 3200
 },
 "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
 "legal_statement": "I agree that my electronic signature is the legally binding equivalent of my handwritten signature.",
 "next_step": {
  "auth": "password",
  "blocked_reason": null,
  "can_sign": true,
  "meanings": [
   "approved"
  ],
  "roles": [
   "qa_approver"
  ],
  "step": 2
 },
 "part11_mode": true,
 "policy": {
  "action": "approve",
  "auth": "password",
  "distinct_signers": true,
  "exclude_author": true,
  "fixed": false,
  "id": "esp_00000000000000000000000000000001",
  "record_type": "ncr",
  "row_version": 1,
  "signatures": [],
  "steps": [
   {
    "meaning": "reviewed",
    "roles": [
     "qa_engineer"
    ]
   },
   {
    "meaning": "approved",
    "roles": [
     "qa_approver"
    ]
   }
  ],
  "updated_at": "2026-11-23T19:05:12.000000Z",
  "version": 1
 },
 "record_id": "ncr_00000000000000000000000000000001",
 "record_type": "ncr",
 "record_version": 3,
 "required": true,
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "reviewed",
   "meaning_label": "Reviewed",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ],
 "signer": {
  "enrolled": true,
  "legal_name": "Marie Tremblay",
  "locked_until": null,
  "methods": [
   "password"
  ],
  "username": "mtremblay@example.com"
 },
 "summary": [
  {
   "label": "NCR",
   "value": "NCR-000001"
  },
  {
   "label": "Dispositions",
   "value": "scrap 100, rework 200, use as is 2,900"
  }
 ]
};

export const exampleQaSettings: QaSettings = {
 "cal_due_warning_days": 14,
 "capa_sor": "superplanner",
 "complaint_sor": "superplanner",
 "defect_codes": [
  {
   "code": "PULL-LOW",
   "name": "Pull force low",
   "severity": "critical"
  }
 ],
 "final_release_role": "qa_approver",
 "inspection_due_hours": {
  "final": 24,
  "in_process": 4,
  "incoming": 48
 },
 "mrb_location_id": null,
 "reportability_rules": [
  {
   "days": 30,
   "event_type": "all",
   "regime": "fda_mdr"
  },
  {
   "days": 10,
   "event_type": "death",
   "regime": "hc_mdpr"
  },
  {
   "days": 10,
   "event_type": "serious_injury",
   "regime": "hc_mdpr"
  },
  {
   "days": 30,
   "event_type": "all",
   "regime": "hc_mdpr"
  }
 ],
 "row_version": 4
};

export const exampleQaSummary: QaSummary = {
 "equipment_due": 2,
 "open_lots": 4,
 "open_ncrs": 3,
 "overdue_capas": 0,
 "overdue_lots": 1
};

export const exampleResultsBatchResponse: ResultsBatchResponse = {
 "accepted": 1,
 "client_batch_id": "tab-7:000123",
 "inspection_lot_id": "ilt_00000000000000000000000000000001",
 "replayed": false,
 "results": [
  {
   "characteristic_id": "ich_00000000000000000000000000000001",
   "corrects_result_id": null,
   "defects": 0,
   "entered_at": "2026-11-23T19:05:12.000000Z",
   "entered_by": "usr_00000000000000000000000000000001",
   "equipment_id": "eqp_00000000000000000000000000000001",
   "id": "irs_00000000000000000000000000000001",
   "note": "",
   "passed": true,
   "reason": null,
   "sample_no": 1,
   "superseded": false,
   "value": 41.7
  }
 ],
 "row_version": 2,
 "status": "in_progress",
 "verdict": {
  "characteristics": [
   {
    "ac": 0,
    "characteristic_id": "ich_00000000000000000000000000000001",
    "code": "PULL",
    "defective": 0,
    "entered": 2,
    "n": 13,
    "re": 1,
    "verdict": "pending"
   },
   {
    "ac": 2,
    "characteristic_id": "ich_00000000000000000000000000000002",
    "code": "VIS",
    "defective": 0,
    "entered": 0,
    "n": 125,
    "re": 3,
    "verdict": "pending"
   }
  ],
  "verdict": "pending"
 }
};

export const exampleSamplingPreview: SamplingPreview = {
 "ac": 2,
 "aql": "0.65",
 "full": false,
 "level": "II",
 "lot_size": 3200,
 "n": 125,
 "re": 3,
 "state": "normal"
};

export const exampleScheme: SamplingScheme = {
 "approved_at": "2026-11-23T19:05:12.000000Z",
 "attachments": [],
 "code": "EXAMPLE-TABLE",
 "created_at": "2026-11-23T19:05:12.000000Z",
 "fixed_n": null,
 "id": "ssc_00000000000000000000000000000001",
 "kind": "table",
 "links": [],
 "name": "Example table (test only)",
 "note": "test only - load your licensed tables",
 "percent": null,
 "row_version": 1,
 "signatures": [
  {
   "action": "approve",
   "auth_method": "password",
   "comment": "",
   "content_matches_current": true,
   "id": "esg_00000000000000000000000000000001",
   "meaning": "approved",
   "meaning_label": "Approved",
   "record_version": 3,
   "signed_at": "2026-11-23T19:05:12.000000Z",
   "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
   "signer_legal_name": "Marie Tremblay",
   "signer_username": "mtremblay@example.com",
   "status": "valid",
   "step": 1
  }
 ],
 "status": "approved",
 "switching": true,
 "table": {
  "levels": [
   "S-4",
   "II"
  ],
  "lot_size_ranges": [
   {
    "letters": {
     "II": "J",
     "S-4": "E"
    },
    "max": 1200,
    "min": 1
   },
   {
    "letters": {
     "II": "K",
     "S-4": "G"
    },
    "max": 3200,
    "min": 1201
   },
   {
    "letters": {
     "II": "L",
     "S-4": "H"
    },
    "max": null,
    "min": 3201
   }
  ],
  "plans": {
   "normal": {
    "E": {
     "0.65": {
      "ac": 0,
      "n": 13,
      "re": 1
     }
    },
    "G": {
     "0.65": {
      "ac": 0,
      "n": 32,
      "re": 1
     }
    },
    "H": {
     "0.65": {
      "ac": 1,
      "n": 50,
      "re": 2
     }
    },
    "J": {
     "0.65": {
      "ac": 1,
      "n": 80,
      "re": 2
     }
    },
    "K": {
     "0.65": {
      "ac": 2,
      "n": 125,
      "re": 3
     }
    },
    "L": {
     "0.65": {
      "ac": 3,
      "n": 200,
      "re": 4
     }
    }
   },
   "tightened": {
    "E": {
     "0.65": {
      "ac": 0,
      "n": 20,
      "re": 1
     }
    },
    "G": {
     "0.65": {
      "ac": 0,
      "n": 50,
      "re": 1
     }
    },
    "H": {
     "0.65": {
      "ac": 1,
      "n": 80,
      "re": 2
     }
    },
    "J": {
     "0.65": {
      "ac": 1,
      "n": 125,
      "re": 2
     }
    },
    "K": {
     "0.65": {
      "ac": 1,
      "n": 200,
      "re": 2
     }
    },
    "L": {
     "0.65": {
      "ac": 2,
      "n": 315,
      "re": 3
     }
    }
   }
  },
  "switching": {
   "to_normal": {
    "consecutive_accepted": 5
   },
   "to_tightened": {
    "of_last": 5,
    "rejected": 2
   }
  }
 },
 "updated_at": "2026-11-23T19:05:12.000000Z"
};

export const exampleSchemeInput: Partial<SchemeInput> = {
 "code": "EXAMPLE-TABLE",
 "kind": "table",
 "name": "Example table (test only)",
 "note": "test only - load your licensed tables",
 "switching": true,
 "table": {
  "levels": [
   "S-4",
   "II"
  ],
  "lot_size_ranges": [
   {
    "letters": {
     "II": "J",
     "S-4": "E"
    },
    "max": 1200,
    "min": 1
   },
   {
    "letters": {
     "II": "K",
     "S-4": "G"
    },
    "max": 3200,
    "min": 1201
   },
   {
    "letters": {
     "II": "L",
     "S-4": "H"
    },
    "max": null,
    "min": 3201
   }
  ],
  "plans": {
   "normal": {
    "E": {
     "0.65": {
      "ac": 0,
      "n": 13,
      "re": 1
     }
    },
    "G": {
     "0.65": {
      "ac": 0,
      "n": 32,
      "re": 1
     }
    },
    "H": {
     "0.65": {
      "ac": 1,
      "n": 50,
      "re": 2
     }
    },
    "J": {
     "0.65": {
      "ac": 1,
      "n": 80,
      "re": 2
     }
    },
    "K": {
     "0.65": {
      "ac": 2,
      "n": 125,
      "re": 3
     }
    },
    "L": {
     "0.65": {
      "ac": 3,
      "n": 200,
      "re": 4
     }
    }
   },
   "tightened": {
    "E": {
     "0.65": {
      "ac": 0,
      "n": 20,
      "re": 1
     }
    },
    "G": {
     "0.65": {
      "ac": 0,
      "n": 50,
      "re": 1
     }
    },
    "H": {
     "0.65": {
      "ac": 1,
      "n": 80,
      "re": 2
     }
    },
    "J": {
     "0.65": {
      "ac": 1,
      "n": 125,
      "re": 2
     }
    },
    "K": {
     "0.65": {
      "ac": 1,
      "n": 200,
      "re": 2
     }
    },
    "L": {
     "0.65": {
      "ac": 2,
      "n": 315,
      "re": 3
     }
    }
   }
  },
  "switching": {
   "to_normal": {
    "consecutive_accepted": 5
   },
   "to_tightened": {
    "of_last": 5,
    "rejected": 2
   }
  }
 }
};

export const exampleSignatureInput: Partial<SignatureInput> = {
 "comment": "Reviewed against drawing rev C",
 "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
 "meaning": "approved",
 "password": "correct horse battery staple",
 "username": "mtremblay@example.com"
};

export const exampleSignatureManifest: SignatureManifest = {
 "action": "approve",
 "auth_method": "password",
 "comment": "",
 "content_matches_current": true,
 "id": "esg_00000000000000000000000000000001",
 "meaning": "approved",
 "meaning_label": "Approved",
 "record_version": 3,
 "signed_at": "2026-11-23T19:05:12.000000Z",
 "signed_at_local": "2026-11-23 14:05:12 EST (UTC-05:00)",
 "signer_legal_name": "Marie Tremblay",
 "signer_username": "mtremblay@example.com",
 "status": "valid",
 "step": 1
};

export const exampleTime: MetaTime = {
 "app_utc": "2026-11-23T19:05:12.000000Z",
 "db_utc": "2026-11-23T19:05:12.000000Z",
 "max_skew_ms": 2000,
 "ok": true,
 "skew_ms": 1.4
};

export const exampleVerify: VerifyResult = {
 "chain_ok": true,
 "content_hash_ok": true,
 "content_matches_current": false,
 "current_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
 "mac_ok": true,
 "record_version_current": 4,
 "record_version_signed": 3,
 "signature_id": "esg_00000000000000000000000000000001"
};

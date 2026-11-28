/**
 * M10 S0 contract examples: `backend/superplanner/api/mfg/fixtures/example_m10.json` verbatim, typed against
 * `typesM10.ts` so the compiler flags drift. Regenerate when the fixture changes. Also served by the m10 e2e spec as
 * route mocks for screens whose services are not built yet.
 */
import type { PendingSignatures } from "./typesM7";
import type {
  Agreement,
  BatchPack,
  Coa,
  CoaLine,
  Deviation,
  DhrException,
  DhrRecord,
  DhrSectionPage,
  DhrSummary,
  IqResult,
  LabelAssignment,
  LabelTemplate,
  OrgAuditRow,
  PrintEvent,
  PrintJob,
  Printer,
  Releasable,
  Residency,
  ReviewQueueRow,
  UdiDevice,
  UdiExport,
  UdiParse,
  ValPackage,
  VerifyResult,
} from "./typesM10";

export const exAgreement: Agreement = {
  "coa": {
    "characteristics": [
      {
        "code": "BLF",
        "item_id": null,
        "label": "Plunger break-loose force",
        "label_fr": "Force de décollement du piston",
        "report": "value",
        "spec": {
          "lsl": null,
          "nominal": null,
          "unit": "N",
          "usl": 10.0
        }
      },
      {
        "code": "GLF",
        "item_id": null,
        "label": "Glide force",
        "label_fr": "Force de glissement",
        "report": "value",
        "spec": {
          "lsl": null,
          "nominal": null,
          "unit": "N",
          "usl": 4.0
        }
      },
      {
        "code": "PART",
        "item_id": null,
        "label": "Particulate",
        "label_fr": "Particules",
        "report": "summary",
        "spec": null
      }
    ],
    "language": "en_fr",
    "statement": "The lot was manufactured and tested according to the agreed specifications.",
    "statement_fr": "Le lot a été fabriqué et contrôlé selon les spécifications convenues."
  },
  "created_at": "2026-11-23T19:05:12.000000Z",
  "customer": "PHARMACO",
  "effective_from": "2026-11-01",
  "external_ref": "PQA-2026-014",
  "id": "cqa_00000000000000000000000000000001",
  "item_ids": [
    "itm_00000000000000000000000000000009"
  ],
  "number": "QA-AG-000001",
  "pack": {
    "documents": [
      "coa",
      "coc",
      "ster_cert",
      "dhr_summary"
    ],
    "per": "lot"
  },
  "row_version": 2,
  "signatures": [
    {
      "action": "approve",
      "auth_method": "password",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000001",
      "meaning": "approved",
      "meaning_label": "Approved",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:20:40 EST (UTC-05:00)",
      "signer_legal_name": "Marie Tremblay",
      "signer_username": "mtremblay@example.com",
      "status": "valid",
      "step": 1
    }
  ],
  "status": "approved",
  "supersedes_id": null,
  "title": "Prefillable syringe supply quality agreement",
  "updated_at": "2026-11-23T19:20:40.000000Z",
  "version": 1
};

export const exBatchPack: BatchPack = {
  "agreement_id": "cqa_00000000000000000000000000000001",
  "created_at": "2026-11-23T19:05:12.000000Z",
  "customer": "PHARMACO",
  "demand_line_id": null,
  "documents": [
    {
      "filename": "P2611QC03/COA-000001.pdf",
      "kind": "coa",
      "lot_id": "lot_00000000000000000000000000000011",
      "ref_id": "coa_00000000000000000000000000000001",
      "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
      "size": 22410
    },
    {
      "filename": "P2611QC03/CoC-P2611QC03.pdf",
      "kind": "coc",
      "lot_id": "lot_00000000000000000000000000000011",
      "ref_id": "dhr_00000000000000000000000000000001",
      "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
      "size": 14002
    }
  ],
  "error": null,
  "id": "bpk_00000000000000000000000000000001",
  "lot_ids": [
    "lot_00000000000000000000000000000011"
  ],
  "manifest_sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
  "number": "BP-000001",
  "rendition": {
    "created_at": "2026-11-23T19:20:40.000000Z",
    "filename": "BP-000001.zip",
    "id": "rnd_00000000000000000000000000000004",
    "kind": "zip",
    "renderer_version": "sp-pdf/1",
    "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "size": 51200,
    "warnings": []
  },
  "row_version": 2,
  "status": "ready",
  "updated_at": "2026-11-23T19:20:40.000000Z"
};

export const exCoa: Coa = {
  "agreement_id": "cqa_00000000000000000000000000000001",
  "agreement_number": "QA-AG-000001",
  "agreement_version": 1,
  "content": {
    "dhr": {
      "content_sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
      "number": "DHR-000009",
      "version": 1
    },
    "item": {
      "name": "Prefillable syringe 1 mL",
      "part_number": "PFS-1ML"
    },
    "language": "en_fr",
    "lines": [
      {
        "code": "GLF",
        "conforms": true,
        "defects": 0,
        "label": "Glide force",
        "label_fr": "Force de glissement",
        "max": 3.8,
        "mean": 3.42,
        "min": 3.1,
        "n": 32,
        "report": "value",
        "result_text": "mean 3.42 N (3.10 - 3.80), n = 32",
        "spec": {
          "lsl": null,
          "nominal": null,
          "unit": "N",
          "usl": 4.0
        },
        "spec_source": "customer"
      }
    ],
    "lot": {
      "expires_on": "2029-11-30",
      "lot_code": "P2611QC03"
    },
    "statement": "The lot was manufactured and tested according to the agreed specifications."
  },
  "content_sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
  "created_at": "2026-11-23T19:05:12.000000Z",
  "customer": "PHARMACO",
  "demand_line_id": null,
  "dhr_id": "dhr_00000000000000000000000000000001",
  "dhr_number": "DHR-000009",
  "id": "coa_00000000000000000000000000000001",
  "item_id": "itm_00000000000000000000000000000009",
  "lot_code": "P2611QC03",
  "lot_id": "lot_00000000000000000000000000000011",
  "number": "COA-000001",
  "rendition": {
    "created_at": "2026-11-23T19:20:40.000000Z",
    "filename": "COA-000001.pdf",
    "id": "rnd_00000000000000000000000000000003",
    "kind": "pdf",
    "renderer_version": "sp-pdf/1",
    "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "size": 22410,
    "warnings": []
  },
  "row_version": 2,
  "signatures": [
    {
      "action": "approve",
      "auth_method": "password",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000001",
      "meaning": "approved",
      "meaning_label": "Approved",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:20:40 EST (UTC-05:00)",
      "signer_legal_name": "Marie Tremblay",
      "signer_username": "mtremblay@example.com",
      "status": "valid",
      "step": 1
    }
  ],
  "status": "approved",
  "updated_at": "2026-11-23T19:20:40.000000Z",
  "void_reason": null
};

export const exCoaLine: CoaLine = {
  "code": "GLF",
  "conforms": true,
  "defects": 0,
  "label": "Glide force",
  "label_fr": "Force de glissement",
  "max": 3.8,
  "mean": 3.42,
  "min": 3.1,
  "n": 32,
  "report": "value",
  "result_text": "mean 3.42 N (3.10 - 3.80), n = 32",
  "spec": {
    "lsl": null,
    "nominal": null,
    "unit": "N",
    "usl": 4.0
  },
  "spec_source": "customer"
};

export const exDeviation: Deviation = {
  "approved_at": "2026-11-23T19:05:12.000000Z",
  "author_id": "usr_00000000000000000000000000000002",
  "capa_id": null,
  "closed_at": null,
  "created_at": "2026-11-23T19:05:12.000000Z",
  "description": "Use resin lot R-5521 from the qualified alternate grade for up to 50,000 units.",
  "external_ref": null,
  "id": "dev_00000000000000000000000000000001",
  "kind": "planned",
  "links": [],
  "ncr_id": null,
  "number": "DEV-000001",
  "outcome": null,
  "people": {
    "usr_00000000000000000000000000000002": "Luc Gagnon"
  },
  "risk": {
    "occurrence": 2,
    "rationale": "Same resin family; tensile data equivalent.",
    "severity": 2
  },
  "risk_score": 4,
  "row_version": 3,
  "scope": {
    "item_ids": [
      "itm_00000000000000000000000000000001"
    ],
    "lot_ids": [],
    "max_qty": 50000.0,
    "valid_from": "2026-11-15",
    "valid_to": "2026-12-31",
    "wo_ids": []
  },
  "signatures": [
    {
      "action": "approve",
      "auth_method": "password_totp",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000002",
      "meaning": "reviewed",
      "meaning_label": "Reviewed",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:10:02 EST (UTC-05:00)",
      "signer_legal_name": "Luc Gagnon",
      "signer_username": "lgagnon@example.com",
      "status": "valid",
      "step": 1
    },
    {
      "action": "approve",
      "auth_method": "password",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000001",
      "meaning": "approved",
      "meaning_label": "Approved",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:20:40 EST (UTC-05:00)",
      "signer_legal_name": "Marie Tremblay",
      "signer_username": "mtremblay@example.com",
      "status": "valid",
      "step": 2
    }
  ],
  "sor": "superplanner",
  "status": "approved",
  "title": "Alternate plunger resin lot",
  "updated_at": "2026-11-23T19:20:40.000000Z",
  "used_qty": 23880.0
};

export const exDhrBlocked: Releasable = {
  "blocking": [
    {
      "code": "EXCEPTION_OPEN",
      "message": "DHR_CORRECTION on WO-000413/20 has no disposition.",
      "ref_id": "dhx_00000000000000000000000000000005",
      "ref_number": null,
      "ref_type": "dhr_exception"
    },
    {
      "code": "NCR_OPEN",
      "message": "NCR-000008 is not closed.",
      "ref_id": "ncr_00000000000000000000000000000008",
      "ref_number": "NCR-000008",
      "ref_type": "ncr"
    },
    {
      "code": "LABEL_NOT_RECONCILED",
      "message": "Print job LP-000022 is not reconciled.",
      "ref_id": "lpj_00000000000000000000000000000016",
      "ref_number": "LP-000022",
      "ref_type": "print_job"
    },
    {
      "code": "STERILITY_HOLD",
      "message": "The sterility hold of the lot is open.",
      "ref_id": "hld_0000000000000000000000000000000a",
      "ref_number": null,
      "ref_type": "hold"
    }
  ],
  "ok": false
};

export const exDhrException: DhrException = {
  "allowed": [
    "accepted",
    "deviation",
    "ncr"
  ],
  "carried": false,
  "code": "DHR_TIME_WINDOW",
  "comment": "Covered by the planned deviation for the alternate plunger resin.",
  "data": {
    "kind": "duration",
    "max_minutes": 120,
    "minutes": 135,
    "seq": 30
  },
  "disposition": "deviation",
  "disposition_ref": "dev_00000000000000000000000000000001",
  "disposition_ref_number": "DEV-000001",
  "fingerprint": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
  "id": "dhx_00000000000000000000000000000001",
  "message": "Operation 30 Assembly ran 135 min; the routing allows 120 min.",
  "needs_disposition": false,
  "record_id": "dhr_00000000000000000000000000000001",
  "ref_id": "wop_00000000000000000000000000000003",
  "ref_number": "WO-000412/30",
  "ref_type": "wo_operation",
  "reviewed_at": "2026-11-23T19:05:12.000000Z",
  "reviewed_by": "usr_00000000000000000000000000000002",
  "row_version": 2,
  "section": "operations",
  "severity": "major"
};

export const exDhrLive: DhrRecord = {
  "age_days": 0.6,
  "assembled_at": "2026-11-23T19:05:12.000000Z",
  "changed_after_release": false,
  "content": {
    "equipment": {
      "equipment": [
        {
          "calibration_due": "2027-03-01",
          "certificate": "CAL-2026-0712",
          "code": "FG-07",
          "name": "Force gauge 07",
          "use_date": "2026-11-21",
          "valid": true
        }
      ]
    },
    "genealogy": {
      "backward": [
        {
          "item": "BRL-3ML",
          "kind": "exact",
          "lot_code": "BRL2611-04"
        },
        {
          "item": "PLG-RES",
          "kind": "possible",
          "lot_code": "R-5521"
        }
      ],
      "forward": [
        {
          "kind": "shipment",
          "qty": 12000.0,
          "ref": "DO-000310/1"
        }
      ]
    },
    "header": {
      "dhr_required": true,
      "dis": [
        {
          "gtin": "09521234500018",
          "level": "each",
          "status": "approved"
        }
      ],
      "expiry": "2029-11-30",
      "first_start": "2026-11-20T11:02:00.000000Z",
      "item": {
        "id": "itm_00000000000000000000000000000001",
        "name": "Syringe 3 mL Luer lock",
        "part_number": "SYR-3ML-LL",
        "revision": "C"
      },
      "item_revision": {
        "bom_id": "bom_00000000000000000000000000000001",
        "bom_version": 3,
        "ecos": [
          "ECO-000014"
        ],
        "routing_id": "rtg_00000000000000000000000000000001",
        "routing_version": 2
      },
      "last_receipt": "2026-11-21T22:40:00.000000Z",
      "lot": {
        "expires_on": "2029-11-30",
        "id": "lot_00000000000000000000000000000007",
        "lot_code": "A2611QC07"
      },
      "plant": {
        "name": "Quebec City (sample)",
        "time_zone": "America/Toronto"
      },
      "qty_planned": 24000.0,
      "qty_received": 23880.0,
      "qty_scrapped": 120.0,
      "sterile": true,
      "subject_kind": "lot",
      "wos": [
        {
          "id": "wor_00000000000000000000000000000001",
          "number": "WO-000412",
          "qty": 24000.0,
          "qty_completed": 23880.0,
          "qty_scrapped": 120.0,
          "status": "closed"
        }
      ]
    },
    "holds": {
      "holds": [
        {
          "placed_at": "2026-11-21T22:40:00.000000Z",
          "released_at": "2026-11-22T21:00:00.000000Z",
          "signature": "Approved by Luc Gagnon",
          "source": "sterility"
        },
        {
          "placed_at": "2026-11-21T22:40:00.000000Z",
          "released_at": null,
          "signature": null,
          "source": "dhr"
        }
      ]
    },
    "inspections": {
      "lots": [
        {
          "decision": "accept",
          "defects": 0,
          "lot_size": 23880.0,
          "number": "IL-000091",
          "plan": "IP-000012",
          "plan_version": 4,
          "results": 48,
          "scope": "final",
          "signatures": 1,
          "status": "accepted"
        }
      ]
    },
    "labels": {
      "jobs": [
        {
          "gtin": "09521234500018",
          "number": "LP-000021",
          "status": "reconciled",
          "template": "SYR-EACH",
          "template_version": 2,
          "totals": {
            "destroyed": 100,
            "diff": 0,
            "issued": 24000,
            "printed": 24000,
            "reprinted": 0,
            "retained": 20,
            "used": 23880
          },
          "verify": {
            "first": true,
            "last": true,
            "mismatches": 0
          }
        }
      ]
    },
    "materials": {
      "lines": [
        {
          "held_at_issue": false,
          "incoming": {
            "decision": "accept",
            "inspection_lot": "IL-000077"
          },
          "item": {
            "id": "itm_00000000000000000000000000000003",
            "name": "Barrel 3 mL",
            "part_number": "BRL-3ML"
          },
          "location": "LINE-A",
          "lot_code": "BRL2611-04",
          "lot_id": "lot_0000000000000000000000000000001f",
          "possible": false,
          "posting": "TXN-000981",
          "posting_id": "pst_00000000000000000000000000000009",
          "qty": 24120.0,
          "supplier": "Barrel supplier (fictional)",
          "supplier_lot": "K-88231",
          "txn_type": "wo_issue",
          "uom": "EA"
        }
      ],
      "possible_edges": 2
    },
    "nonconformance": {
      "deviations": [
        {
          "in_scope": true,
          "kind": "planned",
          "number": "DEV-000001",
          "status": "approved",
          "title": "Alternate plunger resin lot"
        }
      ],
      "ncrs": []
    },
    "operations": {
      "events_total": 18,
      "operations": [
        {
          "corrections": 0,
          "ended_at": "2026-11-20T15:15:00.000000Z",
          "events": 6,
          "line": "FLA-01",
          "max_minutes": 120,
          "max_wait_minutes": 240,
          "minutes": 135.0,
          "name": "Assembly",
          "operators": [
            "Op 14",
            "Op 22"
          ],
          "qty_good": 23880.0,
          "qty_in": 24000.0,
          "qty_nc": 0.0,
          "qty_rework": 0.0,
          "qty_scrap": 120.0,
          "seq": 30,
          "started_at": "2026-11-20T13:00:00.000000Z",
          "status": "completed",
          "wait_minutes": 40.0,
          "wo_number": "WO-000412"
        }
      ]
    },
    "review": {
      "exceptions": [
        {
          "code": "DHR_TIME_WINDOW",
          "disposition": "deviation",
          "fingerprint": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
          "ref": "DEV-000001"
        }
      ]
    },
    "serials": {
      "count": 0,
      "list_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "ranges": []
    },
    "sterilisation": {
      "loads": [
        {
          "actual_end": "2026-11-22T20:00:00.000000Z",
          "chamber": "EO-01",
          "co_lots": [
            "A2611QC06"
          ],
          "cycle_code": "EO-STD",
          "number": "SL-000033",
          "planned_start": "2026-11-22T06:00:00.000000Z",
          "release_mode": "parametric",
          "release_signature": "Approved by Luc Gagnon",
          "status": "released"
        }
      ],
      "required": true
    }
  },
  "content_sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
  "counts": {
    "info": 1,
    "major": 1,
    "minor": 0,
    "open": 0
  },
  "decision": null,
  "dhr_required": true,
  "exceptions": [
    {
      "allowed": [
        "accepted",
        "deviation",
        "ncr"
      ],
      "carried": false,
      "code": "DHR_TIME_WINDOW",
      "comment": "Covered by the planned deviation for the alternate plunger resin.",
      "data": {
        "kind": "duration",
        "max_minutes": 120,
        "minutes": 135,
        "seq": 30
      },
      "disposition": "deviation",
      "disposition_ref": "dev_00000000000000000000000000000001",
      "disposition_ref_number": "DEV-000001",
      "fingerprint": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
      "id": "dhx_00000000000000000000000000000001",
      "message": "Operation 30 Assembly ran 135 min; the routing allows 120 min.",
      "needs_disposition": false,
      "record_id": "dhr_00000000000000000000000000000001",
      "ref_id": "wop_00000000000000000000000000000003",
      "ref_number": "WO-000412/30",
      "ref_type": "wo_operation",
      "reviewed_at": "2026-11-23T19:05:12.000000Z",
      "reviewed_by": "usr_00000000000000000000000000000002",
      "row_version": 2,
      "section": "operations",
      "severity": "major"
    },
    {
      "allowed": [],
      "carried": false,
      "code": "DHR_GENEALOGY_POSSIBLE",
      "comment": null,
      "data": {
        "edges": 2
      },
      "disposition": null,
      "disposition_ref": null,
      "disposition_ref_number": null,
      "fingerprint": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2",
      "id": "dhx_00000000000000000000000000000002",
      "message": "Plunger resin lots are linked as possible (backflush across lots).",
      "needs_disposition": false,
      "record_id": "dhr_00000000000000000000000000000001",
      "ref_id": "itm_00000000000000000000000000000004",
      "ref_number": "PLG-RES",
      "ref_type": "item",
      "reviewed_at": null,
      "reviewed_by": null,
      "row_version": 1,
      "section": "genealogy",
      "severity": "info"
    }
  ],
  "hold_id": "hld_00000000000000000000000000000009",
  "hold_open": true,
  "id": "live",
  "item": {
    "id": "itm_00000000000000000000000000000001",
    "name": "Syringe 3 mL Luer lock",
    "part_number": "SYR-3ML-LL",
    "revision": "C"
  },
  "item_revision": {
    "bom_id": "bom_00000000000000000000000000000001",
    "bom_version": 3,
    "ecos": [
      "ECO-000014"
    ],
    "routing_id": "rtg_00000000000000000000000000000001",
    "routing_version": 2
  },
  "lot_code": "A2611QC07",
  "lot_id": "lot_00000000000000000000000000000007",
  "number": "-",
  "reassemble_reason": null,
  "releasable": {
    "blocking": [
      {
        "code": "EXCEPTION_OPEN",
        "message": "DHR_CORRECTION on WO-000413/20 has no disposition.",
        "ref_id": "dhx_00000000000000000000000000000005",
        "ref_number": null,
        "ref_type": "dhr_exception"
      },
      {
        "code": "NCR_OPEN",
        "message": "NCR-000008 is not closed.",
        "ref_id": "ncr_00000000000000000000000000000008",
        "ref_number": "NCR-000008",
        "ref_type": "ncr"
      },
      {
        "code": "LABEL_NOT_RECONCILED",
        "message": "Print job LP-000022 is not reconciled.",
        "ref_id": "lpj_00000000000000000000000000000016",
        "ref_number": "LP-000022",
        "ref_type": "print_job"
      },
      {
        "code": "STERILITY_HOLD",
        "message": "The sterility hold of the lot is open.",
        "ref_id": "hld_0000000000000000000000000000000a",
        "ref_number": null,
        "ref_type": "hold"
      }
    ],
    "ok": false
  },
  "released_at": null,
  "renderer_version": "sp-pdf/1",
  "renditions": [],
  "row_version": 0,
  "section_hashes": {
    "equipment": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "genealogy": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "header": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "holds": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "inspections": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "labels": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "materials": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "nonconformance": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "operations": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "review": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "serials": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "sterilisation": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a"
  },
  "signatures": [],
  "status": "open",
  "subject_kind": "lot",
  "superseded_by_id": null,
  "supersedes_id": null,
  "version": 1,
  "versions": [],
  "wo_ids": [
    "wor_00000000000000000000000000000001"
  ],
  "wo_numbers": [
    "WO-000412"
  ]
};

export const exDhrRecord: DhrRecord = {
  "age_days": 0.6,
  "assembled_at": "2026-11-23T19:05:12.000000Z",
  "changed_after_release": false,
  "content": {
    "equipment": {
      "equipment": [
        {
          "calibration_due": "2027-03-01",
          "certificate": "CAL-2026-0712",
          "code": "FG-07",
          "name": "Force gauge 07",
          "use_date": "2026-11-21",
          "valid": true
        }
      ]
    },
    "genealogy": {
      "backward": [
        {
          "item": "BRL-3ML",
          "kind": "exact",
          "lot_code": "BRL2611-04"
        },
        {
          "item": "PLG-RES",
          "kind": "possible",
          "lot_code": "R-5521"
        }
      ],
      "forward": [
        {
          "kind": "shipment",
          "qty": 12000.0,
          "ref": "DO-000310/1"
        }
      ]
    },
    "header": {
      "dhr_required": true,
      "dis": [
        {
          "gtin": "09521234500018",
          "level": "each",
          "status": "approved"
        }
      ],
      "expiry": "2029-11-30",
      "first_start": "2026-11-20T11:02:00.000000Z",
      "item": {
        "id": "itm_00000000000000000000000000000001",
        "name": "Syringe 3 mL Luer lock",
        "part_number": "SYR-3ML-LL",
        "revision": "C"
      },
      "item_revision": {
        "bom_id": "bom_00000000000000000000000000000001",
        "bom_version": 3,
        "ecos": [
          "ECO-000014"
        ],
        "routing_id": "rtg_00000000000000000000000000000001",
        "routing_version": 2
      },
      "last_receipt": "2026-11-21T22:40:00.000000Z",
      "lot": {
        "expires_on": "2029-11-30",
        "id": "lot_00000000000000000000000000000007",
        "lot_code": "A2611QC07"
      },
      "plant": {
        "name": "Quebec City (sample)",
        "time_zone": "America/Toronto"
      },
      "qty_planned": 24000.0,
      "qty_received": 23880.0,
      "qty_scrapped": 120.0,
      "sterile": true,
      "subject_kind": "lot",
      "wos": [
        {
          "id": "wor_00000000000000000000000000000001",
          "number": "WO-000412",
          "qty": 24000.0,
          "qty_completed": 23880.0,
          "qty_scrapped": 120.0,
          "status": "closed"
        }
      ]
    },
    "holds": {
      "holds": [
        {
          "placed_at": "2026-11-21T22:40:00.000000Z",
          "released_at": "2026-11-22T21:00:00.000000Z",
          "signature": "Approved by Luc Gagnon",
          "source": "sterility"
        },
        {
          "placed_at": "2026-11-21T22:40:00.000000Z",
          "released_at": null,
          "signature": null,
          "source": "dhr"
        }
      ]
    },
    "inspections": {
      "lots": [
        {
          "decision": "accept",
          "defects": 0,
          "lot_size": 23880.0,
          "number": "IL-000091",
          "plan": "IP-000012",
          "plan_version": 4,
          "results": 48,
          "scope": "final",
          "signatures": 1,
          "status": "accepted"
        }
      ]
    },
    "labels": {
      "jobs": [
        {
          "gtin": "09521234500018",
          "number": "LP-000021",
          "status": "reconciled",
          "template": "SYR-EACH",
          "template_version": 2,
          "totals": {
            "destroyed": 100,
            "diff": 0,
            "issued": 24000,
            "printed": 24000,
            "reprinted": 0,
            "retained": 20,
            "used": 23880
          },
          "verify": {
            "first": true,
            "last": true,
            "mismatches": 0
          }
        }
      ]
    },
    "materials": {
      "lines": [
        {
          "held_at_issue": false,
          "incoming": {
            "decision": "accept",
            "inspection_lot": "IL-000077"
          },
          "item": {
            "id": "itm_00000000000000000000000000000003",
            "name": "Barrel 3 mL",
            "part_number": "BRL-3ML"
          },
          "location": "LINE-A",
          "lot_code": "BRL2611-04",
          "lot_id": "lot_0000000000000000000000000000001f",
          "possible": false,
          "posting": "TXN-000981",
          "posting_id": "pst_00000000000000000000000000000009",
          "qty": 24120.0,
          "supplier": "Barrel supplier (fictional)",
          "supplier_lot": "K-88231",
          "txn_type": "wo_issue",
          "uom": "EA"
        }
      ],
      "possible_edges": 2
    },
    "nonconformance": {
      "deviations": [
        {
          "in_scope": true,
          "kind": "planned",
          "number": "DEV-000001",
          "status": "approved",
          "title": "Alternate plunger resin lot"
        }
      ],
      "ncrs": []
    },
    "operations": {
      "events_total": 18,
      "operations": [
        {
          "corrections": 0,
          "ended_at": "2026-11-20T15:15:00.000000Z",
          "events": 6,
          "line": "FLA-01",
          "max_minutes": 120,
          "max_wait_minutes": 240,
          "minutes": 135.0,
          "name": "Assembly",
          "operators": [
            "Op 14",
            "Op 22"
          ],
          "qty_good": 23880.0,
          "qty_in": 24000.0,
          "qty_nc": 0.0,
          "qty_rework": 0.0,
          "qty_scrap": 120.0,
          "seq": 30,
          "started_at": "2026-11-20T13:00:00.000000Z",
          "status": "completed",
          "wait_minutes": 40.0,
          "wo_number": "WO-000412"
        }
      ]
    },
    "review": {
      "exceptions": [
        {
          "code": "DHR_TIME_WINDOW",
          "disposition": "deviation",
          "fingerprint": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
          "ref": "DEV-000001"
        }
      ]
    },
    "serials": {
      "count": 0,
      "list_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "ranges": []
    },
    "sterilisation": {
      "loads": [
        {
          "actual_end": "2026-11-22T20:00:00.000000Z",
          "chamber": "EO-01",
          "co_lots": [
            "A2611QC06"
          ],
          "cycle_code": "EO-STD",
          "number": "SL-000033",
          "planned_start": "2026-11-22T06:00:00.000000Z",
          "release_mode": "parametric",
          "release_signature": "Approved by Luc Gagnon",
          "status": "released"
        }
      ],
      "required": true
    }
  },
  "content_sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
  "counts": {
    "info": 1,
    "major": 1,
    "minor": 0,
    "open": 0
  },
  "decision": "released",
  "dhr_required": true,
  "exceptions": [
    {
      "allowed": [
        "accepted",
        "deviation",
        "ncr"
      ],
      "carried": false,
      "code": "DHR_TIME_WINDOW",
      "comment": "Covered by the planned deviation for the alternate plunger resin.",
      "data": {
        "kind": "duration",
        "max_minutes": 120,
        "minutes": 135,
        "seq": 30
      },
      "disposition": "deviation",
      "disposition_ref": "dev_00000000000000000000000000000001",
      "disposition_ref_number": "DEV-000001",
      "fingerprint": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
      "id": "dhx_00000000000000000000000000000001",
      "message": "Operation 30 Assembly ran 135 min; the routing allows 120 min.",
      "needs_disposition": false,
      "record_id": "dhr_00000000000000000000000000000001",
      "ref_id": "wop_00000000000000000000000000000003",
      "ref_number": "WO-000412/30",
      "ref_type": "wo_operation",
      "reviewed_at": "2026-11-23T19:05:12.000000Z",
      "reviewed_by": "usr_00000000000000000000000000000002",
      "row_version": 2,
      "section": "operations",
      "severity": "major"
    },
    {
      "allowed": [],
      "carried": false,
      "code": "DHR_GENEALOGY_POSSIBLE",
      "comment": null,
      "data": {
        "edges": 2
      },
      "disposition": null,
      "disposition_ref": null,
      "disposition_ref_number": null,
      "fingerprint": "b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2",
      "id": "dhx_00000000000000000000000000000002",
      "message": "Plunger resin lots are linked as possible (backflush across lots).",
      "needs_disposition": false,
      "record_id": "dhr_00000000000000000000000000000001",
      "ref_id": "itm_00000000000000000000000000000004",
      "ref_number": "PLG-RES",
      "ref_type": "item",
      "reviewed_at": null,
      "reviewed_by": null,
      "row_version": 1,
      "section": "genealogy",
      "severity": "info"
    }
  ],
  "hold_id": "hld_00000000000000000000000000000009",
  "hold_open": false,
  "id": "dhr_00000000000000000000000000000001",
  "item": {
    "id": "itm_00000000000000000000000000000001",
    "name": "Syringe 3 mL Luer lock",
    "part_number": "SYR-3ML-LL",
    "revision": "C"
  },
  "item_revision": {
    "bom_id": "bom_00000000000000000000000000000001",
    "bom_version": 3,
    "ecos": [
      "ECO-000014"
    ],
    "routing_id": "rtg_00000000000000000000000000000001",
    "routing_version": 2
  },
  "lot_code": "A2611QC07",
  "lot_id": "lot_00000000000000000000000000000007",
  "number": "DHR-000007",
  "reassemble_reason": null,
  "releasable": {
    "blocking": [],
    "ok": true
  },
  "released_at": "2026-11-23T19:20:40.000000Z",
  "renderer_version": "sp-pdf/1",
  "renditions": [
    {
      "created_at": "2026-11-23T19:20:40.000000Z",
      "filename": "DHR-000007-v1.pdf",
      "id": "rnd_00000000000000000000000000000001",
      "kind": "pdf",
      "renderer_version": "sp-pdf/1",
      "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
      "size": 182344,
      "warnings": []
    },
    {
      "created_at": "2026-11-23T19:20:40.000000Z",
      "filename": "DHR-000007-v1.json",
      "id": "rnd_00000000000000000000000000000002",
      "kind": "json",
      "renderer_version": "sp-pdf/1",
      "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
      "size": 41220,
      "warnings": []
    }
  ],
  "row_version": 3,
  "section_hashes": {
    "equipment": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "genealogy": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "header": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "holds": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "inspections": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "labels": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "materials": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "nonconformance": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "operations": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "review": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "serials": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "sterilisation": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a"
  },
  "signatures": [
    {
      "action": "release",
      "auth_method": "password_totp",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000002",
      "meaning": "reviewed",
      "meaning_label": "Reviewed",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:10:02 EST (UTC-05:00)",
      "signer_legal_name": "Luc Gagnon",
      "signer_username": "lgagnon@example.com",
      "status": "valid",
      "step": 1
    },
    {
      "action": "release",
      "auth_method": "password_totp",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000001",
      "meaning": "released",
      "meaning_label": "Released",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:20:40 EST (UTC-05:00)",
      "signer_legal_name": "Marie Tremblay",
      "signer_username": "mtremblay@example.com",
      "status": "valid",
      "step": 2
    }
  ],
  "status": "released",
  "subject_kind": "lot",
  "superseded_by_id": null,
  "supersedes_id": null,
  "version": 1,
  "versions": [
    {
      "assembled_at": "2026-11-23T19:05:12.000000Z",
      "changed_after_release": false,
      "content_sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
      "id": "dhr_00000000000000000000000000000001",
      "reassemble_reason": null,
      "section_hashes": {
        "equipment": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "genealogy": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "header": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "holds": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "inspections": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "labels": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "materials": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "nonconformance": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "operations": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "review": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "serials": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "sterilisation": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a"
      },
      "status": "released",
      "version": 1
    }
  ],
  "wo_ids": [
    "wor_00000000000000000000000000000001"
  ],
  "wo_numbers": [
    "WO-000412"
  ]
};

export const exDhrSection: DhrSectionPage = {
  "data": {
    "count": 0,
    "list_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "ranges": []
  },
  "items": [
    "SN0001",
    "SN0002"
  ],
  "limit": 500,
  "page": 1,
  "record_id": "dhr_00000000000000000000000000000001",
  "section": "serials",
  "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
  "total": 2
};

export const exDhrSummary: DhrSummary = {
  "age_days": 0.6,
  "assembled_at": "2026-11-23T19:05:12.000000Z",
  "changed_after_release": false,
  "counts": {
    "info": 1,
    "major": 1,
    "minor": 0,
    "open": 0
  },
  "decision": "released",
  "id": "dhr_00000000000000000000000000000001",
  "item": {
    "id": "itm_00000000000000000000000000000001",
    "name": "Syringe 3 mL Luer lock",
    "part_number": "SYR-3ML-LL",
    "revision": "C"
  },
  "lot_code": "A2611QC07",
  "lot_id": "lot_00000000000000000000000000000007",
  "number": "DHR-000007",
  "released_at": "2026-11-23T19:20:40.000000Z",
  "row_version": 3,
  "status": "released",
  "subject_kind": "lot",
  "superseded_by_id": null,
  "version": 1,
  "wo_ids": [
    "wor_00000000000000000000000000000001"
  ],
  "wo_numbers": [
    "WO-000412"
  ]
};

export const exIqResult: IqResult = {
  "at": "2026-11-23T19:05:12.000000Z",
  "checks": [
    {
      "code": "IQ_APP_VERSION",
      "detail": "",
      "expected": null,
      "label": "Application version",
      "observed": "1.10.0",
      "status": "pass"
    },
    {
      "code": "IQ_ARCHIVE_DIR",
      "detail": "/srv/archive is not writable",
      "expected": true,
      "label": "ARCHIVE_DIR writable",
      "observed": false,
      "status": "fail"
    },
    {
      "code": "IQ_CLOCK_SKEW",
      "detail": "",
      "expected": "<= 1000 ms",
      "label": "App / database clock skew",
      "observed": 12.0,
      "status": "pass"
    }
  ],
  "ok": false,
  "plant": "QC"
};

export const exLabelAssignment: LabelAssignment = {
  "customer": null,
  "item_id": "itm_00000000000000000000000000000001",
  "level": "each",
  "template_code": "SYR-EACH"
};

export const exLabelTemplate: LabelTemplate = {
  "approved_at": "2026-11-23T19:05:12.000000Z",
  "code": "SYR-EACH",
  "created_at": "2026-11-23T19:05:12.000000Z",
  "dpi": 300,
  "eco_id": "ecr_0000000000000000000000000000000e",
  "eco_number": "ECO-000014",
  "elements": [
    {
      "barcode": null,
      "bold": true,
      "field": "udi.brand",
      "font_pt": 7,
      "h_mm": 4,
      "kind": "field",
      "lang": null,
      "path": null,
      "rotation": 0,
      "text": null,
      "w_mm": 46,
      "x_mm": 2,
      "y_mm": 2
    },
    {
      "barcode": {
        "ais": [
          "01",
          "17",
          "10"
        ],
        "hri": true,
        "module_mm": 0.5,
        "symbology": "gs1_datamatrix"
      },
      "bold": false,
      "field": null,
      "font_pt": 6,
      "h_mm": 14,
      "kind": "barcode",
      "lang": null,
      "path": null,
      "rotation": 0,
      "text": null,
      "w_mm": 14,
      "x_mm": 2,
      "y_mm": 8
    },
    {
      "barcode": null,
      "bold": false,
      "field": null,
      "font_pt": 6,
      "h_mm": 4,
      "kind": "text",
      "lang": "fr",
      "path": null,
      "rotation": 0,
      "text": "Stérile - usage unique",
      "w_mm": 30,
      "x_mm": 18,
      "y_mm": 8
    }
  ],
  "height_mm": 30.0,
  "id": "lbt_00000000000000000000000000000002",
  "issues": [],
  "languages": [
    "en",
    "fr"
  ],
  "level": "each",
  "name": "Syringe unit label (bilingual)",
  "row_version": 4,
  "status": "approved",
  "supersedes_id": "lbt_00000000000000000000000000000001",
  "updated_at": "2026-11-23T19:20:40.000000Z",
  "version": 2,
  "width_mm": 50.0
};

export const exOrgAuditRow: OrgAuditRow = {
  "action": "release",
  "actor_id": "usr_00000000000000000000000000000003",
  "created_at": "2026-11-23T19:20:40.000000Z",
  "details": {
    "decision": "released"
  },
  "entity_id": "dhr_00000000000000000000000000000001",
  "entity_type": "mfg_dhr",
  "id": 88123,
  "owner_id": "usr_0000000000000000000000000000000b",
  "plant": "QC",
  "reason": "Reviewed by exception",
  "signature_id": "esg_00000000000000000000000000000001"
};

export const exPendingSignatures: PendingSignatures = {
  "next_step": {
    "auth": "password_totp",
    "blocked_reason": "ESIG_SAME_SIGNER",
    "can_sign": false,
    "meanings": [
      "released"
    ],
    "roles": [
      "qa_approver"
    ],
    "step": 2
  },
  "record_id": "dhr_00000000000000000000000000000001",
  "record_type": "dhr",
  "signatures": [
    {
      "action": "release",
      "auth_method": "password_totp",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000002",
      "meaning": "reviewed",
      "meaning_label": "Reviewed",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:10:02 EST (UTC-05:00)",
      "signer_legal_name": "Luc Gagnon",
      "signer_username": "lgagnon@example.com",
      "status": "valid",
      "step": 1
    }
  ],
  "status": "pending_signatures"
};

export const exPrintEvent: PrintEvent = {
  "actor_id": "usr_00000000000000000000000000000005",
  "at": "2026-11-23T19:05:12.000000Z",
  "client_event_id": "tab-7-0001",
  "id": "lpe_00000000000000000000000000000001",
  "job_id": "lpj_00000000000000000000000000000015",
  "kind": "verify",
  "mismatch": null,
  "position": "first",
  "qty": 0,
  "reason": null,
  "result": "match",
  "scan": "]d201095212345000181728113010A2611QC07",
  "serials": null
};

export const exPrintJob: PrintJob = {
  "created_at": "2026-11-23T19:05:12.000000Z",
  "data": {
    "lot.expiry": "2029-11-30",
    "lot.number": "A2611QC07",
    "udi.brand": "SampleCare",
    "udi.gtin": "09521234500018"
  },
  "data_sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
  "element_string": "01095212345000181729113010A2611QC07",
  "events": [
    {
      "actor_id": "usr_00000000000000000000000000000005",
      "at": "2026-11-23T19:05:12.000000Z",
      "client_event_id": "tab-7-0001",
      "id": "lpe_00000000000000000000000000000001",
      "job_id": "lpj_00000000000000000000000000000015",
      "kind": "verify",
      "mismatch": null,
      "position": "first",
      "qty": 0,
      "reason": null,
      "result": "match",
      "scan": "]d201095212345000181728113010A2611QC07",
      "serials": null
    }
  ],
  "gtin": "09521234500018",
  "hri": "(01)09521234500018(17)291130(10)A2611QC07",
  "id": "lpj_00000000000000000000000000000015",
  "item_id": "itm_00000000000000000000000000000001",
  "item_part_number": "SYR-3ML-LL",
  "level": "each",
  "lot_code": "A2611QC07",
  "lot_id": "lot_00000000000000000000000000000007",
  "number": "LP-000021",
  "output": "zpl",
  "printer_id": "lpr_00000000000000000000000000000001",
  "qty": 24000,
  "recon_explanation": null,
  "reconciled_at": "2026-11-23T19:20:40.000000Z",
  "row_version": 6,
  "serials": null,
  "signatures": [],
  "status": "reconciled",
  "target": "printer",
  "template_code": "SYR-EACH",
  "template_id": "lbt_00000000000000000000000000000002",
  "template_version": 2,
  "totals": {
    "destroyed": 100,
    "diff": 0,
    "issued": 24000,
    "printed": 24000,
    "reprinted": 0,
    "retained": 20,
    "used": 23880
  },
  "udi_id": "udi_00000000000000000000000000000001",
  "updated_at": "2026-11-23T19:20:40.000000Z",
  "verify": {
    "first": true,
    "last": true,
    "mismatches": 0
  },
  "wo_id": "wor_00000000000000000000000000000001"
};

export const exPrinter: Printer = {
  "active": true,
  "code": "ZPL-FLA",
  "created_at": "2026-11-23T19:05:12.000000Z",
  "dpi": 300,
  "host": "10.20.0.41",
  "id": "lpr_00000000000000000000000000000001",
  "kind": "zpl_raw",
  "line_id": null,
  "name": "Line A label printer",
  "port": 9100,
  "row_version": 1,
  "updated_at": "2026-11-23T19:05:12.000000Z"
};

export const exResidency: Residency = {
  "data_region": "ca",
  "deployment_region": "ca",
  "items": [
    {
      "detail": "",
      "exception_signature_id": null,
      "kind": "deployment",
      "name": "SP_REGION",
      "ok": true,
      "region": "ca"
    },
    {
      "detail": "",
      "exception_signature_id": null,
      "kind": "archive",
      "name": "ARCHIVE_DIR",
      "ok": true,
      "region": "ca"
    }
  ],
  "mismatches": [
    {
      "detail": "The assistant stays off in Part 11 plants unless signed on.",
      "exception_signature_id": null,
      "kind": "ai",
      "name": "Assistant model endpoint",
      "ok": false,
      "region": "us"
    }
  ],
  "ok": false,
  "org_id": "org_00000000000000000000000000000001"
};

export const exReviewQueueRow: ReviewQueueRow = {
  "age_days": 1.4,
  "changed_after_release": false,
  "id": "dhr_00000000000000000000000000000008",
  "item": {
    "id": "itm_00000000000000000000000000000001",
    "name": "Syringe 3 mL Luer lock",
    "part_number": "SYR-3ML-LL",
    "revision": "C"
  },
  "line_codes": [
    "FLA-01"
  ],
  "lot_code": "A2611QC08",
  "number": "DHR-000008",
  "oldest_exception_age_days": 1.4,
  "open_major": 1,
  "open_minor": 2,
  "reviewer_ids": [
    "usr_00000000000000000000000000000002"
  ],
  "status": "in_review",
  "version": 1
};

export const exUdiDevice: UdiDevice = {
  "attrs": {
    "brand": "SampleCare",
    "catalog_no": "SC-303",
    "combination": false,
    "description": "Sterile single-use syringe 3 mL, Luer lock",
    "fda_class": "II",
    "fda_product_codes": [
      "FMF"
    ],
    "gmdn_code": "47017",
    "gmdn_term": "General-purpose syringe, single-use",
    "hc_class": "II",
    "hc_licence_no": "00000",
    "kit": false,
    "latex": false,
    "mri_safety": "not_evaluated",
    "premarket_nos": [
      "K000000"
    ],
    "rx": true,
    "single_use": true,
    "ster_method": "Ethylene oxide",
    "sterile": true,
    "storage": [],
    "version_model": "3 mL LL"
  },
  "commercial_distribution_date": "2026-12-01",
  "contains_gtin": null,
  "created_at": "2026-11-23T19:05:12.000000Z",
  "di_kind": "base",
  "gtin": "09521234500018",
  "gtin_locked": true,
  "id": "udi_00000000000000000000000000000001",
  "item_id": "itm_00000000000000000000000000000001",
  "item_part_number": "SYR-3ML-LL",
  "level": "each",
  "packaging_id": "pkg_00000000000000000000000000000001",
  "pi_flags": {
    "expiry": true,
    "lot": true,
    "mfg_date": false,
    "serial": false
  },
  "qty_per_package": 1,
  "row_version": 3,
  "signatures": [
    {
      "action": "approve",
      "auth_method": "password",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000001",
      "meaning": "approved",
      "meaning_label": "Approved",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:20:40 EST (UTC-05:00)",
      "signer_legal_name": "Marie Tremblay",
      "signer_username": "mtremblay@example.com",
      "status": "valid",
      "step": 1
    }
  ],
  "status": "approved",
  "updated_at": "2026-11-23T19:20:40.000000Z"
};

export const exUdiExport: UdiExport = {
  "created_at": "2026-11-23T19:05:12.000000Z",
  "id": "uex_00000000000000000000000000000001",
  "kind": "gudid",
  "number": "UX-000001",
  "params": {
    "format": "xlsx",
    "item_ids": null
  },
  "rendition": {
    "created_at": "2026-11-23T19:20:40.000000Z",
    "filename": "UX-000001-gudid.xlsx",
    "id": "rnd_00000000000000000000000000000005",
    "kind": "xlsx",
    "renderer_version": "sp-pdf/1",
    "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "size": 7311,
    "warnings": []
  },
  "result": {
    "errors": [],
    "rows": 3,
    "warnings": [
      {
        "element": "deviceCount",
        "gtin": "19521234500015",
        "message": "Package DI: device count 10 from qty_per_package."
      }
    ]
  },
  "row_version": 2,
  "rule_version": "gudid-2026.1",
  "status": "completed"
};

export const exUdiParse: UdiParse = {
  "ais": {
    "01": "09521234500018",
    "10": "A2611QC07",
    "17": "281130",
    "21": "SN0001"
  },
  "data": "01095212345000181728113010A2611QC07\u001d21SN0001",
  "errors": [],
  "expiry": "2028-11-30",
  "gtin_check_ok": true,
  "hri": "(01)09521234500018(17)281130(10)A2611QC07(21)SN0001",
  "ok": true,
  "production_date": null,
  "symbology": "]d2"
};

export const exValPackage: ValPackage = {
  "baseline_id": "vbl_00000000000000000000000000000002",
  "created_at": "2026-11-23T19:05:12.000000Z",
  "error": null,
  "id": "vpk_00000000000000000000000000000001",
  "kind": "oq",
  "manifest": {
    "files": [
      {
        "kind": "trace",
        "path": "trace/matrix.csv",
        "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
        "size": 18220
      }
    ],
    "kind": "oq",
    "package": "VP-000001"
  },
  "number": "VP-000001",
  "params": {
    "label": "OQ sample environment"
  },
  "prev_baseline_id": "vbl_00000000000000000000000000000001",
  "row_version": 3,
  "sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
  "signatures": [
    {
      "action": "approve",
      "auth_method": "password_totp",
      "comment": "Reviewed by exception",
      "content_matches_current": true,
      "id": "esg_00000000000000000000000000000001",
      "meaning": "approved",
      "meaning_label": "Approved",
      "record_version": 3,
      "signed_at": "2026-11-23T19:20:40.000000Z",
      "signed_at_local": "2026-11-23 14:20:40 EST (UTC-05:00)",
      "signer_legal_name": "Marie Tremblay",
      "signer_username": "mtremblay@example.com",
      "status": "valid",
      "step": 2
    }
  ],
  "size": 412008,
  "status": "approved",
  "updated_at": "2026-11-23T19:20:40.000000Z"
};

export const exVerifyResult: VerifyResult = {
  "job": {
    "created_at": "2026-11-23T19:05:12.000000Z",
    "data": {
      "lot.expiry": "2029-11-30",
      "lot.number": "A2611QC07",
      "udi.brand": "SampleCare",
      "udi.gtin": "09521234500018"
    },
    "data_sha256": "3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a3f1a",
    "element_string": "01095212345000181729113010A2611QC07",
    "events": [
      {
        "actor_id": "usr_00000000000000000000000000000005",
        "at": "2026-11-23T19:05:12.000000Z",
        "client_event_id": "tab-7-0001",
        "id": "lpe_00000000000000000000000000000001",
        "job_id": "lpj_00000000000000000000000000000015",
        "kind": "verify",
        "mismatch": null,
        "position": "first",
        "qty": 0,
        "reason": null,
        "result": "match",
        "scan": "]d201095212345000181728113010A2611QC07",
        "serials": null
      }
    ],
    "gtin": "09521234500018",
    "hri": "(01)09521234500018(17)291130(10)A2611QC07",
    "id": "lpj_00000000000000000000000000000015",
    "item_id": "itm_00000000000000000000000000000001",
    "item_part_number": "SYR-3ML-LL",
    "level": "each",
    "lot_code": "A2611QC07",
    "lot_id": "lot_00000000000000000000000000000007",
    "number": "LP-000021",
    "output": "zpl",
    "printer_id": "lpr_00000000000000000000000000000001",
    "qty": 24000,
    "recon_explanation": null,
    "reconciled_at": "2026-11-23T19:20:40.000000Z",
    "row_version": 6,
    "serials": null,
    "signatures": [],
    "status": "blocked",
    "target": "printer",
    "template_code": "SYR-EACH",
    "template_id": "lbt_00000000000000000000000000000002",
    "template_version": 2,
    "totals": {
      "destroyed": 100,
      "diff": 0,
      "issued": 24000,
      "printed": 24000,
      "reprinted": 0,
      "retained": 20,
      "used": 23880
    },
    "udi_id": "udi_00000000000000000000000000000001",
    "updated_at": "2026-11-23T19:20:40.000000Z",
    "verify": {
      "first": true,
      "last": true,
      "mismatches": 0
    },
    "wo_id": "wor_00000000000000000000000000000001"
  },
  "mismatch": {
    "lot": {
      "expected": "A2611QC07",
      "scanned": "A2611QC08"
    }
  },
  "parsed": {
    "ais": {
      "01": "09521234500018",
      "10": "A2611QC08",
      "17": "281130",
      "21": "SN0001"
    },
    "data": "01095212345000181728113010A2611QC07\u001d21SN0001",
    "errors": [],
    "expiry": "2028-11-30",
    "gtin_check_ok": true,
    "hri": "(01)09521234500018(17)281130(10)A2611QC07(21)SN0001",
    "ok": true,
    "production_date": null,
    "symbology": "]d2"
  },
  "result": "mismatch"
};

/**
 * M5 S0 contract examples (docs/M5-DESIGN.md 9): `backend/superplanner/integration/fixtures/example_m5.json` verbatim,
 * typed against `typesM5.ts` so the compiler flags drift. Regenerate when the fixture changes (15.WP-U).
 */
import type {
  AuditEvent,
  AuthConfig,
  BatchDetail,
  ChangeRequest,
  Delivery,
  EcoImpact,
  Endpoint,
  EventPage,
  IntegrationSettings,
  Org,
  OrgOverview,
  OrgPlant,
  Recall,
  Reconciliation,
  TokenCreated,
  TotpSetup,
  TraceResponse,
  TransferInput,
  TransferOrder,
  WhereUsedResponse,
} from "./typesM5";

export const exampleAuthConfig: AuthConfig = {
 "mode": "accounts",
 "sso_enabled": true,
 "sso_label": "HBL sign-in",
 "sso_required_domains": [
  "hbl.example"
 ],
 "password_login": true
};

export const exampleTotpSetup: TotpSetup = {
 "secret": "JBSWY3DPEHPK3PXP",
 "otpauth_uri": "otpauth://totp/SuperPlanner:ana%40hbl.example?secret=JBSWY3DPEHPK3PXP"
};

export const example2faRequired: { error: { code: string; message: string; details: { pending_token: string; setup_required: boolean } } } = {
 "error": {
  "code": "AUTH_2FA_REQUIRED",
  "message": "Enter the code from your authenticator app.",
  "details": {
   "pending_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
   "setup_required": false
  }
 }
};

export const exampleTokenCreated: TokenCreated = {
 "id": "tok_00000000000000000000000000000001",
 "kind": "personal",
 "name": "ERP middleware",
 "prefix": "spt_Ab12Cd34",
 "scopes": [
  "integration.read",
  "integration.write"
 ],
 "workspace_owner_id": "usr_00000000000000000000000000000000",
 "expires_at": "2027-02-03T03:30:00Z",
 "last_used_at": null,
 "last_used_ip": null,
 "created_at": "2026-11-05T03:30:00Z",
 "revoked_at": null,
 "token": "spt_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
};

export const exampleOrg: Org = {
 "id": "org_00000000000000000000000000000001",
 "name": "HBL",
 "slug": "hbl",
 "require_2fa": true,
 "my_role": "org_admin",
 "plants": 2,
 "members": 14,
 "row_version": 1,
 "created_at": "2026-11-05T03:30:00Z"
};

export const exampleOrgPlant: OrgPlant = {
 "id": "orp_00000000000000000000000000000001",
 "code": "HYD",
 "name": "Hyderabad",
 "plant_owner_id": "usr_11111111111111111111111111111111",
 "my_roles": [
  "plant_admin"
 ],
 "row_version": 1,
 "created_at": "2026-11-05T03:30:00Z"
};

export const exampleOrgOverview: OrgOverview = {
 "org": {
  "id": "org_00000000000000000000000000000001",
  "name": "HBL"
 },
 "plants": [
  {
   "plant": {
    "code": "HYD",
    "owner_id": "usr_11111111111111111111111111111111"
   },
   "visible": true,
   "kpis": {
    "otd": 0.92,
    "oee": 0.71
   },
   "late_demand": 2,
   "open_triggers": 3,
   "integration": {
    "enabled": true,
    "dead_deliveries": 0,
    "last_batch_at": "2026-11-05T03:30:00+00:00"
   }
  }
 ]
};

export const exampleIntegrationSettings: IntegrationSettings = {
 "enabled": true,
 "adapter": "generic_v1",
 "plant_code": "HYD",
 "sor": {
  "items": "erp",
  "boms": "erp",
  "routings": "erp",
  "suppliers": "erp",
  "item_suppliers": "erp",
  "purchase_orders": "erp",
  "po_receipts": "superplanner",
  "demand_orders": "erp",
  "purchase_requests": "superplanner",
  "work_orders": "superplanner",
  "floor": "superplanner",
  "transfers": "superplanner",
  "stock": "superplanner"
 },
 "goods_receipts_owner": "superplanner",
 "filedrop_enabled": true,
 "export_enabled": false,
 "export_interval_minutes": 15,
 "row_version": 3,
 "adapters": [
  "generic_v1"
 ]
};

export const exampleBatchResult: BatchDetail = {
 "id": "inb_00000000000000000000000000000001",
 "entity": "item",
 "mode": "upsert",
 "status": "completed",
 "counts": {
  "created": 1,
  "rejected": 1
 },
 "results": [
  {
   "ref": "MAT-100045",
   "status": "created",
   "id": "itm_00000000000000000000000000000009",
   "errors": []
  },
  {
   "ref": "MAT-100046",
   "status": "rejected",
   "id": null,
   "errors": [
    {
     "code": "INT_UNMAPPED_VALUE",
     "message": "Unit 'BOX' has no value map."
    }
   ]
  }
 ],
 "received_at": "2026-11-05T03:30:00Z",
 "finished_at": null
};

export const exampleEventsPage: EventPage = {
 "items": [],
 "next_after": 1042
};

export const exampleEndpoint: Endpoint = {
 "id": "iep_00000000000000000000000000000001",
 "name": "ERP middleware",
 "url": "https://erp-mw.hbl.example/sp",
 "event_types": [],
 "active": true,
 "cursor": 1041,
 "secret_set": true,
 "pending": 1,
 "dead": 0,
 "row_version": 1,
 "created_at": "2026-11-05T03:30:00Z"
};

export const exampleDelivery: Delivery = {
 "id": "dlv_00000000000000000000000000000001",
 "endpoint_id": "iep_00000000000000000000000000000001",
 "event_seq": 1042,
 "event_type": "work_order.released",
 "status": "pending",
 "attempts": 2,
 "next_attempt_at": "2026-11-05T03:31:00Z",
 "last_error": "HTTP 503",
 "last_status_code": 503,
 "delivered_at": null,
 "created_at": "2026-11-05T03:30:00Z"
};

export const exampleReconciliation: Reconciliation = {
 "id": "irc_00000000000000000000000000000001",
 "entities": [
  "stock"
 ],
 "status": "completed",
 "summary": {
  "stock": {
   "different": 1,
   "missing_in_sp": 0,
   "missing_in_erp": 0,
   "sor_conflicts": 0
  }
 },
 "results": {
  "stock": {
   "different": [
    {
     "item": "KV-CAP-100N",
     "location": "STORES",
     "lot": "",
     "sp_qty": 98,
     "erp_qty": 100,
     "delta": 2
    }
   ]
  }
 },
 "created_at": "2026-11-05T03:30:00Z",
 "finished_at": "2026-11-05T03:30:00Z"
};

export const exampleTrace: TraceResponse = {
 "root": {
  "kind": "serial",
  "id": "ser_00000000000000000000000000000001",
  "item": {
   "id": "itm_00000000000000000000000000000001",
   "part_number": "KV-TPU-1000",
   "revision": "A",
   "description": "TPU",
   "uom": "EA",
   "make_buy": "make",
   "active": true
  },
  "label": "TPU-26-0001",
  "qty": 1.0,
  "precision": "exact",
  "at": "2026-11-05T03:30:00Z",
  "status": "shipped",
  "plant": null,
  "link": "/mfg/serials/ser_00000000000000000000000000000001",
  "depth": 0,
  "children": [
   {
    "kind": "wo",
    "id": "wko_00000000000000000000000000000001",
    "item": null,
    "label": "WO-000150",
    "qty": 3.0,
    "precision": "exact",
    "at": null,
    "status": null,
    "plant": null,
    "link": "/mfg/work-orders/wko_00000000000000000000000000000001",
    "depth": 1,
    "children": [
     {
      "kind": "lot",
      "id": "lot_00000000000000000000000000000001",
      "item": null,
      "label": "KV-CAP-100N lot SUPP-2611",
      "qty": 120.0,
      "precision": "possible",
      "at": null,
      "status": null,
      "plant": null,
      "link": "",
      "depth": 2,
      "children": []
     },
     {
      "kind": "serial",
      "id": "ser_00000000000000000000000000000002",
      "item": null,
      "label": "PCB-26-0417",
      "qty": 1.0,
      "precision": "exact",
      "at": null,
      "status": null,
      "plant": null,
      "link": "",
      "depth": 2,
      "children": []
     }
    ]
   }
  ]
 },
 "direction": "backward",
 "depth": 30,
 "nodes": 4,
 "truncated": false
};

export const exampleWhereUsed: WhereUsedResponse = {
 "items": [
  {
   "kind": "wo",
   "id": "wko_00000000000000000000000000000001",
   "label": "WO-000150",
   "precision": "exact"
  }
 ],
 "truncated": false
};

export const exampleRecall: Recall = {
 "id": "rcl_00000000000000000000000000000001",
 "number": "RCL-000001",
 "name": "Capacitor lot SUPP-2611",
 "sources": [
  {
   "item_id": "itm_00000000000000000000000000000005",
   "supplier_lot": "SUPP-2611"
  }
 ],
 "include_possible": true,
 "report": {
  "units": [
   {
    "serial": "TPU-26-0001",
    "item": "KV-TPU-1000",
    "status": "shipped",
    "precision": "possible",
    "customer": "Railway zone A",
    "demand_order": "DO-KV-003",
    "shipped_on": "2026-11-03",
    "path": [
     "SUPP-2611",
     "WO-000150",
     "TPU-26-0001"
    ]
   }
  ],
  "lots": [
   {
    "lot_code": "SUPP-2611",
    "item": "KV-CAP-100N",
    "on_hand": 380,
    "location": "STORES"
   }
  ],
  "wos": [
   {
    "number": "WO-000150",
    "status": "completed"
   }
  ],
  "by_customer": [
   {
    "customer": "Railway zone A",
    "units": 1
   }
  ],
  "by_program": [],
  "open_pos": []
 },
 "quarantined_at": null,
 "row_version": 1,
 "created_at": "2026-11-05T03:30:00Z",
 "updated_at": "2026-11-05T03:30:00Z"
};

export const exampleEco: ChangeRequest = {
 "id": "ecr_00000000000000000000000000000001",
 "number": "ECO-000001",
 "title": "Replace C14 capacitor",
 "reason": "Supplier EOL",
 "kind": "eco",
 "source": "manual",
 "status": "draft",
 "priority": 5,
 "effectivity": {
  "mode": "date",
  "date": "2027-01-01"
 },
 "note": "",
 "requested_by": null,
 "approved_by": null,
 "approved_at": null,
 "implemented_at": null,
 "items": [
  {
   "id": "eci_00000000000000000000000000000001",
   "doc_type": "bom",
   "doc_id": "bom_00000000000000000000000000000002",
   "supersedes_doc_id": "bom_00000000000000000000000000000001",
   "disposition": {
    "open_wos": "flag",
    "open_pos": "flag_cancel",
    "stock": "use_up"
   }
  }
 ],
 "row_version": 1,
 "created_at": "2026-11-05T03:30:00Z",
 "updated_at": "2026-11-05T03:30:00Z"
};

export const exampleEcoImpact: EcoImpact = {
 "cr_id": "ecr_00000000000000000000000000000001",
 "effectivity": {
  "mode": "date",
  "date": "2027-01-01"
 },
 "explosion_delta": [
  {
   "parent": "KV-PCB-CPU",
   "removed": [
    "KV-CAP-100N"
   ],
   "added": [
    "KV-CAP-100N-B"
   ],
   "changed": []
  }
 ],
 "open_wos": [
  {
   "number": "WO-000150",
   "component": "KV-CAP-100N",
   "qty": 30
  }
 ],
 "planned_orders": [],
 "open_purchases": [],
 "phase_out_stock": [
  {
   "item": "KV-CAP-100N",
   "on_hand": 380,
   "on_order": 1000,
   "value": 1140.0
  }
 ],
 "mrp_delta": [],
 "use_up_date": "2027-02-14",
 "computed_ms": 2100
};

export const exampleTransferBody: TransferInput = {
 "dest_plant_owner_id": "usr_33333333333333333333333333333333",
 "lines": [
  {
   "item_id": "itm_00000000000000000000000000000005",
   "qty": 100,
   "ship_date": "2026-11-10",
   "receive_date": "2026-11-12"
  }
 ]
};

export const exampleTransfer: TransferOrder = {
 "id": "tro_00000000000000000000000000000001",
 "number": "TO-000001",
 "direction": "out",
 "status": "open",
 "source_plant": {
  "owner_id": "usr_11111111111111111111111111111111",
  "code": "HYD"
 },
 "dest_plant": {
  "owner_id": "usr_33333333333333333333333333333333",
  "code": "BLR"
 },
 "mirror_of": null,
 "from_location_id": null,
 "to_location_id": null,
 "note": "",
 "lines": [
  {
   "id": "trl_00000000000000000000000000000001",
   "line_no": 1,
   "item_id": "itm_00000000000000000000000000000005",
   "qty": 100,
   "shipped_qty": 0,
   "received_qty": 0,
   "ship_date": "2026-11-10",
   "receive_date": "2026-11-12"
  }
 ],
 "row_version": 1,
 "created_at": "2026-11-05T03:30:00Z",
 "updated_at": "2026-11-05T03:30:00Z"
};

export const exampleAuditEvent: AuditEvent = {
 "id": 1,
 "entity_type": "mfg_item",
 "entity_id": "itm_00000000000000000000000000000001",
 "action": "create",
 "details": {},
 "actor_id": "usr_local",
 "owner_id": "usr_local",
 "created_at": "2026-11-05T03:30:00Z",
 "chain_hash": "0000000000000000000000000000000000000000000000000000000000000000"
};

/**
 * M6 S0 contract examples (docs/M6-DESIGN.md 8): `backend/superplanner/assistant/fixtures/example_m6.json` verbatim,
 * typed against `typesM6.ts` so the compiler flags drift. Regenerate when the fixture changes (11.WP-U).
 */
import type {
  ApprovalsResponse,
  AssistantPlantSettings,
  AssistantStatus,
  AssistantTurn,
  Conversation,
  ConversationDetail,
  ConversationInput,
  DashboardResponse,
  DigestInput,
  DigestSubscription,
  DowntimeM6,
  DraftApplied,
  OrgDashboardResponse,
  PushPayload,
  PushSubscriptionInput,
  PushSubscriptionRecord,
  QuickExplanation,
  ThresholdsInput,
  TurnAccepted,
  TurnInput,
  VapidPublicKey,
} from "./typesM6";

export const exampleAssistantStatus: AssistantStatus = {
 "available": true,
 "code": null,
 "message": "",
 "privacy_notice": "The assistant sends your question and the planning records it looks up (part numbers, quantities, dates, order numbers - no prices unless you ask about cost, no personal data) to Anthropic, an AI provider, to answer. Answers may be wrong; check the linked records. Nothing is sent when you use the built-in explanations.",
 "budget_left": {
  "user": 381600,
  "plant": 1963000
 },
 "plant": {
  "assistant_enabled": true,
  "assistant_allow_whatif": true
 },
 "model": "claude-opus-5-5",
 "max_text_chars": 4000,
 "max_tool_rounds": 8,
 "quick_kinds": [
  "why_late",
  "limits",
  "changes"
 ]
};

export const exampleAssistantUnavailable: AssistantStatus = {
 "available": false,
 "code": "AI_DISABLED",
 "message": "The assistant is switched off on this server.",
 "privacy_notice": "The assistant sends your question and the planning records it looks up (part numbers, quantities, dates, order numbers - no prices unless you ask about cost, no personal data) to Anthropic, an AI provider, to answer. Answers may be wrong; check the linked records. Nothing is sent when you use the built-in explanations.",
 "budget_left": {
  "user": 381600,
  "plant": 1963000
 },
 "plant": {
  "assistant_enabled": true,
  "assistant_allow_whatif": true
 },
 "model": "claude-opus-5-5",
 "max_text_chars": 4000,
 "max_tool_rounds": 8,
 "quick_kinds": [
  "why_late",
  "limits",
  "changes"
 ]
};

export const exampleAssistantSettings: AssistantPlantSettings = {
 "assistant_enabled": true,
 "assistant_allow_whatif": false
};

export const exampleConversationInput: ConversationInput = {
 "title": "",
 "allow_whatif": false
};

export const exampleConversation: Conversation = {
 "id": "asc_00000000000000000000000000000001",
 "title": "Why is DO-KV-003/10 late",
 "allow_whatif": false,
 "created_at": "2026-11-06T04:30:00Z",
 "updated_at": "2026-11-06T04:30:21Z",
 "turns": 1
};

export const exampleConversationDetail: ConversationDetail = {
 "id": "asc_00000000000000000000000000000001",
 "title": "Why is DO-KV-003/10 late",
 "allow_whatif": false,
 "created_at": "2026-11-06T04:30:00Z",
 "updated_at": "2026-11-06T04:30:21Z",
 "turns": 1,
 "history": [
  {
   "id": "ast_00000000000000000000000000000001",
   "conversation_id": "asc_00000000000000000000000000000001",
   "status": "completed",
   "user_text": "Why is DO-KV-003/10 late and what can I do?",
   "context": {
    "type": "demand_line",
    "id": "dln_0000000000000000000000000000000a"
   },
   "allow_whatif": false,
   "steps": [
    {
     "at": "2026-11-06T04:30:00Z",
     "kind": "thinking",
     "name": null,
     "summary": "thinking",
     "ok": true
    },
    {
     "at": "2026-11-06T04:30:04Z",
     "kind": "tool",
     "name": "demand_status",
     "summary": "tool: demand_status (DO-KV-003/10)",
     "ok": true
    },
    {
     "at": "2026-11-06T04:30:09Z",
     "kind": "tool",
     "name": "mrp_pegging",
     "summary": "tool: mrp_pegging (KV-FPGA-7A)",
     "ok": true
    },
    {
     "at": "2026-11-06T04:30:13Z",
     "kind": "tool",
     "name": "overtime_options",
     "summary": "tool: overtime_options",
     "ok": true
    },
    {
     "at": "2026-11-06T04:30:14Z",
     "kind": "tool",
     "name": "draft_action",
     "summary": "tool: draft_action (open_overtime)",
     "ok": true
    },
    {
     "at": "2026-11-06T04:30:15Z",
     "kind": "tool",
     "name": "draft_action",
     "summary": "tool: draft_action (expedite_po_schedule)",
     "ok": true
    },
    {
     "at": "2026-11-06T04:30:21Z",
     "kind": "answer",
     "name": null,
     "summary": "answer",
     "ok": true
    }
   ],
   "answer": "**DO-KV-003/10 is projected 6 days late** [R1]. Two causes:\n\n1. **Material**: KV-FPGA-7A is short 120 on 2026-11-12 [R2]; the covering PO-000231 docks on 2026-11-18 [R3].\n2. **Capacity**: SMT-1 is loaded 112% in week 47 [R4].\n\nOptions (drafts below, nothing has been changed):\n\n- open the suggested Saturday shift on SMT-1 (saves 2.5 days);\n- ask the supplier to expedite PO-000231 to 2026-11-11.",
   "citations": [
    {
     "ref": "R1",
     "type": "demand_line",
     "id": "dln_0000000000000000000000000000000a",
     "label": "DO-KV-003/10 (KV-TPU-1000 x 40, due 2026-11-20)",
     "link": "/mfg/demand/dor_00000000000000000000000000000003?line=dln_0000000000000000000000000000000a"
    },
    {
     "ref": "R2",
     "type": "mrp_exception",
     "id": "mrx_42",
     "label": "KV-FPGA-7A short 120 on 2026-11-12",
     "link": "/mfg/mrp/runs/mrr_00000000000000000000000000000005/exceptions?item=itm_00000000000000000000000000000016"
    },
    {
     "ref": "R3",
     "type": "purchase_order",
     "id": "pdc_00000000000000000000000000000007",
     "label": "PO-000231 line 1 (KV-FPGA-7A, dock 2026-11-18)",
     "link": "/mfg/purchasing/orders/pdc_00000000000000000000000000000007"
    },
    {
     "ref": "R4",
     "type": "aps_bottleneck",
     "id": "lin_00000000000000000000000000000003",
     "label": "SMT-1 load 112% week 47",
     "link": "/mfg/schedule/runs/apr_0000000000000000000000000000000c?view=load&line=lin_00000000000000000000000000000003"
    }
   ],
   "drafts": [
    {
     "draft_id": "drf_00000000000000000000000000000001",
     "kind": "open_overtime",
     "summary": "Re-run schedule 12 with the suggested Saturday shift on SMT-1 (2026-11-14 06:00-14:00) opened: saves 2.5 days of tardiness on DO-KV-003/10 [R4].",
     "method": "POST",
     "path": "/api/v1/mfg/aps/runs",
     "body": {
      "copy_of": "apr_0000000000000000000000000000000c",
      "open_shifts": [
       {
        "line_id": "lin_00000000000000000000000000000003",
        "start": "2026-11-14T06:00:00+05:30",
        "end": "2026-11-14T14:00:00+05:30"
       }
      ]
     },
     "if_match_of": null,
     "required_permission": "schedule_run",
     "allowed": true,
     "applied_at": null,
     "applied_status": null,
     "response_ref": null
    },
    {
     "draft_id": "drf_00000000000000000000000000000002",
     "kind": "expedite_po_schedule",
     "summary": "Ask the supplier to pull PO-000231 line 1 forward from 2026-11-18 to 2026-11-11 (needed date) [R3].",
     "method": "PUT",
     "path": "/api/v1/mfg/purchase-orders/pdc_00000000000000000000000000000007",
     "body": {
      "supplier_id": "sup_00000000000000000000000000000002",
      "currency": "INR",
      "order_date": "2026-10-20",
      "note": "Assistant draft: expedite schedule 1 of line 1 to 2026-11-11 for DO-KV-003/10 - agree with the supplier before saving.",
      "lines": [
       {
        "id": "pln_00000000000000000000000000000001",
        "line_no": 1,
        "item_id": "itm_00000000000000000000000000000016",
        "unit_price": 5400.0,
        "note": "",
        "schedules": [
         {
          "id": "psc_00000000000000000000000000000001",
          "seq": 1,
          "requested_date": "2026-11-11",
          "confirmed_date": null,
          "qty": 120
         }
        ]
       }
      ]
     },
     "if_match_of": {
      "type": "purchase_order",
      "id": "pdc_00000000000000000000000000000007",
      "row_version": 4
     },
     "required_permission": "po_edit",
     "allowed": false,
     "applied_at": null,
     "applied_status": null,
     "response_ref": null
    }
   ],
   "error": null,
   "model": "claude-opus-5-5",
   "fallback_code": null,
   "tokens": {
    "input": 18400,
    "output": 910,
    "cache_read": 12000
   },
   "rounds": 3,
   "created_at": "2026-11-06T04:30:00Z",
   "started_at": "2026-11-06T04:30:00Z",
   "finished_at": "2026-11-06T04:30:21Z"
  }
 ]
};

export const exampleTurnInput: TurnInput = {
 "text": "Why is DO-KV-003/10 late and what can I do?",
 "context": {
  "type": "demand_line",
  "id": "dln_0000000000000000000000000000000a"
 },
 "allow_whatif": false
};

export const exampleTurnAccepted: TurnAccepted = {
 "turn_id": "ast_00000000000000000000000000000001",
 "conversation_id": "asc_00000000000000000000000000000001",
 "status": "queued"
};

export const exampleTurnRunning: AssistantTurn = {
 "id": "ast_00000000000000000000000000000002",
 "conversation_id": "asc_00000000000000000000000000000001",
 "status": "running",
 "user_text": "Why is DO-KV-003/10 late and what can I do?",
 "context": {
  "type": "demand_line",
  "id": "dln_0000000000000000000000000000000a"
 },
 "allow_whatif": false,
 "steps": [
  {
   "at": "2026-11-06T04:30:00Z",
   "kind": "thinking",
   "name": null,
   "summary": "thinking",
   "ok": true
  },
  {
   "at": "2026-11-06T04:30:04Z",
   "kind": "tool",
   "name": "demand_status",
   "summary": "tool: demand_status (DO-KV-003/10)",
   "ok": true
  },
  {
   "at": "2026-11-06T04:30:09Z",
   "kind": "tool",
   "name": "mrp_pegging",
   "summary": "tool: mrp_pegging (KV-FPGA-7A)",
   "ok": true
  }
 ],
 "answer": null,
 "citations": [],
 "drafts": [],
 "error": null,
 "model": "claude-opus-5-5",
 "fallback_code": null,
 "tokens": {
  "input": 9100,
  "output": 240,
  "cache_read": 6000
 },
 "rounds": 2,
 "created_at": "2026-11-06T04:30:00Z",
 "started_at": "2026-11-06T04:30:00Z",
 "finished_at": null
};

export const exampleTurnCompleted: AssistantTurn = {
 "id": "ast_00000000000000000000000000000001",
 "conversation_id": "asc_00000000000000000000000000000001",
 "status": "completed",
 "user_text": "Why is DO-KV-003/10 late and what can I do?",
 "context": {
  "type": "demand_line",
  "id": "dln_0000000000000000000000000000000a"
 },
 "allow_whatif": false,
 "steps": [
  {
   "at": "2026-11-06T04:30:00Z",
   "kind": "thinking",
   "name": null,
   "summary": "thinking",
   "ok": true
  },
  {
   "at": "2026-11-06T04:30:04Z",
   "kind": "tool",
   "name": "demand_status",
   "summary": "tool: demand_status (DO-KV-003/10)",
   "ok": true
  },
  {
   "at": "2026-11-06T04:30:09Z",
   "kind": "tool",
   "name": "mrp_pegging",
   "summary": "tool: mrp_pegging (KV-FPGA-7A)",
   "ok": true
  },
  {
   "at": "2026-11-06T04:30:13Z",
   "kind": "tool",
   "name": "overtime_options",
   "summary": "tool: overtime_options",
   "ok": true
  },
  {
   "at": "2026-11-06T04:30:14Z",
   "kind": "tool",
   "name": "draft_action",
   "summary": "tool: draft_action (open_overtime)",
   "ok": true
  },
  {
   "at": "2026-11-06T04:30:15Z",
   "kind": "tool",
   "name": "draft_action",
   "summary": "tool: draft_action (expedite_po_schedule)",
   "ok": true
  },
  {
   "at": "2026-11-06T04:30:21Z",
   "kind": "answer",
   "name": null,
   "summary": "answer",
   "ok": true
  }
 ],
 "answer": "**DO-KV-003/10 is projected 6 days late** [R1]. Two causes:\n\n1. **Material**: KV-FPGA-7A is short 120 on 2026-11-12 [R2]; the covering PO-000231 docks on 2026-11-18 [R3].\n2. **Capacity**: SMT-1 is loaded 112% in week 47 [R4].\n\nOptions (drafts below, nothing has been changed):\n\n- open the suggested Saturday shift on SMT-1 (saves 2.5 days);\n- ask the supplier to expedite PO-000231 to 2026-11-11.",
 "citations": [
  {
   "ref": "R1",
   "type": "demand_line",
   "id": "dln_0000000000000000000000000000000a",
   "label": "DO-KV-003/10 (KV-TPU-1000 x 40, due 2026-11-20)",
   "link": "/mfg/demand/dor_00000000000000000000000000000003?line=dln_0000000000000000000000000000000a"
  },
  {
   "ref": "R2",
   "type": "mrp_exception",
   "id": "mrx_42",
   "label": "KV-FPGA-7A short 120 on 2026-11-12",
   "link": "/mfg/mrp/runs/mrr_00000000000000000000000000000005/exceptions?item=itm_00000000000000000000000000000016"
  },
  {
   "ref": "R3",
   "type": "purchase_order",
   "id": "pdc_00000000000000000000000000000007",
   "label": "PO-000231 line 1 (KV-FPGA-7A, dock 2026-11-18)",
   "link": "/mfg/purchasing/orders/pdc_00000000000000000000000000000007"
  },
  {
   "ref": "R4",
   "type": "aps_bottleneck",
   "id": "lin_00000000000000000000000000000003",
   "label": "SMT-1 load 112% week 47",
   "link": "/mfg/schedule/runs/apr_0000000000000000000000000000000c?view=load&line=lin_00000000000000000000000000000003"
  }
 ],
 "drafts": [
  {
   "draft_id": "drf_00000000000000000000000000000001",
   "kind": "open_overtime",
   "summary": "Re-run schedule 12 with the suggested Saturday shift on SMT-1 (2026-11-14 06:00-14:00) opened: saves 2.5 days of tardiness on DO-KV-003/10 [R4].",
   "method": "POST",
   "path": "/api/v1/mfg/aps/runs",
   "body": {
    "copy_of": "apr_0000000000000000000000000000000c",
    "open_shifts": [
     {
      "line_id": "lin_00000000000000000000000000000003",
      "start": "2026-11-14T06:00:00+05:30",
      "end": "2026-11-14T14:00:00+05:30"
     }
    ]
   },
   "if_match_of": null,
   "required_permission": "schedule_run",
   "allowed": true,
   "applied_at": null,
   "applied_status": null,
   "response_ref": null
  },
  {
   "draft_id": "drf_00000000000000000000000000000002",
   "kind": "expedite_po_schedule",
   "summary": "Ask the supplier to pull PO-000231 line 1 forward from 2026-11-18 to 2026-11-11 (needed date) [R3].",
   "method": "PUT",
   "path": "/api/v1/mfg/purchase-orders/pdc_00000000000000000000000000000007",
   "body": {
    "supplier_id": "sup_00000000000000000000000000000002",
    "currency": "INR",
    "order_date": "2026-10-20",
    "note": "Assistant draft: expedite schedule 1 of line 1 to 2026-11-11 for DO-KV-003/10 - agree with the supplier before saving.",
    "lines": [
     {
      "id": "pln_00000000000000000000000000000001",
      "line_no": 1,
      "item_id": "itm_00000000000000000000000000000016",
      "unit_price": 5400.0,
      "note": "",
      "schedules": [
       {
        "id": "psc_00000000000000000000000000000001",
        "seq": 1,
        "requested_date": "2026-11-11",
        "confirmed_date": null,
        "qty": 120
       }
      ]
     }
    ]
   },
   "if_match_of": {
    "type": "purchase_order",
    "id": "pdc_00000000000000000000000000000007",
    "row_version": 4
   },
   "required_permission": "po_edit",
   "allowed": false,
   "applied_at": null,
   "applied_status": null,
   "response_ref": null
  }
 ],
 "error": null,
 "model": "claude-opus-5-5",
 "fallback_code": null,
 "tokens": {
  "input": 18400,
  "output": 910,
  "cache_read": 12000
 },
 "rounds": 3,
 "created_at": "2026-11-06T04:30:00Z",
 "started_at": "2026-11-06T04:30:00Z",
 "finished_at": "2026-11-06T04:30:21Z"
};

export const exampleTurnFailed: AssistantTurn = {
 "id": "ast_00000000000000000000000000000003",
 "conversation_id": "asc_00000000000000000000000000000001",
 "status": "failed",
 "user_text": "Why is DO-KV-003/10 late and what can I do?",
 "context": {
  "type": "demand_line",
  "id": "dln_0000000000000000000000000000000a"
 },
 "allow_whatif": false,
 "steps": [
  {
   "at": "2026-11-06T04:30:00Z",
   "kind": "thinking",
   "name": null,
   "summary": "thinking",
   "ok": true
  }
 ],
 "answer": null,
 "citations": [],
 "drafts": [],
 "error": {
  "code": "AI_CONNECTION_ERROR",
  "message": "The AI service could not be reached. Use the quick explanations, or try again later."
 },
 "model": "claude-opus-5-5",
 "fallback_code": null,
 "tokens": {
  "input": 0,
  "output": 0,
  "cache_read": 0
 },
 "rounds": 0,
 "created_at": "2026-11-06T04:30:00Z",
 "started_at": "2026-11-06T04:30:00Z",
 "finished_at": "2026-11-06T04:30:21Z"
};

export const exampleDraftApplied: DraftApplied = {
 "status": "succeeded",
 "response_ref": "apr_0000000000000000000000000000000d"
};

export const exampleQuickWhyLate: QuickExplanation = {
 "kind": "why_late",
 "title": "Why is DO-KV-003/10 late?",
 "subject": {
  "type": "demand_line",
  "id": "dln_0000000000000000000000000000000a",
  "label": "DO-KV-003/10"
 },
 "sections": [
  {
   "title": "Material (latest MRP run 5)",
   "items": [
    {
     "text": "Projected 2026-11-26, 6 days after the due date 2026-11-20.",
     "refs": [
      "Q1"
     ]
    },
    {
     "text": "Limiting path: KV-FPGA-7A short 120, covered by PO-000231 docking 2026-11-18.",
     "refs": [
      "Q2",
      "Q3"
     ]
    }
   ]
  },
  {
   "title": "Schedule (published run 12)",
   "items": [
    {
     "text": "Late chain: SMT-1 op 20 waits for capacity (load 112% week 47).",
     "refs": [
      "Q4"
     ]
    }
   ]
  }
 ],
 "citations": [
  {
   "ref": "Q1",
   "type": "demand_line",
   "id": "dln_0000000000000000000000000000000a",
   "label": "DO-KV-003/10 (KV-TPU-1000 x 40, due 2026-11-20)",
   "link": "/mfg/demand/dor_00000000000000000000000000000003?line=dln_0000000000000000000000000000000a"
  },
  {
   "ref": "Q2",
   "type": "mrp_exception",
   "id": "mrx_42",
   "label": "KV-FPGA-7A short 120 on 2026-11-12",
   "link": "/mfg/mrp/runs/mrr_00000000000000000000000000000005/exceptions?item=itm_00000000000000000000000000000016"
  },
  {
   "ref": "Q3",
   "type": "purchase_order",
   "id": "pdc_00000000000000000000000000000007",
   "label": "PO-000231 line 1 (KV-FPGA-7A, dock 2026-11-18)",
   "link": "/mfg/purchasing/orders/pdc_00000000000000000000000000000007"
  },
  {
   "ref": "Q4",
   "type": "aps_bottleneck",
   "id": "lin_00000000000000000000000000000003",
   "label": "SMT-1 load 112% week 47",
   "link": "/mfg/schedule/runs/apr_0000000000000000000000000000000c?view=load&line=lin_00000000000000000000000000000003"
  }
 ],
 "sources": [
  "GET /mfg/mrp/runs/{id}/demand",
  "GET /mfg/aps/runs/{id}/demand"
 ],
 "empty_message": ""
};

export const exampleErrors: Record<string, { error: { code: string; message: string; details: Record<string, unknown> } }> = {
 "turn_running_409": {
  "error": {
   "code": "AI_TURN_RUNNING",
   "message": "Your previous question is still being answered.",
   "details": {
    "turn_id": "ast_00000000000000000000000000000002"
   }
  }
 },
 "plant_opted_out_422": {
  "error": {
   "code": "AI_PLANT_OPTED_OUT",
   "message": "The assistant is switched off for this plant.",
   "details": {
    "code": "AI_PLANT_OPTED_OUT"
   }
  }
 },
 "budget_422": {
  "error": {
   "code": "AI_BUDGET_EXCEEDED",
   "message": "The daily assistant budget is used up.",
   "details": {
    "code": "AI_BUDGET_EXCEEDED",
    "budget_left": {
     "user": 1000,
     "plant": 900000
    }
   }
  }
 },
 "whatif_422": {
  "error": {
   "code": "AI_WHATIF_NOT_ALLOWED",
   "message": "What-if runs by the assistant are not allowed in this plant.",
   "details": {
    "code": "AI_WHATIF_NOT_ALLOWED"
   }
  }
 },
 "digest_no_smtp_422": {
  "error": {
   "code": "DIGEST_NO_SMTP",
   "message": "E-mail digests need an SMTP server; ask your administrator.",
   "details": {}
  }
 },
 "push_disabled_422": {
  "error": {
   "code": "PUSH_DISABLED",
   "message": "Push notifications are not set up on this server.",
   "details": {}
  }
 },
 "db_unavailable_503": {
  "error": {
   "code": "DB_UNAVAILABLE",
   "message": "The database is switching over; try again in a few seconds.",
   "details": {
    "retry_after": 5
   }
  }
 }
};

export const exampleVapidPublicKey: VapidPublicKey = {
 "enabled": true,
 "public_key": "BAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
 "topics": [
  "critical_alerts",
  "approvals",
  "digest_ready"
 ]
};

export const examplePushSubscriptionInput: PushSubscriptionInput = {
 "endpoint": "https://fcm.googleapis.com/fcm/send/dXq3...",
 "keys": {
  "p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
  "auth": "BTBZMqHH6r4Tts7J_aSIgg"
 },
 "topics": [
  "critical_alerts",
  "approvals"
 ]
};

export const examplePushSubscription: PushSubscriptionRecord = {
 "id": "psb_00000000000000000000000000000001",
 "endpoint_host": "fcm.googleapis.com",
 "topics": [
  "critical_alerts",
  "approvals"
 ],
 "user_agent": "Chrome/131 Android",
 "created_at": "2026-11-06T04:30:00Z",
 "active": true
};

export const examplePushPayload: PushPayload = {
 "title": "SMT-1 is down",
 "body": "Downtime reported 10:12 (feeder jam).",
 "link": "/m/lines/lin_00000000000000000000000000000003",
 "topic": "critical_alerts",
 "tag": null
};

export const exampleDashboard: DashboardResponse = {
 "as_of": "2026-11-06T04:30:00Z",
 "period": "13w",
 "plant": {
  "owner_id": "usr_11111111111111111111111111111111",
  "name": "Kavach Hyderabad",
  "currency": "INR",
  "time_zone": "Asia/Kolkata"
 },
 "tiles": {
  "otd": {
   "value": 0.91,
   "unit": "%",
   "trend": [
    {
     "period": "2026-W42",
     "value": 0.88
    },
    {
     "period": "2026-W43",
     "value": 0.93
    },
    {
     "period": "2026-W44",
     "value": 0.9
    },
    {
     "period": "2026-W45",
     "value": 0.91
    }
   ],
   "status": "watch",
   "thresholds": {
    "alert_below": 0.85,
    "watch_below": 0.95
   },
   "drill": [
    {
     "label": "Demand lines of the week",
     "path": "/mfg/demand?due_week=2026-W45"
    }
   ],
   "details": {
    "wo_on_time": 0.87
   },
   "note": ""
  },
  "backlog": {
   "value": 1.04,
   "unit": "%",
   "trend": [],
   "status": "watch",
   "thresholds": {},
   "drill": [
    {
     "label": "Load view",
     "path": "/mfg/schedule/runs/apr_0000000000000000000000000000000c?view=load"
    }
   ],
   "details": {
    "weeks_4": {
     "required_h": 1460.0,
     "capacity_h": 1400.0,
     "load": 1.04
    },
    "weeks_8": {
     "required_h": 2310.0,
     "capacity_h": 2800.0,
     "load": 0.83
    },
    "by_stage": [
     {
      "stage": "SMT",
      "load_4w": 1.12,
      "load_8w": 0.9
     }
    ],
    "beyond_horizon_h": 120.0
   },
   "note": ""
  },
  "material_risk": {
   "value": 7,
   "unit": "count",
   "trend": [],
   "status": "watch",
   "thresholds": {},
   "drill": [
    {
     "label": "Short items",
     "path": "/mfg/mrp?short_only=1"
    }
   ],
   "details": {
    "items_short_4w": 7,
    "value_short_4w": 182400.0,
    "currency": "INR",
    "late_lines_material": 3,
    "risk_lines_below_80": 2
   },
   "note": ""
  },
  "execution": {
   "value": 0.82,
   "unit": "%",
   "trend": [],
   "status": "ok",
   "thresholds": {},
   "drill": [
    {
     "label": "KPIs",
     "path": "/mfg/kpis"
    }
   ],
   "details": {
    "adherence": 0.82,
    "oee": 0.71,
    "fpy": 0.985,
    "scrap_rate": 0.006
   },
   "note": ""
  },
  "inventory": {
   "value": 12650000.0,
   "unit": "INR",
   "trend": [],
   "status": "ok",
   "thresholds": {},
   "drill": [
    {
     "label": "Stock by family",
     "path": "/mfg/inventory?by=family"
    }
   ],
   "details": {
    "turns": null,
    "turns_note": "n/a until 3 monthly snapshots exist",
    "by_family": [
     {
      "family": "FPGA",
      "value": 4200000.0
     }
    ]
   },
   "note": ""
  },
  "late_pos": {
   "value": 4,
   "unit": "count",
   "trend": [],
   "status": "watch",
   "thresholds": {},
   "drill": [
    {
     "label": "Delivery board",
     "path": "/mfg/purchasing/schedule?overdue=1"
    }
   ],
   "details": {
    "by_supplier": [
     {
      "supplier": {
       "id": "sup_00000000000000000000000000000002",
       "code": "AVN",
       "name": "Avnet"
      },
      "open_overdue": 2,
      "lateness_12m": 0.18
     }
    ]
   },
   "note": ""
  },
  "quality": {
   "value": 1,
   "unit": "count",
   "trend": [],
   "status": "alert",
   "thresholds": {},
   "drill": [
    {
     "label": "Recalls",
     "path": "/mfg/recalls"
    }
   ],
   "details": {
    "open_recalls": 1,
    "ecos_by_status": {
     "submitted": 2,
     "approved": 1
    },
    "top_scrap_reasons": [
     {
      "reason": "SOLDER_BRIDGE",
      "qty": 14
     }
    ]
   },
   "note": ""
  },
  "integration": {
   "value": 0,
   "unit": "count",
   "trend": [],
   "status": "ok",
   "thresholds": {},
   "drill": [
    {
     "label": "Integration console",
     "path": "/integration"
    }
   ],
   "details": {
    "dead_deliveries": 0,
    "failed_batches_7d": 0,
    "stale_reconciliation": false
   },
   "note": ""
  }
 },
 "source": "primary",
 "computed_ms": 412
};

export const exampleOrgDashboard: OrgDashboardResponse = {
 "as_of": "2026-11-06T04:30:00Z",
 "period": "13w",
 "org": {
  "id": "org_00000000000000000000000000000001",
  "name": "HBL"
 },
 "plants": [
  {
   "plant": {
    "owner_id": "usr_11111111111111111111111111111111",
    "code": "HYD",
    "name": "Kavach Hyderabad"
   },
   "tiles": {
    "otd": {
     "value": 0.91,
     "unit": "%",
     "trend": [
      {
       "period": "2026-W42",
       "value": 0.88
      },
      {
       "period": "2026-W43",
       "value": 0.93
      },
      {
       "period": "2026-W44",
       "value": 0.9
      },
      {
       "period": "2026-W45",
       "value": 0.91
      }
     ],
     "status": "watch",
     "thresholds": {
      "alert_below": 0.85,
      "watch_below": 0.95
     },
     "drill": [
      {
       "label": "Demand lines of the week",
       "path": "/mfg/demand?due_week=2026-W45"
      }
     ],
     "details": {
      "wo_on_time": 0.87
     },
     "note": ""
    },
    "backlog": {
     "value": 1.04,
     "unit": "%",
     "trend": [],
     "status": "watch",
     "thresholds": {},
     "drill": [
      {
       "label": "Load view",
       "path": "/mfg/schedule/runs/apr_0000000000000000000000000000000c?view=load"
      }
     ],
     "details": {
      "weeks_4": {
       "required_h": 1460.0,
       "capacity_h": 1400.0,
       "load": 1.04
      },
      "weeks_8": {
       "required_h": 2310.0,
       "capacity_h": 2800.0,
       "load": 0.83
      },
      "by_stage": [
       {
        "stage": "SMT",
        "load_4w": 1.12,
        "load_8w": 0.9
       }
      ],
      "beyond_horizon_h": 120.0
     },
     "note": ""
    },
    "material_risk": {
     "value": 7,
     "unit": "count",
     "trend": [],
     "status": "watch",
     "thresholds": {},
     "drill": [
      {
       "label": "Short items",
       "path": "/mfg/mrp?short_only=1"
      }
     ],
     "details": {
      "items_short_4w": 7,
      "value_short_4w": 182400.0,
      "currency": "INR",
      "late_lines_material": 3,
      "risk_lines_below_80": 2
     },
     "note": ""
    },
    "execution": {
     "value": 0.82,
     "unit": "%",
     "trend": [],
     "status": "ok",
     "thresholds": {},
     "drill": [
      {
       "label": "KPIs",
       "path": "/mfg/kpis"
      }
     ],
     "details": {
      "adherence": 0.82,
      "oee": 0.71,
      "fpy": 0.985,
      "scrap_rate": 0.006
     },
     "note": ""
    },
    "inventory": {
     "value": 12650000.0,
     "unit": "INR",
     "trend": [],
     "status": "ok",
     "thresholds": {},
     "drill": [
      {
       "label": "Stock by family",
       "path": "/mfg/inventory?by=family"
      }
     ],
     "details": {
      "turns": null,
      "turns_note": "n/a until 3 monthly snapshots exist",
      "by_family": [
       {
        "family": "FPGA",
        "value": 4200000.0
       }
      ]
     },
     "note": ""
    },
    "late_pos": {
     "value": 4,
     "unit": "count",
     "trend": [],
     "status": "watch",
     "thresholds": {},
     "drill": [
      {
       "label": "Delivery board",
       "path": "/mfg/purchasing/schedule?overdue=1"
      }
     ],
     "details": {
      "by_supplier": [
       {
        "supplier": {
         "id": "sup_00000000000000000000000000000002",
         "code": "AVN",
         "name": "Avnet"
        },
        "open_overdue": 2,
        "lateness_12m": 0.18
       }
      ]
     },
     "note": ""
    },
    "quality": {
     "value": 1,
     "unit": "count",
     "trend": [],
     "status": "alert",
     "thresholds": {},
     "drill": [
      {
       "label": "Recalls",
       "path": "/mfg/recalls"
      }
     ],
     "details": {
      "open_recalls": 1,
      "ecos_by_status": {
       "submitted": 2,
       "approved": 1
      },
      "top_scrap_reasons": [
       {
        "reason": "SOLDER_BRIDGE",
        "qty": 14
       }
      ]
     },
     "note": ""
    },
    "integration": {
     "value": 0,
     "unit": "count",
     "trend": [],
     "status": "ok",
     "thresholds": {},
     "drill": [
      {
       "label": "Integration console",
       "path": "/integration"
      }
     ],
     "details": {
      "dead_deliveries": 0,
      "failed_batches_7d": 0,
      "stale_reconciliation": false
     },
     "note": ""
    }
   }
  }
 ],
 "totals": {
  "otd": {
   "value": 0.91,
   "unit": "%",
   "trend": [],
   "status": "watch",
   "thresholds": {},
   "drill": [],
   "details": {
    "weights": "due demand lines per plant"
   },
   "note": ""
  }
 },
 "computed_ms": 990
};

export const exampleThresholdsInput: ThresholdsInput = {
 "thresholds": {
  "otd": {
   "alert_below": 0.8,
   "watch_below": 0.9,
   "watch_above": null,
   "alert_above": null
  }
 }
};

export const exampleDigestInput: DigestInput = {
 "scope": "plant",
 "scope_id": "usr_11111111111111111111111111111111",
 "frequency": "weekly",
 "local_time": "07:30",
 "weekday": 0
};

export const exampleDigest: DigestSubscription = {
 "id": "dgs_00000000000000000000000000000001",
 "scope": "plant",
 "scope_id": "usr_11111111111111111111111111111111",
 "scope_label": "Kavach Hyderabad",
 "frequency": "weekly",
 "local_time": "07:30",
 "weekday": 0,
 "time_zone": "Asia/Kolkata",
 "created_at": "2026-11-06T04:30:00Z",
 "last_sent_at": null
};

export const exampleApprovals: ApprovalsResponse = {
 "items": [
  {
   "kind": "pr",
   "id": "pdc_00000000000000000000000000000009",
   "number": "PR-000044",
   "title": "PR-000044 (Avnet, 3 lines)",
   "summary": "INR 648,000",
   "waiting_since": "2026-11-06T02:30:00Z",
   "permission": "pr_approve",
   "row_version": 3,
   "actions": [
    {
     "label": "Approve",
     "method": "POST",
     "path": "/api/v1/mfg/purchase-requests/pdc_00000000000000000000000000000009/approve",
     "body": {}
    },
    {
     "label": "Reject",
     "method": "POST",
     "path": "/api/v1/mfg/purchase-requests/pdc_00000000000000000000000000000009/reject",
     "body": {
      "reason": ""
     }
    }
   ],
   "link": "/mfg/purchasing/requests/pdc_00000000000000000000000000000009"
  },
  {
   "kind": "overtime",
   "id": "apr_0000000000000000000000000000000c:lin_00000000000000000000000000000003:2026-11-14T00:30:00Z",
   "number": "12",
   "title": "Saturday shift on SMT-1 (2026-11-14 06:00-14:00)",
   "summary": "saves 2.5 days of tardiness",
   "waiting_since": null,
   "permission": "schedule_run",
   "row_version": null,
   "actions": [
    {
     "label": "Accept",
     "method": "POST",
     "path": "/api/v1/mfg/aps/runs",
     "body": {
      "copy_of": "apr_0000000000000000000000000000000c",
      "open_shifts": [
       {
        "line_id": "lin_00000000000000000000000000000003",
        "start": "2026-11-14T00:30:00Z",
        "end": "2026-11-14T08:30:00Z"
       }
      ]
     }
    }
   ],
   "link": "/mfg/schedule/runs/apr_0000000000000000000000000000000c?view=overtime"
  }
 ],
 "counts": {
  "pr": 1,
  "eco": 0,
  "replan_proposal": 0,
  "overtime": 1
 }
};

export const exampleDowntimeAcknowledged: DowntimeM6 = {
 "id": "dtm_00000000000000000000000000000001",
 "row_version": 2,
 "created_at": "2026-11-06T04:20:00Z",
 "updated_at": "2026-11-06T04:30:00Z",
 "line": {
  "id": "lin_00000000000000000000000000000003",
  "code": "SMT-1",
  "name": "SMT line 1"
 },
 "kind": "breakdown",
 "planned": false,
 "start_at": "2026-11-06T04:20:00Z",
 "end_at": null,
 "expected_end_at": null,
 "open": true,
 "minutes": null,
 "reason": "Feeder jam",
 "note": "",
 "reported_by": null,
 "closed_by": null,
 "triggers": [],
 "acknowledged_by": {
  "id": "usr_22222222222222222222222222222222",
  "code": "",
  "name": "Ravi (supervisor)"
 },
 "acknowledged_at": "2026-11-06T04:30:00Z"
};

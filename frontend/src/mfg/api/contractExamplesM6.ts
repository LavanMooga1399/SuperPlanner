/**
 * M6 S0 contract examples (docs/M6-DESIGN.md 8): typed against `typesM6.ts` so the compiler flags drift. Written
 * from the design before `backend/superplanner/assistant/fixtures/example_m6.json` existed; replace with the
 * fixture verbatim when it lands (11.WP-U).
 */
import type {
  ApprovalsResponse,
  AssistantStatus,
  AssistantTurn,
  Conversation,
  DashboardResponse,
  DigestList,
  OrgDashboardResponse,
  PushSubscriptionRecord,
  QuickExplanation,
} from "./typesM6";

export const exampleAssistantStatus: AssistantStatus = {
  available: true,
  code: null,
  privacy_notice:
    "The assistant sends your question and the planning records it looks up (part numbers, quantities, dates, order numbers - no prices unless you ask about cost, no personal data) to Anthropic, an AI provider, to answer. Answers may be wrong; check the linked records. Nothing is sent when you use the built-in explanations.",
  budget_left: { user: 400000, plant: 2000000 },
  allow_whatif: true,
};

export const exampleAssistantOff: AssistantStatus = { available: false, code: "AI_DISABLED", privacy_notice: exampleAssistantStatus.privacy_notice, budget_left: null };

export const exampleConversation: Conversation = {
  id: "conv_00000000000000000000000000000001",
  title: "Why is DO-KV-003/10 late",
  allow_whatif: false,
  created_at: "2026-11-06T09:00:00Z",
  updated_at: "2026-11-06T09:00:21Z",
};

/** The scripted S0 turn: tool steps, citations (R1-R3) and two draft cards. */
export const exampleTurn: AssistantTurn = {
  id: "turn_00000000000000000000000000000001",
  conversation_id: exampleConversation.id,
  status: "completed",
  user_text: "Why is DO-KV-003/10 late and what can I do?",
  allow_whatif: false,
  steps: [
    "thinking",
    "tool: demand_status (DO-KV-003/10)",
    "tool: schedule_order (WO-0042)",
    "tool: overtime_options ()",
    "answer",
  ],
  answer:
    "DO-KV-003/10 is projected **3 days late** [R1].\n\nCauses:\n- The limiting path runs through the purchased part KV-PCB-7, due on 12 Nov from Supplier A [R2].\n- WO-0042 then waits for SMT-1, which is fully loaded until 14 Nov [R3].\n\nOptions:\n1. Ask Supplier A to deliver KV-PCB-7 on 9 Nov (draft below).\n2. Open overtime on SMT-1 on Saturday (draft below); this saves about 2 days.",
  citations: [
    { ref: "R1", type: "demand_line", id: "dl_1", label: "DO-KV-003/10", link: "/mfg/demand/do_3?line=dl_1" },
    { ref: "R2", type: "po_schedule", id: "ps_7", label: "PO-0019 line 1 (KV-PCB-7)", link: "/mfg/purchasing/orders/po_19?schedule=ps_7" },
    { ref: "R3", type: "work_order", id: "wo_42", label: "WO-0042", link: "/mfg/work-orders/wo_42" },
  ],
  drafts: [
    {
      draft_id: "draft_00000000000000000000000000000001",
      kind: "expedite_po_schedule",
      summary: "PO-0019 line 1 (KV-PCB-7): requested dock date 12 Nov -> 9 Nov, with a note for the purchaser to agree it with Supplier A.",
      method: "PUT",
      path: "/api/v1/mfg/purchase-orders/po_19",
      body: { supplier_id: "sup_a", lines: [{ id: "pol_1", item_id: "kv_pcb_7", qty: 200, schedules: [{ id: "ps_7", qty: 200, requested_date: "2026-11-09" }] }], note: "Expedite to 9 Nov for DO-KV-003/10 (assistant suggestion)" },
      if_match_of: { type: "purchase_order", id: "po_19", row_version: 4 },
      required_permission: "po_edit",
      applied_at: null,
    },
    {
      draft_id: "draft_00000000000000000000000000000002",
      kind: "open_overtime",
      summary: "New schedule run from the published one with overtime on SMT-1, Saturday 8 Nov 06:00-14:00.",
      method: "POST",
      path: "/api/v1/mfg/aps/runs",
      body: { copy_of: "aps_run_5", open_shifts: [{ line_id: "line_smt1", start: "2026-11-08T00:30:00Z", end: "2026-11-08T08:30:00Z" }], label: "Overtime SMT-1 Sat (assistant)" },
      if_match_of: null,
      required_permission: "schedule_run",
      applied_at: null,
    },
  ],
  error: null,
  notes: [],
  model: "claude-opus-5-5",
  fallback_code: null,
  started_at: "2026-11-06T09:00:01Z",
  finished_at: "2026-11-06T09:00:21Z",
};

export const exampleQuick: QuickExplanation = {
  kind: "why_late",
  title: "Why is DO-KV-003/10 late?",
  answer: "- Material: KV-PCB-7 arrives 12 Nov (PO-0019) [R2]\n- Schedule: WO-0042 waits for SMT-1 until 14 Nov [R3]",
  citations: exampleTurn.citations.slice(1),
};

export const exampleApprovals: ApprovalsResponse = {
  items: [
    { kind: "pr", id: "pr_12", row_version: 2, label: "PR-0012", summary: "3 lines, KV-PCB-7 x 200 and 2 more, needed by 10 Nov", link: "/mfg/purchasing/requests/pr_12", created_at: "2026-11-05T10:00:00Z", requested_by: { id: "u_2", name: "Priya (planner)" } },
    { kind: "eco", id: "eco_3", row_version: 5, label: "ECO-0003", summary: "Replace C12 capacitor on KV-100 rev B", link: "/mfg/eco/eco_3", created_at: "2026-11-04T08:00:00Z" },
    { kind: "proposal", id: "aps_run_9", row_version: 1, label: "Replan 06-11 08:10", summary: "From 3 triggers (SMT-1 down 2 h)", link: "/mfg/schedule/runs/aps_run_9", created_at: "2026-11-06T08:10:00Z", base_run_id: "aps_run_5" },
    {
      kind: "overtime", id: "aps_run_5", row_version: 7, label: "Overtime SMT-1 Sat 06:00-14:00", summary: "Saves 2.1 days of lateness on 4 orders", link: "/mfg/schedule/runs/aps_run_5/overtime", created_at: "2026-11-06T07:00:00Z",
      shifts: [{ line_id: "line_smt1", start: "2026-11-08T00:30:00Z", end: "2026-11-08T08:30:00Z" }], cost: 9600, tardiness_saved_minutes: 3024,
    },
  ],
  counts: { pr: 1, eco: 1, proposal: 1, overtime: 1 },
};

export const exampleDashboard: DashboardResponse = {
  as_of: "2026-11-06T06:00:00Z",
  period: "13w",
  tiles: {
    otd: { label: "On-time delivery", value: 0.91, unit: "ratio", trend: [0.88, 0.9, 0.93, 0.91], status: "watch", thresholds: { alert: 0.85, watch: 0.95 }, drill: { label: "Demand lines of the week", link: "/mfg/demand" } },
    backlog: { label: "Backlog vs capacity (4 weeks)", value: 0.97, unit: "ratio", trend: [], status: "ok", thresholds: null, drill: "/mfg/schedule", details: [{ label: "Next 8 weeks", value: 0.82, unit: "ratio" }] },
    material_risk: { label: "Material risk", value: 4, unit: "items", trend: [], status: "alert", thresholds: null, drill: "/mfg/shortages", details: [{ label: "Value short", value: 12400, unit: "currency" }, { label: "Late from material", value: 2, unit: "lines" }] },
    inventory_turns: { label: "Inventory turns", value: null, unit: "turns", trend: [], status: "na", thresholds: null, drill: "/mfg/inventory", note: "Needs 3 months of daily snapshots." },
  },
};

export const exampleOrgDashboard: OrgDashboardResponse = {
  as_of: exampleDashboard.as_of,
  period: "13w",
  plants: [{ owner_id: "u_kv", plant_name: "Kavach", plant_code: "KV", tiles: exampleDashboard.tiles }],
  totals: { otd: { ...exampleDashboard.tiles.otd, weights: "weighted by demand lines due" } },
};

export const exampleDigests: DigestList = {
  items: [{ id: "dg_1", scope: "plant", scope_id: "u_kv", frequency: "weekly", local_time: "07:00", weekday: 1, last_sent_at: null }],
  email_available: true,
};

export const examplePushSubscription: PushSubscriptionRecord = { id: "push_1", topics: ["critical_alerts", "approvals"], created_at: "2026-11-06T09:00:00Z" };

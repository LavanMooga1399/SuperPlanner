/** Plain-language texts of the assistant (M6 1.1, 1.2, 1.7; P2 2.12 catalog wording). */
import type { AiCode, BudgetLeft, ContextType, DraftKind, TurnStep } from "../api/typesM6";

export const AI_CODE_TEXT: Record<string, string> = {
  AI_DISABLED: "The assistant is turned off on this server.",
  AI_SDK_MISSING: "The assistant is not installed on this server.",
  AI_NO_CREDENTIALS: "The assistant is not set up on this server (no credentials).",
  AI_PLANT_OPTED_OUT: "The assistant is turned off for this plant (plant setting by the owner or a plant admin).",
  AI_BUDGET_EXCEEDED: "Today's assistant allowance is used up. It resets tomorrow.",
  AI_WHATIF_NOT_ALLOWED: "This plant does not allow the assistant to run what-if plans.",
  AI_TURN_RUNNING: "You already have a question running. Wait for it or stop it first.",
  AI_FORBIDDEN: "Your role in this plant does not include the assistant.",
  AI_ROUND_LIMIT: "The question needed more look-ups than allowed; the answer covers what was found.",
  AI_TURN_LOST: "The server stopped working on this question. Ask again.",
  AI_CANCELLED: "Stopped.",
  AI_BUSY: "The assistant is handling other requests. Try again in a moment.",
  AI_RATE_LIMITED: "The assistant is busy right now (rate limit); try again in a minute.",
  AI_AUTH_FAILED: "The assistant is not set up correctly (the credentials were rejected).",
  AI_API_ERROR: "The assistant returned an error.",
  AI_CONNECTION_ERROR: "The assistant could not be reached.",
  AI_REFUSED: "The assistant declined this request. It answers planning questions only.",
  AI_TRUNCATED: "The answer was cut off; try a narrower question.",
  AI_UNEXPECTED: "The assistant failed unexpectedly.",
  MFG_FORBIDDEN: "Your role in this plant does not include the assistant.",
};

export function aiCodeText(code: AiCode | null | undefined, fallback?: string): string {
  if (!code) return fallback ?? "The assistant is not available.";
  return AI_CODE_TEXT[code] ?? fallback ?? `The assistant is not available (${code}).`;
}

/** Codes that will not go away by retrying now (no "try again" button). */
export function isLastingCode(code: string | null | undefined): boolean {
  return ["AI_DISABLED", "AI_SDK_MISSING", "AI_NO_CREDENTIALS", "AI_PLANT_OPTED_OUT", "AI_BUDGET_EXCEEDED", "AI_AUTH_FAILED", "AI_FORBIDDEN", "MFG_FORBIDDEN"].includes(code ?? "");
}

const TOOL_TEXT: Record<string, string> = {
  find_records: "Looking up records",
  demand_status: "Checking the demand line",
  mrp_exceptions: "Reading MRP messages",
  mrp_item_plan: "Reading the item plan",
  mrp_pegging: "Following the pegging",
  schedule_order: "Reading the schedule of the order",
  schedule_bottlenecks: "Finding bottlenecks",
  overtime_options: "Checking overtime options",
  line_status: "Checking the lines",
  kpis: "Reading KPIs",
  supplier_performance: "Checking supplier deliveries",
  trace: "Tracing",
  recall_scope: "Estimating a recall scope",
  eco_impact: "Checking the change impact",
  stock: "Checking stock",
  run_whatif_mrp: "Running a what-if MRP",
  run_whatif_aps: "Running a what-if schedule",
  draft_action: "Preparing a suggestion",
};

export interface StepView {
  kind: string;
  text: string;
  ok: boolean;
}

/** A turn step (`{kind, name, summary: "tool: demand_status (DO-KV-003/10)"}`) as one line of the progress list. */
export function stepView(s: TurnStep): StepView {
  const ok = s.ok !== false;
  if (s.kind === "tool") {
    const m = (s.summary ?? "").match(/^tool:\s*([a-z_]+)\s*(?:\((.*)\))?\s*$/i);
    const name = s.name ?? m?.[1] ?? "";
    const detail = m ? m[2] : s.summary && !s.summary.startsWith("tool:") ? s.summary : "";
    return { kind: "tool", text: `${TOOL_TEXT[name] ?? (name.replace(/_/g, " ") || "Looking something up")}${detail ? ` (${detail})` : ""}`, ok };
  }
  if (s.kind === "thinking") return { kind: "thinking", text: "Thinking", ok };
  if (s.kind === "answer") return { kind: "answer", text: "Writing the answer", ok };
  return { kind: s.kind, text: s.summary || s.kind, ok };
}

export const DRAFT_KIND_TEXT: Record<string, string> = {
  expedite_po_schedule: "Ask the supplier to deliver earlier",
  release_planned_orders: "Release planned orders",
  open_overtime: "Open overtime",
  schedule_edit: "Change the schedule",
  create_pr: "Create a purchase request",
  raise_priority: "Raise the priority",
  whatif_run: "Start a what-if run (cannot be published)",
};

export function draftKindText(k: DraftKind | (string & {})): string {
  return DRAFT_KIND_TEXT[k] ?? k.replace(/_/g, " ");
}

export const SUGGESTED_QUESTIONS = [
  "Which demand lines are late this week, and why?",
  "What limits output this week, and would overtime help?",
  "Which purchase orders should I chase first?",
];

/** The page the user is on, sent as the turn `context` and used by "Why late?" (1.2, 1.7). */
export function contextFromPath(pathname: string, search = ""): { type: ContextType; id: string; label: string } | null {
  const q = new URLSearchParams(search);
  const rules: [RegExp, ContextType, string][] = [
    [/^\/mfg\/demand\/([^/]+)/, "demand_order", "this demand order"],
    [/^\/mfg\/work-orders\/(?!kitting)([^/]+)/, "work_order", "this work order"],
    [/^\/mfg\/items\/([^/]+)/, "item", "this item"],
    [/^\/mfg\/schedule\/runs\/([^/]+)/, "aps_run", "this schedule run"],
    [/^\/mfg\/mrp\/runs\/([^/]+)/, "mrp_run", "this MRP run"],
    [/^\/mfg\/purchasing\/orders\/([^/]+)/, "purchase_order", "this purchase order"],
    [/^\/mfg\/purchasing\/suppliers\/([^/]+)/, "supplier", "this supplier"],
    [/^\/mfg\/eco\/([^/]+)/, "eco", "this change request"],
    [/^\/mfg\/floor\/lines\/([^/]+)/, "line", "this line"],
    [/^\/m\/lines\/([^/]+)/, "line", "this line"],
    [/^\/m\/wo\/([^/]+)/, "work_order", "this work order"],
  ];
  for (const [re, type, label] of rules) {
    const m = pathname.match(re);
    if (m && m[1] !== "new") {
      const line = type === "demand_order" ? q.get("line") : null;
      if (line) return { type: "demand_line", id: line, label: "this demand line" };
      return { type, id: decodeURIComponent(m[1]), label };
    }
  }
  return null;
}

/** "Why late?" makes sense for these contexts. */
export const LATE_CONTEXTS = new Set(["demand_order", "demand_line", "work_order"]);

export function budgetText(b: BudgetLeft | null | undefined): string | null {
  if (!b) return null;
  const n = Math.min(b.user, b.plant);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} M tokens left today`;
  if (n >= 1000) return `${Math.round(n / 1000)} k tokens left today`;
  return `${n} tokens left today`;
}

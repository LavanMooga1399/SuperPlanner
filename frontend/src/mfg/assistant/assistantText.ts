/** Plain-language texts of the assistant (M6 1.1, 1.2, 1.7; P2 2.12 catalog wording). */
import type { AiCode, BudgetLeft, ContextType, DraftKind, TurnStep } from "../api/typesM6";
import { t } from "../../lib/i18n";

export const AI_CODE_TEXT: Record<string, string> = {
  AI_DISABLED: t("assistant.assistantText.str.theAssistantIsTurnedOff"),
  AI_SDK_MISSING: t("assistant.assistantText.str.theAssistantIsNotInstalled"),
  AI_NO_CREDENTIALS: t("assistant.assistantText.str.theAssistantIsNotSet"),
  AI_PLANT_OPTED_OUT: t("assistant.assistantText.str.theAssistantIsTurnedOff2"),
  AI_BUDGET_EXCEEDED: t("assistant.assistantText.str.todaySAssistantAllowanceIs"),
  AI_WHATIF_NOT_ALLOWED: t("assistant.assistantText.str.thisPlantDoesNotAllow"),
  AI_TURN_RUNNING: t("assistant.assistantText.str.youAlreadyHaveAQuestion"),
  AI_FORBIDDEN: t("assistant.assistantText.str.yourRoleInThisPlant"),
  AI_ROUND_LIMIT: t("assistant.assistantText.str.theQuestionNeededMoreLook"),
  AI_TURN_LOST: t("assistant.assistantText.str.theServerStoppedWorkingOn"),
  AI_CANCELLED: t("assistant.assistantText.str.stopped"),
  AI_BUSY: t("assistant.assistantText.str.theAssistantIsHandlingOther"),
  AI_RATE_LIMITED: t("assistant.assistantText.str.theAssistantIsBusyRight"),
  AI_AUTH_FAILED: t("assistant.assistantText.str.theAssistantIsNotSet2"),
  AI_API_ERROR: t("assistant.assistantText.str.theAssistantReturnedAnError"),
  AI_CONNECTION_ERROR: t("assistant.assistantText.str.theAssistantCouldNotBe"),
  AI_REFUSED: t("assistant.assistantText.str.theAssistantDeclinedThisRequest"),
  AI_TRUNCATED: t("assistant.assistantText.str.theAnswerWasCutOff"),
  AI_UNEXPECTED: t("assistant.assistantText.str.theAssistantFailedUnexpectedly"),
  MFG_FORBIDDEN: t("assistant.assistantText.str.yourRoleInThisPlant"),
};

export function aiCodeText(code: AiCode | null | undefined, fallback?: string): string {
  if (!code) return fallback ?? t("assistant.assistantText.str.theAssistantIsNotAvailable");
  return AI_CODE_TEXT[code] ?? fallback ?? t("assistant.assistantText.tpl.theAssistantIsNotAvailable", { code: code });
}

/** Codes that will not go away by retrying now (no "try again" button). */
export function isLastingCode(code: string | null | undefined): boolean {
  return ["AI_DISABLED", "AI_SDK_MISSING", "AI_NO_CREDENTIALS", "AI_PLANT_OPTED_OUT", "AI_BUDGET_EXCEEDED", "AI_AUTH_FAILED", "AI_FORBIDDEN", "MFG_FORBIDDEN"].includes(code ?? "");
}

const TOOL_TEXT: Record<string, string> = {
  find_records: t("assistant.assistantText.str.lookingUpRecords"),
  demand_status: t("assistant.assistantText.str.checkingTheDemandLine"),
  mrp_exceptions: t("assistant.assistantText.str.readingMrpMessages"),
  mrp_item_plan: t("assistant.assistantText.str.readingTheItemPlan"),
  mrp_pegging: t("assistant.assistantText.str.followingThePegging"),
  schedule_order: t("assistant.assistantText.str.readingTheScheduleOfThe"),
  schedule_bottlenecks: t("assistant.assistantText.str.findingBottlenecks"),
  overtime_options: t("assistant.assistantText.str.checkingOvertimeOptions"),
  line_status: t("assistant.assistantText.str.checkingTheLines"),
  kpis: t("assistant.assistantText.str.readingKpis"),
  supplier_performance: t("assistant.assistantText.str.checkingSupplierDeliveries"),
  trace: t("assistant.assistantText.str.tracing"),
  recall_scope: t("assistant.assistantText.str.estimatingARecallScope"),
  eco_impact: t("assistant.assistantText.str.checkingTheChangeImpact"),
  stock: t("assistant.assistantText.str.checkingStock"),
  run_whatif_mrp: t("assistant.assistantText.str.runningAWhatIfMrp"),
  run_whatif_aps: t("assistant.assistantText.str.runningAWhatIfSchedule"),
  draft_action: t("assistant.assistantText.str.preparingASuggestion"),
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
    return { kind: "tool", text: `${TOOL_TEXT[name] ?? (name.replace(/_/g, " ") || t("assistant.assistantText.str.lookingSomethingUp"))}${detail ? ` (${detail})` : ""}`, ok };
  }
  if (s.kind === "thinking") return { kind: "thinking", text: t("assistant.assistantText.str.thinking"), ok };
  if (s.kind === "answer") return { kind: "answer", text: t("assistant.assistantText.str.writingTheAnswer"), ok };
  return { kind: s.kind, text: s.summary || s.kind, ok };
}

export const DRAFT_KIND_TEXT: Record<string, string> = {
  expedite_po_schedule: t("assistant.assistantText.str.askTheSupplierToDeliver"),
  release_planned_orders: t("assistant.assistantText.str.releasePlannedOrders"),
  open_overtime: t("assistant.assistantText.str.openOvertime"),
  schedule_edit: t("assistant.assistantText.str.changeTheSchedule"),
  create_pr: t("assistant.assistantText.str.createAPurchaseRequest"),
  raise_priority: t("assistant.assistantText.str.raiseThePriority"),
  whatif_run: t("assistant.assistantText.str.startAWhatIfRun"),
};

export function draftKindText(k: DraftKind | (string & {})): string {
  return DRAFT_KIND_TEXT[k] ?? k.replace(/_/g, " ");
}

export const SUGGESTED_QUESTIONS = [
  t("assistant.assistantText.str.whichDemandLinesAreLate"),
  t("assistant.assistantText.str.whatLimitsOutputThisWeek"),
  t("assistant.assistantText.str.whichPurchaseOrdersShouldI"),
];

/** The page the user is on, sent as the turn `context` and used by "Why late?" (1.2, 1.7). */
export function contextFromPath(pathname: string, search = ""): { type: ContextType; id: string; label: string } | null {
  const q = new URLSearchParams(search);
  const rules: [RegExp, ContextType, string][] = [
    [/^\/mfg\/demand\/([^/]+)/, "demand_order", t("assistant.assistantText.str.thisDemandOrder")],
    [/^\/mfg\/work-orders\/(?!kitting)([^/]+)/, "work_order", t("assistant.assistantText.str.thisWorkOrder")],
    [/^\/mfg\/items\/([^/]+)/, "item", t("assistant.assistantText.str.thisItem")],
    [/^\/mfg\/schedule\/runs\/([^/]+)/, "aps_run", t("assistant.assistantText.str.thisScheduleRun")],
    [/^\/mfg\/mrp\/runs\/([^/]+)/, "mrp_run", t("assistant.assistantText.str.thisMrpRun")],
    [/^\/mfg\/purchasing\/orders\/([^/]+)/, "purchase_order", t("assistant.assistantText.str.thisPurchaseOrder")],
    [/^\/mfg\/purchasing\/suppliers\/([^/]+)/, "supplier", t("assistant.assistantText.str.thisSupplier")],
    [/^\/mfg\/eco\/([^/]+)/, "eco", t("assistant.assistantText.str.thisChangeRequest")],
    [/^\/mfg\/floor\/lines\/([^/]+)/, "line", t("assistant.assistantText.str.thisLine")],
    [/^\/m\/lines\/([^/]+)/, "line", t("assistant.assistantText.str.thisLine")],
    [/^\/m\/wo\/([^/]+)/, "work_order", t("assistant.assistantText.str.thisWorkOrder")],
  ];
  for (const [re, type, label] of rules) {
    const m = pathname.match(re);
    if (m && m[1] !== "new") {
      const line = type === "demand_order" ? q.get("line") : null;
      if (line) return { type: "demand_line", id: line, label: t("assistant.assistantText.str.thisDemandLine") };
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
  if (n >= 1_000_000) return t("assistant.assistantText.tpl.mTokensLeftToday", { toFixed: (n / 1_000_000).toFixed(1) });
  if (n >= 1000) return t("assistant.assistantText.tpl.kTokensLeftToday", { Math: Math.round(n / 1000) });
  return t("assistant.assistantText.tpl.tokensLeftToday", { n: n });
}

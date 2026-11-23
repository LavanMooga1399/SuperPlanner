import { useId } from "react";
import { Icon, type IconName } from "../../components/Icon";
import type { Provenance } from "../api/types";
import { t } from "../../lib/i18n";

export type ConfidenceLevel = "high" | "medium" | "low";

/** PHASE2.md 2.3: high >= 0.8, medium 0.5-0.8, low < 0.5. */
export function confidenceLevel(c: number): ConfidenceLevel {
  return c >= 0.8 ? "high" : c >= 0.5 ? "medium" : "low";
}

const LEVEL: Record<ConfidenceLevel, { label: string; icon: IconName; tone: string }> = {
  high: { label: t("studio.confidenceBadge.str.high"), icon: "check", tone: "ok" },
  medium: { label: t("studio.confidenceBadge.str.medium"), icon: "info", tone: "warn" },
  low: { label: t("studio.confidenceBadge.str.low"), icon: "alert", tone: "danger" },
};

/** Where a value came from, in plain words. */
export function provenanceText(p: Provenance): string {
  const note = p.note ? ` (${p.note})` : "";
  switch (p.source) {
    case "text":
      return p.span ? t("studio.confidenceBadge.tpl.readFrom", { text: p.span.text, note: note }) : t("studio.confidenceBadge.tpl.readFromYourText", { note: note });
    case "table":
      return p.cell ? t("studio.confidenceBadge.tpl.readFromRowColumnOf", { v: p.cell.row + 1, v2: p.cell.column + 1, note: note }) : t("studio.confidenceBadge.tpl.readFromYourTable", { note: note });
    case "ai":
      return `Suggested by AI assist${p.span ? `, from "${p.span.text}"` : ""}${note}`;
    case "default":
      return t("studio.confidenceBadge.tpl.default", { note: note });
    case "derived":
      return `${p.note || t("studio.confidenceBadge.str.workedOutFromOtherValues")}${p.span ? `, from "${p.span.text}"` : ""}`;
    case "answer":
      return t("studio.confidenceBadge.str.yourAnswer");
    case "edit":
      return t("studio.confidenceBadge.str.youEnteredThis");
  }
}

/**
 * High / Medium / Low with the source on hover and keyboard focus (PHASE2.md 3.3). Values the user answered
 * or typed show "Yours" instead of a confidence.
 */
export function ConfidenceBadge({ path, provenance }: { path: string; provenance: Provenance | undefined }) {
  const tipId = `conf-${useId()}`;
  if (!provenance) return null;
  const mine = provenance.source === "edit" || provenance.source === "answer";
  const level = confidenceLevel(provenance.confidence);
  const m = mine ? { label: t("studio.confidenceBadge.str.yours"), icon: "check" as IconName, tone: "info" } : LEVEL[level];
  const text = provenanceText(provenance);
  return (
    <span
      className={`conf-badge badge ${m.tone}`}
      data-testid={`intake-confidence-${path}`}
      data-level={mine ? "mine" : level}
      tabIndex={0}
      aria-describedby={tipId}
    >
      <Icon name={m.icon} size={12} />
      {m.label}
      <span className="sr-only">{mine ? "" : " confidence"}</span>
      <span role="tooltip" id={tipId} className="conf-tip">
        {text}
      </span>
    </span>
  );
}

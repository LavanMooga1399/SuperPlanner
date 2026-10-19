import { useId } from "react";
import { Icon, type IconName } from "../../components/Icon";
import type { Provenance } from "../api/types";

export type ConfidenceLevel = "high" | "medium" | "low";

/** PHASE2.md 2.3: high >= 0.8, medium 0.5-0.8, low < 0.5. */
export function confidenceLevel(c: number): ConfidenceLevel {
  return c >= 0.8 ? "high" : c >= 0.5 ? "medium" : "low";
}

const LEVEL: Record<ConfidenceLevel, { label: string; icon: IconName; tone: string }> = {
  high: { label: "High", icon: "check", tone: "ok" },
  medium: { label: "Medium", icon: "info", tone: "warn" },
  low: { label: "Low", icon: "alert", tone: "danger" },
};

/** Where a value came from, in plain words. */
export function provenanceText(p: Provenance): string {
  const note = p.note ? ` (${p.note})` : "";
  switch (p.source) {
    case "text":
      return p.span ? `Read from: "${p.span.text}"${note}` : `Read from your text${note}`;
    case "table":
      return p.cell ? `Read from row ${p.cell.row + 1}, column ${p.cell.column + 1} of your table${note}` : `Read from your table${note}`;
    case "ai":
      return `Suggested by AI assist${p.span ? `, from "${p.span.text}"` : ""}${note}`;
    case "default":
      return `Default${note}`;
    case "derived":
      return `${p.note || "Worked out from other values"}${p.span ? `, from "${p.span.text}"` : ""}`;
    case "answer":
      return "Your answer";
    case "edit":
      return "You entered this";
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
  const m = mine ? { label: "Yours", icon: "check" as IconName, tone: "info" } : LEVEL[level];
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

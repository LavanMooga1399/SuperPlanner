/** Duration ranges and the PERT expected value (PHASE2.md 2.14), for display in the intake screens. */
import type { DraftDuration, DurationUnit } from "../api/types";

/** Same rounding as the engine: (o + 4m + p) / 6, half up, whole minutes. */
export function pertMinutes(optimistic: number, likely: number, pessimistic: number): number {
  return Math.floor((optimistic + 4 * likely + pessimistic + 3) / 6);
}

/** Expected value in the draft's own unit (not rounded to minutes). */
export function pertValue(d: Pick<DraftDuration, "optimistic" | "likely" | "pessimistic">): number {
  return (d.optimistic + 4 * d.likely + d.pessimistic) / 6;
}

export function isRange(d: DraftDuration | null | undefined): boolean {
  return !!d && d.optimistic < d.pessimistic;
}

const UNIT_WORDS: Record<DurationUnit, [string, string]> = {
  minutes: ["minute", "minutes"],
  hours: ["hour", "hours"],
  days: ["day", "days"],
  weeks: ["week", "weeks"],
};

export const UNIT_LABEL: Record<DurationUnit, string> = { minutes: "Minutes", hours: "Hours", days: "Days", weeks: "Weeks" };

export function num(v: number): string {
  const r = Math.round(v * 100) / 100;
  return Number.isInteger(r) ? String(r) : String(r).replace(/(\.\d*?)0+$/, "$1");
}

export function unitWord(v: number, unit: DurationUnit): string {
  return UNIT_WORDS[unit][v === 1 ? 0 : 1];
}

/** "2-3 days, expected 2.5 days" for a range; "1 week" for a single value. */
export function formatRange(d: DraftDuration | null | undefined): string {
  if (!d) return "not set";
  if (!isRange(d)) return `${num(d.likely)} ${unitWord(d.likely, d.unit)}`;
  const e = pertValue(d);
  const likely = d.likely !== (d.optimistic + d.pessimistic) / 2 ? `, most likely ${num(d.likely)}` : "";
  return `${num(d.optimistic)}-${num(d.pessimistic)} ${UNIT_WORDS[d.unit][1]}${likely}, expected ${num(e)} ${unitWord(e, d.unit)}`;
}

/** Work time in hours ("172 h") for build summaries, which are minutes of working time. */
export function formatWorkMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = minutes / 60;
  return `${h >= 100 ? Math.round(h) : num(Math.round(h * 10) / 10)} h`;
}

/** Chip text for an engine estimate in minutes: "5h 20m-8h". */
export function formatMinutesRange(o: number, p: number, fmt: (m: number) => string): string {
  return `${fmt(o)}-${fmt(p)}`;
}

/** Month arithmetic on "YYYY-MM" strings (FINANCE.md 3). */
import type { Month } from "../api/types";

export const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

export function isMonth(s: unknown): s is Month {
  return typeof s === "string" && MONTH_RE.test(s);
}

export function currentUtcMonth(): Month {
  const d = new Date();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function parts(m: Month): [number, number] {
  return [Number(m.slice(0, 4)), Number(m.slice(5, 7))];
}

export function monthToIndex(m: Month): number {
  const [y, mo] = parts(m);
  return y * 12 + (mo - 1);
}

export function indexToMonth(i: number): Month {
  const y = Math.floor(i / 12);
  const mo = i - y * 12 + 1;
  return `${String(y).padStart(4, "0")}-${String(mo).padStart(2, "0")}`;
}

export function addMonths(m: Month, n: number): Month {
  return indexToMonth(monthToIndex(m) + Math.round(n));
}

/** Months from a to b (b - a). */
export function monthsBetween(a: Month, b: Month): number {
  return monthToIndex(b) - monthToIndex(a);
}

export function compareMonths(a: Month, b: Month): number {
  return monthToIndex(a) - monthToIndex(b);
}

const NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2030-10" -> "Oct 2030". */
export function fmtMonth(m: Month | null | undefined): string {
  if (!m || !isMonth(m)) return "-";
  const [y, mo] = parts(m);
  return `${NAMES[mo - 1]} ${y}`;
}

export function fmtMonthShort(m: Month): string {
  const [y, mo] = parts(m);
  return `${NAMES[mo - 1]} ${String(y).slice(2)}`;
}

/** "in 3 years 2 months" style text. */
export function fmtDurationMonths(n: number): string {
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(Math.round(n));
  const y = Math.floor(a / 12);
  const m = a % 12;
  const ys = y ? `${y} year${y === 1 ? "" : "s"}` : "";
  const ms = m ? `${m} month${m === 1 ? "" : "s"}` : "";
  return sign + ([ys, ms].filter(Boolean).join(" ") || "0 months");
}

/** Years (may be fractional) from start to m, rounded to 0.1. */
export function yearsFromStart(start: Month, m: Month): number {
  return Math.round((monthsBetween(start, m) / 12) * 10) / 10;
}

export function monthInYears(start: Month, years: number): Month {
  return addMonths(start, Math.round(years * 12));
}

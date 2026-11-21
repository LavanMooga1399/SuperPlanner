/**
 * One place for number/date formatting (UX-STANDARD 4): Indian English, 24-hour clock, digit grouping.
 * Plant-local values keep their own offset (see mfg/lib/plantTime.ts); browser-local timestamps use these.
 */
export const LOCALE = "en-IN";

const nf = new Map<string, Intl.NumberFormat>();
function numberFormat(min: number, max: number): Intl.NumberFormat {
  const k = `${min}:${max}`;
  let f = nf.get(k);
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: min, maximumFractionDigits: max });
    nf.set(k, f);
  }
  return f;
}

/** Grouped number, up to `max` decimals (default 6, as the API rounds outputs). */
export function formatNumber(x: number | null | undefined, max = 6, min = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  return numberFormat(min, Math.max(min, max)).format(x);
}

const dtf = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const df = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric" });

/** Browser-local date and time, e.g. "21 Nov 2026, 17:20". */
export function formatDateTime(d: Date | string | number | null | undefined): string {
  if (d === null || d === undefined || d === "") return "";
  const x = d instanceof Date ? d : new Date(d);
  return Number.isNaN(x.getTime()) ? String(d) : dtf.format(x);
}

export function formatDate(d: Date | string | number | null | undefined): string {
  if (d === null || d === undefined || d === "") return "";
  const x = d instanceof Date ? d : new Date(d);
  return Number.isNaN(x.getTime()) ? String(d) : df.format(x);
}

const tf = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

/** Browser-local time of day, 24 h, e.g. "17:20". */
export function formatTime(d: Date | string | number | null | undefined): string {
  if (d === null || d === undefined || d === "") return "";
  const x = d instanceof Date ? d : new Date(d);
  return Number.isNaN(x.getTime()) ? String(d) : tf.format(x);
}

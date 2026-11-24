
import { intlLocale, t } from "./i18n";

/**
 * One place for number/date formatting (UX-STANDARD 4): Indian English (or French (Canada), M7 10: narrow no-break
 * space thousands, comma decimal), 24-hour clock, digit grouping. Plant-local values keep their own offset (see
 * mfg/lib/plantTime.ts); browser-local timestamps use these.
 */
export const LOCALE = intlLocale();

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

const MON = [t("shell.locale.str.jan"), t("shell.locale.str.feb"), t("shell.locale.str.mar"), t("shell.locale.str.apr"), t("shell.locale.str.may"), t("shell.locale.str.jun"), t("shell.locale.str.jul"), t("shell.locale.str.aug"), t("shell.locale.str.sep"), t("shell.locale.str.oct"), t("shell.locale.str.nov"), t("shell.locale.str.dec")];

/** Calendar date ("2026-11-02", or the date part of an ISO timestamp) without a time-zone shift: "2 Nov 2026". */
export function formatDay(d: string | null | undefined): string {
  if (!d) return "";
  const m = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${Number(m[3])} ${MON[Number(m[2]) - 1]} ${m[1]}` : d;
}

/** Date range of two calendar dates, shortest unambiguous form: "24 Oct – 22 Nov 2026", "1–22 Nov 2026". */
export function formatDateRange(from: string | null | undefined, to: string | null | undefined): string {
  const a = from?.match(/^(\d{4})-(\d{2})-(\d{2})/);
  const b = to?.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!a || !b) return [formatDay(from), formatDay(to)].filter(Boolean).join(" – ");
  if (a[1] !== b[1]) return `${formatDay(from)} – ${formatDay(to)}`;
  if (a[2] !== b[2]) return `${Number(a[3])} ${MON[Number(a[2]) - 1]} – ${formatDay(to)}`;
  if (a[3] === b[3]) return formatDay(to);
  return `${Number(a[3])}–${formatDay(to)}`;
}

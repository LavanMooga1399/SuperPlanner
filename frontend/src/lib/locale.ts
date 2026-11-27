
import { intlLocale, t } from "./i18n";

/**
 * One place for number/date formatting (UX-STANDARD 4): the format from `intlLocale()` (person override, else language +
 * plant country: en-CA / fr-CA, en-IN, en-US), 24-hour clock, digit grouping. Plant-local values keep their own offset (see
 * mfg/lib/plantTime.ts); browser-local timestamps use these.
 */
export let LOCALE = intlLocale();

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


/** Re-read the format after the plant region is known (live binding: importers of `LOCALE` see the new value). */
export function refreshLocale(): boolean {
  const next = intlLocale();
  if (next === LOCALE) return false;
  LOCALE = next;
  nf.clear();
  cf.clear();
  return true;
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/**
 * Browser-local date and time, e.g. "21 Nov 2026 17:20". Dates are always day - month - year with the short month
 * of the UI language (UX-STANDARD 8), whatever the number format (en-CA's Intl date would be "Nov 21, 2026").
 */
export function formatDateTime(d: Date | string | number | null | undefined): string {
  if (d === null || d === undefined || d === "") return "";
  const x = d instanceof Date ? d : new Date(d);
  return Number.isNaN(x.getTime()) ? String(d) : `${formatDate(x)} ${pad2(x.getHours())}:${pad2(x.getMinutes())}`;
}

/** Browser-local calendar date, e.g. "21 Nov 2026". */
export function formatDate(d: Date | string | number | null | undefined): string {
  if (d === null || d === undefined || d === "") return "";
  const x = d instanceof Date ? d : new Date(d);
  return Number.isNaN(x.getTime()) ? String(d) : `${x.getDate()} ${MON[x.getMonth()]} ${x.getFullYear()}`;
}

/** Browser-local time of day, 24 h, e.g. "17:20". */
export function formatTime(d: Date | string | number | null | undefined): string {
  if (d === null || d === undefined || d === "") return "";
  const x = d instanceof Date ? d : new Date(d);
  return Number.isNaN(x.getTime()) ? String(d) : `${pad2(x.getHours())}:${pad2(x.getMinutes())}`;
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

/** Units of measure counted in whole pieces (quantities shown without decimals). */
const COUNT_UOMS = new Set(["EA", "EACH", "PC", "PCS", "PCE", "UN", "UNIT", "UNITS", "U", "NOS", "NO", "SET", "SETS", "PR", "PAIR", "BOX", "BX", "CS", "CASE", "PK", "PACK", "ROLL", "RL", "REEL", "BAG", "BTL", "KIT", "LOT", "PAL", "SHEET", "SH", "TRAY", "VIAL", "AMP", "DOZ"]);

/**
 * Quantity by unit of measure (demo review): count units (EA, PCS, ...) as whole numbers; other units (kg, m, L)
 * with at most 3 decimals, trailing zeros trimmed; grouped by locale. Unknown unit = up to 3 decimals.
 */
export function formatQty(x: number | null | undefined, uom?: string | null): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  const count = uom ? COUNT_UOMS.has(uom.trim().toUpperCase()) : false;
  const v = count && Math.abs(x - Math.round(x)) < 1e-6 ? Math.round(x) : x;
  if (count && Number.isInteger(v)) return formatNumber(v, 0);
  // small amounts keep 3 significant digits (0.00025 kg), larger ones at most 3 decimals
  if (v !== 0 && Math.abs(v) < 1) return Number(v.toPrecision(3)).toLocaleString(LOCALE, { maximumFractionDigits: 10 });
  return formatNumber(v, 3);
}

const cf = new Map<string, Intl.NumberFormat>();
/**
 * Money with its ISO currency (M9 executive views): "US$1,234,567" / "1 234 567 $ CA" by the active format;
 * `compact` gives "US$45M" for KPI cards, `digits` the fraction digits (default 0, unit costs pass 2-4),
 * `signed` a leading + for deltas. Null -> "–" (FX missing is never shown as a number).
 */
export function formatMoney(x: number | null | undefined, currency: string, opts: { compact?: boolean; digits?: number; signed?: boolean } = {}): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  const digits = opts.digits ?? 0;
  const k = `${currency}:${digits}:${opts.compact ? 1 : 0}:${opts.signed ? 1 : 0}`;
  let f = cf.get(k);
  if (!f) {
    try {
      f = new Intl.NumberFormat(LOCALE, {
        style: "currency",
        currency: currency || "USD",
        currencyDisplay: "symbol",
        minimumFractionDigits: opts.compact ? 0 : digits,
        maximumFractionDigits: opts.compact ? 1 : digits,
        notation: opts.compact ? "compact" : "standard",
        signDisplay: opts.signed ? "exceptZero" : "auto",
      });
    } catch {
      f = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: digits });
    }
    cf.set(k, f);
  }
  return f.format(x);
}

/** Signed number for deltas: "+1,200", "−300", "0". */
export function formatSigned(x: number | null | undefined, max = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  const s = formatNumber(Math.abs(x), max);
  return x > 0 ? `+${s}` : x < 0 ? `−${s}` : s;
}

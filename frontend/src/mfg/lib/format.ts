/** Number/date formatting for the Manufacturing screens. */
import type { MakeBuy, Weekday } from "../api/types";

/** Up to 6 decimals (M 4.4: outputs rounded to 6 decimals for display), no thousands separators. */
export function fmtQty(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  const r = Math.round(x * 1e6) / 1e6;
  return String(r);
}

/** Minutes with up to 6 decimals (time preview: the numbers equal the API response). */
export const fmtMinutes = fmtQty;

/** "2 h 15 min" style for a minutes total. */
export function fmtHours(minutes: number): string {
  if (!Number.isFinite(minutes)) return "";
  const m = Math.round(minutes);
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (h === 0) return `${rest} min`;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

export function fmtPct(x: number): string {
  return `${Math.round(x * 10000) / 100}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `2026-11-02` -> `2 Nov 2026`. */
export function fmtDate(d: string | null | undefined): string {
  if (!d) return "";
  const m = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return d;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

/** ISO datetime -> `2 Nov 2026 06:10` in the value's own offset (plant-time values carry the plant offset). */
export function fmtLocalDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = iso.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  if (!m) return iso;
  return `${fmtDate(m[1])} ${m[2]}`;
}

/** API timestamps (UTC `Z`) in the browser's locale. */
export function fmtTimestamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export const WEEKDAY_LABEL: Record<Weekday, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

export const MAKE_BUY_LABEL: Record<MakeBuy, string> = {
  make: "Make",
  buy: "Buy",
  phantom: "Phantom",
};

/** Add days to a `YYYY-MM-DD` date (UTC arithmetic, no time zone involved). */
export function addDays(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Minutes of a `+HH:MM` offset. */
export function offsetMinutes(offset: string): number {
  const m = offset.match(/^([+-])(\d{2}):(\d{2})$/);
  if (!m) return 0;
  return (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3]));
}

/** Local `YYYY-MM-DDTHH:MM` + offset -> ISO with that offset. */
export function localToIso(local: string, offset: string): string {
  const v = local.length === 16 ? `${local}:00` : local;
  return `${v}${offset}`;
}

/** ISO with offset -> `YYYY-MM-DDTHH:MM` local in `offset` (converts when the value carries another offset). */
export function isoToLocal(iso: string, offset: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const shifted = new Date(d.getTime() + offsetMinutes(offset) * 60000);
  return shifted.toISOString().slice(0, 16);
}

/** Minutes between two ISO datetimes. */
export function minutesBetween(a: string, b: string): number {
  return (new Date(b).getTime() - new Date(a).getTime()) / 60000;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

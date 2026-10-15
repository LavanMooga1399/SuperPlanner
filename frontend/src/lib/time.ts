/**
 * Time helpers. Every plan has one fixed UTC offset (that of `horizon_start`,
 * ARCHITECTURE 4). The UI renders and edits times in that offset, never in
 * the browser's zone.
 */

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const pad = (n: number, w = 2) => String(Math.abs(Math.trunc(n))).padStart(w, "0");

/** Offset in minutes of an ISO datetime string ("Z" -> 0). Defaults to 0. */
export function offsetMinutesOf(iso: string | null | undefined): number {
  if (!iso) return 0;
  const m = iso.match(/([+-])(\d{2}):?(\d{2})$/);
  if (!m) return 0;
  const sign = m[1] === "-" ? -1 : 1;
  return sign * (Number(m[2]) * 60 + Number(m[3]));
}

/** "+05:30" style text for an offset in minutes. */
export function offsetText(offsetMin: number): string {
  const sign = offsetMin < 0 ? "-" : "+";
  const a = Math.abs(offsetMin);
  return `${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

export function offsetLabel(offsetMin: number): string {
  return `UTC${offsetText(offsetMin)}`;
}

/** The browser's current UTC offset as "+05:30" (sent on template instantiation). */
export function browserUtcOffset(): string {
  return offsetText(-new Date().getTimezoneOffset());
}

export function isoToMs(iso: string): number {
  return new Date(iso).getTime();
}

/** Wall-clock parts of an instant in the given offset. */
export function wallParts(ms: number, offsetMin: number) {
  const d = new Date(ms + offsetMin * 60000);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth(),
    day: d.getUTCDate(),
    weekday: d.getUTCDay(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
  };
}

/** ISO string of an instant rendered in the given offset ("2026-10-19T06:00:00+05:30"). */
export function msToIso(ms: number, offsetMin: number): string {
  const p = wallParts(ms, offsetMin);
  return `${p.year}-${pad(p.month + 1)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}:00${offsetText(offsetMin)}`;
}

/** Engine minute -> ISO in the plan offset. */
export function minuteToIso(minute: number, horizonStart: string): string {
  return msToIso(isoToMs(horizonStart) + minute * 60000, offsetMinutesOf(horizonStart));
}

/** ISO -> engine minute (floored), relative to horizon start. */
export function isoToMinute(iso: string, horizonStart: string): number {
  return Math.floor((isoToMs(iso) - isoToMs(horizonStart)) / 60000);
}

/** "Tue 20 Oct 10:00" */
export function fmtDateTime(ms: number, offsetMin: number): string {
  const p = wallParts(ms, offsetMin);
  return `${DAY_NAMES[p.weekday]} ${p.day} ${MONTH_NAMES[p.month]} ${pad(p.hour)}:${pad(p.minute)}`;
}

/** "Tue 20 Oct" */
export function fmtDate(ms: number, offsetMin: number): string {
  const p = wallParts(ms, offsetMin);
  return `${DAY_NAMES[p.weekday]} ${p.day} ${MONTH_NAMES[p.month]}`;
}

/** "10:00" */
export function fmtTime(ms: number, offsetMin: number): string {
  const p = wallParts(ms, offsetMin);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

export function fmtIso(iso: string | null | undefined, offsetMin?: number): string {
  if (!iso) return "-";
  return fmtDateTime(isoToMs(iso), offsetMin ?? offsetMinutesOf(iso));
}

/** Minute of the plan axis formatted in the plan offset. */
export function fmtMinute(minute: number, horizonStart: string): string {
  return fmtDateTime(isoToMs(horizonStart) + minute * 60000, offsetMinutesOf(horizonStart));
}

/** "2h 15m", "45m", "3d 4h", "0m". Negative values get a leading minus. */
export function fmtDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return "-";
  const neg = minutes < 0;
  let m = Math.round(Math.abs(minutes));
  const d = Math.floor(m / 1440);
  m -= d * 1440;
  const h = Math.floor(m / 60);
  m -= h * 60;
  const parts: string[] = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  if (m || parts.length === 0) parts.push(`${m}m`);
  return (neg ? "-" : "") + parts.slice(0, 2).join(" ");
}

/** Signed delta, e.g. "+2h 15m", "-30m", "0m". */
export function fmtDelta(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "-";
  if (minutes === 0) return "0m";
  return (minutes > 0 ? "+" : "") + fmtDuration(minutes);
}

/** ISO (any offset) -> value for <input type="datetime-local"> in the plan offset. */
export function isoToInput(iso: string | null | undefined, offsetMin: number): string {
  if (!iso) return "";
  const p = wallParts(isoToMs(iso), offsetMin);
  return `${p.year}-${pad(p.month + 1)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
}

/** <input type="datetime-local"> value (plan wall clock) -> ISO with the plan offset. */
export function inputToIso(value: string, offsetMin: number): string | null {
  if (!value) return null;
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return null;
  return `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00${offsetText(offsetMin)}`;
}

/** Local date "YYYY-MM-DD" (browser zone) for date inputs default. */
export function todayDate(): string {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Relative time for UTC server timestamps, e.g. "5 min ago". */
export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "-";
  const diff = (Date.now() - isoToMs(iso)) / 1000;
  if (Number.isNaN(diff)) return "-";
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return `${Math.round(diff / 86400)} d ago`;
}

/** Server timestamps (UTC) shown in the browser's local zone. */
export function fmtLocal(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return "-";
  if (s < 10) return `${s.toFixed(1)} s`;
  return `${Math.round(s)} s`;
}

export function fmtMoney(v: number | null | undefined, currency: string): string {
  if (v === null || v === undefined) return "-";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: v >= 1000 ? 0 : 2,
    }).format(v);
  } catch {
    return `${v.toFixed(2)} ${currency}`;
  }
}

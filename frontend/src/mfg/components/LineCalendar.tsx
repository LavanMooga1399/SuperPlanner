/**
 * Month view of one line's working windows (M 11.2): `GET /lines/{id}/windows` for one month (<= 31 days,
 * within the 62-day limit). Per day a 24 h strip: base time solid, optional time hatched, calendar exceptions
 * in red, plus the hours as text (status is never shown by color alone).
 */
import { useMemo } from "react";
import { Icon } from "../../components/Icon";
import { getLineWindows } from "../api/client";
import type { CalendarExceptionRecord, LineRecord } from "../api/types";
import { addDays, fmtHours, offsetMinutes } from "../lib/format";
import { useLoad } from "../lib/useMfg";
import { MfgError } from "./Feedback";

const DAY_MS = 86400000;

interface Piece {
  from: number;
  to: number;
  kind: "base" | "optional" | "exception";
  label: string;
}

/** Split [start, end) (ISO with offset) into per-local-day pieces in minutes. */
function pieces(startIso: string, endIso: string, offMin: number): { date: string; from: number; to: number }[] {
  const s = Date.parse(startIso) + offMin * 60000;
  const e = Date.parse(endIso) + offMin * 60000;
  if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return [];
  const out: { date: string; from: number; to: number }[] = [];
  let m = s;
  while (m < e) {
    const dayStart = Math.floor(m / DAY_MS) * DAY_MS;
    const segEnd = Math.min(e, dayStart + DAY_MS);
    out.push({ date: new Date(dayStart).toISOString().slice(0, 10), from: (m - dayStart) / 60000, to: (segEnd - dayStart) / 60000 });
    m = segEnd;
  }
  return out;
}

export function monthBounds(month: string): { from: string; to: string } {
  const from = `${month}-01`;
  const d = new Date(`${from}T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() + 1);
  return { from, to: d.toISOString().slice(0, 10) };
}

export function LineCalendar({
  line,
  month,
  utcOffset,
  exceptions,
  refreshKey,
}: {
  line: LineRecord;
  month: string;
  utcOffset: string;
  exceptions: CalendarExceptionRecord[];
  refreshKey: number;
}) {
  const { from, to } = monthBounds(month);
  const win = useLoad((signal) => getLineWindows(line.id, from, to, ["base", "optional"], signal), [line.id, from, to, refreshKey]);
  const off = offsetMinutes(win.data?.utc_offset ?? utcOffset);

  const byDay = useMemo(() => {
    const m = new Map<string, Piece[]>();
    const add = (date: string, p: Piece) => m.set(date, [...(m.get(date) ?? []), p]);
    for (const w of win.data?.windows ?? []) for (const p of pieces(w.start, w.end, off)) add(p.date, { from: p.from, to: p.to, kind: w.kind, label: w.shift_label });
    for (const x of exceptions) {
      const applies = x.scope === "plant" || (x.scope === "group" && x.group_id === line.group_id) || (x.scope === "line" && x.line_id === line.id);
      if (!applies) continue;
      for (const p of pieces(x.start, x.end, off)) add(p.date, { from: p.from, to: p.to, kind: "exception", label: x.label || x.kind });
    }
    return m;
  }, [win.data, exceptions, off, line.id, line.group_id]);

  const days: string[] = [];
  for (let d = from; d < to; d = addDays(d, 1)) days.push(d);
  const lead = (new Date(`${from}T00:00:00Z`).getUTCDay() + 6) % 7; // Monday first

  return (
    <div className="col" style={{ gap: 6 }}>
      <MfgError error={win.error} onRetry={win.reload} />
      <div className="legend">
        <span className="legend-item">
          <span className="swatch mfg-sw-base" /> Base shift
        </span>
        <span className="legend-item">
          <span className="swatch mfg-sw-optional" /> Optional (overtime)
        </span>
        <span className="legend-item">
          <span className="swatch mfg-sw-exception" /> Holiday / shutdown / maintenance
        </span>
        {win.data ? (
          <span className="legend-item" data-testid="line-calendar-totals">
            Month: {fmtHours(win.data.totals.base_minutes)} base, {fmtHours(win.data.totals.optional_minutes)} optional
          </span>
        ) : null}
        {win.loading ? <span className="spinner" aria-hidden /> : null}
      </div>
      <div className="mfg-month" data-testid="line-calendar" data-line-id={line.id} data-month={month} data-loading={win.loading ? "true" : "false"} role="grid" aria-label={`Working time of ${line.code} in ${month}`}>
        <div role="row" className="mfg-month-row mfg-month-head">
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
            <div role="columnheader" key={d}>
              {d}
            </div>
          ))}
        </div>
        {chunk([...Array<string | null>(lead).fill(null), ...days], 7).map((week, wi) => (
          <div role="row" className="mfg-month-row" key={wi}>
            {week.map((date, di) => {
              if (!date) return <div role="gridcell" key={di} className="mfg-day empty" />;
              const ps = byDay.get(date) ?? [];
              const base = ps.filter((p) => p.kind === "base").reduce((s, p) => s + p.to - p.from, 0);
              const opt = ps.filter((p) => p.kind === "optional").reduce((s, p) => s + p.to - p.from, 0);
              const exc = ps.filter((p) => p.kind === "exception");
              return (
                <div
                  role="gridcell"
                  key={date}
                  className={`mfg-day${exc.length ? " has-exception" : ""}`}
                  data-testid="calendar-day"
                  data-date={date}
                  data-base-minutes={Math.round(base)}
                  data-optional-minutes={Math.round(opt)}
                  aria-label={`${date}: ${base ? fmtHours(base) : "no"} base time${opt ? `, ${fmtHours(opt)} optional` : ""}${exc.length ? `, ${exc.map((e) => e.label).join(", ")}` : ""}`}
                >
                  <div className="mfg-day-num">{Number(date.slice(8))}</div>
                  <div className="mfg-strip" aria-hidden>
                    {ps.map((p, i) => (
                      <span key={i} className={`mfg-strip-${p.kind}`} style={{ left: `${(p.from / 1440) * 100}%`, width: `${((p.to - p.from) / 1440) * 100}%` }} title={`${p.label} ${hhmm(p.from)}-${hhmm(p.to)}`} />
                    ))}
                  </div>
                  <div className="mfg-day-text small">
                    {base ? fmtHours(base) : <span className="faint">-</span>}
                    {opt ? <span className="muted"> +{fmtHours(opt)}</span> : null}
                  </div>
                  {exc.length ? (
                    <div className="mfg-day-exc small" title={exc.map((e) => e.label).join(", ")}>
                      <Icon name="ban" size={11} /> {exc[0].label}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function chunk<T>(arr: T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += n) {
    const c = arr.slice(i, i + n);
    while (c.length < n) c.push(null as T);
    out.push(c);
  }
  return out;
}

function hhmm(m: number): string {
  const r = Math.round(m);
  return `${String(Math.floor(r / 60)).padStart(2, "0")}:${String(r % 60).padStart(2, "0")}`;
}

/**
 * Weekly shift preview (M 11.2): SVG of 7 day columns x 24 h from `POST /shift-templates/preview` (debounced
 * 300 ms). Windows that run past midnight (night shifts) are drawn split: the part before midnight in the start
 * day's column and the rest at the top of the next day's column (Sunday night wraps to Monday). Breaks show as
 * gaps; per-day totals are listed as text.
 */
import { useMemo } from "react";
import { previewShiftTemplate } from "../api/client";
import { WEEKDAYS, type ShiftTemplateInput, type WeekWindow, type Weekday } from "../api/types";
import { fmtHours, WEEKDAY_LABEL } from "../lib/format";
import { fieldErrors, useDebounced, useLoad } from "../lib/useMfg";
import { MfgError } from "./Feedback";

const DAY = 1440;
const WEEK = 7 * DAY;

export interface Segment {
  day: number;
  from: number;
  to: number;
  shift: string;
  /** "start": continues next day; "end": continued from the previous day; "both"; null: within one day. */
  split: "start" | "end" | "both" | null;
}

/** Split week windows at midnight; minutes past Sunday 24:00 wrap to Monday. */
export function splitAtMidnight(windows: WeekWindow[]): Segment[] {
  const out: Segment[] = [];
  for (const w of windows) {
    let m = w.start_minute;
    while (m < w.end_minute) {
      const dayStart = Math.floor(m / DAY) * DAY;
      const segEnd = Math.min(w.end_minute, dayStart + DAY);
      const continued = m > w.start_minute;
      const continues = segEnd < w.end_minute;
      out.push({
        day: Math.floor((m % WEEK) / DAY),
        from: m - dayStart,
        to: segEnd - dayStart,
        shift: w.shift,
        split: continued && continues ? "both" : continues ? "start" : continued ? "end" : null,
      });
      m = segEnd;
    }
  }
  return out;
}

const COL_W = 96;
const AXIS_W = 40;
const HEAD_H = 22;
const HOUR_H = 14;
const PALETTE = ["var(--accent)", "var(--fin-c2, #0d9488)", "var(--fin-c4, #7c3aed)", "var(--fin-c3, #d97706)", "var(--fin-c5, #db2777)"];

export function ShiftWeekPreview({ template }: { template: ShiftTemplateInput }) {
  const body = useMemo(() => JSON.stringify(template), [template]);
  const debounced = useDebounced(body, 300);
  const valid = template.shifts.length > 0 && template.shifts.every((s) => s.days.length > 0 && /^\d{2}:\d{2}$/.test(s.start) && /^\d{2}:\d{2}$/.test(s.end));
  const preview = useLoad(
    (signal) => (valid ? previewShiftTemplate(JSON.parse(debounced) as ShiftTemplateInput, signal) : null),
    [debounced, valid],
  );
  const shiftNames = template.shifts.map((s) => s.name);
  const segments = useMemo(() => splitAtMidnight(preview.data?.week_windows ?? []), [preview.data]);
  const width = AXIS_W + COL_W * 7;
  const height = HEAD_H + HOUR_H * 24;
  const errors = fieldErrors(preview.error);
  const describe = segments
    .map((s) => `${WEEKDAY_LABEL[WEEKDAYS[s.day]]} ${hhmm(s.from)}-${hhmm(s.to)} ${s.shift}${s.split === "start" ? " (continues next day)" : s.split === "end" ? " (from the previous day)" : ""}`)
    .join("; ");

  return (
    <div className="col" style={{ gap: 6 }}>
      {errors.length ? (
        <div className="banner danger" role="alert">
          <div className="banner-body">
            <strong>These shifts do not fit together</strong>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {errors.map((e, i) => (
                <li key={i}>{e.field ? `${e.field}: ${e.message}` : e.message}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <MfgError error={preview.error} />
      )}
      <div className="mfg-week-wrap">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          className="mfg-week"
          role="img"
          aria-label={`Working time in a week: ${describe || "none"}`}
          data-testid="shift-week-preview"
          data-loading={preview.loading ? "true" : "false"}
        >
          {WEEKDAYS.map((d, i) => (
            <g key={d}>
              <rect x={AXIS_W + i * COL_W} y={HEAD_H} width={COL_W} height={HOUR_H * 24} className={i % 2 ? "mfg-week-col alt" : "mfg-week-col"} />
              <text x={AXIS_W + i * COL_W + COL_W / 2} y={15} textAnchor="middle" className="mfg-week-head">
                {WEEKDAY_LABEL[d]}
              </text>
            </g>
          ))}
          {[0, 6, 12, 18, 24].map((h) => (
            <g key={h}>
              <line x1={AXIS_W - 4} x2={width} y1={HEAD_H + h * HOUR_H} y2={HEAD_H + h * HOUR_H} className="mfg-week-grid" />
              <text x={AXIS_W - 6} y={HEAD_H + h * HOUR_H + 4} textAnchor="end" className="mfg-week-axis">
                {String(h).padStart(2, "0")}:00
              </text>
            </g>
          ))}
          {segments.map((s, i) => {
            const idx = Math.max(0, shiftNames.indexOf(s.shift));
            const y = HEAD_H + (s.from / 60) * HOUR_H;
            const h = Math.max(1, ((s.to - s.from) / 60) * HOUR_H);
            const x = AXIS_W + s.day * COL_W + 6;
            return (
              <g key={i} data-testid="week-segment" data-day={WEEKDAYS[s.day]} data-shift={s.shift} data-split={s.split ?? "none"} data-from={s.from} data-to={s.to}>
                <rect x={x} y={y} width={COL_W - 12} height={h} rx={3} fill={PALETTE[idx % PALETTE.length]} opacity={0.85} />
                {h >= 13 ? (
                  <text x={x + 5} y={y + 11} className="mfg-week-label">
                    {s.shift}
                    {s.split === "start" || s.split === "both" ? " ↓" : ""}
                    {s.split === "end" ? " (cont.)" : ""}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
      {preview.data ? (
        <ul className="mfg-plain-list row wrap small" data-testid="shift-week-totals" aria-label="Working time per day">
          {WEEKDAYS.map((d: Weekday) => (
            <li key={d} className="chip">
              {WEEKDAY_LABEL[d]}: {fmtHours(preview.data?.minutes_per_day[d] ?? 0)}
            </li>
          ))}
          <li className="chip">
            <strong>Week: {fmtHours(preview.data.total_minutes)}</strong>
          </li>
        </ul>
      ) : null}
      <p className="faint small" style={{ margin: 0 }}>
        Breaks are shown as gaps. A shift belongs to the day it starts; night shifts continue at the top of the next day (↓).
      </p>
    </div>
  );
}

function hhmm(m: number): string {
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

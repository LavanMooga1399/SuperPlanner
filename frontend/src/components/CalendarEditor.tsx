import { useEffect, useState } from "react";
import { WEEKDAYS, type Calendar, type TimeWindow, type Weekday } from "../api/types";
import { DEFAULT_WORK_WEEK, hhmmToMin } from "../lib/planEdit";
import { msToIso } from "../lib/time";
import { Icon } from "./Icon";
import { PlanDateTimeInput } from "./Inputs";

const DAY_LABEL: Record<Weekday, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$|^24:00$/;

function TimeText({ value, onChange, label }: { value: string; onChange(v: string): void; label: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const ok = HHMM_RE.test(text);
  return (
    <input
      className="input sm time-input"
      value={text}
      aria-label={label}
      aria-invalid={!ok}
      placeholder="HH:MM"
      inputMode="numeric"
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        let v = text.trim();
        if (/^\d{1,2}$/.test(v)) v = `${v.padStart(2, "0")}:00`;
        if (/^\d:\d{2}$/.test(v)) v = `0${v}`;
        if (HHMM_RE.test(v)) {
          setText(v);
          if (v !== value) onChange(v);
        } else setText(value);
      }}
    />
  );
}

function DayStrip({ windows }: { windows: TimeWindow[] }) {
  return (
    <div className="cal-strip" aria-hidden>
      {windows.map(([a, b], i) => {
        const s = hhmmToMin(a);
        const e = hhmmToMin(b);
        if (!(e > s)) return null;
        return <span key={i} style={{ left: `${(s / 1440) * 100}%`, width: `${((e - s) / 1440) * 100}%` }} />;
      })}
    </div>
  );
}

export function CalendarEditor({
  value,
  onChange,
  offsetMin,
  resourceName,
}: {
  value: Calendar | null;
  onChange(v: Calendar | null): void;
  offsetMin: number;
  resourceName: string;
}) {
  const always = value === null;
  const weekly = value?.weekly ?? null;
  const blocked = value?.blocked ?? [];

  const setWeekly = (w: Calendar["weekly"]) => onChange({ weekly: w, blocked });
  const setDay = (day: Weekday, wins: TimeWindow[]) => {
    const next = { ...(weekly ?? {}) };
    if (wins.length) next[day] = wins;
    else delete next[day];
    setWeekly(next);
  };

  return (
    <div className="col">
      <label className="switch">
        <input
          type="checkbox"
          checked={always}
          onChange={(e) => onChange(e.target.checked ? null : DEFAULT_WORK_WEEK)}
        />
        <span>Always available (24/7, no closed times)</span>
      </label>
      {!always ? (
        <>
          <label className="checkbox">
            <input type="checkbox" checked={weekly === null} onChange={(e) => setWeekly(e.target.checked ? null : DEFAULT_WORK_WEEK.weekly)} />
            Open around the clock, only the blocked periods below are closed
          </label>
          {weekly !== null ? (
            <div className="cal-grid" role="group" aria-label={`Weekly opening hours of ${resourceName}`}>
              {WEEKDAYS.map((day) => {
                const wins = weekly[day] ?? [];
                return (
                  <div key={day} style={{ display: "contents" }}>
                    <div className="cal-day">{DAY_LABEL[day]}</div>
                    <div className="col" style={{ gap: 4 }}>
                      <DayStrip windows={wins} />
                      <div className="cal-windows">
                        {wins.length === 0 ? <span className="small faint">Closed</span> : null}
                        {wins.map(([a, b], i) => {
                          const bad = !(hhmmToMin(b) > hhmmToMin(a)) || a === "24:00";
                          return (
                            <span key={i} className="row" style={{ gap: 4 }}>
                              <TimeText value={a} label={`${DAY_LABEL[day]} window ${i + 1} opens`} onChange={(v) => setDay(day, wins.map((w, k) => (k === i ? [v, w[1]] : w)))} />
                              <span className="faint">–</span>
                              <TimeText value={b} label={`${DAY_LABEL[day]} window ${i + 1} closes`} onChange={(v) => setDay(day, wins.map((w, k) => (k === i ? [w[0], v] : w)))} />
                              {bad ? <Icon name="alert" title="Opening must be before closing" style={{ color: "var(--danger)" }} /> : null}
                              <button type="button" className="btn ghost sm icon" aria-label={`Remove ${DAY_LABEL[day]} window ${i + 1}`} onClick={() => setDay(day, wins.filter((_, k) => k !== i))}>
                                <Icon name="x" />
                              </button>
                            </span>
                          );
                        })}
                        <button
                          type="button"
                          className="btn ghost sm"
                          aria-label={`Add opening window on ${DAY_LABEL[day]}`}
                          onClick={() => {
                            const last = wins[wins.length - 1];
                            const startMin = last ? Math.min(hhmmToMin(last[1]), 1380) : 540;
                            const fmt = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
                            setDay(day, [...wins, [fmt(startMin), fmt(Math.min(1440, startMin + 240))]]);
                          }}
                        >
                          <Icon name="plus" /> Window
                        </button>
                        {day === "mon" && wins.length ? (
                          <button
                            type="button"
                            className="btn ghost sm"
                            onClick={() => setWeekly({ ...weekly, tue: wins, wed: wins, thu: wins, fri: wins })}
                          >
                            <Icon name="copy" /> Copy to Tue–Fri
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
          <div className="small faint">Times are wall-clock times in the plan’s UTC offset. Split night shifts at midnight (22:00–24:00 and 00:00–06:00).</div>

          <h3 className="mt">Blocked periods</h3>
          {blocked.length === 0 ? <div className="small muted">No maintenance, holidays or other closures.</div> : null}
          {blocked.map((b, i) => {
            const bad = new Date(b.end).getTime() <= new Date(b.start).getTime();
            return (
              <div className="row wrap" key={i}>
                <PlanDateTimeInput value={b.start} offsetMin={offsetMin} allowEmpty={false} label={`Blocked period ${i + 1} start`} onChange={(v) => v && onChange({ weekly, blocked: blocked.map((x, k) => (k === i ? { ...x, start: v } : x)) })} />
                <span className="faint">to</span>
                <PlanDateTimeInput value={b.end} offsetMin={offsetMin} allowEmpty={false} label={`Blocked period ${i + 1} end`} onChange={(v) => v && onChange({ weekly, blocked: blocked.map((x, k) => (k === i ? { ...x, end: v } : x)) })} />
                <input
                  className="input sm"
                  style={{ width: 160 }}
                  placeholder="Reason"
                  aria-label={`Blocked period ${i + 1} reason`}
                  defaultValue={b.reason}
                  key={b.reason}
                  onBlur={(e) => e.target.value !== b.reason && onChange({ weekly, blocked: blocked.map((x, k) => (k === i ? { ...x, reason: e.target.value } : x)) })}
                />
                {bad ? <span className="badge danger"><Icon name="alert" /> End must be after start</span> : null}
                <button type="button" className="btn ghost sm icon" aria-label={`Remove blocked period ${i + 1}`} onClick={() => onChange({ weekly, blocked: blocked.filter((_, k) => k !== i) })}>
                  <Icon name="x" />
                </button>
              </div>
            );
          })}
          <div>
            <button
              type="button"
              className="btn sm"
              onClick={() => {
                const now = Date.now();
                const startMs = Math.ceil(now / 3600000) * 3600000;
                onChange({ weekly, blocked: [...blocked, { start: msToIso(startMs, offsetMin), end: msToIso(startMs + 4 * 3600000, offsetMin), reason: "" }] });
              }}
            >
              <Icon name="plus" /> Add blocked period
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}

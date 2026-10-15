import { useState } from "react";
import type { Comparison, Metrics, Problem, ScheduleSummary, TaskDelta } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDelta, fmtDuration, fmtMoney } from "../lib/time";
import { avgUtilization } from "./KpiCards";
import { Icon } from "./Icon";
import { methodLabel } from "./RunProgress";
import { StatusBadge } from "./StatusBadge";

function DeltaCell({ v, kind, currency }: { v: number | null; kind: "min" | "count" | "money"; currency: string }) {
  if (v === null || v === undefined) return <span className="faint">-</span>;
  if (v === 0) return <span className="faint">no change</span>;
  const better = v < 0;
  const text = kind === "min" ? fmtDelta(v) : kind === "money" ? (v > 0 ? "+" : "-") + fmtMoney(Math.abs(v), currency) : (v > 0 ? "+" : "") + v;
  return (
    <span className={better ? "delta-neg" : "delta-pos"}>
      <Icon name={better ? "check" : "alert"} size={12} /> {text} <span className="sr-only">{better ? "(better)" : "(worse)"}</span>
    </span>
  );
}

function MiniGantt({ deltas, side, title, names }: { deltas: TaskDelta[]; side: "a" | "b"; title: string; names: Map<string, string> }) {
  const rows = deltas.filter((d) => (side === "a" ? d.in_a : d.in_b));
  let lo = Infinity;
  let hi = -Infinity;
  for (const d of deltas) {
    for (const v of [d.start_a, d.start_b, d.end_a, d.end_b]) if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  }
  if (!rows.length || !Number.isFinite(lo)) return null;
  const W = 900;
  const rowH = 14;
  const H = rows.length * rowH + 4;
  const sx = (m: number) => ((m - lo) / Math.max(1, hi - lo)) * (W - 4) + 2;
  return (
    <div>
      <div className="small muted" style={{ marginBottom: 4 }}>{title}</div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={Math.min(H, 360)} preserveAspectRatio="none" role="img" aria-label={`${title}: ${rows.length} bars`} style={{ background: "var(--surface-2)", borderRadius: 6 }}>
        {rows.map((d, i) => {
          const s = side === "a" ? d.start_a! : d.start_b!;
          const e = side === "a" ? d.end_a! : d.end_b!;
          const changed = d.start_delta_minutes !== 0 || d.end_delta_minutes !== 0 || d.resource_changed || !d.in_a || !d.in_b;
          return (
            <rect key={d.task_id} x={sx(s)} y={2 + i * rowH} width={Math.max(2, sx(e) - sx(s))} height={rowH - 4} rx={2} fill={changed ? "var(--warn)" : "var(--bar)"} opacity={changed ? 1 : 0.7}>
              <title>{`${names.get(d.task_id) ?? d.name}${changed ? " (changed)" : ""}`}</title>
            </rect>
          );
        })}
      </svg>
    </div>
  );
}

export function ScheduleComparison({ cmp, draft, terms }: { cmp: Comparison; draft: Problem; terms: Terms }) {
  const [onlyChanged, setOnlyChanged] = useState(true);
  const names = new Map(draft.tasks.map((t) => [t.id, t.name]));
  const resName = (id: string) => draft.resources.find((r) => r.id === id)?.name ?? id;
  const cur = draft.currency;
  const a: Metrics | null = cmp.a.metrics;
  const b: Metrics | null = cmp.b.metrics;
  const md = cmp.metric_deltas;
  const ua = avgUtilization(a);
  const ub = avgUtilization(b);
  const head = (s: ScheduleSummary, letter: string) => (
    <div className="col" style={{ gap: 4 }}>
      <div className="row wrap">
        <span className="chip">{letter}</span>
        <strong>{s.label}</strong>
      </div>
      <div className="row wrap">
        <StatusBadge kind={s.status} />
        <StatusBadge kind={s.feasibility} />
      </div>
      <span className="small muted" title={s.solver}>{methodLabel(s.solver)} · plan v{s.base_problem_version}</span>
    </div>
  );
  const rows: Array<{ label: string; a: string; b: string; d: JSX.Element }> = [
    { label: "Duration", a: a ? fmtDuration(a.makespan_minutes) : "-", b: b ? fmtDuration(b.makespan_minutes) : "-", d: <DeltaCell v={md.makespan_minutes} kind="min" currency={cur} /> },
    { label: `Late ${terms.tasksL}`, a: a ? String(a.late_tasks) : "-", b: b ? String(b.late_tasks) : "-", d: <DeltaCell v={md.late_tasks} kind="count" currency={cur} /> },
    { label: "Total lateness", a: a ? fmtDuration(a.total_tardiness_minutes) : "-", b: b ? fmtDuration(b.total_tardiness_minutes) : "-", d: <DeltaCell v={md.total_tardiness_minutes} kind="min" currency={cur} /> },
    { label: "Weighted lateness", a: a ? fmtDuration(a.weighted_tardiness) : "-", b: b ? fmtDuration(b.weighted_tardiness) : "-", d: <DeltaCell v={md.weighted_tardiness} kind="min" currency={cur} /> },
    { label: "Cost", a: a ? fmtMoney(a.cost, cur) : "-", b: b ? fmtMoney(b.cost, cur) : "-", d: <DeltaCell v={md.cost} kind="money" currency={cur} /> },
    { label: `Avg. ${terms.resourceL} use`, a: ua === null ? "-" : `${Math.round(ua * 100)}%`, b: ub === null ? "-" : `${Math.round(ub * 100)}%`, d: <span className="faint">-</span> },
  ];
  const tasks = onlyChanged
    ? cmp.task_deltas.filter((d) => d.start_delta_minutes !== 0 || d.end_delta_minutes !== 0 || d.resource_changed || !d.in_a || !d.in_b)
    : cmp.task_deltas;

  return (
    <div className="col gap-lg">
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: "22%" }}>Measure</th>
              <th>{head(cmp.a, "A")}</th>
              <th>{head(cmp.b, "B")}</th>
              <th>Change (B - A)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <td className="muted">{r.label}</td>
                <td className="num" style={{ textAlign: "left" }}>{r.a}</td>
                <td className="num" style={{ textAlign: "left" }}>{r.b}</td>
                <td>{r.d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card card-body col">
        <MiniGantt deltas={cmp.task_deltas} side="a" title={`A: ${cmp.a.label}`} names={names} />
        <MiniGantt deltas={cmp.task_deltas} side="b" title={`B: ${cmp.b.label}`} names={names} />
        <div className="legend">
          <span className="legend-item"><span className="swatch" style={{ background: "var(--bar)", opacity: 0.7 }} /> Unchanged</span>
          <span className="legend-item"><span className="swatch" style={{ background: "var(--warn)" }} /> Moved, changed {terms.resourceL} or only in one</span>
        </div>
      </div>

      <div className="col">
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <h3>{cmp.changed_task_count} of {cmp.task_deltas.length} {terms.tasksL} changed</h3>
          <div className="grow" />
          <label className="checkbox small">
            <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} /> Only changed
          </label>
        </div>
        <div className="table-wrap" style={{ maxHeight: "60vh" }}>
          <table className="table" data-testid="compare-table">
            <thead>
              <tr>
                <th>{terms.task}</th>
                <th>Start shift</th>
                <th>End shift</th>
                <th>{terms.resources} A</th>
                <th>{terms.resources} B</th>
              </tr>
            </thead>
            <tbody>
              {tasks.length === 0 ? (
                <tr><td colSpan={5} className="muted">No differences.</td></tr>
              ) : null}
              {tasks.map((d) => (
                <tr key={d.task_id} data-testid={`compare-row-${d.task_id}`}>
                  <td>
                    {names.get(d.task_id) ?? d.name}
                    {!d.in_a ? <span className="badge accent" style={{ marginLeft: 6 }}>only in B</span> : null}
                    {!d.in_b ? <span className="badge warn" style={{ marginLeft: 6 }}>only in A</span> : null}
                  </td>
                  <td><DeltaCell v={d.start_delta_minutes} kind="min" currency={cur} /></td>
                  <td><DeltaCell v={d.end_delta_minutes} kind="min" currency={cur} /></td>
                  <td className="small">{d.resources_a.map(resName).join(", ") || <span className="faint">-</span>}</td>
                  <td className="small">
                    {d.resources_b.map(resName).join(", ") || <span className="faint">-</span>}
                    {d.resource_changed ? <span className="badge warn" style={{ marginLeft: 6 }}><Icon name="refresh" /> changed</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

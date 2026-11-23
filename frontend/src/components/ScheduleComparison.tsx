import { useState } from "react";
import type { Comparison, Metrics, Problem, ScheduleSummary, TaskDelta } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDelta, fmtDuration, fmtMoney } from "../lib/time";
import { avgUtilization } from "./KpiCards";
import { Icon } from "./Icon";
import { methodLabel } from "./RunProgress";
import { StatusBadge } from "./StatusBadge";
import { VirtualTable } from "../mfg/components/VirtualTable";
import { t, t as tr } from "../lib/i18n";

function DeltaCell({ v, kind, currency }: { v: number | null; kind: "min" | "count" | "money"; currency: string }) {
  if (v === null || v === undefined) return <span className="faint">-</span>;
  if (v === 0) return <span className="faint">{tr("studio.scheduleComparison.text.noChange")}</span>;
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
      <span className="small muted" title={s.solver}>{tr("studio.scheduleComparison.text.planV", { solver: methodLabel(s.solver), baseproblemversion: s.base_problem_version })}</span>
    </div>
  );
  const rows: Array<{ label: string; a: string; b: string; d: JSX.Element }> = [
    { label: tr("studio.scheduleComparison.str.duration"), a: a ? fmtDuration(a.makespan_minutes) : "-", b: b ? fmtDuration(b.makespan_minutes) : "-", d: <DeltaCell v={md.makespan_minutes} kind="min" currency={cur} /> },
    { label: tr("studio.scheduleComparison.tpl.late", { tasksL: terms.tasksL }), a: a ? String(a.late_tasks) : "-", b: b ? String(b.late_tasks) : "-", d: <DeltaCell v={md.late_tasks} kind="count" currency={cur} /> },
    { label: tr("studio.scheduleComparison.str.totalLateness"), a: a ? fmtDuration(a.total_tardiness_minutes) : "-", b: b ? fmtDuration(b.total_tardiness_minutes) : "-", d: <DeltaCell v={md.total_tardiness_minutes} kind="min" currency={cur} /> },
    { label: tr("studio.scheduleComparison.str.weightedLateness"), a: a ? fmtDuration(a.weighted_tardiness) : "-", b: b ? fmtDuration(b.weighted_tardiness) : "-", d: <DeltaCell v={md.weighted_tardiness} kind="min" currency={cur} /> },
    { label: tr("studio.scheduleComparison.str.cost"), a: a ? fmtMoney(a.cost, cur) : "-", b: b ? fmtMoney(b.cost, cur) : "-", d: <DeltaCell v={md.cost} kind="money" currency={cur} /> },
    { label: tr("studio.scheduleComparison.tpl.avgUse", { resourceL: terms.resourceL }), a: ua === null ? "-" : `${Math.round(ua * 100)}%`, b: ub === null ? "-" : `${Math.round(ub * 100)}%`, d: <span className="faint">-</span> },
  ];
  const tasks = onlyChanged
    ? cmp.task_deltas.filter((d) => d.start_delta_minutes !== 0 || d.end_delta_minutes !== 0 || d.resource_changed || !d.in_a || !d.in_b)
    : cmp.task_deltas;

  return (
    <div className="col gap-lg">
      <div className="card" style={{ overflowX: "auto", position: "relative" }}>
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: "22%" }}>{t("studio.scheduleComparison.head.measure")}</th>
              <th>{head(cmp.a, "A")}</th>
              <th>{head(cmp.b, "B")}</th>
              <th>{t("studio.scheduleComparison.head.changeBA")}</th>
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
          <span className="legend-item"><span className="swatch" style={{ background: "var(--bar)", opacity: 0.7 }} />{" "}{tr("studio.scheduleComparison.text.unchanged")}</span>
          <span className="legend-item"><span className="swatch" style={{ background: "var(--warn)" }} />{" "}{tr("studio.scheduleComparison.text.movedChangedOrOnlyIn", { resourceL: terms.resourceL })}</span>
        </div>
      </div>

      <div className="col">
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <h3>{tr("common.nOfM", { n: cmp.changed_task_count, m: cmp.task_deltas.length })} {terms.tasksL} changed</h3>
          <div className="grow" />
          <label className="checkbox small">
            <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />{" "}{tr("studio.scheduleComparison.text.onlyChanged")}
          </label>
        </div>
        <VirtualTable
          rows={tasks}
          columns={[
            {
              key: "task",
              header: terms.task,
              width: "minmax(200px, 2fr)",
              sortValue: (d) => names.get(d.task_id) ?? d.name,
              exportValue: (d) => names.get(d.task_id) ?? d.name,
              render: (d) => (
                <span className="row" style={{ gap: 6, flexWrap: "nowrap", minWidth: 0 }}>
                  <span className="mfg-ellipsis">{names.get(d.task_id) ?? d.name}</span>
                  {!d.in_a ? <span className="badge accent">{tr("studio.scheduleComparison.text.onlyInB")}</span> : null}
                  {!d.in_b ? <span className="badge warn">{tr("studio.scheduleComparison.text.onlyInA")}</span> : null}
                </span>
              ),
            },
            { key: "start", header: "Start shift", width: "120px", sortValue: (d) => d.start_delta_minutes, exportValue: (d) => d.start_delta_minutes, render: (d) => <DeltaCell v={d.start_delta_minutes} kind="min" currency={cur} /> },
            { key: "end", header: "End shift", width: "120px", sortValue: (d) => d.end_delta_minutes, exportValue: (d) => d.end_delta_minutes, render: (d) => <DeltaCell v={d.end_delta_minutes} kind="min" currency={cur} /> },
            { key: "ra", header: `${terms.resources} A`, width: "minmax(140px, 1fr)", render: (d) => d.resources_a.map(resName).join(", ") || <span className="faint">-</span> },
            {
              key: "rb",
              header: `${terms.resources} B`,
              width: "minmax(160px, 1fr)",
              exportValue: (d) => d.resources_b.map(resName).join(", "),
              render: (d) => (
                <span className="row" style={{ gap: 6, flexWrap: "nowrap", minWidth: 0 }}>
                  <span className="mfg-ellipsis">{d.resources_b.map(resName).join(", ") || <span className="faint">-</span>}</span>
                  {d.resource_changed ? (
                    <span className="badge warn">
                      <Icon name="refresh" /> {t("studio.scheduleComparison.btn.changed")}
                    </span>
                  ) : null}
                </span>
              ),
            },
          ]}
          rowKey={(d) => d.task_id}
          label={t("studio.scheduleComparison.label.differencesPerTask")}
          testId="compare-table"
          height="60vh"
          exportName="schedule-comparison"
          rowExtras={(d) => ({ testId: `compare-row-${d.task_id}` })}
          empty={t("studio.scheduleComparison.empty.noDifferences")}
          card={{ title: "task", fields: ["start", "end", "rb"] }}
        />
      </div>
    </div>
  );
}

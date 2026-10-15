import type { Metrics, Schedule } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, fmtMinute, fmtMoney } from "../lib/time";

export function avgUtilization(m: Metrics | null): number | null {
  if (!m) return null;
  const v = Object.values(m.utilization);
  if (!v.length) return null;
  return v.reduce((a, b) => a + b, 0) / v.length;
}

export function KpiCards({ schedule, terms, currency }: { schedule: Schedule; terms: Terms; currency: string }) {
  const m = schedule.metrics;
  const util = avgUtilization(m);
  const cards = [
    {
      label: "Completion",
      value: m ? fmtMinute(m.makespan_minutes, schedule.horizon_start) : "-",
      sub: m ? `${fmtDuration(m.makespan_minutes)} after the plan start` : "",
    },
    {
      label: `Late ${terms.tasksL}`,
      value: m ? String(m.late_tasks + m.hard_deadline_misses) : "-",
      sub: !m
        ? ""
        : m.hard_deadline_misses
          ? `${m.hard_deadline_misses} hard ${terms.deadlineL}${m.hard_deadline_misses === 1 ? "" : "s"} missed`
          : m.total_tardiness_minutes
            ? `${fmtDuration(m.total_tardiness_minutes)} late in total`
            : `all ${terms.deadlineL}s met`,
      tone: m && m.late_tasks + m.hard_deadline_misses > 0 ? "var(--danger)" : undefined,
    },
    { label: "Cost", value: m ? fmtMoney(m.cost, currency) : "-", sub: "" },
    {
      label: `Avg. ${terms.resourceL} use`,
      value: util === null ? "-" : `${Math.round(util * 100)}%`,
      sub: "while the plan runs",
    },
    {
      label: `${terms.tasks} scheduled`,
      value: m ? `${m.scheduled_tasks} / ${m.total_tasks}` : "-",
      sub: schedule.hard_violation_count ? `${schedule.hard_violation_count} rule violation${schedule.hard_violation_count === 1 ? "" : "s"}` : "no rule violations",
      tone: schedule.hard_violation_count ? "var(--danger)" : undefined,
    },
  ];
  return (
    <div className="kpis" data-testid="kpi-cards">
      {cards.map((c) => (
        <div className="card kpi" key={c.label}>
          <div className="kpi-label">{c.label}</div>
          <div className="kpi-value" style={c.tone ? { color: c.tone } : undefined}>
            {c.value}
          </div>
          {c.sub ? <div className="kpi-sub">{c.sub}</div> : null}
        </div>
      ))}
    </div>
  );
}

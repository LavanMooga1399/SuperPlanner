import type { ReactNode } from "react";
import type { Metrics, Schedule } from "../api/types";
import type { GlossaryKey } from "../lib/glossary";
import type { Terms } from "../lib/terms";
import { fmtDuration, fmtMinute, fmtMoney } from "../lib/time";
import { Term } from "./Term";
import { t } from "../lib/i18n";

export function avgUtilization(m: Metrics | null): number | null {
  if (!m) return null;
  const v = Object.values(m.utilization);
  if (!v.length) return null;
  return v.reduce((a, b) => a + b, 0) / v.length;
}

export function KpiCards({ schedule, terms, currency }: { schedule: Schedule; terms: Terms; currency: string }) {
  const m = schedule.metrics;
  const util = avgUtilization(m);
  const cards: { label: string; term?: GlossaryKey; value: ReactNode; sub: string; tone?: string }[] = [
    {
      label: t("studio.kpiCards.str.completion"),
      term: "makespan",
      value: m ? fmtMinute(m.makespan_minutes, schedule.horizon_start) : "-",
      sub: m ? t("studio.kpiCards.tpl.afterThePlanStart", { makespanminutes: fmtDuration(m.makespan_minutes) }) : "",
    },
    {
      label: t("studio.kpiCards.tpl.late", { tasksL: terms.tasksL }),
      value: m ? String(m.late_tasks + m.hard_deadline_misses) : "-",
      sub: !m
        ? ""
        : m.hard_deadline_misses
          ? t("studio.kpiCards.tpl.hardMissed", { harddeadlinemisses: m.hard_deadline_misses, deadlineL: terms.deadlineL, v: m.hard_deadline_misses === 1 ? "" : "s" })
          : m.total_tardiness_minutes
            ? t("studio.kpiCards.tpl.lateInTotal", { totaltardinessminutes: fmtDuration(m.total_tardiness_minutes) })
            : t("studio.kpiCards.tpl.allSMet", { deadlineL: terms.deadlineL }),
      tone: m && m.late_tasks + m.hard_deadline_misses > 0 ? "var(--danger)" : undefined,
    },
    { label: t("studio.kpiCards.str.cost"), value: m ? fmtMoney(m.cost, currency) : "-", sub: "" },
    {
      label: t("studio.kpiCards.tpl.avgUse", { resourceL: terms.resourceL }),
      value: util === null ? "-" : `${Math.round(util * 100)}%`,
      sub: t("studio.kpiCards.str.whileThePlanRuns"),
    },
    {
      label: `${terms.tasks} scheduled`,
      value: m ? `${m.scheduled_tasks} / ${m.total_tasks}` : "-",
      sub: schedule.hard_violation_count ? t("studio.kpiCards.tpl.ruleViolation", { hardviolationcount: schedule.hard_violation_count, v: schedule.hard_violation_count === 1 ? "" : "s" }) : t("studio.kpiCards.str.noRuleViolations"),
      tone: schedule.hard_violation_count ? "var(--danger)" : undefined,
    },
  ];
  return (
    <div className="kpis" data-testid="kpi-cards">
      {cards.map((c) => (
        <div className="card kpi" key={c.label}>
          <div className="kpi-label">
            {c.label}
            {c.term ? <Term k={c.term} bare /> : null}
          </div>
          <div className="kpi-value" style={c.tone ? { color: c.tone } : undefined}>
            {c.value}
          </div>
          {c.sub ? <div className="kpi-sub">{c.sub}</div> : null}
        </div>
      ))}
    </div>
  );
}

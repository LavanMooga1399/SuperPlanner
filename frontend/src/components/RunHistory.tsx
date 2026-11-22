import { Link } from "react-router";
import type { SolverRun } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, fmtLocal, fmtMoney, fmtSeconds } from "../lib/time";
import { Icon } from "./Icon";
import { methodLabel } from "./RunProgress";
import { StatusBadge } from "./StatusBadge";
import { DataTable } from "../mfg/components/DataTable";
import { t } from "../lib/i18n";

export function RunHistory({
  runs,
  currentRunId,
  terms,
  currency,
  onRefresh,
}: {
  runs: SolverRun[];
  currentRunId: string | null;
  terms: Terms;
  currency: string;
  onRefresh(): void;
}) {
  return (
    <div className="card card-table" data-testid="run-history">
      <div className="card-header">
        <h3>{t("studio.runHistory.head.runHistory")}</h3>
        <button className="btn ghost sm" onClick={onRefresh} aria-label={t("studio.runHistory.aria.refreshRunHistory")}>
          <Icon name="refresh" />
        </button>
      </div>
      <DataTable
        rows={runs}
        columns={[
          {
            key: "started",
            header: "Started",
            width: "minmax(170px, 1.2fr)",
            sortValue: (r) => r.created_at,
            exportValue: (r) => r.created_at,
            render: (r) => (
              <span>
                {fmtLocal(r.created_at)}
                {r.source_schedule_id ? <span className="chip" style={{ marginLeft: 6 }}>Replan</span> : null}
              </span>
            ),
          },
          { key: "status", header: "Status", width: "120px", sortValue: (r) => r.status, exportValue: (r) => r.status, render: (r) => <StatusBadge kind={r.status} /> },
          { key: "result", header: "Result", width: "130px", sortValue: (r) => r.feasibility ?? "", exportValue: (r) => r.feasibility ?? "", render: (r) => (r.feasibility ? <StatusBadge kind={r.feasibility} /> : <span className="faint">-</span>) },
          { key: "method", header: "Method", width: "minmax(140px, 1fr)", render: (r) => (r.selection ? r.selection.used.map(methodLabel).join(" → ") : String(r.request?.strategy ?? "auto")) },
          { key: "duration", header: "Duration", width: "100px", align: "right", sortValue: (r) => r.objectives?.makespan_minutes ?? null, render: (r) => (r.objectives ? fmtDuration(r.objectives.makespan_minutes) : "-") },
          { key: "cost", header: "Cost", width: "110px", align: "right", sortValue: (r) => r.objectives?.cost ?? null, render: (r) => (r.objectives ? fmtMoney(r.objectives.cost, currency) : "-") },
          { key: "took", header: "Took", width: "80px", align: "right", sortValue: (r) => r.elapsed_seconds ?? null, render: (r) => fmtSeconds(r.elapsed_seconds) },
          {
            key: "actions",
            header: <span className="sr-only">Links</span>,
            label: "Links",
            width: "170px",
            exportValue: () => "",
            render: (r) => (
              <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                <Link className="btn ghost sm" to={`?run=${encodeURIComponent(r.id)}`}>
                  {t("studio.runHistory.btn.details")}
                </Link>
                {r.primary_schedule_id ? (
                  <Link className="btn ghost sm" to={`../schedule?id=${encodeURIComponent(r.primary_schedule_id)}`}>
                    {terms.schedule}
                  </Link>
                ) : null}
              </span>
            ),
          },
        ]}
        rowKey={(r) => r.id}
        label={t("studio.runHistory.label.runHistory")}
        tableId="studio-run-history"
        exportName="run-history"
        rowExtras={(r) => ({ testId: `run-row-${r.id}`, className: r.id === currentRunId ? "mfg-selected" : undefined })}
        empty={t("studio.runHistory.empty.noRunsYetEachTime")}
        card={{ title: "started", status: "status", actions: "actions", fields: ["result", "duration", "cost"] }}
      />
    </div>
  );
}

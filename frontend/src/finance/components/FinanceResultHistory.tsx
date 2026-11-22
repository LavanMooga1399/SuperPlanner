import { Link } from "react-router";
import { ErrorBanner, Loading } from "../../components/Banner";
import { useAsync } from "../../lib/useAsync";
import { fmtLocal } from "../../lib/time";
import { listFinanceResults } from "../api/client";
import { formatMoney } from "../lib/money";
import { StatusPill } from "./StatusPill";
import { DataTable } from "../../mfg/components/DataTable";

export function FinanceResultHistory({ planId, currentId, currency, locale, refreshKey }: { planId: string; currentId: string | null; currency: string; locale: string; refreshKey?: unknown }) {
  const list = useAsync((s) => listFinanceResults(planId, undefined, s), [planId, refreshKey]);
  return (
    <section className="card card-table" aria-labelledby="fin-history-title" data-testid="fin-result-history">
      <div className="card-header">
        <h2 id="fin-history-title">Earlier results</h2>
      </div>
      {list.loading && !list.data ? (
        <Loading label="Loading results…" />
      ) : list.error ? (
        <div className="card-body"><ErrorBanner error={list.error} onRetry={list.reload} /></div>
      ) : (
        <DataTable
          rows={list.data?.items ?? []}
          columns={[
            {
              key: "made",
              header: "Made",
              width: "minmax(170px, 1.2fr)",
              sortValue: (r) => r.created_at,
              exportValue: (r) => r.created_at,
              render: (r) => (
                <span>
                  {fmtLocal(r.created_at)}
                  {r.id === currentId ? <span className="chip" style={{ marginLeft: 6 }}>shown</span> : null}
                </span>
              ),
            },
            { key: "kind", header: "Kind", width: "minmax(140px, 1fr)", render: (r) => (r.kind === "what_if" ? `What-if${r.label ? `: ${r.label}` : ""}` : `Plan v${r.base_plan_version}`) },
            { key: "status", header: "Status", width: "130px", sortValue: (r) => r.feasibility, exportValue: (r) => r.feasibility, render: (r) => <StatusPill kind={r.feasibility} /> },
            { key: "track", header: "On track", width: "90px", align: "right", sortValue: (r) => r.goals_on_track, render: (r) => `${r.goals_on_track} / ${r.goals_total}` },
            { key: "monthly", header: "Monthly now", width: "130px", align: "right", sortValue: (r) => r.monthly_contribution_now, render: (r) => formatMoney(r.monthly_contribution_now, currency, locale) },
            {
              key: "actions",
              header: <span className="sr-only">Actions</span>,
              label: "Actions",
              width: "160px",
              align: "right",
              exportValue: () => "",
              render: (r) => (
                <span className="row" style={{ gap: 4, flexWrap: "nowrap", justifyContent: "flex-end" }}>
                  <Link className="btn sm ghost" to={`/finance/${planId}/results?result=${r.id}`}>
                    Open
                  </Link>
                  {currentId && r.id !== currentId ? (
                    <Link className="btn sm ghost" to={`/finance/${planId}/compare?a=${currentId}&b=${r.id}`}>
                      Compare
                    </Link>
                  ) : null}
                </span>
              ),
            },
          ]}
          rowKey={(r) => r.id}
          label="Results of this plan, newest first"
          tableId="finance-result-history"
          exportName="finance-results"
          rowExtras={(r) => ({ className: r.id === currentId ? "mfg-selected" : undefined })}
          empty="No results yet."
          card={{ title: "made", status: "status", actions: "actions", fields: ["kind", "track", "monthly"] }}
        />
      )}
    </section>
  );
}

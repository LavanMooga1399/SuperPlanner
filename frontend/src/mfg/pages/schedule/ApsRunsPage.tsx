/**
 * `/mfg/schedule` (M3 12): schedule runs with status, live progress (polled every 2 s while a run is queued or
 * running), KPIs and the published badge; "New schedule" form. Router state `{ prefill: ApsParams }` opens the
 * form prefilled (overtime tab "Re-run with these opened").
 */
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { listApsRuns } from "../../api/clientM3";
import type { ApsParams, ApsRunRecord } from "../../api/typesM3";
import { ApsProgress, ApsStatusChip, PolicyBadge, PublishedBadge } from "../../components/ApsBits";
import { MfgError } from "../../components/Feedback";
import { DataTable } from "../../components/DataTable";
import type { Column } from "../../components/VirtualTable";
import { PermissionGate } from "../../components/PermissionGate";
import { RunKindBadge } from "../../components/StatusM2";
import { fmtTimestamp } from "../../lib/format";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { usePolling } from "../../lib/usePolling";
import { useLoad } from "../../lib/useMfg";
import { ApsRunForm } from "./ApsRunForm";
import { PageHeader } from "../../../components/PageHeader";
import { t } from "../../../lib/i18n";

export function apsRunTitle(r: Pick<ApsRunRecord, "run_no" | "label">): string {
  return `${t("common.scheduleNo", { n: r.run_no })}${r.label ? ` · ${r.label}` : ""}`;
}

export function isActive(r: ApsRunRecord): boolean {
  return r.status === "queued" || r.status === "running";
}

export function ApsRunsPage() {
  const navigate = useNavigate();
  const loc = useLocation();
  const prefill = (loc.state as { prefill?: ApsParams } | null)?.prefill ?? null;
  const canRun = useCan("schedule_run");
  const clock = usePlantClock();
  const runs = useLoad((signal) => listApsRuns({ limit: 50, offset: 0 }, signal), []);
  const [form, setForm] = useState(Boolean(prefill));
  const items = runs.data?.items ?? [];
  usePolling(runs.reload, items.some(isActive));

  const columns: Column<ApsRunRecord>[] = [
    {
      key: "run",
      header: t("mfg.apsRunsPage.str.run"),
      width: "minmax(220px, 2fr)",
      sortValue: (r) => r.run_no,
      exportValue: (r) => apsRunTitle(r),
      render: (r) => (
        <span className="row" style={{ gap: 6, flexWrap: "nowrap", minWidth: 0 }}>
          <Link to={mfgPaths.apsRun(r.id)} className="mfg-ellipsis">
            {apsRunTitle(r)}
          </Link>
          {r.is_published ? <PublishedBadge /> : null}
          {r.parent_run_id ? <span className="faint small">{t("mfg.apsRunsPage.text.editedCopy")}</span> : null}
        </span>
      ),
    },
    { key: "kind", header: t("mfg.apsRunsPage.str.kind"), width: "100px", sortValue: (r) => r.kind, render: (r) => <RunKindBadge kind={r.kind} /> },
    { key: "status", header: t("mfg.apsRunsPage.str.status"), width: "150px", sortValue: (r) => r.status, exportValue: (r) => r.status, render: (r) => (isActive(r) ? <ApsProgress run={r} /> : <ApsStatusChip run={r} />) },
    { key: "policy", header: t("mfg.apsRunsPage.str.overtimePolicy"), width: "140px", render: (r) => <PolicyBadge policy={r.policy} /> },
    { key: "from", header: t("mfg.apsRunsPage.str.from"), width: "140px", sortValue: (r) => r.as_of, render: (r) => clock.dateTime(r.as_of) },
    { key: "late", header: t("mfg.apsRunsPage.str.lateOrders"), width: "100px", align: "right", sortValue: (r) => r.summary?.late_orders, render: (r) => (r.summary ? <span className={r.summary.late_orders ? "mfg-neg" : undefined}>{r.summary.late_orders}</span> : "") },
    { key: "tardiness", header: t("mfg.apsRunsPage.str.weightedLateness"), width: "140px", align: "right", sortValue: (r) => r.summary?.weighted_tardiness, render: (r) => (r.summary ? fmtDuration(r.summary.weighted_tardiness) || "0" : "") },
    { key: "overtime", header: t("mfg.apsRunsPage.str.overtimeUsed"), width: "120px", align: "right", sortValue: (r) => r.summary?.overtime_minutes, render: (r) => (r.summary ? fmtDuration(r.summary.overtime_minutes) || "none" : "") },
    { key: "finished", header: t("mfg.apsRunsPage.str.finished"), width: "minmax(200px, 1fr)", sortValue: (r) => r.finished_at, render: (r) => `${fmtTimestamp(r.finished_at)} ${r.actor.name}` },
  ];
  return (
    <div className="col gap-lg">
      <PageHeader
        title={t("mfg.apsRunsPage.title.productionSchedule")}
        description={t("mfg.apsRunsPage.desc.finitecapacityPlanOfEveryOperation")}
        actions={
          <>
            <Link className="btn" to={mfgPaths.simulations()} data-testid="aps-risk-link">
          <Icon name="graph" /> {t("mfg.apsRunsPage.btn.deliveryRisk")}
        </Link>
        <PermissionGate perm="schedule_run">
          <button type="button" className="btn primary" onClick={() => setForm(true)} disabled={form} data-testid="aps-new-run">
            <Icon name="play" /> {t("mfg.apsRunsPage.btn.newSchedule")}
          </button>
        </PermissionGate>
          </>
        }
      />
      {form ? (
        <ApsRunForm
          initial={prefill}
          onClose={() => setForm(false)}
          onDone={(r) => {
            setForm(false);
            navigate(mfgPaths.apsRun(r.id));
          }}
        />
      ) : null}
      <MfgError error={runs.error} onRetry={runs.reload} />
      {runs.data && items.length === 0 && !form ? (
        <Banner tone="info" title={t("mfg.apsRunsPage.title.noScheduleYet")} testId="aps-empty">
          {t("mfg.apsRunsPage.text.itUsesTheLatestMrp", { v: canRun ? t("mfg.apsRunsPage.str.createAScheduleToPlace") : t("mfg.apsRunsPage.str.nobodyHasScheduledThisPlant") })}
        </Banner>
      ) : null}
      {items.length || (runs.loading && !runs.data) ? (
        <DataTable
          rows={items}
          columns={columns}
          rowKey={(r) => r.id}
          label={t("mfg.apsRunsPage.label.scheduleRuns")}
          testId="aps-runs"
          loading={runs.loading && !runs.data}
          exportName="schedule-runs"
          rowExtras={(r) => ({ testId: "aps-run-row", data: { "run-no": r.run_no, status: r.status, published: r.is_published } })}
          card={{ title: "run", status: "status", fields: ["late", "overtime", "finished"] }}
        />
      ) : null}
    </div>
  );
}

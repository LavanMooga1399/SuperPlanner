/** `/mfg/mrp` (M2 14.2): MRP runs (kind, status, KPIs, stale, pinned) and the "Run MRP" form. */
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { listMrpRuns, updateMrpRun } from "../../api/clientM2";
import type { MrpRunRecord } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { DataTable } from "../../components/DataTable";
import type { Column } from "../../components/VirtualTable";
import { PermissionGate } from "../../components/PermissionGate";
import { RunKindBadge, RunStatusChip } from "../../components/StatusM2";
import { fmtDate, fmtTimestamp } from "../../lib/format";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { useLoad } from "../../lib/useMfg";
import { MrpRunForm } from "./MrpRunForm";
import { PageHeader } from "../../../components/PageHeader";
import { t } from "../../../lib/i18n";
import { LOCALE } from "../../../lib/locale";

export function runTitle(r: MrpRunRecord): string {
  return `${t("common.runNo", { n: r.run_no })}${r.label ? ` · ${r.label}` : ""}`;
}

export function MrpRunsPage() {
  const navigate = useNavigate();
  const canRun = useCan("mrp_run");
  const runs = useLoad((signal) => listMrpRuns({ limit: 50, offset: 0 }, signal), []);
  const [form, setForm] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const items = runs.data?.items ?? [];
  const latestLive = items.find((r) => r.kind === "live" && r.status === "completed");

  const pin = async (r: MrpRunRecord) => {
    setError(null);
    try {
      await updateMrpRun(r.id, { label: r.label, note: r.note, pinned: !r.pinned }, r.row_version);
      runs.reload();
    } catch (e) {
      setError(e);
    }
  };

  const columns: Column<MrpRunRecord>[] = [
    {
      key: "run",
      header: t("mfg.mrpRunsPage.str.run"),
      width: "minmax(250px, 2fr)",
      sortValue: (r) => r.run_no,
      exportValue: (r) => runTitle(r),
      render: (r) => (
        <span className="row" style={{ gap: 6, flexWrap: "nowrap", minWidth: 0 }}>
          <Link to={mfgPaths.run(r.id)} className="mfg-ellipsis" style={{ flex: "0 1 auto", minWidth: 48 }}>
            {runTitle(r)}
          </Link>
          {r.id === latestLive?.id ? (
            <span className="badge accent" title={t("mfg.mrpRunsPage.attr.plannedOrdersCanBeFirmed")}>
              <Icon name="star" /> {t("mfg.mrpRunsPage.btn.latest")}
            </span>
          ) : null}
          {r.pinned ? (
            <span className="badge info">
              <Icon name="lock" /> {t("mfg.mrpRunsPage.btn.kept")}
            </span>
          ) : null}
          {r.stale?.is_stale ? (
            <span className="badge warn" title={t("mfg.mrpRunsPage.attr.dataChangedAfterThisRun")}>
              <Icon name="clock" /> {t("mfg.mrpRunsPage.btn.outOfDate")}
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "kind", header: t("mfg.mrpRunsPage.str.kind"), width: "84px", sortValue: (r) => r.kind, render: (r) => <RunKindBadge kind={r.kind} /> },
    { key: "status", header: t("mfg.mrpRunsPage.str.status"), width: "116px", sortValue: (r) => r.status, render: (r) => <RunStatusChip status={r.status} /> },
    { key: "as_of", header: t("mfg.mrpRunsPage.str.asOf"), width: "100px", sortValue: (r) => r.as_of, render: (r) => fmtDate(r.as_of) },
    {
      key: "late",
      header: t("mfg.mrpRunsPage.str.lateDemand"),
      width: "100px",
      align: "right",
      sortValue: (r) => (r.summary ? r.summary.demand_late + r.summary.demand_past_due : null),
      render: (r) => {
        const s = r.summary;
        return s ? <span className={s.demand_late + s.demand_past_due ? "mfg-neg" : undefined}>{t("common.nOfM", { n: s.demand_late + s.demand_past_due, m: s.demand_lines })}</span> : "";
      },
    },
    { key: "short", header: t("mfg.mrpRunsPage.str.partsShort"), width: "88px", align: "right", sortValue: (r) => r.summary?.items_short, render: (r) => (r.summary ? r.summary.items_short.toLocaleString(LOCALE) : "") },
    {
      key: "planned",
      header: t("mfg.mrpRunsPage.str.plannedMakeBuy"),
      width: "132px",
      align: "right",
      sortValue: (r) => (r.summary ? r.summary.planned_make + r.summary.planned_buy : null),
      render: (r) => (r.summary ? `${r.summary.planned_make.toLocaleString(LOCALE)} / ${r.summary.planned_buy.toLocaleString(LOCALE)}` : ""),
    },
    { key: "finished", header: t("mfg.mrpRunsPage.str.finished"), width: "136px", sortValue: (r) => r.finished_at, render: (r) => fmtTimestamp(r.finished_at) },
    { key: "by", header: t("mfg.mrpRunsPage.str.by"), width: "minmax(80px, 1fr)", sortValue: (r) => r.actor.name, render: (r) => r.actor.name },
  ];
  if (canRun)
    columns.push({
      key: "actions",
      header: <span className="sr-only">{t("mfg.mrpRunsPage.text.actions")}</span>,
      label: t("mfg.mrpRunsPage.str.actions"),
      width: "84px",
      align: "right",
      exportValue: () => "",
      render: (r) => (
        <button type="button" className="btn sm ghost" onClick={() => void pin(r)} title={r.pinned ? t("mfg.mrpRunsPage.str.allowAutomaticCleanUpOf") : t("mfg.mrpRunsPage.str.keepThisRunOtherwiseOnly")}>
          <Icon name={r.pinned ? "unlock" : "lock"} /> {r.pinned ? t("mfg.mrpRunsPage.str.unkeep") : t("mfg.mrpRunsPage.str.keep")}
        </button>
      ),
    });

  return (
    <div className="col gap-lg">
      <PageHeader
        title={t("mfg.mrpRunsPage.title.materialPlanningMrp")}
        description={t("mfg.mrpRunsPage.desc.planWhatToMakeAnd")}
        actions={
          <>
            <PermissionGate perm="mrp_run">
          <button type="button" className="btn primary" onClick={() => setForm(true)} disabled={form} data-testid="mrp-new-run">
            <Icon name="play" /> {t("mfg.mrpRunsPage.btn.runMrp")}
          </button>
        </PermissionGate>
          </>
        }
      />
      {form ? <MrpRunForm onClose={() => setForm(false)} onDone={(r) => navigate(mfgPaths.run(r.id))} /> : null}
      <MfgError error={runs.error ?? error} onRetry={runs.reload} />
      {runs.data && items.length === 0 && !form ? (
        <Banner tone="info" title={t("mfg.mrpRunsPage.title.noPlanYet")} testId="mrp-empty">
          {t("mfg.mrpRunsPage.text.demandOrdersMustBeOpen", { v: canRun ? t("mfg.mrpRunsPage.str.runMrpToPlanMaterials") : t("mfg.mrpRunsPage.str.nobodyHasRunMrpIn") })}
        </Banner>
      ) : null}
      {items.length || runs.loading ? (
        <DataTable
          rows={items}
          columns={columns}
          rowKey={(r) => r.id}
          label={t("mfg.mrpRunsPage.label.mrpRuns")}
          testId="mrp-runs"
          loading={runs.loading && !runs.data}
          exportName="mrp-runs"
          rowExtras={(r) => ({ testId: "mrp-run-row", data: { "run-no": r.run_no, kind: r.kind, status: r.status } })}
          card={{ title: "run", status: "status", fields: ["late", "short", "finished"] }}
        />
      ) : null}
    </div>
  );
}

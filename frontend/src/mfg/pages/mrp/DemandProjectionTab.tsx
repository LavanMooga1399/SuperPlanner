/** Demand projection (M2 14.2 `DemandProjectionTab`, 8.10): due vs projected per demand line, limiting path chips. */
import { useEffect, useMemo } from "react";
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listRunDemand } from "../../api/clientM2";
import type { DemandProjectionRow, LimitingStep, ProjectionStatus } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { ProjectionChip } from "../../components/StatusM2";
import { fmtDate } from "../../lib/format";
import { fmtNum, segmentText } from "../../lib/formatM2";
import { LIMITING_REASON } from "../../lib/mrpText";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useRun } from "./RunShell";
import { FilterBar } from "../../../components/FilterBar";
import { t } from "../../../lib/i18n";

/** "KV-TPU-1000 (16 working days) <- KV-VCU-2000 <- ... <- KV-IC-FPGA-V1: PO-KV-0101/10/1 available 24 Nov". */
export function LimitingPath({ steps, runId }: { steps: LimitingStep[]; runId?: string }) {
  if (!steps.length) return null;
  return (
    <div className="mfg-chip-row" aria-label={t("mfg.demandProjectionTab.aria.whyItIsLateLimiting")} data-testid="limiting-path">
      <span className="faint small">{t("mfg.demandProjectionTab.text.why")}</span>
      {steps.map((s, i) => (
        <span key={i} className="row" style={{ gap: 4 }}>
          {i > 0 ? (
            <span aria-hidden className="faint">
              ←
            </span>
          ) : null}
          <span className={`mfg-step-chip${i === steps.length - 1 ? " mfg-step-last" : ""}`} data-testid="limiting-step" data-reason={s.reason} title={`${s.label}${s.date ? `, ${fmtDate(s.date)}` : ""}`}>
            {runId ? (
              <Link to={mfgPaths.runItem(runId, s.item.id)} className="mono">
                {s.item.part_number}
              </Link>
            ) : (
              <span className="mono">{s.item.part_number}</span>
            )}
            <span className="muted">{s.label}</span>
            {i === steps.length - 1 || s.reason !== "component" ? <span className="faint">({LIMITING_REASON[s.reason] ?? s.reason})</span> : null}
          </span>
        </span>
      ))}
    </div>
  );
}

export function DemandProjectionTab() {
  const { run } = useRun();
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") ?? "") as ProjectionStatus | "";
  const sort = (params.get("sort") ?? "-late_days") as "-late_days" | "due_date";
  const line = params.get("line");
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  const data = usePaged<DemandProjectionRow>((offset, limit, signal) => listRunDemand(run.id, { status: status || undefined, sort, limit, offset }, signal), [run.id, status, sort], 200);
  useEffect(() => {
    if (line && data.rows.some((r) => r.demand_line_id === line)) document.querySelector(".mfg-highlight")?.scrollIntoView({ block: "center" });
  }, [line, data.rows]);
  const rows = useMemo(() => data.rows, [data.rows]);
  return (
    <div className="col gap-lg">
      <FilterBar pageKey="DemandProjectionTab">
        <div className="field">
          <label htmlFor="dp-status">{t("mfg.demandProjectionTab.label.show")}</label>
          <select id="dp-status" className="select" value={status} onChange={(e) => set("status", e.target.value)} data-testid="demand-proj-status">
            <option value="">{t("mfg.demandProjectionTab.text.allDemandLines")}</option>
            <option value="late">{t("mfg.demandProjectionTab.text.late")}</option>
            <option value="past_due">{t("mfg.demandProjectionTab.text.pastDue")}</option>
            <option value="on_time">{t("mfg.demandProjectionTab.text.onTime")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="dp-sort">{t("mfg.demandProjectionTab.label.sortBy")}</label>
          <select id="dp-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "-late_days" ? "" : e.target.value)}>
            <option value="-late_days">{t("mfg.demandProjectionTab.text.mostLateFirst")}</option>
            <option value="due_date">{t("mfg.demandProjectionTab.text.dueDate")}</option>
          </select>
        </div>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="demand-projection">
          <thead>
            <tr>
              <th>{t("mfg.demandProjectionTab.head.demandLine")}</th>
              <th>{t("mfg.demandProjectionTab.head.item")}</th>
              <th className="right">{t("mfg.demandProjectionTab.head.qty")}</th>
              <th>{t("mfg.demandProjectionTab.head.prio")}</th>
              <th>{t("mfg.demandProjectionTab.head.due")}</th>
              <th>{t("mfg.demandProjectionTab.head.projected")}</th>
              <th>{t("mfg.demandProjectionTab.head.status")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="muted">
                  {data.loading ? t("mfg.demandProjectionTab.str.loading") : t("mfg.demandProjectionTab.str.noDemandLines")}
                </td>
              </tr>
            ) : null}
            {rows.map((d, i) => [
              <tr key={`${i}a`} data-testid="demand-line" data-late-days={d.late_days} data-line={d.order ? `${d.order.number}/${d.line_no}` : "extra"} className={d.demand_line_id && d.demand_line_id === line ? "mfg-highlight" : undefined}>
                <td>
                  {d.link ? (
                    <Link to={d.link} className="mono">
                      {d.order ? `${d.order.number}/${d.line_no}` : "What-if"}
                    </Link>
                  ) : (
                    <span className="mono">{d.order ? `${d.order.number}/${d.line_no}` : t("mfg.demandProjectionTab.str.whatIfDemand")}</span>
                  )}
                  {d.order?.program ? <span className="faint small"> · {d.order.program}</span> : null}
                  {d.segment ? <div className="faint small">{segmentText(d.segment)}</div> : null}
                </td>
                <td>
                  <Link to={mfgPaths.runItem(run.id, d.item.id)} className="mono">
                    {d.item.part_number}
                  </Link>
                </td>
                <td className="right">{fmtNum(d.qty)}</td>
                <td>P{d.priority}</td>
                <td>{fmtDate(d.due_date)}</td>
                <td>{fmtDate(d.projected_date)}</td>
                <td>
                  <ProjectionChip status={d.status} lateDays={d.late_days} />
                </td>
              </tr>,
              d.limiting.length ? (
                <tr key={`${i}b`} className="mfg-schedule-row">
                  <td colSpan={7}>
                    <LimitingPath steps={d.limiting} runId={run.id} />
                  </td>
                </tr>
              ) : null,
            ])}
          </tbody>
        </table>
        {data.rows.length < data.total ? (
          <div className="card-footer">
            <button type="button" className="btn sm" onClick={data.onEndReached} disabled={data.loading}>
              <Icon name="chevron-down" />{" "}{t("mfg.demandProjectionTab.text.showMore", { t: t("common.nOfM", { n: data.rows.length, m: data.total }) })}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

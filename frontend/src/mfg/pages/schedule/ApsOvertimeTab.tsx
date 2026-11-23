/**
 * Overtime of a schedule run (M3 12, 6.8, 16 Q1):
 * - `allow` runs: every extra shift the scheduler opened, with cost and why (the late or critical work using it).
 * - `suggest` runs: the extra shifts that would reduce lateness, each with the weighted late minutes it saves and its
 *   cost, ranked by saving per cost. The planner accepts the ones they want ("Accept" per row) and re-runs with
 *   those shifts opened (the run form, prefilled), or re-runs with automatic overtime (Allow).
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { getApsOvertime, rerunWithOpenShifts } from "../../api/clientM3";
import type { OvertimeWindow } from "../../api/typesM3";
import { MfgError, Spinner } from "../../components/Feedback";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { useResourceNames } from "../../lib/resourceNames";
import { useLoad } from "../../lib/useMfg";
import { orderLink } from "./ApsOrdersTab";
import { useApsRun } from "./ApsRunShell";
import { t, t as tr } from "../../../lib/i18n";

const STATUS: Record<OvertimeWindow["status"], { label: string; tone: string; icon: "check" | "help" | "lock" }> = {
  opened: { label: tr("mfg.apsOvertimeTab.str.openedByTheScheduler"), tone: "warn", icon: "check" },
  suggested: { label: tr("mfg.apsOvertimeTab.str.suggested"), tone: "info", icon: "help" },
  forced: { label: tr("mfg.apsOvertimeTab.str.openedByYou"), tone: "accent", icon: "lock" },
};

const keyOf = (w: OvertimeWindow) => w.assignment_id ? `${w.assignment_id}:${w.start}` : `${w.line_id}:${w.start}`;

export function ApsOvertimeTab() {
  const { run } = useApsRun();
  const clock = usePlantClock();
  const navigate = useNavigate();
  const canRun = useCan("schedule_run");
  const ot = useLoad((signal) => getApsOvertime(run.id, undefined, signal), [run.id]);
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const items = ot.data?.items ?? [];
  const opened = items.filter((w) => w.status !== "suggested");
  const suggested = useMemo(
    () => items.filter((w) => w.status === "suggested").sort((a, b) => (b.tardiness_saved_minutes ?? 0) / Math.max(1, b.cost) - (a.tardiness_saved_minutes ?? 0) / Math.max(1, a.cost)),
    [items],
  );
  const policy = run.policy ?? run.summary?.policy ?? run.params?.overtime ?? "suggest";
  const t = ot.data?.totals;
  const acceptedRows = suggested.filter((w) => accepted.has(keyOf(w)));

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // accept: a live, publishable copy of this run with the accepted shifts opened as planner overtime, then compare
  const rerunAccepted = async () => {
    setBusy(true);
    setError(null);
    try {
      const n = acceptedRows.length;
      const next = await rerunWithOpenShifts(
        run.id,
        acceptedRows.map((w) => ({ line_id: w.line_id, start: w.start, end: w.end })),
        `${run.label || `${tr("common.scheduleNo", { n: run.run_no })}`} with ${n} extra shift${n === 1 ? "" : "s"}`,
      );
      navigate(mfgPaths.apsCompare(next.id, run.id));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid="aps-overtime" data-policy={policy}>
      <MfgError error={ot.error ?? error} onRetry={ot.reload} />
      {ot.loading && !ot.data ? <Spinner /> : null}
      {t ? (
        <div className="kpis">
          <div className="card kpi">
            <div className="kpi-label">{tr("mfg.apsOvertimeTab.text.overtimeUsed")}</div>
            <div className="kpi-value">{fmtDuration(t.opened_minutes) || "none"}</div>
            <div className="kpi-sub">{tr("mfg.apsOvertimeTab.text.cost", { fmtNum: fmtNum(Math.round(t.opened_cost)) })}</div>
          </div>
          <div className="card kpi">
            <div className="kpi-label">{tr("mfg.apsOvertimeTab.text.overtimeSuggested")}</div>
            <div className="kpi-value">{fmtDuration(t.suggested_minutes) || "none"}</div>
            <div className="kpi-sub">
              {tr("mfg.apsOvertimeTab.text.costSavesWeightedLateness", { fmtNum: fmtNum(Math.round(t.suggested_cost)), v: fmtDuration(t.tardiness_saved_minutes) || "0" })}
            </div>
          </div>
        </div>
      ) : null}

      {policy === "off" ? (
        <Banner tone="info" title={tr("mfg.apsOvertimeTab.title.thisRunUsedRegularShifts")}>
          {tr("mfg.apsOvertimeTab.text.nothingWasOpenedOrSuggested")}
        </Banner>
      ) : null}

      {ot.data && (opened.length || policy === "allow") ? (
        <section className="card" data-testid="overtime-opened">
          <div className="card-header">
            <h3>{tr("mfg.apsOvertimeTab.text.extraShifts", { v: policy === "allow" ? tr("mfg.apsOvertimeTab.str.openedByTheScheduler2") : tr("mfg.apsOvertimeTab.str.inThisPlan"), length: opened.length })}</h3>
          </div>
          <OtTable rows={opened} clock={clock} mode="opened" runId={run.id} />
        </section>
      ) : null}

      {policy === "suggest" && ot.data ? (
        <section className="card" data-testid="overtime-suggested">
          <div className="card-header">
            <h3>{tr("mfg.apsOvertimeTab.text.suggestedExtraShifts", { length: suggested.length })}</h3>
            <span className="muted small">{tr("mfg.apsOvertimeTab.text.bestSavingPerCostFirst")}</span>
          </div>
          {suggested.length === 0 ? (
            <div className="card-body muted">{tr("mfg.apsOvertimeTab.text.noExtraShiftWouldReduce")}</div>
          ) : (
            <OtTable
              runId={run.id}
              rows={suggested}
              clock={clock}
              mode="suggested"
              accepted={accepted}
              onToggle={(w) =>
                setAccepted((s) => {
                  const n = new Set(s);
                  const k = keyOf(w);
                  if (n.has(k)) n.delete(k);
                  else n.add(k);
                  return n;
                })
              }
              canAccept={canRun}
            />
          )}
          {suggested.length ? (
            <div className="card-footer row wrap">
              <button type="button" className="btn primary" disabled={!canRun || busy || acceptedRows.length === 0} title={canRun ? undefined : needsText("schedule_run")} onClick={() => void rerunAccepted()} data-testid="overtime-rerun-accepted">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />}{" "}{tr("mfg.apsOvertimeTab.text.reRunWithTheseOpened", { length: acceptedRows.length })}
              </button>
              <button type="button" className="btn ghost" disabled={!canRun} onClick={() => setAccepted(new Set(suggested.map(keyOf)))}>
                {tr("mfg.apsOvertimeTab.btn.acceptAll")}
              </button>
              <span className="faint small">
                {tr("mfg.apsOvertimeTab.text.createsANewRunWith")}
              </span>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function OtTable({
  runId,
  rows,
  clock,
  mode,
  accepted,
  onToggle,
  canAccept,
}: {
  runId: string;
  rows: OvertimeWindow[];
  clock: ReturnType<typeof usePlantClock>;
  mode: "opened" | "suggested";
  accepted?: Set<string>;
  onToggle?(w: OvertimeWindow): void;
  canAccept?: boolean;
}) {
  const names = useResourceNames();
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {mode === "suggested" ? <th>{tr("mfg.apsOvertimeTab.text.accept")}</th> : null}
            <th>{t("mfg.apsOvertimeTab.head.line")}</th>
            <th>{t("mfg.apsOvertimeTab.head.when")}</th>
            <th className="right">{t("mfg.apsOvertimeTab.head.hours")}</th>
            <th className="right">{t("mfg.apsOvertimeTab.head.cost")}</th>
            <th>{mode === "suggested" ? tr("mfg.apsOvertimeTab.str.latenessSaved") : tr("mfg.apsOvertimeTab.str.why")}</th>
            <th>{t("mfg.apsOvertimeTab.head.status")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={mode === "suggested" ? 7 : 6} className="muted">
                {tr("mfg.apsOvertimeTab.text.noneNoWorkWouldOtherwise")}
              </td>
            </tr>
          ) : null}
          {rows.map((w) => {
            const s = STATUS[w.status];
            const k = keyOf(w);
            return (
              <tr key={k} data-testid="overtime-row" data-status={w.status} data-line={names.line(w.line_id).code} data-saved={w.tardiness_saved_minutes ?? ""}>
                {mode === "suggested" ? (
                  <td>
                    <input type="checkbox" checked={accepted?.has(k) ?? false} disabled={!canAccept} onChange={() => onToggle?.(w)} aria-label={tr("mfg.apsOvertimeTab.tpl.acceptExtraShiftOn", { code: names.line(w.line_id).code, start: clock.dateTime(w.start) })} data-testid="overtime-accept" />
                  </td>
                ) : null}
                <td className="mono">
                  {names.line(w.line_id).code}
                  {names.line(w.line_id).group_id ? <span className="faint small"> · {names.group(names.line(w.line_id).group_id).code}</span> : null}
                </td>
                <td className="small">
                  {clock.dateTime(w.start)} – {clock.time(w.end)}
                </td>
                <td className="right">{(w.minutes / 60).toFixed(1)}</td>
                <td className="right">{fmtNum(Math.round(w.cost))}</td>
                <td className="small">
                  {mode === "suggested" ? <strong>{fmtDuration(w.tardiness_saved_minutes ?? 0)} weighted</strong> : null}
                  {w.reason ? (
                    <div className={mode === "suggested" ? "faint" : undefined} data-testid="overtime-reason">
                      {w.reason}
                    </div>
                  ) : mode === "opened" ? (
                    <div>{w.status === "forced" ? tr("mfg.apsOvertimeTab.str.openedByYou2") : tr("mfg.apsOvertimeTab.str.openedForWorkThatWould")}</div>
                  ) : null}
                  {w.orders?.length ? (
                    <ul className="mfg-ot-orders" data-testid="overtime-orders">
                      {w.orders.map((o) => (
                        <li key={o.order.id}>
                          <Link to={orderLink(o.order, runId)} className="mono">
                            {o.order.number}
                          </Link>{" "}
                          <span className="faint">
                            {tr("mfg.apsOvertimeTab.text.inThisShift", { minutes: fmtDuration(o.minutes), v: o.op_nos.length ? ` (op ${o.op_nos.join(", ")})` : "", v2: o.late_minutes > 0 ? ` · ${fmtDuration(o.late_minutes)} late` : "" })}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </td>
                <td>
                  <span className={`badge ${s.tone}`}>
                    <Icon name={s.icon} /> {s.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

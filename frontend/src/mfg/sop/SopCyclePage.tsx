/**
 * `/mfg/sop/cycles/:cycleId/:step?` (M9 6, 10): one S&OP cycle as a stepper - Demand (consensus by family x month
 * with overrides and reasons), Supply (rough-cut heatmap, scenarios, run), Financial (P&L in the report currency),
 * Compare (KPI cards and deltas, up to 5 scenarios), Approve (two signed steps: reviewed by a plant manager, approved
 * by an executive - distinct people, always signed) and Publish (per-node forecast versions and MPS targets,
 * follow-ups that stay with the planners). After the first signature the cycle is frozen; reopening needs a reason.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDateTime, formatDay, formatMoney, formatNumber } from "../../lib/locale";
import { advanceCycle, approveCycle, cancelCycle, getCycle, getDemand, listScenarios, publishCycle, reopenCycle } from "../api/clientM9";
import { SOP_STEPS, type SopCycle, type SopPublishNode, type SopScenario, type SopStep } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { errorCode, useLoad } from "../lib/useMfg";
import { SignatureList } from "../qa/RecordShell";
import { ReasonConfirm } from "../forecast/ForecastPage";
import { codeText9, CycleChip, isRunning, KpiCard, monthLabel, NodeTag, num, pct, stepText, useNodes } from "../network/shared";
import { DemandTab } from "./SopDemandTab";
import { CompareTab, FinancialTab, SupplyTab } from "./SopSupplyTabs";

const VIEWS = ["demand", "supply", "financial", "compare", "approve", "publish"] as const;
export type View = (typeof VIEWS)[number];
type Nodes = ReturnType<typeof useNodes>;

/** Which view a cycle step opens on. */
function viewOf(s: string): View {
  return s === "supply_review" ? "supply" : s === "pre_sop" ? "compare" : s === "executive" || s === "approved" ? (s === "approved" ? "publish" : "approve") : s === "published" ? "publish" : "demand";
}
const NEXT: Partial<Record<SopStep, SopStep>> = { draft: "demand_review", demand_review: "supply_review", supply_review: "pre_sop", pre_sop: "executive" };

export function SopCyclePage() {
  const { cycleId = "", step } = useParams();
  const cycle = useLoad((s) => getCycle(cycleId, s), [cycleId]);
  const c = cycle.data;
  const view: View = VIEWS.includes(step as View) ? (step as View) : c ? viewOf(c.status) : "demand";
  const scenarios = useLoad((s) => listScenarios({ cycle_id: cycleId }, s), [cycleId]);
  const nodes = useNodes();
  const canEdit = useCan("sop_edit");
  const [advance, setAdvance] = useState(false);
  const [reopen, setReopen] = useState(false);
  const [cancel, setCancel] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  usePolling(cycle.reload, isRunning(c?.publish_job_status));
  usePolling(scenarios.reload, (scenarios.data?.items ?? []).some((x) => x.status === "running"));
  useEffect(() => {
    if (c) document.title = `${c.number} - ${t("net.sop.title")}`;
  }, [c]);
  if (cycle.error && !c) return <MfgError error={cycle.error} onRetry={cycle.reload} />;
  if (!c) return <Spinner />;
  const list = scenarios.data?.items ?? [];
  const rec = list.find((x) => x.id === c.recommended_scenario_id) ?? null;
  const appr = list.find((x) => x.id === c.approved_scenario_id) ?? null;
  const next = NEXT[c.status as SopStep];
  const locked = c.signatures.some((s) => s.status === "valid");
  const canReopen = (c.status === "executive" || c.status === "approved") && canEdit;
  const reload = () => {
    cycle.reload();
    scenarios.reload();
  };
  const curIdx = SOP_STEPS.indexOf(c.status as SopStep);
  return (
    <div className="col gap-lg" data-testid="sop-cycle-page" data-status={c.status}>
      <div className="mfg-breadcrumb small muted">
        <Link to={mfgPaths.sop()}>{t("net.sop.title")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{c.number}</span>
      </div>
      <PageHeader
        title={t("net.cyc.tpl.title", { n: c.number, p: monthLabel(c.period) })}
        meta={
          <>
            <CycleChip s={c.status} />
            {locked && c.status !== "published" ? (
              <span className="badge warn" data-testid="sop-locked">
                <Icon name="lock" /> {t("net.cyc.locked")}
              </span>
            ) : null}
          </>
        }
        facts={[
          [t("net.cyc.fact.horizon"), plural(c.horizon_months, t("noun.month"), t("noun.months"))],
          [t("net.cyc.fact.currency"), c.report_currency],
          [t("net.cyc.fact.recommended"), rec ? `${rec.number} ${rec.name}` : "–"],
          [t("net.cyc.fact.approved"), appr ? `${appr.number} ${appr.name}` : "–"],
        ]}
        actions={
          <>
            {canReopen ? (
              <button type="button" className="btn" onClick={() => setReopen(true)} data-testid="sop-reopen">
                <Icon name="refresh" /> {t("net.cyc.btn.reopen")}
              </button>
            ) : null}
            {c.status !== "cancelled" && c.status !== "published" && !locked ? (
              <button type="button" className="btn" disabled={!canEdit} onClick={() => setCancel(true)}>
                <Icon name="ban" /> {t("net.cyc.btn.cancel")}
              </button>
            ) : null}
            {next ? (
              <button type="button" className="btn primary" disabled={!canEdit} title={canEdit ? undefined : needsText("sop_edit")} onClick={() => setAdvance(true)} data-testid="sop-advance">
                <Icon name="arrow-right" /> {t("net.cyc.btn.advance", { s: stepText(next) })}
              </button>
            ) : null}
          </>
        }
      />
      <MfgError error={err} />
      {c.reopen_reason ? (
        <Banner tone="info" title={t("net.cyc.reopened")}>
          {c.reopen_reason}
        </Banner>
      ) : null}
      <ol className="sop-steps" aria-label={t("net.cyc.aria.stepper")} data-testid="sop-stepper">
        {VIEWS.map((v) => {
          const stepOf: Record<View, SopStep> = { demand: "demand_review", supply: "supply_review", financial: "supply_review", compare: "pre_sop", approve: "executive", publish: "published" };
          const info = c.steps.find((s) => s.step === stepOf[v]);
          const done = curIdx > SOP_STEPS.indexOf(stepOf[v]);
          return (
            <li key={v}>
              <NavLink to={mfgPaths.sopCycle(c.id, v)} className={() => (view === v ? "active" : "")} aria-current={view === v ? "step" : undefined} data-testid={`sop-view-${v}`}>
                <span className="sop-step-name">
                  {done ? <Icon name="check" size={12} /> : info?.overdue ? <Icon name="alert" size={12} /> : null}
                  {t(`net.cyc.view.${v}` as const)}
                </span>
                <span className={`sop-step-meta${info?.overdue && !done ? " overdue" : ""}`}>
                  {info?.due ? t("net.sop.tpl.due", { d: formatDay(info.due) }) : " "}
                  {info?.owner_name ? ` · ${info.owner_name}` : ""}
                  {info?.overdue && !done ? ` · ${t("net.sop.overdue")}` : ""}
                </span>
              </NavLink>
            </li>
          );
        })}
      </ol>
      {view === "demand" ? (
        <DemandTab cycle={c} nodes={nodes} locked={locked || !canEdit || c.status === "cancelled"} />
      ) : view === "supply" ? (
        <SupplyTab cycle={c} nodes={nodes} scenarios={list} onChanged={reload} />
      ) : view === "financial" ? (
        <FinancialTab cycle={c} nodes={nodes} scenarios={list} />
      ) : view === "compare" ? (
        <CompareTab cycle={c} scenarios={list} onChanged={reload} />
      ) : view === "approve" ? (
        <ApproveTab cycle={c} scenarios={list} onChanged={reload} />
      ) : (
        <PublishTab cycle={c} scenarios={list} nodes={nodes} onChanged={reload} />
      )}
      {advance && next ? (
        <AdvanceDialog
          cycle={c}
          next={next}
          onClose={() => setAdvance(false)}
          onDone={(x) => {
            setAdvance(false);
            cycle.setData(x);
            toast(t("net.cyc.toast.advanced", { s: stepText(x.status) }));
          }}
        />
      ) : null}
      {reopen ? <ReopenDialog cycle={c} onClose={() => setReopen(false)} onDone={() => (setReopen(false), reload())} /> : null}
      {cancel ? (
        <ReasonConfirm
          title={t("net.cyc.dlg.cancelTitle", { n: c.number })}
          body={t("net.cyc.dlg.cancelBody")}
          confirm={t("net.cyc.btn.cancel")}
          danger
          onClose={() => setCancel(false)}
          run={async (why) => {
            try {
              await cancelCycle(c, why);
              setCancel(false);
              reload();
            } catch (e) {
              setErr(e);
              setCancel(false);
            }
          }}
        />
      ) : null}
    </div>
  );
}

function AdvanceDialog({ cycle, next, onClose, onDone }: { cycle: SopCycle; next: SopStep; onClose(): void; onDone(c: SopCycle): void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      onDone(await advanceCycle(cycle, note.trim()));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const code = errorCode(err);
  return (
    <Dialog
      title={t("net.cyc.dlg.advanceTitle", { s: stepText(next) })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={busy} onClick={() => void go()} data-testid="sop-advance-go">
            <Icon name="arrow-right" /> {t("net.cyc.btn.advanceShort")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        {code === "SOP_NO_BASELINE" ? <Banner tone="warn" role="alert" title={t("net.cyc.err.noBaseline")}>{t("net.cyc.err.noBaselineBody")}</Banner> : code === "SOP_NO_RECOMMENDATION" ? <Banner tone="warn" role="alert" title={t("net.cyc.err.noRec")}>{t("net.cyc.err.noRecBody")}</Banner> : <MfgError error={err} />}
        <p style={{ margin: 0 }}>{t(`net.cyc.advance.${next}` as "net.cyc.advance.demand_review")}</p>
        <div className="field">
          <label htmlFor="sop-adv-note">{t("net.cyc.label.stepNote")}</label>
          <textarea id="sop-adv-note" className="textarea" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          <span className="hint">{t("net.cyc.hint.stepNote")}</span>
        </div>
      </div>
    </Dialog>
  );
}

function ReopenDialog({ cycle, onClose, onDone }: { cycle: SopCycle; onClose(): void; onDone(): void }) {
  const [to, setTo] = useState<SopStep>("pre_sop");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <ConfirmDialog
      title={t("net.cyc.dlg.reopenTitle", { n: cycle.number })}
      confirmLabel={t("net.cyc.btn.reopen")}
      busy={busy}
      confirmDisabled={!why.trim()}
      onCancel={onClose}
      onConfirm={() => {
        setBusy(true);
        setErr(null);
        reopenCycle(cycle, to, why.trim())
          .then(() => {
            toast(t("net.cyc.toast.reopened"));
            onDone();
          })
          .catch((e: unknown) => setErr(e))
          .finally(() => setBusy(false));
      }}
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("net.cyc.dlg.reopenBody")}</p>
        <div className="field">
          <label htmlFor="sop-reopen-to">{t("net.cyc.label.reopenTo")}</label>
          <select id="sop-reopen-to" className="select" value={to} onChange={(e) => setTo(e.target.value as SopStep)}>
            {(["demand_review", "supply_review", "pre_sop"] as SopStep[]).map((s) => (
              <option key={s} value={s}>
                {stepText(s)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="sop-reopen-why">
            {t("plan.label.reason")} <span className="req" aria-hidden />
          </label>
          <textarea id="sop-reopen-why" className="textarea" rows={2} maxLength={500} value={why} onChange={(e) => setWhy(e.target.value)} data-testid="sop-reopen-reason" />
        </div>
      </div>
    </ConfirmDialog>
  );
}

// ---------------------------------------------------------------- approve
function ApproveTab({ cycle, scenarios, onChanged }: { cycle: SopCycle; scenarios: SopScenario[]; onChanged(): void }) {
  const done = scenarios.filter((s) => s.status === "completed");
  const [scenarioId, setScenarioId] = useState(cycle.approved_scenario_id ?? cycle.recommended_scenario_id ?? done[0]?.id ?? "");
  const [signing, setSigning] = useState(false);
  const demand = useLoad((s) => getDemand(cycle.id, {}, s), [cycle.id]);
  const sc = scenarios.find((s) => s.id === scenarioId) ?? null;
  const valid = cycle.signatures.filter((s) => s.status === "valid");
  const canSign = cycle.status === "executive";
  const totals = useMemo(() => {
    const rows = demand.data?.items ?? [];
    return { consensus: rows.reduce((a, r) => a + r.consensus_qty, 0), stat: rows.reduce((a, r) => a + r.stat_qty, 0), fams: new Set(rows.map((r) => r.family)).size };
  }, [demand.data]);
  const k = sc?.kpis?.horizon;
  const ccy = sc?.kpis?.currency ?? cycle.report_currency;
  return (
    <div className="col pl-gap" data-testid="sop-approve">
      {cycle.status === "approved" || cycle.status === "published" ? (
        <Banner tone="ok" icon="check" title={t("net.cyc.appr.done")}>
          {t("net.cyc.appr.doneBody")}
        </Banner>
      ) : !canSign ? (
        <Banner tone="info" title={t("net.cyc.appr.notYet")}>
          {t("net.cyc.appr.notYetBody")}
        </Banner>
      ) : null}
      <section className="card col pl-gap" aria-labelledby="sop-appr-h">
        <h2 className="pl-h2" id="sop-appr-h">
          {t("net.cyc.appr.what")}
        </h2>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          <div className="field">
            <label htmlFor="sop-appr-sc">{t("net.cyc.appr.scenario")}</label>
            <select id="sop-appr-sc" className="select" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} disabled={!canSign || valid.length > 0} data-testid="sop-appr-scenario">
              {done.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.number} · {s.name}
                  {s.id === cycle.recommended_scenario_id ? ` (${t("net.cyc.recommended")})` : ""}
                </option>
              ))}
            </select>
          </div>
          {sc && sc.validator && !sc.validator.ok ? (
            <span className="badge danger">
              <Icon name="alert" /> {t("net.scn.invalid")}
            </span>
          ) : sc?.validator?.ok ? (
            <span className="badge ok">
              <Icon name="shield" /> {t("net.scn.valid")}
            </span>
          ) : null}
        </div>
        {cycle.recommend_note ? (
          <p className="small" style={{ margin: 0 }}>
            <strong>{t("net.cyc.appr.recNote")}</strong> {cycle.recommend_note}
          </p>
        ) : null}
        {k ? (
          <div className="net-kpis">
            <KpiCard label={t("net.kpi.service")} value={pct(k.service_pct)} sub={t("net.tpl.unmet", { n: num(k.unmet_units) })} />
            <KpiCard label={t("net.kpi.revenue")} value={formatMoney(k.revenue, ccy, { compact: true })} unit={ccy} />
            <KpiCard label={t("net.kpi.gm")} value={formatMoney(k.gross_margin, ccy, { compact: true })} unit={ccy} sub={t("net.tpl.gmPct", { v: pct(k.gm_pct) })} />
            <KpiCard label={t("net.kpi.inventory")} value={formatMoney(k.inventory_value, ccy, { compact: true })} unit={ccy} sub={k.days_of_cover === null ? undefined : t("net.tpl.cover", { n: num(k.days_of_cover) })} />
            <KpiCard label={t("net.kpi.capex")} value={formatMoney(k.capex, ccy, { compact: true })} unit={ccy} />
          </div>
        ) : null}
        <dl className="pl-facts">
          <div>
            <dt>{t("net.cyc.appr.consensus")}</dt>
            <dd>{t("net.tpl.unitsFam", { n: formatNumber(totals.consensus), f: plural(totals.fams, t("net.noun.family"), t("net.noun.families")) })}</dd>
          </div>
          <div>
            <dt>{t("net.cyc.appr.vsStat")}</dt>
            <dd>{totals.stat ? pct(totals.consensus / totals.stat - 1) : "–"}</dd>
          </div>
          <div>
            <dt>{t("net.cyc.appr.hash")}</dt>
            <dd className="mono small">{cycle.content_hash ? cycle.content_hash.slice(0, 16) : "–"}</dd>
          </div>
        </dl>
      </section>
      <section className="card col pl-gap" aria-labelledby="sop-sig-h">
        <div className="pl-card-header">
          <h2 className="pl-h2" id="sop-sig-h">
            {t("net.cyc.appr.signatures")}
          </h2>
          {canSign ? (
            <button type="button" className="btn primary" disabled={!sc || sc.status !== "completed" || sc.validator?.ok === false} onClick={() => setSigning(true)} data-testid="sop-sign">
              <Icon name="lock" /> {valid.length ? t("net.cyc.btn.signApprove") : t("net.cyc.btn.signReview")}
            </button>
          ) : null}
        </div>
        <ol className="pl-bullets">
          <li className={valid.some((s) => s.step === 1) ? "" : "muted"}>{t("net.cyc.appr.step1")}</li>
          <li className={valid.some((s) => s.step === 2) ? "" : "muted"}>{t("net.cyc.appr.step2")}</li>
        </ol>
        {cycle.signatures.length ? <SignatureList signatures={cycle.signatures} /> : <p className="muted small" style={{ margin: 0 }}>{t("net.cyc.appr.noSig")}</p>}
      </section>
      {signing && sc ? (
        <SignatureDialog<SopCycle>
          title={t("net.cyc.dlg.signTitle", { n: cycle.number })}
          recordType="sop_cycle"
          recordId={cycle.id}
          recordLabel={cycle.number}
          action="approve"
          submitLabel={valid.length ? t("net.cyc.btn.signApprove") : t("net.cyc.btn.signReview")}
          plainLabel={t("net.cyc.btn.approve")}
          effect={valid.length ? t("net.cyc.dlg.signEffect2") : t("net.cyc.dlg.signEffect1")}
          extraRows={[
            { label: t("net.cyc.appr.scenario"), value: `${sc.number} · ${sc.name}` },
            { label: t("net.kpi.service"), value: pct(k?.service_pct) },
            { label: t("net.kpi.gm"), value: `${formatMoney(k?.gross_margin, ccy)} (${pct(k?.gm_pct)})` },
            { label: t("net.cyc.appr.consensus"), value: formatNumber(totals.consensus) },
          ]}
          commentLabel={t("net.cyc.label.signComment")}
          perform={(sig, comment) => approveCycle(cycle, sc.id, sig, comment)}
          onDone={(res) => {
            toast(signedToast(res, t("net.cyc.toast.approved", { n: cycle.number })));
            setSigning(false);
            onChanged();
          }}
          onClose={() => setSigning(false)}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- publish
function PublishTab({ cycle, scenarios, nodes, onChanged }: { cycle: SopCycle; scenarios: SopScenario[]; nodes: Nodes; onChanged(): void }) {
  const canPublish = useCan("sop_publish");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const res = cycle.publish_result;
  const appr = scenarios.find((s) => s.id === cycle.approved_scenario_id);
  const running = isRunning(cycle.publish_job_status);
  const columns = useMemo<Column<SopPublishNode>[]>(
    () => [
      { key: "node", header: t("net.label.node"), width: "120px", sortValue: (x) => nodes.code(x.node), render: (x) => <NodeTag node={nodes.byId.get(x.node)} id={x.node} /> },
      { key: "fv", header: t("net.pubc.version"), width: "200px", render: (x) => (x.forecast_version_id ? <span className="badge ok"><Icon name="check" /> {t("net.pubc.activated")}</span> : <span className="badge warn"><Icon name="alert" /> {t("net.pubc.noVersion")}</span>) },
      { key: "targets", header: t("net.pubc.targets"), width: "130px", align: "right", sortValue: (x) => x.targets, render: (x) => <span className="pl-num">{num(x.targets)}</span> },
      { key: "warn", header: t("net.pubc.warnings"), width: "minmax(220px, 1fr)", wrap: true, render: (x) => (x.warnings.length ? <span className="small">{x.warnings.map((w) => `${codeText9(w.code)}${w.family ? ` (${w.family})` : ""}`).join(" · ")}</span> : <span className="muted">–</span>) },
    ],
    [nodes],
  );
  const publish = async (why: string) => {
    setBusy(true);
    setErr(null);
    try {
      await publishCycle(cycle, why);
      toast(t("net.pubc.toast.started", { n: cycle.number }));
      setConfirm(false);
      onChanged();
    } catch (e) {
      setErr(e);
      setConfirm(false);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="col pl-gap" data-testid="sop-publish">
      <MfgError error={err} />
      {cycle.status === "approved" ? (
        <section className="card row wrap" style={{ justifyContent: "space-between", gap: 12 }}>
          <span>{t("net.pubc.ready", { s: appr ? `${appr.number} ${appr.name}` : "–" })}</span>
          <button type="button" className="btn primary" disabled={!canPublish || running || busy} title={canPublish ? undefined : needsText("sop_publish")} onClick={() => setConfirm(true)} data-testid="sop-publish-btn">
            <Icon name="flag" /> {t("net.pubc.btn")}
          </button>
        </section>
      ) : cycle.status !== "published" ? (
        <Banner tone="info">{t("net.pubc.needApproval")}</Banner>
      ) : null}
      {running ? (
        <Banner tone="accent" icon="loader" role="status">
          {t("net.pubc.running")}
        </Banner>
      ) : null}
      {res ? (
        <>
          <p className="pl-note ok" style={{ margin: 0 }}>
            <Icon name="check" size={14} /> {t("net.pubc.done", { d: formatDateTime(res.published_at) })}
          </p>
          <section className="card card-table">
            <DataTable<SopPublishNode> rows={res.nodes} columns={columns} rowKey={(x) => x.node} label={t("net.pubc.aria")} testId="sop-publish-nodes" exportName="sop-publish" empty={t("net.pub.none")} />
          </section>
          <section className="card col pl-gap" aria-labelledby="sop-fu-h">
            <h2 className="pl-h2" id="sop-fu-h">
              {t("net.pubc.followUps")}
            </h2>
            <p className="small muted" style={{ margin: 0 }}>
              {t("net.pubc.followUpsHint")}
            </p>
            {res.follow_ups.length ? (
              <ul className="pl-bullets" data-testid="sop-follow-ups">
                {res.follow_ups.map((f) => (
                  <li key={f.change_id}>
                    <strong>{t(`net.chg.kind.${f.kind}` as const)}</strong> · {f.label}
                    {f.node ? ` · ${nodes.code(f.node)}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="small" style={{ margin: 0 }}>
                {t("net.pubc.noFollowUps")}
              </p>
            )}
          </section>
        </>
      ) : null}
      {confirm ? (
        <ReasonConfirm title={t("net.pubc.dlgTitle", { n: cycle.number })} body={t("net.pubc.dlgBody")} confirm={t("net.pubc.btn")} onClose={() => setConfirm(false)} run={publish} />
      ) : null}
    </div>
  );
}

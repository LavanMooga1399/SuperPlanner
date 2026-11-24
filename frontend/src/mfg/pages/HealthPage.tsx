/**
 * `/mfg/health` (M 11.1): the data-health check ("Gate 1"). Errors block planning; warnings and notes do not.
 * As-of date + horizon, counts, filter chips by severity and code, issues with server-built "Fix" links.
 */
import { useMemo, useState } from "react";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { getHealthReport } from "../api/client";
import type { Severity } from "../api/types";
import { MfgError, Spinner } from "../components/Feedback";
import { HealthIssueList } from "../components/HealthIssueList";
import { SeverityBadge } from "../components/StatusChip";
import { fmtDate } from "../lib/format";
import { useDebounced, useLoad, usePlant } from "../lib/useMfg";
import { plural, t, t as tr } from "../../lib/i18n";
import { PageHeader } from "../../components/PageHeader";
import { DateInput } from "../../components/DateInput";
import { LOCALE } from "../../lib/locale";

const SEVERITIES: { key: Severity; label: string }[] = [
  { key: "error", label: tr("mfg.healthPage.str.errors") },
  { key: "warning", label: tr("mfg.healthPage.str.warnings") },
  { key: "info", label: tr("mfg.healthPage.str.notes") },
];

export function HealthPage() {
  const plant = usePlant();
  const [asOf, setAsOf] = useState("");
  const [horizon, setHorizon] = useState("");
  const [tick, setTick] = useState(0);
  const dh = useDebounced(horizon, 400);
  const hNum = Number(dh);
  const hValid = dh === "" || (Number.isInteger(hNum) && hNum >= 7 && hNum <= 730);
  const report = useLoad(
    (signal) => (hValid ? getHealthReport({ as_of: asOf || undefined, horizon_days: dh ? hNum : undefined }, signal) : null),
    [asOf, dh, hValid, tick],
  );
  const [sev, setSev] = useState<Set<Severity>>(new Set());
  const [codes, setCodes] = useState<Set<string>>(new Set());
  const r = report.data;

  const issues = useMemo(() => {
    const all = r?.issues ?? [];
    return all.filter((i) => (sev.size === 0 || sev.has(i.severity)) && (codes.size === 0 || codes.has(i.code)));
  }, [r, sev, codes]);

  const severityOf = useMemo(() => {
    const m = new Map<string, Severity>();
    for (const i of r?.issues ?? []) m.set(i.code, i.severity);
    return m;
  }, [r]);

  const toggle = <T,>(set: Set<T>, v: T): Set<T> => {
    const n = new Set(set);
    if (n.has(v)) n.delete(v);
    else n.add(v);
    return n;
  };

  return (
    <div className="col gap-lg">
      <PageHeader
        title={t("mfg.healthPage.title.dataHealth")}
        description={t("mfg.healthPage.desc.checksThatYourItemsBoms")}
        actions={
          <>
            <div className="toolbar" style={{ marginBottom: 0, alignItems: "flex-end" }}>
          <div className="field">
            <label htmlFor="health-asof">{t("mfg.healthPage.label.checkFrom")}</label>
            <DateInput id="health-asof" small value={asOf} testId="health-as-of" onChange={(v) => setAsOf(v)} />
          </div>
          <div className="field" style={{ width: 130 }}>
            <label htmlFor="health-horizon">{t("mfg.healthPage.label.daysAhead")}</label>
            <input
              id="health-horizon"
              type="number"
              min={7}
              max={730}
              className="input sm"
              placeholder={String(plant.data?.planning_horizon_days ?? 90)}
              value={horizon}
              aria-invalid={!hValid}
              onChange={(e) => setHorizon(e.target.value)}
              data-testid="health-horizon"
            />
          </div>
          <button type="button" className="btn" onClick={() => setTick((t) => t + 1)} disabled={report.loading} data-testid="health-run">
            {report.loading ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />}{" "}{tr("mfg.healthPage.text.checkAgain")}
          </button>
        </div></>} />
      {!hValid ? <span className="field-error">{tr("mfg.healthPage.text.daysAheadMustBeA")}</span> : null}
      <MfgError error={report.error} onRetry={report.reload} />
      {report.loading && !r ? <Spinner label={t("mfg.healthPage.label.checkingYourData")} /> : null}

      {r ? (
        <>
          <div data-testid="health-status" data-ok={String(r.ok)} data-errors={r.counts.error} role="status">
            {r.ok ? (
              <Banner tone="ok" title={t("mfg.healthPage.title.readyForPlanning")}>
                {tr("mfg.healthPage.text.noErrorsFromOverThe", { asof: fmtDate(r.as_of), horizondays: plural(r.horizon_days, "day"), warning: plural(r.counts.warning, "warning"), info: plural(r.counts.info, "note") })}
              </Banner>
            ) : (
              <Banner tone="danger" icon="x" title={`${r.counts.error} ${r.counts.error === 1 ? tr("mfg.healthPage.str.problemBlocks") : tr("mfg.healthPage.str.problemsBlock")} planning`}>
                {tr("mfg.healthPage.text.fixTheErrorsBelowEach", { asof: fmtDate(r.as_of), horizondays: r.horizon_days })}
              </Banner>
            )}
          </div>

          <div className="row wrap" role="group" aria-label={t("mfg.healthPage.aria.filterBySeverity")}>
            {SEVERITIES.map((s) => (
              <button key={s.key} type="button" className="btn sm" aria-pressed={sev.has(s.key)} onClick={() => setSev((x) => toggle(x, s.key))} data-testid={`health-filter-${s.key}`}>
                <SeverityBadge severity={s.key} label={`${s.label}: ${r.counts[s.key]}`} />
              </button>
            ))}
            {sev.size || codes.size ? (
              <button
                type="button"
                className="btn sm ghost"
                onClick={() => {
                  setSev(new Set());
                  setCodes(new Set());
                }}
              >
                <Icon name="x" /> {t("mfg.healthPage.btn.clearFilters")}
              </button>
            ) : null}
          </div>
          {Object.keys(r.by_code).length ? (
            <div className="row wrap" role="group" aria-label={t("mfg.healthPage.aria.filterByCheck")}>
              {Object.entries(r.by_code).map(([code, n]) => (
                <button key={code} type="button" className="btn sm mfg-code-chip" aria-pressed={codes.has(code)} onClick={() => setCodes((x) => toggle(x, code))} data-testid="health-code-chip" data-code={code}>
                  <Icon name={severityOf.get(code) === "error" ? "x" : severityOf.get(code) === "warning" ? "alert" : "info"} size={12} />
                  <code>{code}</code> {n}
                </button>
              ))}
            </div>
          ) : null}
          {r.truncated ? (
            <Banner tone="warn" title={t("mfg.healthPage.title.onlyTheFirstIssuesAre")}>
              {tr("mfg.healthPage.text.theCountsAboveAreComplete", { length: r.issues.length.toLocaleString(LOCALE) })}
            </Banner>
          ) : null}
          {r.issues.length === 0 ? (
            <div className="empty">
              <Icon name="check" size={32} />
              <h2>{t("mfg.healthPage.head.nothingToReport")}</h2>
            </div>
          ) : null}
          <HealthIssueList issues={issues} />
          <p className="faint small" style={{ margin: 0 }}>
            {tr("mfg.healthPage.text.dataFingerprint")}{" "}<code>{r.fingerprint.slice(0, 12)}</code>{" "}{tr("mfg.healthPage.text.version", { dataversion: r.data_version })}
          </p>
        </>
      ) : null}
    </div>
  );
}

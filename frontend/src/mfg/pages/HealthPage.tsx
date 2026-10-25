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

const SEVERITIES: { key: Severity; label: string }[] = [
  { key: "error", label: "Errors" },
  { key: "warning", label: "Warnings" },
  { key: "info", label: "Notes" },
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
      <div className="page-header mfg-header">
        <div>
          <h1>Data health</h1>
          <p>Checks that your items, BOMs, routings, plant and people fit together before anything is planned.</p>
        </div>
        <div className="toolbar" style={{ marginBottom: 0, alignItems: "flex-end" }}>
          <div className="field">
            <label htmlFor="health-asof">Check from</label>
            <input id="health-asof" type="date" className="input sm" value={asOf} onChange={(e) => setAsOf(e.target.value)} data-testid="health-as-of" />
          </div>
          <div className="field" style={{ width: 130 }}>
            <label htmlFor="health-horizon">Days ahead</label>
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
            {report.loading ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} Check again
          </button>
        </div>
      </div>
      {!hValid ? <span className="field-error">Days ahead must be a whole number from 7 to 730.</span> : null}
      <MfgError error={report.error} onRetry={report.reload} />
      {report.loading && !r ? <Spinner label="Checking your data…" /> : null}

      {r ? (
        <>
          <div data-testid="health-status" data-ok={String(r.ok)} data-errors={r.counts.error} role="status">
            {r.ok ? (
              <Banner tone="ok" title="Ready for planning">
                No errors from {fmtDate(r.as_of)} over the next {r.horizon_days} days. {r.counts.warning} warnings and {r.counts.info} notes are worth a look but do not block anything.
              </Banner>
            ) : (
              <Banner tone="danger" icon="x" title={`${r.counts.error} ${r.counts.error === 1 ? "problem blocks" : "problems block"} planning`}>
                Fix the errors below (each has a "Fix" link to the right place), then check again. Checked from {fmtDate(r.as_of)} over {r.horizon_days} days.
              </Banner>
            )}
          </div>

          <div className="row wrap" role="group" aria-label="Filter by severity">
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
                <Icon name="x" /> Clear filters
              </button>
            ) : null}
          </div>
          {Object.keys(r.by_code).length ? (
            <div className="row wrap" role="group" aria-label="Filter by check">
              {Object.entries(r.by_code).map(([code, n]) => (
                <button key={code} type="button" className="btn sm mfg-code-chip" aria-pressed={codes.has(code)} onClick={() => setCodes((x) => toggle(x, code))} data-testid="health-code-chip" data-code={code}>
                  <Icon name={severityOf.get(code) === "error" ? "x" : severityOf.get(code) === "warning" ? "alert" : "info"} size={12} />
                  <code>{code}</code> {n}
                </button>
              ))}
            </div>
          ) : null}
          {r.truncated ? (
            <Banner tone="warn" title="Only the first issues are listed">
              The counts above are complete; {r.issues.length.toLocaleString()} issues are shown. Fix the errors first and check again.
            </Banner>
          ) : null}
          {r.issues.length === 0 ? (
            <div className="empty">
              <Icon name="check" size={32} />
              <h2>Nothing to report</h2>
            </div>
          ) : null}
          <HealthIssueList issues={issues} />
          <p className="faint small" style={{ margin: 0 }}>
            Data fingerprint <code>{r.fingerprint.slice(0, 12)}</code> · version {r.data_version}
          </p>
        </>
      ) : null}
    </div>
  );
}

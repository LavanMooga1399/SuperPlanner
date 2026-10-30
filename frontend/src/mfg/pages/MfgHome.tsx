/** `/mfg` overview (M 11.1): counts, health status (run on open), sample loader, quick links, export. */
import { useState } from "react";
import { Link } from "react-router";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { getHealthReport, getSummary, resetMfg } from "../api/client";
import { RESET_PHRASE, type SampleLoadResponse, type Summary, type SummaryCounts } from "../api/types";
import type { SummaryLatestRun, SummaryM2Counts } from "../api/typesM2";
import type { PublishedScheduleSummary } from "../api/typesM3";
import { PermissionGate } from "../components/PermissionGate";
import { ExportButtons } from "../components/ExportButtons";
import { MfgError } from "../components/Feedback";
import { SampleLoader } from "../components/SampleLoader";
import { MakeBuyBadge } from "../components/StatusChip";
import { mfgPaths } from "../lib/paths";
import { useLoad } from "../lib/useMfg";

const KPIS: { key: keyof SummaryCounts; label: string; sub?: (c: SummaryCounts) => string; to: string }[] = [
  { key: "items", label: "Items", sub: (c) => `${c.make} make · ${c.buy} buy · ${c.phantom} phantom`, to: mfgPaths.items() },
  { key: "bom_lines", label: "BOM lines", sub: (c) => `in ${c.boms} BOMs`, to: mfgPaths.items() },
  { key: "operations", label: "Operations", sub: (c) => `in ${c.routings} routings`, to: mfgPaths.items() },
  { key: "lines", label: "Lines", sub: (c) => `in ${c.groups} stages`, to: mfgPaths.groups() },
  { key: "shift_templates", label: "Shift templates", to: mfgPaths.shifts() },
  { key: "operators", label: "Operators", to: mfgPaths.operators() },
  { key: "tool_pools", label: "Tool pools", to: mfgPaths.tooling() },
];

function HealthCard({ tick }: { tick: number }) {
  const health = useLoad((signal) => getHealthReport({}, signal), [tick]);
  const r = health.data;
  return (
    <div className="card" data-testid="mfg-home-health" data-ok={r ? String(r.ok) : undefined}>
      <div className="card-header">
        <h2>Data health</h2>
        <Link to={mfgPaths.health()} className="btn sm">
          Open data health <Icon name="arrow-right" />
        </Link>
      </div>
      <div className="card-body">
        {health.loading && !r ? (
          <span className="row muted" role="status">
            <span className="spinner" aria-hidden /> Checking your data…
          </span>
        ) : null}
        <MfgError error={health.error} onRetry={health.reload} />
        {r ? (
          r.ok ? (
            <div className="row">
              <span className="badge ok">
                <Icon name="check" /> Ready for planning
              </span>
              <span className="muted small">
                {r.counts.warning} warnings · {r.counts.info} notes. Nothing blocks planning.
              </span>
            </div>
          ) : (
            <div className="row wrap">
              <span className="badge danger">
                <Icon name="x" /> {r.counts.error} {r.counts.error === 1 ? "problem blocks" : "problems block"} planning
              </span>
              <span className="muted small">
                {r.counts.warning} warnings · {r.counts.info} notes. Each problem has a "Fix" link.
              </span>
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}

function ResetDialog({ onClose, onDone }: { onClose(): void; onDone(): void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await resetMfg(text);
      onDone();
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title="Delete all manufacturing data?"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            Cancel
          </button>
          <button
            type="button"
            className="btn danger"
            disabled={text !== RESET_PHRASE || busy}
            onClick={() => void run()}
            data-testid="mfg-reset-confirm"
          >
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="trash" />}
            Delete everything
          </button>
        </>
      }
    >
      <p style={{ margin: 0 }}>
        Items, BOMs, routings, plant setup, shifts, people and tooling are deleted. Scheduling and finance plans are
        not affected. This cannot be undone.
      </p>
      <div className="field">
        <label htmlFor="mfg-reset-phrase">
          Type <code>{RESET_PHRASE}</code> to confirm
        </label>
        <input
          id="mfg-reset-phrase"
          className="input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoComplete="off"
          data-testid="mfg-reset-phrase"
        />
      </div>
      <MfgError error={error} title="Could not delete the data" />
    </Dialog>
  );
}

/** M2 12.3: additive `/summary` counts and the latest live run. Shown only when the server provides them. */
function PlanningCard({ summary }: { summary: Summary }) {
  const x = summary as Summary & { counts: SummaryM2Counts; latest_run?: SummaryLatestRun | null; published_schedule?: PublishedScheduleSummary | null };
  const ps = x.published_schedule ?? null;
  const c = x.counts;
  if (c.open_demand_lines === undefined) return null;
  const run = x.latest_run ?? null;
  const tiles: { label: string; value: number; to: string; bad?: boolean; testId: string }[] = [
    { label: "Open demand lines", value: c.open_demand_lines ?? 0, to: mfgPaths.demand(), testId: "mfg-count-open-demand" },
    { label: "Open work orders", value: c.open_work_orders ?? 0, to: mfgPaths.workOrders(), testId: "mfg-count-open-wo" },
    { label: "Open purchase orders", value: c.open_purchase_orders ?? 0, to: mfgPaths.purchaseDocs("po"), testId: "mfg-count-open-po" },
    { label: "Open purchase requests", value: c.open_purchase_requests ?? 0, to: mfgPaths.purchaseDocs("pr"), testId: "mfg-count-open-pr" },
    { label: "Overdue deliveries", value: c.overdue_schedules ?? 0, to: mfgPaths.deliveryBoard({ overdue: "1" }), bad: (c.overdue_schedules ?? 0) > 0, testId: "mfg-count-overdue" },
  ];
  return (
    <section className="card" data-testid="mfg-planning-card">
      <div className="card-header">
        <h2>Planning & stores</h2>
        <span className="row" style={{ gap: 6 }}>
        {ps ? (
          <Link to={mfgPaths.apsRun(ps.id)} className="btn sm" data-testid="mfg-published-schedule">
            Schedule #{ps.run_no}: {ps.late_orders ? `${ps.late_orders} late orders` : "all on time"}
            {ps.stale ? " (out of date)" : ""} <Icon name="arrow-right" />
          </Link>
        ) : (
          <Link to={mfgPaths.schedule()} className="btn sm">
            Schedule production <Icon name="arrow-right" />
          </Link>
        )}
        {run ? (
          <Link to={mfgPaths.run(run.id)} className="btn sm">
            MRP run #{run.run_no}: {run.demand_late ? `${run.demand_late} late` : "all on time"}
            {run.stale ? " (out of date)" : ""} <Icon name="arrow-right" />
          </Link>
        ) : (
          <Link to={mfgPaths.mrp()} className="btn sm">
            Run MRP <Icon name="arrow-right" />
          </Link>
        )}
        </span>
      </div>
      <div className="card-body kpis">
        {tiles.map((t) => (
          <Link key={t.label} to={t.to} className="card kpi mfg-kpi" data-testid={t.testId}>
            <div className="kpi-label">{t.label}</div>
            <div className="kpi-value" style={t.bad ? { color: "var(--danger)" } : undefined}>
              {t.value.toLocaleString()}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function MfgHome() {
  const [tick, setTick] = useState(0);
  const summary = useLoad((signal) => getSummary(signal), [tick]);
  const [loaded, setLoaded] = useState<SampleLoadResponse | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetDone, setResetDone] = useState(false);
  const c = summary.data?.counts;
  const empty = c ? c.items === 0 && c.groups === 0 : false;

  return (
    <div className="col gap-lg">
      <div className="page-header mfg-header">
        <div>
          <h1>Manufacturing</h1>
          <p>Describe your plant and your products, then plan materials: demand, stock, purchasing, MRP and work orders.</p>
        </div>
        <div className="row wrap">
          <Link className="btn" to={mfgPaths.importStart()}>
            <Icon name="upload" /> Import from Excel or CSV
          </Link>
          <ExportButtons />
        </div>
      </div>

      {loaded ? (
        <Banner
          tone={loaded.health.ok ? "ok" : "warn"}
          role="status"
          testId="sample-loaded"
          title={`Sample "${loaded.sample_id}" loaded`}
          actions={
            <Link className="btn sm" to={mfgPaths.items()}>
              Browse items
            </Link>
          }
        >
          {loaded.health.ok
            ? `Data health: ready for planning (${loaded.health.counts.warning} warnings, ${loaded.health.counts.info} notes).`
            : `Data health: ${loaded.health.counts.error} problems to fix.`}
        </Banner>
      ) : null}
      {resetDone ? (
        <Banner tone="ok" role="status" testId="mfg-reset-done" title="All manufacturing data was deleted" />
      ) : null}

      <MfgError error={summary.error} onRetry={summary.reload} />

      {empty ? (
        <Banner tone="accent" title="No manufacturing data yet" testId="mfg-empty">
          Load a sample below to explore, or import your item master and BOMs from Excel. You can also start by
          describing the plant (stages, lines and shifts) under Plant.
        </Banner>
      ) : null}

      {c ? (
        <div className="kpis" data-testid="mfg-summary">
          {KPIS.map((k) => (
            <Link key={k.key} to={k.to} className="card kpi mfg-kpi" data-testid={`mfg-count-${k.key}`}>
              <div className="kpi-label">{k.label}</div>
              <div className="kpi-value">{c[k.key].toLocaleString()}</div>
              {k.sub ? <div className="kpi-sub">{k.sub(c)}</div> : null}
            </Link>
          ))}
        </div>
      ) : summary.loading ? (
        <div className="empty" role="status">
          <span className="spinner" aria-hidden /> Loading…
        </div>
      ) : null}

      {summary.data ? <PlanningCard summary={summary.data} /> : null}

      <div className="grid-2">
        <HealthCard tick={tick} />
        <div className="card">
          <div className="card-header">
            <h2>End items</h2>
            <Link to={mfgPaths.items()} className="btn sm ghost">
              All items <Icon name="arrow-right" />
            </Link>
          </div>
          <div className="card-body">
            {summary.data && summary.data.end_items.length === 0 ? (
              <p className="muted small" style={{ margin: 0 }}>
                End items are the finished products: make items with a BOM or routing that are not used inside
                another item.
              </p>
            ) : null}
            <ul className="mfg-plain-list">
              {(summary.data?.end_items ?? []).map((it) => (
                <li key={it.id} className="row">
                  <Link to={mfgPaths.itemBom(it.id)} className="mono">
                    {it.part_number}
                  </Link>
                  <span className="grow muted small mfg-ellipsis">{it.description}</span>
                  <MakeBuyBadge value={it.make_buy} />
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <PermissionGate perm="owner">
        <SampleLoader
          onLoaded={(res) => {
            setLoaded(res);
            setResetDone(false);
            setTick((t) => t + 1);
          }}
        />
      </PermissionGate>

      <PermissionGate perm="owner">
      <details className="card mfg-danger-zone">
        <summary className="card-header">
          <span className="row">
            <Icon name="settings" /> Advanced
          </span>
        </summary>
        <div className="card-body row wrap">
          <span className="grow muted small">
            Start over: delete all manufacturing data of your account (scheduling and finance plans stay).
          </span>
          <button type="button" className="btn danger sm" onClick={() => setResetOpen(true)} data-testid="mfg-reset">
            <Icon name="trash" /> Delete all manufacturing data
          </button>
        </div>
      </details>
      </PermissionGate>
      {resetOpen ? (
        <ResetDialog
          onClose={() => setResetOpen(false)}
          onDone={() => {
            setResetOpen(false);
            setResetDone(true);
            setLoaded(null);
            setTick((t) => t + 1);
          }}
        />
      ) : null}
    </div>
  );
}

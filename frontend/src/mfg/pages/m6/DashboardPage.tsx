/**
 * `/mfg/dashboard` (M6 3.1): the plant's management tiles for 4 / 13 / 52 weeks with status (icon + text), trend,
 * targets and a drill-down link (server-built, internal only). Export to Excel / CSV (D2), a print layout (A4
 * landscape, CSS), the email digest subscription (3.3, hidden without SMTP) and, for the owner / plant admin, the
 * thresholds (D7) behind "Adjust targets".
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError } from "../../../api/client";
import { Icon } from "../../../components/Icon";
import { saveBlob } from "../../api/client";
import { createDigest, deleteDigest, exportDashboard, getDashboard, listDigests, putDashboardThresholds } from "../../api/clientM6";
import type { DashboardPeriod, DashboardResponse, DigestInput, ThresholdKey, ThresholdsInput } from "../../api/typesM6";
import { MfgError, Spinner } from "../../components/Feedback";
import { useAccess } from "../../lib/permissions";
import { errorText, useLoad } from "../../lib/useMfg";
import { isPeriod, orderedTiles, PeriodSelect, TileCard } from "./dashboardBits";

export const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const period: DashboardPeriod = isPeriod(params.get("period")) ? (params.get("period") as DashboardPeriod) : "13w";
  const dash = useLoad((signal) => getDashboard(period, signal), [period]);
  const access = useAccess();
  const [busy, setBusy] = useState<string | null>(null);
  const [exportErr, setExportErr] = useState<unknown>(null);
  const canTune = access.isOwner || access.can("owner") || Boolean(access.me?.roles?.includes("plant_admin"));
  useEffect(() => {
    document.title = "Plant dashboard - SuperPlanner";
  }, []);

  const exp = async (format: "xlsx" | "csv") => {
    setBusy(format);
    setExportErr(null);
    try {
      saveBlob(await exportDashboard(period, format));
    } catch (e) {
      setExportErr(e);
    } finally {
      setBusy(null);
    }
  };
  const d = dash.data;
  return (
    <div className="col gap-lg dash-print" data-testid="dashboard">
      <div className="row wrap" style={{ justifyContent: "space-between", gap: 12 }}>
        <div>
          <h1 style={{ margin: 0 }}>Plant dashboard</h1>
          <span className="muted small">
            {d ? `${d.plant.name ? `${d.plant.name} · ` : ""}as of ${new Date(d.as_of).toLocaleString()}` : ""}
          </span>
        </div>
        <div className="row wrap no-print" style={{ gap: 8 }}>
          <PeriodSelect value={period} onChange={(v) => setParams({ period: v }, { replace: true })} />
          <button type="button" className="btn" onClick={() => void exp("xlsx")} disabled={busy !== null} data-testid="dash-export-xlsx">
            {busy === "xlsx" ? <span className="spinner" aria-hidden /> : <Icon name="download" />} Excel
          </button>
          <button type="button" className="btn ghost" onClick={() => void exp("csv")} disabled={busy !== null} data-testid="dash-export-csv">
            {busy === "csv" ? <span className="spinner" aria-hidden /> : <Icon name="download" />} CSV
          </button>
          <button type="button" className="btn ghost" onClick={() => window.print()} data-testid="dash-print">
            <Icon name="file" /> Print
          </button>
        </div>
      </div>
      <MfgError error={exportErr} title="Export failed" />
      {dash.error && !d ? <MfgError error={dash.error} onRetry={dash.reload} /> : null}
      {dash.loading && !d ? <Spinner /> : null}
      {d ? (
        <div className="dash-grid" data-testid="dash-tiles">
          {orderedTiles(d.tiles).map(([k, t]) => (
            <TileCard key={k} name={k} tile={t} currency={d.plant.currency} />
          ))}
        </div>
      ) : null}
      <div className="no-print col gap-lg">
        <DigestSettings scope="plant" scopeId={access.me?.workspace_owner_id ?? ""} />
        {canTune && d ? <Thresholds dash={d} onSaved={dash.reload} /> : null}
        <p className="muted small" style={{ margin: 0 }}>
          The organisation view with all plants is on the organisation page. <Link to="/orgs">Organisations</Link>
        </p>
      </div>
    </div>
  );
}

/** Email digest (3.3). Without SMTP on the server the email part is hidden; the push topic still works (mobile). */
export function DigestSettings({ scope, scopeId }: { scope: "plant" | "org"; scopeId: string }) {
  const list = useLoad((signal) => listDigests(signal), []);
  const [noSmtp, setNoSmtp] = useState(false);
  const [f, setF] = useState<{ frequency: "daily" | "weekly"; local_time: string; weekday: number }>({ frequency: "weekly", local_time: "07:00", weekday: 0 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const mine = (list.data?.items ?? []).filter((x) => x.scope === scope && x.scope_id === scopeId);
  const emailOff = noSmtp;

  const add = async () => {
    setBusy(true);
    setErr(null);
    const body: DigestInput = { scope, scope_id: scopeId, frequency: f.frequency, local_time: f.local_time, weekday: f.frequency === "weekly" ? f.weekday : null };
    try {
      await createDigest(body);
      list.reload();
    } catch (e) {
      if (e instanceof ApiError && (e.code === "DIGEST_NO_SMTP" || e.details?.code === "DIGEST_NO_SMTP")) setNoSmtp(true);
      else setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" data-testid="digest-settings" aria-labelledby="digest-h">
      <div className="card-header">
        <h2 id="digest-h">Email digest</h2>
      </div>
      <div className="card-body col">
        {list.error && !list.data ? <MfgError error={list.error} onRetry={list.reload} /> : null}
        {emailOff ? (
          <p className="muted" style={{ margin: 0 }} data-testid="digest-no-smtp">
            <Icon name="info" size={14} /> Email is not set up on this server, so digests by email are off. On a phone you can get a push message when the
            digest is ready (SuperPlanner mobile, Notifications).
          </p>
        ) : (
          <>
            <p className="muted small" style={{ margin: 0 }}>
              A summary of these tiles and the top 10 alerts, with a CSV attached. It only contains what you may see.
            </p>
            {mine.length ? (
              <ul className="mfg-plain-list">
                {mine.map((s) => (
                  <li key={s.id} className="row" style={{ gap: 8 }} data-testid="digest-row">
                    <Icon name="calendar" size={14} />
                    {s.frequency === "daily" ? "Every day" : `Every ${WEEKDAY_NAMES[s.weekday ?? 0] ?? "week"}`} at {s.local_time}
                    {s.time_zone ? <span className="muted small">({s.time_zone})</span> : null}
                    {s.last_sent_at ? <span className="muted small">last sent {new Date(s.last_sent_at).toLocaleString()}</span> : null}
                    <button type="button" className="btn ghost sm" onClick={() => void deleteDigest(s.id).then(list.reload, setErr)} aria-label="Stop this digest">
                      <Icon name="trash" /> Stop
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="row wrap" style={{ gap: 8, alignItems: "flex-end" }}>
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor="digest-freq">How often</label>
                <select id="digest-freq" className="select" value={f.frequency} onChange={(e) => setF({ ...f, frequency: e.target.value as "daily" | "weekly" })} data-testid="digest-frequency">
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </div>
              {f.frequency === "weekly" ? (
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="digest-day">On</label>
                  <select id="digest-day" className="select" value={f.weekday} onChange={(e) => setF({ ...f, weekday: Number(e.target.value) })}>
                    {WEEKDAY_NAMES.map((n, i) => (
                      <option key={n} value={i}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor="digest-time">At (plant time)</label>
                <input id="digest-time" type="time" className="input" value={f.local_time} onChange={(e) => setF({ ...f, local_time: e.target.value })} />
              </div>
              <button type="button" className="btn" onClick={() => void add()} disabled={busy || !scopeId || !f.local_time} data-testid="digest-add">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="plus" />} Send me this digest
              </button>
            </div>
          </>
        )}
        <MfgError error={err} title="Could not save the digest" />
      </div>
    </section>
  );
}

/** D7 keys (`model_m6.DEFAULT_THRESHOLDS`): direction, unit and the server defaults. */
const THRESHOLD_ROWS: { key: ThresholdKey; label: string; dir: "below" | "above"; unit: "%" | "count"; watch: number; alert: number }[] = [
  { key: "otd", label: "On-time delivery", dir: "below", unit: "%", watch: 0.95, alert: 0.85 },
  { key: "adherence", label: "Schedule adherence", dir: "below", unit: "%", watch: 0.85, alert: 0.7 },
  { key: "fpy", label: "First-pass yield", dir: "below", unit: "%", watch: 0.98, alert: 0.95 },
  { key: "backlog_load", label: "Backlog vs capacity", dir: "above", unit: "%", watch: 0.9, alert: 1.1 },
  { key: "material_risk", label: "Items short (material risk)", dir: "above", unit: "count", watch: 1, alert: 10 },
  { key: "late_pos", label: "Late purchase orders", dir: "above", unit: "count", watch: 1, alert: 10 },
];
const TILE_OF: Partial<Record<ThresholdKey, string>> = { otd: "otd", backlog_load: "backlog", material_risk: "material_risk", late_pos: "late_pos" };

/** D7: watch / attention targets per measure (owner, plant admin). Percentages are entered as percent. */
function Thresholds({ dash, onSaved }: { dash: DashboardResponse; onSaved(): void }) {
  const [open, setOpen] = useState(false);
  const init = () => {
    const out: Record<string, { watch: string; alert: string }> = {};
    for (const r of THRESHOLD_ROWS) {
      const th = (TILE_OF[r.key] ? dash.tiles[TILE_OF[r.key]!]?.thresholds : undefined) ?? {};
      const w = r.dir === "below" ? th.watch_below : th.watch_above;
      const a = r.dir === "below" ? th.alert_below : th.alert_above;
      const k = r.unit === "%" ? 100 : 1;
      const show = (v: unknown, d: number) => String(+((typeof v === "number" ? v : d) * k).toFixed(4));
      out[r.key] = { watch: show(w, r.watch), alert: show(a, r.alert) };
    }
    return out;
  };
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    const out: ThresholdsInput["thresholds"] = {};
    for (const r of THRESHOLD_ROWS) {
      const k = r.unit === "%" ? 100 : 1;
      const v = (s: string) => (s.trim() === "" ? null : Number(s) / k);
      out[r.key] = r.dir === "below" ? { watch_below: v(f[r.key].watch), alert_below: v(f[r.key].alert) } : { watch_above: v(f[r.key].watch), alert_above: v(f[r.key].alert) };
    }
    try {
      await putDashboardThresholds({ thresholds: out });
      setMsg("Saved");
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const bad = Object.values(f).some((v) => [v.watch, v.alert].some((s) => s.trim() !== "" && !(Number.isFinite(Number(s)) && Number(s) >= 0)));
  return (
    <section className="card" data-testid="dash-thresholds">
      <div className="card-body col">
        <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={open} onClick={() => setOpen((v) => !v)} data-testid="dash-thresholds-toggle">
          <Icon name={open ? "chevron-down" : "chevron-right"} /> Adjust targets (owner, plant admin)
        </button>
        {open ? (
          <>
            <p className="muted small" style={{ margin: 0 }}>
              A tile shows "Watch" past the watch value and "Needs attention" past the attention value. Percentages are entered as percent.
            </p>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Measure</th>
                    <th scope="col">Watch</th>
                    <th scope="col">Needs attention</th>
                  </tr>
                </thead>
                <tbody>
                  {THRESHOLD_ROWS.map((r) => (
                    <tr key={r.key}>
                      <th scope="row" style={{ fontWeight: 500 }}>
                        {r.label} <span className="muted small">({r.dir}{r.unit === "%" ? ", %" : ""})</span>
                      </th>
                      {(["watch", "alert"] as const).map((which) => (
                        <td key={which}>
                          <input
                            className="input"
                            inputMode="decimal"
                            aria-label={`${r.label}: ${which === "watch" ? "watch" : "needs attention"} ${r.dir}${r.unit === "%" ? " (%)" : ""}`}
                            value={f[r.key][which]}
                            onChange={(e) => setF({ ...f, [r.key]: { ...f[r.key], [which]: e.target.value } })}
                            data-testid={`threshold-${r.key}-${which}`}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button type="button" className="btn primary" disabled={busy || bad} onClick={() => void save()} data-testid="thresholds-save">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} Save targets
              </button>
              {msg ? <span role="status">{msg}</span> : null}
            </div>
            {err ? <p className="field-error">{errorText(err)}</p> : null}
          </>
        ) : null}
      </div>
    </section>
  );
}

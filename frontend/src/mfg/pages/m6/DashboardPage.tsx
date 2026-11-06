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
import type { DashboardPeriod, DashboardResponse, DashboardThresholds, DigestInput } from "../../api/typesM6";
import { MfgError, Spinner } from "../../components/Feedback";
import { useAccess } from "../../lib/permissions";
import { errorText, useLoad, usePlant } from "../../lib/useMfg";
import { isPeriod, orderedTiles, PeriodSelect, TileCard, tileName } from "./dashboardBits";

export const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const period: DashboardPeriod = isPeriod(params.get("period")) ? (params.get("period") as DashboardPeriod) : "13w";
  const dash = useLoad((signal) => getDashboard(period, signal), [period]);
  const plant = usePlant();
  const access = useAccess();
  const [busy, setBusy] = useState<string | null>(null);
  const [exportErr, setExportErr] = useState<unknown>(null);
  const canTune = access.isOwner || Boolean(access.me?.roles?.includes("plant_admin"));
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
            {plant.data?.name ? `${plant.data.name} · ` : ""}
            {d ? `as of ${new Date(d.as_of).toLocaleString()}` : ""}
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
            <TileCard key={k} name={k} tile={t} currency={plant.data?.currency} />
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
  const emailOff = noSmtp || list.data?.email_available === false;

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

/** D7: per-tile watch / alert targets (owner, plant admin). Values in the tile's unit; ratios as percent. */
function Thresholds({ dash, onSaved }: { dash: DashboardResponse; onSaved(): void }) {
  const [open, setOpen] = useState(false);
  const tiles = orderedTiles(dash.tiles).filter(([, t]) => t.thresholds);
  const init = () => {
    const out: Record<string, { watch: string; alert: string }> = {};
    for (const [k, t] of tiles) {
      const pct = t.unit === "ratio" ? 100 : 1;
      const w = t.thresholds?.watch;
      const a = t.thresholds?.alert;
      out[k] = { watch: typeof w === "number" ? String(+(w * pct).toFixed(4)) : "", alert: typeof a === "number" ? String(+(a * pct).toFixed(4)) : "" };
    }
    return out;
  };
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  if (!tiles.length) return null;
  const save = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    const out: DashboardThresholds = {};
    for (const [k, t] of tiles) {
      const pct = t.unit === "ratio" ? 100 : 1;
      const num = (s: string) => (s.trim() === "" ? null : Number(s) / pct);
      out[k] = { watch: num(f[k].watch), alert: num(f[k].alert) };
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
  const bad = Object.values(f).some((v) => [v.watch, v.alert].some((s) => s.trim() !== "" && !Number.isFinite(Number(s))));
  return (
    <section className="card" data-testid="dash-thresholds">
      <div className="card-body col">
        <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <Icon name={open ? "chevron-down" : "chevron-right"} /> Adjust targets (owner, plant admin)
        </button>
        {open ? (
          <>
            <p className="muted small" style={{ margin: 0 }}>
              A tile shows "Watch" below the watch value and "Needs attention" below the alert value. Percentages are entered as percent.
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>Tile</th>
                  <th>Watch below</th>
                  <th>Needs attention below</th>
                </tr>
              </thead>
              <tbody>
                {tiles.map(([k, t]) => (
                  <tr key={k}>
                    <td>{tileName(k, t)}</td>
                    {(["watch", "alert"] as const).map((which) => (
                      <td key={which}>
                        <input
                          className="input"
                          inputMode="decimal"
                          aria-label={`${tileName(k, t)}: ${which === "watch" ? "watch below" : "needs attention below"}${t.unit === "ratio" ? " (%)" : ""}`}
                          value={f[k]?.[which] ?? ""}
                          onChange={(e) => setF({ ...f, [k]: { ...f[k], [which]: e.target.value } })}
                          data-testid={`threshold-${k}-${which}`}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
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

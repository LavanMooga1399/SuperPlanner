/**
 * Integration console (M5 4, `/mfg/integration/*`, `integration_admin`): how this plant talks to its ERP through
 * `superplanner.v1` (adapter `generic_v1`, 14 Q1).
 * - Overview: health at a glance (failed and waiting deliveries, rejected records, last data in, file drop).
 * - Settings: on/off, who owns each kind of data (system of record), who books goods receipts (14 Q2), file drop
 *   and file export.
 * - Endpoints (webhooks), Deliveries (retry / park), Data in (batches with per-record results), Events (the outbox
 *   feed), File drop, Code mappings, Reconciliation, Plant tokens: in IntegrationPages2.tsx.
 */
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { getFiledropStatus, getIntegrationSettings, listBatches, listDeliveries, updateIntegrationSettings } from "../../api/clientM5";
import { SOR_ENTITIES, type IntegrationSettings, type SorEntity, type SorValue } from "../../api/typesM5";
import { MfgError, Spinner } from "../../components/Feedback";
import { invalidateErpOwnership } from "../../lib/erpOwnership";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { isConflict, useLoad } from "../../lib/useMfg";

export const SOR_LABEL: Record<SorEntity, { label: string; help: string; allowed: SorValue[] }> = {
  items: { label: "Items", help: "Part number, description, unit, make/buy, cost. Planning settings (lot sizes, safety stock, families) always stay here.", allowed: ["erp", "superplanner", "shared"] },
  boms: { label: "BOMs", help: "Whole structure; changes from the ERP are recorded as engineering changes.", allowed: ["erp", "superplanner"] },
  routings: { label: "Routings", help: "Operations and times; line rates and changeovers stay here.", allowed: ["erp", "superplanner"] },
  suppliers: { label: "Suppliers", help: "All except the preferred flag.", allowed: ["erp", "superplanner", "shared"] },
  item_suppliers: { label: "Item suppliers", help: "Prices, lead times, MOQ per supplier.", allowed: ["erp", "superplanner", "shared"] },
  purchase_orders: { label: "Purchase orders", help: "Header, lines and delivery schedules.", allowed: ["erp", "superplanner"] },
  po_receipts: { label: "Goods receipts", help: "See below.", allowed: ["erp", "superplanner"] },
  demand_orders: { label: "Customer demand", help: "All except priority.", allowed: ["erp", "superplanner"] },
  purchase_requests: { label: "Purchase requests", help: "Raised here, sent to the ERP.", allowed: ["superplanner"] },
  work_orders: { label: "Work orders", help: "Created and run here, sent to the ERP.", allowed: ["superplanner", "erp"] },
  floor: { label: "Shop-floor results", help: "Good, scrap, labour; sent to the ERP.", allowed: ["superplanner"] },
  transfers: { label: "Transfers between plants", help: "Sent to the ERP.", allowed: ["superplanner"] },
  stock: { label: "Stock movements", help: "The ledger here is the record; ERP stock is compared in Reconciliation.", allowed: ["superplanner", "erp"] },
};

const SOR_TEXT: Record<SorValue, string> = { erp: "ERP", superplanner: "SuperPlanner", shared: "Both (last change wins)" };

const TABS: { key: string; label: string }[] = [
  { key: "", label: "Overview" },
  { key: "settings", label: "Settings" },
  { key: "endpoints", label: "Webhooks" },
  { key: "deliveries", label: "Deliveries" },
  { key: "batches", label: "Data in" },
  { key: "events", label: "Events out" },
  { key: "filedrop", label: "File drop" },
  { key: "value-maps", label: "Code mappings" },
  { key: "reconciliation", label: "Reconciliation" },
  { key: "tokens", label: "Plant tokens" },
];

export function IntegrationLayout() {
  const can = useCan("integration_admin");
  useEffect(() => {
    document.title = "Integration - SuperPlanner";
  }, []);
  return (
    <div className="col gap-lg" data-testid="integration">
      <div className="mfg-page-head">
        <div>
          <h1>ERP integration</h1>
          <p>Data in from the ERP, events out to it, and who owns what. Uses the vendor-neutral format superplanner.v1.</p>
        </div>
      </div>
      {!can ? (
        <Banner tone="info" title="Plant admins manage the integration">
          {needsText("integration_admin")}
        </Banner>
      ) : null}
      <nav className="tabs" aria-label="Integration sections">
        {TABS.map((t) => (
          <NavLink key={t.key} to={mfgPaths.integration(t.key || undefined)} end={!t.key} className={({ isActive }) => `tab${isActive ? " active" : ""}`} data-testid={`int-tab-${t.key || "overview"}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}

export function IntegrationOverview() {
  const st = useLoad((signal) => getIntegrationSettings(signal), []);
  const dead = useLoad((signal) => listDeliveries({ status: "dead", limit: 1 }, signal).catch(() => null), []);
  const waiting = useLoad((signal) => listDeliveries({ status: "pending", limit: 1 }, signal).catch(() => null), []);
  const batches = useLoad((signal) => listBatches({ limit: 5 }, signal).catch(() => null), []);
  const fd = useLoad((signal) => getFiledropStatus(signal).catch(() => null), []);
  const s = st.data;
  if (st.loading && !s) return <Spinner />;
  if (!s) return <MfgError error={st.error} onRetry={st.reload} />;
  const last = batches.data?.items[0] ?? null;
  const rejected = (batches.data?.items ?? []).reduce((a, b) => a + (b.counts.rejected ?? 0), 0);
  return (
    <div className="col gap-lg" data-testid="int-overview" data-enabled={s.enabled}>
      {!s.enabled ? (
        <Banner tone="info" title="The integration is off for this plant" actions={<Link className="btn sm primary" to={mfgPaths.integration("settings")}>Set it up</Link>}>
          Nothing is sent to an ERP and ERP data is not accepted. Turn it on under Settings.
        </Banner>
      ) : null}
      <div className="kpis">
        <Link to={`${mfgPaths.integration("deliveries")}?status=dead`} className="card kpi" style={{ textDecoration: "none", color: "inherit" }} data-testid="int-kpi-dead">
          <div className="kpi-label">Failed deliveries</div>
          <div className="kpi-value" style={{ color: dead.data?.total ? "var(--danger)" : undefined }}>
            {dead.data?.total ?? "–"} {dead.data?.total ? <Icon name="alert" size={16} /> : null}
          </div>
          <div className="kpi-sub">stopped after 24 h of retries</div>
        </Link>
        <Link to={`${mfgPaths.integration("deliveries")}?status=pending`} className="card kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="kpi-label">Waiting to send</div>
          <div className="kpi-value">{waiting.data?.total ?? "–"}</div>
          <div className="kpi-sub">incl. retries; later events of a failing webhook wait</div>
        </Link>
        <Link to={mfgPaths.integration("batches")} className="card kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="kpi-label">Last data in</div>
          <div className="kpi-value" style={{ fontSize: 18 }}>
            {last ? new Date(last.received_at).toLocaleString() : "none yet"}
          </div>
          <div className="kpi-sub">{rejected ? `${rejected} rejected records in the last 5 batches` : "no rejected records recently"}</div>
        </Link>
        <Link to={mfgPaths.integration("filedrop")} className="card kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="kpi-label">File drop</div>
          <div className="kpi-value" style={{ fontSize: 18 }}>
            {!fd.data?.enabled ? "off" : fd.data.inbox.length ? `${fd.data.inbox.length} waiting` : "ok"}
          </div>
          <div className="kpi-sub">{fd.data?.last_poll_at ? `checked ${new Date(fd.data.last_poll_at).toLocaleTimeString()}` : ""}</div>
        </Link>
      </div>
      <section className="card">
        <div className="card-header">
          <h2>Who owns what</h2>
          <Link to={mfgPaths.integration("settings")} className="small">
            Change
          </Link>
        </div>
        <SorSummary s={s} />
      </section>
    </div>
  );
}

function SorSummary({ s }: { s: IntegrationSettings }) {
  return (
    <div className="table-wrap">
      <table className="table" data-testid="sor-summary">
        <tbody>
          {SOR_ENTITIES.map((e) => (
            <tr key={e} data-entity={e} data-sor={s.sor[e] ?? "superplanner"}>
              <td>{SOR_LABEL[e].label}</td>
              <td>
                {(s.sor[e] ?? "superplanner") === "erp" ? (
                  <span className="badge info">
                    <Icon name="lock" size={12} /> ERP
                  </span>
                ) : (s.sor[e] ?? "superplanner") === "shared" ? (
                  <span className="badge warn">
                    <Icon name="refresh" size={12} /> Both
                  </span>
                ) : (
                  <span className="badge ok">
                    <Icon name="check" size={12} /> SuperPlanner
                  </span>
                )}
              </td>
              <td className="small muted">{SOR_LABEL[e].help}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function IntegrationSettingsTab() {
  const can = useCan("integration_admin");
  const st = useLoad((signal) => getIntegrationSettings(signal), []);
  const [f, setF] = useState<IntegrationSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [expert, setExpert] = useState(false);
  useEffect(() => {
    if (st.data) setF(st.data);
  }, [st.data]);
  if (!f) return st.error ? <MfgError error={st.error} onRetry={st.reload} /> : <Spinner />;
  const setSor = (e: SorEntity, v: SorValue) => setF({ ...f, sor: { ...f.sor, [e]: v }, ...(e === "po_receipts" ? { goods_receipts_owner: v === "erp" ? "erp" : "superplanner" } : {}) });
  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const { row_version: _v, adapters: _a, ...body } = f;
      const next = await updateIntegrationSettings(body, f.row_version);
      setF(next);
      setSaved(true);
      setConflict(false);
      invalidateErpOwnership();
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="col gap-lg"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="int-settings"
    >
      {conflict ? (
        <Banner tone="warn" title="Someone else changed the settings" actions={<button type="button" className="btn sm" onClick={() => { setConflict(false); st.reload(); }}>Reload</button>}>
          Your changes were not saved.
        </Banner>
      ) : null}
      <section className="card">
        <div className="card-body col">
          <label className="checkbox">
            <input type="checkbox" checked={f.enabled} disabled={!can} onChange={(e) => setF({ ...f, enabled: e.target.checked })} data-testid="int-enabled" />
            <span>
              <strong>Connect this plant to an ERP</strong> <span className="muted small">Records changes for the ERP and accepts ERP data. Off = this plant works on its own.</span>
            </span>
          </label>
          <div className="field" style={{ maxWidth: 320 }}>
            <label htmlFor="int-code">Plant code for files and events</label>
            <input id="int-code" className="input mono" value={f.plant_code} disabled={!can} onChange={(e) => setF({ ...f, plant_code: e.target.value.replace(/[^A-Za-z0-9_.-]/g, "") })} maxLength={32} required data-testid="int-plant-code" />
            <span className="hint">Letters, digits, - _ . : names this plant's folder on the integration volume and appears in every event.</span>
          </div>
          <div className="field" style={{ maxWidth: 320 }}>
            <label htmlFor="int-adapter">Format</label>
            <select id="int-adapter" className="select" value={f.adapter} disabled={!can} onChange={(e) => setF({ ...f, adapter: e.target.value })}>
              {(f.adapters?.length ? f.adapters : ["generic_v1"]).map((a) => (
                <option key={a} value={a}>
                  {a === "generic_v1" ? "Generic (superplanner.v1): REST, files, webhooks" : a}
                </option>
              ))}
            </select>
            <span className="hint">ERP-specific formats are added once your ERP is known; your ERP's integration layer can map to this format today.</span>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>Who owns what</h2>
          <span className="muted small">Data owned by the ERP is read-only here; data owned here is rejected when the ERP sends it.</span>
        </div>
        <div className="table-wrap">
          <table className="table" data-testid="sor-table">
            <thead>
              <tr>
                <th>Data</th>
                <th>Owned by</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {SOR_ENTITIES.filter((e) => e !== "po_receipts").map((e) => {
                const m = SOR_LABEL[e];
                const v = f.sor[e] ?? "superplanner";
                return (
                  <tr key={e} data-entity={e}>
                    <td>{m.label}</td>
                    <td>
                      {m.allowed.length > 1 ? (
                        <select className="select sm" aria-label={`${m.label} owned by`} value={v} disabled={!can} onChange={(ev) => setSor(e, ev.target.value as SorValue)} data-testid={`sor-${e}`}>
                          {m.allowed.map((a) => (
                            <option key={a} value={a}>
                              {SOR_TEXT[a]}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span>{SOR_TEXT[v]}</span>
                      )}
                    </td>
                    <td className="small muted">{m.help}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>Goods receipts against purchase orders</h2>
        </div>
        <div className="card-body col" role="radiogroup" aria-label="Who books goods receipts" data-testid="int-receipts-owner">
          <label className="checkbox">
            <input type="radio" name="gr" checked={f.goods_receipts_owner === "superplanner"} disabled={!can} onChange={() => setF({ ...f, goods_receipts_owner: "superplanner", sor: { ...f.sor, po_receipts: "superplanner" } })} data-testid="gr-superplanner" />
            <span>
              <strong>Booked here</strong> <span className="muted small">Stores receive in SuperPlanner; each receipt is sent to the ERP.</span>
            </span>
          </label>
          <label className="checkbox">
            <input type="radio" name="gr" checked={f.goods_receipts_owner === "erp"} disabled={!can} onChange={() => setF({ ...f, goods_receipts_owner: "erp", sor: { ...f.sor, po_receipts: "erp" } })} data-testid="gr-erp" />
            <span>
              <strong>Booked in the ERP</strong> <span className="muted small">Receiving here is switched off; the ERP sends each receipt in.</span>
            </span>
          </label>
        </div>
      </section>

      <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={expert} onClick={() => setExpert((v) => !v)}>
        <Icon name="settings" /> Files (file drop and export)
      </button>
      {expert ? (
        <section className="card">
          <div className="card-body col">
            <label className="checkbox">
              <input type="checkbox" checked={f.filedrop_enabled} disabled={!can} onChange={(e) => setF({ ...f, filedrop_enabled: e.target.checked })} />
              <span>
                <strong>Read files from the inbox folder</strong> <span className="muted small">CSV, Excel or JSON dropped by the ERP (or an SFTP server) are imported with the saved mapping.</span>
              </span>
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={f.export_enabled} disabled={!can} onChange={(e) => setF({ ...f, export_enabled: e.target.checked })} />
              <span>
                <strong>Also write events as files</strong> <span className="muted small">CSV per event type and JSON lines in the outbox folder.</span>
              </span>
            </label>
            {f.export_enabled ? (
              <div className="field" style={{ maxWidth: 220 }}>
                <label htmlFor="int-every">Every (minutes, 5-1440)</label>
                <input id="int-every" className="input" type="number" min={5} max={1440} value={f.export_interval_minutes} disabled={!can} onChange={(e) => setF({ ...f, export_interval_minutes: Number(e.target.value) || 15 })} />
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
      <MfgError error={error} />
      {can ? (
        <div className="row">
          <button type="submit" className="btn primary" disabled={busy || !f.plant_code.trim()} data-testid="int-settings-save">
            <Icon name="save" /> Save
          </button>
          {saved ? (
            <span className="badge ok">
              <Icon name="check" /> Saved
            </span>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}

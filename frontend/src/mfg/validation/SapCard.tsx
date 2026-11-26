/**
 * SAP S/4HANA card on the integration console (M8 9, 12): connection settings (OData base URL and version, plant,
 * basic or OAuth2 client credentials - secrets are write-only), unit and storage location maps folded under expert
 * settings, the last pull per entity with its cursor, and "Sync now" for the inbound entities. Shown only to
 * `integration_admin`.
 */
import { useState } from "react";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { toast } from "../../components/Toast";
import { t } from "../../lib/i18n";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { getSapSettings, syncSap, updateSapSettings } from "../api/clientM8";
import { SAP_IN_ENTITIES, type SapSettings, type SapSettingsInput } from "../api/typesM8";
import { DataTable } from "../components/DataTable";
import { ConflictBanner, MfgError, Spinner } from "../components/Feedback";
import { FormErrors } from "../components/Field";
import { useCan } from "../lib/permissions";
import { isConflict, useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";

const ENTITY_KEY: Record<string, "plan.sap.e.product"> = Object.fromEntries(
  ["product", "bom", "routing", "supplier", "info_record", "stock", "purchase_order", "sales_order", "billing", "planned_order_out", "pr_out", "pir_out", "confirmation_out"].map((e) => [e, `plan.sap.e.${e}` as "plan.sap.e.product"]),
);
const entityText = (e: string) => (ENTITY_KEY[e] ? t(ENTITY_KEY[e]) : e);

const mapText = (m: Record<string, string>) => Object.entries(m).map(([k, v]) => `${k}=${v}`).join("\n");
const parseMap = (s: string) => Object.fromEntries(s.split(/\n|,/).map((x) => x.split("=").map((y) => y.trim())).filter((p) => p.length === 2 && p[0] && p[1]));

export function SapCard() {
  const canAdmin = useCan("integration_admin");
  const st = useLoad((s) => (canAdmin ? getSapSettings(s) : null), [canAdmin]);
  const [editing, setEditing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (!canAdmin) return null;
  const s = st.data;
  const sync = async () => {
    setSyncing(true);
    setErr(null);
    try {
      const r = await syncSap([...SAP_IN_ENTITIES]);
      toast(t("plan.sap.toast.sync", { n: r.entities.length }));
      st.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setSyncing(false);
    }
  };
  const rows = s ? [...new Set([...SAP_IN_ENTITIES, ...Object.keys(s.last_sync)])].map((e) => ({ e, last: s.last_sync[e] ?? null, cursor: s.cursors[e] ?? null })) : [];
  return (
    <section className="card" data-testid="sap-card" aria-labelledby="sap-h">
      <div className="card-header pl-card-header">
        <h2 className="pl-h2" id="sap-h">
          {t("plan.sap.title")}{" "}
          {s ? (
            <span className={`badge ${s.enabled ? "ok" : "info"}`} data-testid="sap-enabled">
              <Icon name={s.enabled ? "check" : "circle"} /> {s.enabled ? t("plan.sap.on") : t("plan.sap.off")}
            </span>
          ) : null}
        </h2>
        <span className="row" style={{ gap: 6 }}>
          <button type="button" className="btn sm" disabled={!s} onClick={() => setEditing(true)} data-testid="sap-edit">
            <Icon name="settings" /> {t("plan.sap.btn.settings")}
          </button>
          <button type="button" className="btn sm primary" disabled={!s?.enabled || syncing} title={s?.enabled ? undefined : t("plan.sap.hint.enable")} onClick={() => void sync()} data-testid="sap-sync">
            {syncing ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} {t("plan.sap.btn.sync")}
          </button>
        </span>
      </div>
      <MfgError error={err} />
      <MfgError error={st.error} onRetry={st.reload} />
      {st.loading && !s ? <Spinner /> : null}
      {s ? (
        <>
          <div className="card-body">
            <p className="muted small" style={{ margin: "0 0 8px" }}>{t("plan.sap.desc")}</p>
            <dl className="pl-facts">
              <div><dt>{t("plan.sap.f.url")}</dt><dd className="mono mfg-ellipsis" title={s.base_url}>{s.base_url || "–"}</dd></div>
              <div><dt>{t("plan.sap.f.plant")}</dt><dd className="mono">{s.plant || "–"}</dd></div>
              <div><dt>{t("plan.sap.f.version")}</dt><dd>{t("plan.sap.odata", { v: s.odata_version })}</dd></div>
              <div><dt>{t("plan.sap.f.auth")}</dt><dd>{s.auth === "basic" ? t("plan.sap.auth.basic") : t("plan.sap.auth.oauth2")}</dd></div>
              <div><dt>{t("plan.sap.f.secret")}</dt><dd>{(s.auth === "basic" ? s.password_set : s.client_secret_set) ? t("plan.sap.secret.set") : t("plan.sap.secret.missing")}</dd></div>
            </dl>
          </div>
          <DataTable
            rows={rows}
            rowKey={(r) => r.e}
            label={t("plan.sap.sync.title")}
            testId="sap-sync-table"
            columnSettings={false}
            columns={[
              { key: "e", header: t("plan.sap.sync.entity"), width: "minmax(160px, 1fr)", render: (r) => entityText(r.e) },
              {
                key: "status",
                header: t("plan.sap.sync.status"),
                width: "200px",
                render: (r) =>
                  !r.last ? (
                    <span className="muted">{t("plan.sap.sync.never")}</span>
                  ) : r.last.status === "completed" ? (
                    <span className="badge ok"><Icon name="check" /> {t("plan.status.done")}</span>
                  ) : r.last.status === "failed" ? (
                    <span className="pl-by">
                      <span className="badge danger"><Icon name="x" /> {t("plan.status.failed")}</span>
                      {r.last.error ? <span className="mono small" data-testid="sap-error">{r.last.error}</span> : null}
                    </span>
                  ) : (
                    <span className="badge accent"><Icon name="loader" /> {t("plan.status.running")}</span>
                  ),
              },
              { key: "at", header: t("plan.sap.sync.at"), width: "150px", render: (r) => (r.last?.at ? formatDateTime(r.last.at) : "") },
              {
                key: "n",
                header: t("plan.sap.sync.records"),
                width: "130px",
                align: "right",
                render: (r) => (
                  <span className="pl-by">
                    <span className="pl-num">{r.last?.records !== null && r.last?.records !== undefined ? formatNumber(r.last.records) : ""}</span>
                    {r.last?.packaging_skipped ? <span className="muted small" title={t("plan.sap.hint.packSkipped")}>{t("plan.sap.sync.packSkipped", { n: formatNumber(r.last.packaging_skipped) })}</span> : null}
                  </span>
                ),
              },
              { key: "cursor", header: t("plan.sap.sync.cursor"), width: "minmax(160px, 1fr)", drop: 1, render: (r) => (r.cursor ? <span className="mono small">{r.cursor}</span> : <span className="muted">–</span>) },
            ]}
          />
        </>
      ) : null}
      {editing && s ? <SapDialog s={s} onClose={() => setEditing(false)} onSaved={(n) => {
        st.setData(n);
        setEditing(false);
      }} /> : null}
    </section>
  );
}

function SapDialog({ s, onClose, onSaved }: { s: SapSettings; onClose(): void; onSaved(n: SapSettings): void }) {
  const reason = useChangeReason();
  const [f, setF] = useState<SapSettingsInput>({
    enabled: s.enabled,
    base_url: s.base_url,
    odata_version: s.odata_version,
    plant: s.plant,
    auth: s.auth,
    username: s.username,
    password: null,
    token_url: s.token_url,
    client_id: s.client_id,
    client_secret: null,
    location_map: s.location_map,
    unit_map: s.unit_map,
    mrp_controllers: s.mrp_controllers,
    strip_zeros: s.strip_zeros,
    order_types: s.order_types,
    page_size: s.page_size,
    schedule: s.schedule,
  });
  const [units, setUnits] = useState(mapText(s.unit_map));
  const [locs, setLocs] = useState(mapText(s.location_map));
  const [expert, setExpert] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const set = (x: Partial<SapSettingsInput>) => setF({ ...f, ...x });
  const save = async () => {
    const r = await reason.ask(t("plan.sap.what"));
    if (r === null) return;
    setBusy(true);
    setErr(null);
    try {
      onSaved(await updateSapSettings({ ...f, unit_map: parseMap(units), location_map: parseMap(locs) }, s.row_version, r));
      toast(t("plan.sap.toast.saved"));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const field = (id: string, label: string, value: string, on: (v: string) => void, opts: { type?: string; ph?: string; hint?: string; name?: string } = {}) => (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} name={opts.name} className="input" type={opts.type ?? "text"} value={value} placeholder={opts.ph} autoComplete="off" onChange={(e) => on(e.target.value)} />
      {opts.hint ? <span className="hint">{opts.hint}</span> : null}
    </div>
  );
  return (
    <Dialog
      title={t("plan.sap.dlg.title")}
      wide
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={busy} onClick={() => void save()} data-testid="sap-save">
            {busy ? <span className="spinner" aria-hidden /> : null} {t("plan.sap.btn.save")}
          </button>
        </>
      }
    >
      {isConflict(err) ? <ConflictBanner onReload={onClose} /> : <MfgError error={err} />}
      <FormErrors error={err}>
        <div className="col pl-gap">
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={f.enabled} onChange={(e) => set({ enabled: e.target.checked })} data-testid="sap-enable" /> {t("plan.sap.f.enabled")}
          </label>
          <div className="pl-form-grid">
            {field("sap-url", t("plan.sap.f.url"), f.base_url, (v) => set({ base_url: v }), { ph: "https://s4.example.com/sap/opu/odata/sap", name: "base_url" })}
            <div className="field">
              <label htmlFor="sap-ver">{t("plan.sap.f.version")}</label>
              <select id="sap-ver" className="select" value={f.odata_version} onChange={(e) => set({ odata_version: e.target.value as "v2" | "v4" })}>
                <option value="v2">{t("plan.sap.odata", { v: "v2" })}</option>
                <option value="v4">{t("plan.sap.odata", { v: "v4" })}</option>
              </select>
            </div>
            {field("sap-plant", t("plan.sap.f.plant"), f.plant, (v) => set({ plant: v }), { hint: t("plan.sap.hint.plant"), name: "plant" })}
            <div className="field">
              <label htmlFor="sap-auth">{t("plan.sap.f.auth")}</label>
              <select id="sap-auth" className="select" value={f.auth} onChange={(e) => set({ auth: e.target.value as "basic" | "oauth2" })}>
                <option value="basic">{t("plan.sap.auth.basic")}</option>
                <option value="oauth2">{t("plan.sap.auth.oauth2")}</option>
              </select>
            </div>
            {f.auth === "basic" ? (
              <>
                {field("sap-user", t("plan.sap.f.user"), f.username, (v) => set({ username: v }), { name: "username" })}
                {field("sap-pw", t("plan.sap.f.password"), f.password ?? "", (v) => set({ password: v || null }), { type: "password", ph: s.password_set ? t("plan.sap.ph.kept") : "", name: "password" })}
              </>
            ) : (
              <>
                {field("sap-token", t("plan.sap.f.tokenUrl"), f.token_url, (v) => set({ token_url: v }), { name: "token_url" })}
                {field("sap-cid", t("plan.sap.f.clientId"), f.client_id, (v) => set({ client_id: v }), { name: "client_id" })}
                {field("sap-cs", t("plan.sap.f.clientSecret"), f.client_secret ?? "", (v) => set({ client_secret: v || null }), { type: "password", ph: s.client_secret_set ? t("plan.sap.ph.kept") : "", name: "client_secret" })}
              </>
            )}
          </div>
          <button type="button" className="btn ghost sm pl-expert-toggle" aria-expanded={expert} onClick={() => setExpert((v) => !v)}>
            <Icon name={expert ? "chevron-down" : "chevron-right"} /> {t("plan.label.expert")}
          </button>
          {expert ? (
            <div className="pl-expert col pl-gap">
              <div className="pl-form-grid">
                <div className="field">
                  <label htmlFor="sap-units">{t("plan.sap.f.units")}</label>
                  <textarea id="sap-units" className="textarea mono" rows={5} value={units} onChange={(e) => setUnits(e.target.value)} />
                  <span className="hint">{t("plan.sap.hint.map")}</span>
                </div>
                <div className="field">
                  <label htmlFor="sap-locs">{t("plan.sap.f.locations")}</label>
                  <textarea id="sap-locs" className="textarea mono" rows={5} value={locs} onChange={(e) => setLocs(e.target.value)} />
                  <span className="hint">{t("plan.sap.hint.locs")}</span>
                </div>
                {field("sap-page", t("plan.sap.f.pageSize"), String(f.page_size), (v) => set({ page_size: Number(v) || 2000 }), { type: "number", name: "page_size" })}
              </div>
              <label className="row" style={{ gap: 6 }}>
                <input type="checkbox" checked={f.strip_zeros} onChange={(e) => set({ strip_zeros: e.target.checked })} /> {t("plan.sap.f.strip")}
              </label>
            </div>
          ) : null}
        </div>
      </FormErrors>
      {reason.dialog}
    </Dialog>
  );
}


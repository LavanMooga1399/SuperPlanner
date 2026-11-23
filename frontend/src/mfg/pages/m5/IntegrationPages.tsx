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
import { formatDateTime, formatTime } from "../../../lib/locale";
import { t, t as tr } from "../../../lib/i18n";
import { DataTable } from "../../components/DataTable";

export const SOR_LABEL: Record<SorEntity, { label: string; help: string; allowed: SorValue[] }> = {
  items: { label: tr("mfg.integrationPages.str.items"), help: tr("mfg.integrationPages.str.partNumberDescriptionUnitMake"), allowed: ["erp", "superplanner", "shared"] },
  boms: { label: "BOMs", help: tr("mfg.integrationPages.str.wholeStructureChangesFromThe"), allowed: ["erp", "superplanner"] },
  routings: { label: tr("mfg.integrationPages.str.routings"), help: tr("mfg.integrationPages.str.operationsAndTimesLineRates"), allowed: ["erp", "superplanner"] },
  suppliers: { label: tr("mfg.integrationPages.str.suppliers"), help: tr("mfg.integrationPages.str.allExceptThePreferredFlag"), allowed: ["erp", "superplanner", "shared"] },
  item_suppliers: { label: tr("mfg.integrationPages.str.itemSuppliers"), help: tr("mfg.integrationPages.str.pricesLeadTimesMoqPer"), allowed: ["erp", "superplanner", "shared"] },
  purchase_orders: { label: tr("mfg.integrationPages.str.purchaseOrders"), help: tr("mfg.integrationPages.str.headerLinesAndDeliverySchedules"), allowed: ["erp", "superplanner"] },
  po_receipts: { label: tr("mfg.integrationPages.str.goodsReceipts"), help: tr("mfg.integrationPages.str.seeBelow"), allowed: ["erp", "superplanner"] },
  demand_orders: { label: tr("mfg.integrationPages.str.customerDemand"), help: tr("mfg.integrationPages.str.allExceptPriority"), allowed: ["erp", "superplanner"] },
  purchase_requests: { label: tr("mfg.integrationPages.str.purchaseRequests"), help: tr("mfg.integrationPages.str.raisedHereSentToThe"), allowed: ["superplanner"] },
  work_orders: { label: tr("mfg.integrationPages.str.workOrders"), help: tr("mfg.integrationPages.str.createdAndRunHereSent"), allowed: ["superplanner", "erp"] },
  floor: { label: tr("mfg.integrationPages.str.shopFloorResults"), help: tr("mfg.integrationPages.str.goodScrapLabourSentTo"), allowed: ["superplanner"] },
  transfers: { label: tr("mfg.integrationPages.str.transfersBetweenPlants"), help: tr("mfg.integrationPages.str.sentToTheErp"), allowed: ["superplanner"] },
  stock: { label: tr("mfg.integrationPages.str.stockMovements"), help: tr("mfg.integrationPages.str.theLedgerHereIsThe"), allowed: ["superplanner", "erp"] },
};

const SOR_TEXT: Record<SorValue, string> = { erp: "ERP", superplanner: "SuperPlanner", shared: tr("mfg.integrationPages.str.bothLastChangeWins") };

const TABS: { key: string; label: string }[] = [
  { key: "", label: tr("mfg.integrationPages.str.overview") },
  { key: "settings", label: tr("mfg.integrationPages.str.settings") },
  { key: "endpoints", label: tr("mfg.integrationPages.str.webhooks") },
  { key: "deliveries", label: tr("mfg.integrationPages.str.deliveries") },
  { key: "batches", label: tr("mfg.integrationPages.str.dataIn") },
  { key: "events", label: tr("mfg.integrationPages.str.eventsOut") },
  { key: "filedrop", label: tr("mfg.integrationPages.str.fileDrop") },
  { key: "value-maps", label: tr("mfg.integrationPages.str.codeMappings") },
  { key: "reconciliation", label: tr("mfg.integrationPages.str.reconciliation") },
  { key: "tokens", label: tr("mfg.integrationPages.str.plantTokens") },
];

export function IntegrationLayout() {
  const can = useCan("integration_admin");
  useEffect(() => {
    document.title = tr("mfg.integrationPages.str.integrationSuperplanner");
  }, []);
  return (
    <div className="col gap-lg" data-testid="integration">
      <div className="mfg-page-head">
        <div>
          <h1>{t("mfg.integrationPages.head.erpIntegration")}</h1>
          <p>{t("mfg.integrationPages.text.dataInFromTheErp")}</p>
        </div>
      </div>
      {!can ? (
        <Banner tone="info" title={t("mfg.integrationPages.title.plantAdminsManageTheIntegration")}>
          {needsText("integration_admin")}
        </Banner>
      ) : null}
      <nav className="tabs" aria-label={t("mfg.integrationPages.aria.integrationSections")}>
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
        <Banner tone="info" title={t("mfg.integrationPages.title.theIntegrationIsOffFor")} actions={<Link className="btn sm primary" to={mfgPaths.integration("settings")}>{tr("mfg.integrationPages.text.setItUp")}</Link>}>
          {tr("mfg.integrationPages.text.nothingIsSentToAn")}
        </Banner>
      ) : null}
      <div className="kpis">
        <Link to={`${mfgPaths.integration("deliveries")}?status=dead`} className="card kpi" style={{ textDecoration: "none", color: "inherit" }} data-testid="int-kpi-dead">
          <div className="kpi-label">{tr("mfg.integrationPages.text.failedDeliveries")}</div>
          <div className="kpi-value" style={{ color: dead.data?.total ? "var(--danger)" : undefined }}>
            {dead.data?.total ?? "–"} {dead.data?.total ? <Icon name="alert" size={16} /> : null}
          </div>
          <div className="kpi-sub">{tr("mfg.integrationPages.text.stoppedAfter24HOf")}</div>
        </Link>
        <Link to={`${mfgPaths.integration("deliveries")}?status=pending`} className="card kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="kpi-label">{tr("mfg.integrationPages.text.waitingToSend")}</div>
          <div className="kpi-value">{waiting.data?.total ?? "–"}</div>
          <div className="kpi-sub">{tr("mfg.integrationPages.text.inclRetriesLaterEventsOf")}</div>
        </Link>
        <Link to={mfgPaths.integration("batches")} className="card kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="kpi-label">{tr("mfg.integrationPages.text.lastDataIn")}</div>
          <div className="kpi-value" style={{ fontSize: 18 }}>
            {last ? formatDateTime(last.received_at) : tr("mfg.integrationPages.str.noneYet")}
          </div>
          <div className="kpi-sub">{rejected ? tr("mfg.integrationPages.tpl.rejectedRecordsInTheLast", { rejected: rejected }) : tr("mfg.integrationPages.str.noRejectedRecordsRecently")}</div>
        </Link>
        <Link to={mfgPaths.integration("filedrop")} className="card kpi" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="kpi-label">{tr("mfg.integrationPages.text.fileDrop")}</div>
          <div className="kpi-value" style={{ fontSize: 18 }}>
            {!fd.data?.enabled ? "off" : fd.data.inbox.length ? `${fd.data.inbox.length} waiting` : "ok"}
          </div>
          <div className="kpi-sub">{fd.data?.last_poll_at ? `checked ${formatTime(fd.data.last_poll_at)}` : ""}</div>
        </Link>
      </div>
      <section className="card card-table">
        <div className="card-header">
          <h2>{t("mfg.integrationPages.head.whoOwnsWhat")}</h2>
          <Link to={mfgPaths.integration("settings")} className="small">
            {t("mfg.integrationPages.btn.change")}
          </Link>
        </div>
        <SorSummary s={s} />
      </section>
    </div>
  );
}

function SorBadge({ v }: { v: string }) {
  return v === "erp" ? (
    <span className="badge info">
      <Icon name="lock" size={12} /> {t("mfg.integrationPages.btn.erp")}
    </span>
  ) : v === "shared" ? (
    <span className="badge warn">
      <Icon name="refresh" size={12} /> {t("mfg.integrationPages.btn.both")}
    </span>
  ) : (
    <span className="badge ok">
      <Icon name="check" size={12} /> {t("mfg.integrationPages.btn.superplanner")}
    </span>
  );
}

function SorSummary({ s }: { s: IntegrationSettings }) {
  return (
    <DataTable
      rows={[...SOR_ENTITIES]}
      columns={[
        { key: "data", header: "Data", width: "minmax(150px, 1fr)", sortValue: (e) => SOR_LABEL[e].label, render: (e) => SOR_LABEL[e].label },
        { key: "owner", header: "Owned by", width: "150px", sortValue: (e) => s.sor[e] ?? "superplanner", exportValue: (e) => s.sor[e] ?? "superplanner", render: (e) => <SorBadge v={s.sor[e] ?? "superplanner"} /> },
        { key: "notes", header: "Notes", width: "minmax(240px, 3fr)", wrap: true, render: (e) => <span className="small muted">{SOR_LABEL[e].help}</span> },
      ]}
      rowKey={(e) => e}
      label={t("mfg.integrationPages.label.whoOwnsWhat")}
      testId="sor-summary"
      columnSettings={false}
      rowExtras={(e) => ({ data: { entity: e, sor: s.sor[e] ?? "superplanner" } })}
      card={{ title: "data", status: "owner", fields: ["notes"] }}
    />
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
        <Banner tone="warn" title={t("mfg.integrationPages.title.someoneElseChangedTheSettings")} actions={<button type="button" className="btn sm" onClick={() => { setConflict(false); st.reload(); }}>{tr("mfg.integrationPages.text.reload")}</button>}>
          {tr("mfg.integrationPages.text.yourChangesWereNotSaved")}
        </Banner>
      ) : null}
      <section className="card">
        <div className="card-body col">
          <label className="checkbox">
            <input type="checkbox" checked={f.enabled} disabled={!can} onChange={(e) => setF({ ...f, enabled: e.target.checked })} data-testid="int-enabled" />
            <span>
              <strong>{tr("mfg.integrationPages.text.connectThisPlantToAn")}</strong> <span className="muted small">{tr("mfg.integrationPages.text.recordsChangesForTheErp")}</span>
            </span>
          </label>
          <div className="field" style={{ maxWidth: 320 }}>
            <label htmlFor="int-code">{t("mfg.integrationPages.label.plantCodeForFilesAnd")}</label>
            <input id="int-code" className="input mono" value={f.plant_code} disabled={!can} onChange={(e) => setF({ ...f, plant_code: e.target.value.replace(/[^A-Za-z0-9_.-]/g, "") })} maxLength={32} required data-testid="int-plant-code" />
            <span className="hint">{tr("mfg.integrationPages.text.lettersDigitsNamesThisPlant")}</span>
          </div>
          <div className="field" style={{ maxWidth: 320 }}>
            <label htmlFor="int-adapter">{t("mfg.integrationPages.label.format")}</label>
            <select id="int-adapter" className="select" value={f.adapter} disabled={!can} onChange={(e) => setF({ ...f, adapter: e.target.value })}>
              {(f.adapters?.length ? f.adapters : ["generic_v1"]).map((a) => (
                <option key={a} value={a}>
                  {a === "generic_v1" ? tr("mfg.integrationPages.str.genericSuperplannerV1RestFiles") : a}
                </option>
              ))}
            </select>
            <span className="hint">{tr("mfg.integrationPages.text.erpSpecificFormatsAreAdded")}</span>
          </div>
        </div>
      </section>

      <section className="card card-table">
        <div className="card-header">
          <h2>{t("mfg.integrationPages.head.whoOwnsWhat")}</h2>
          <span className="muted small">{tr("mfg.integrationPages.text.dataOwnedByTheErp")}</span>
        </div>
        <DataTable
          rows={SOR_ENTITIES.filter((e) => e !== "po_receipts")}
          columns={[
            { key: "data", header: "Data", width: "minmax(150px, 1fr)", render: (e) => SOR_LABEL[e].label },
            {
              key: "owner",
              header: "Owned by",
              width: "190px",
              exportValue: (e) => f.sor[e] ?? "superplanner",
              render: (e) => {
                const m = SOR_LABEL[e];
                const v = f.sor[e] ?? "superplanner";
                return m.allowed.length > 1 ? (
                  <select className="select sm" aria-label={tr("mfg.integrationPages.tpl.ownedBy", { label: m.label })} value={v} disabled={!can} onChange={(ev) => setSor(e, ev.target.value as SorValue)} data-testid={`sor-${e}`}>
                    {m.allowed.map((a) => (
                      <option key={a} value={a}>
                        {SOR_TEXT[a]}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span>{SOR_TEXT[v]}</span>
                );
              },
            },
            { key: "notes", header: "Notes", width: "minmax(240px, 3fr)", wrap: true, render: (e) => <span className="small muted">{SOR_LABEL[e].help}</span> },
          ]}
          rowKey={(e) => e}
          label={t("mfg.integrationPages.label.whoOwnsWhat")}
          testId="sor-table"
          columnSettings={false}
          rowExtras={(e) => ({ data: { entity: e } })}
          card={{ title: "data", actions: "owner", fields: ["notes"] }}
        />
      </section>

      <section className="card">
        <div className="card-header">
          <h2>{t("mfg.integrationPages.head.goodsReceiptsAgainstPurchaseOrders")}</h2>
        </div>
        <div className="card-body col" role="radiogroup" aria-label={t("mfg.integrationPages.aria.whoBooksGoodsReceipts")} data-testid="int-receipts-owner">
          <label className="checkbox">
            <input type="radio" name="gr" checked={f.goods_receipts_owner === "superplanner"} disabled={!can} onChange={() => setF({ ...f, goods_receipts_owner: "superplanner", sor: { ...f.sor, po_receipts: "superplanner" } })} data-testid="gr-superplanner" />
            <span>
              <strong>{tr("mfg.integrationPages.text.bookedHere")}</strong> <span className="muted small">{tr("mfg.integrationPages.text.storesReceiveInSuperplannerEach")}</span>
            </span>
          </label>
          <label className="checkbox">
            <input type="radio" name="gr" checked={f.goods_receipts_owner === "erp"} disabled={!can} onChange={() => setF({ ...f, goods_receipts_owner: "erp", sor: { ...f.sor, po_receipts: "erp" } })} data-testid="gr-erp" />
            <span>
              <strong>{tr("mfg.integrationPages.text.bookedInTheErp")}</strong> <span className="muted small">{tr("mfg.integrationPages.text.receivingHereIsSwitchedOff")}</span>
            </span>
          </label>
        </div>
      </section>

      <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={expert} onClick={() => setExpert((v) => !v)}>
        <Icon name="settings" /> {t("mfg.integrationPages.btn.filesFileDropAndExport")}
      </button>
      {expert ? (
        <section className="card">
          <div className="card-body col">
            <label className="checkbox">
              <input type="checkbox" checked={f.filedrop_enabled} disabled={!can} onChange={(e) => setF({ ...f, filedrop_enabled: e.target.checked })} />
              <span>
                <strong>{tr("mfg.integrationPages.text.readFilesFromTheInbox")}</strong> <span className="muted small">{tr("mfg.integrationPages.text.csvExcelOrJsonDropped")}</span>
              </span>
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={f.export_enabled} disabled={!can} onChange={(e) => setF({ ...f, export_enabled: e.target.checked })} />
              <span>
                <strong>{tr("mfg.integrationPages.text.alsoWriteEventsAsFiles")}</strong> <span className="muted small">{tr("mfg.integrationPages.text.csvPerEventTypeAnd")}</span>
              </span>
            </label>
            {f.export_enabled ? (
              <div className="field" style={{ maxWidth: 220 }}>
                <label htmlFor="int-every">{t("mfg.integrationPages.label.everyMinutes51440")}</label>
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
            <Icon name="save" /> {t("mfg.integrationPages.btn.save")}
          </button>
          {saved ? (
            <span className="badge ok">
              <Icon name="check" /> {t("mfg.integrationPages.btn.saved")}
            </span>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}

/** Integration console, part 2 (M5 4.3-4.8): webhooks, deliveries, data in, events out, file drop, code mappings, reconciliation, plant tokens. */
import { formatDateTime } from "../../../lib/locale";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { TokenManager } from "../../../auth/TokensPage";
import { Banner } from "../../../components/Banner";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { listItems } from "../../api/client";
import {
  createEndpoint,
  deleteEndpoint,
  getBatch,
  getFiledropStatus,
  getIntegrationSettings,
  getReconciliation,
  getValueMaps,
  listBatches,
  listDeliveries,
  listEndpoints,
  listEvents,
  listMappingProfiles,
  listReconciliations,
  putValueMaps,
  retryDelivery,
  startReconciliation,
  testEndpoint,
  updateEndpoint,
} from "../../api/clientM5";
import type { Batch, BatchRecordResult, Delivery, Endpoint, ReconKind, ReconRow, StockSnapshotV1, ValueMap } from "../../api/typesM5";
import { MfgError, Spinner } from "../../components/Feedback";
import { DataTable, ShowMore } from "../../components/DataTable";
import { FilterBar } from "../../../components/FilterBar";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { usePolling } from "../../lib/usePolling";
import { t, t as tr } from "../../../lib/i18n";

const EVENT_TYPES = [
  "work_order.created",
  "work_order.released",
  "work_order.completed",
  "work_order.closed",
  "work_order.cancelled",
  "purchase_request.submitted",
  "purchase_request.approved",
  "inventory.posting",
  "floor.operation_completed",
  "schedule.published",
  "eco.implemented",
  "transfer_order.shipped",
  "transfer_order.received",
];

const when = (iso: string | null | undefined) => (iso ? formatDateTime(iso) : "");

// ---------------------------------------------------------------- webhooks
/** 32 random bytes, url-safe base64: the signing secret (shown once; the server stores it encrypted) */
function newSecret(): string {
  const b = new Uint8Array(32);
  crypto.getRandomValues(b);
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function EndpointsTab() {
  const can = useCan("integration_admin");
  const eps = useLoad((signal) => listEndpoints(signal), []);
  const [edit, setEdit] = useState<Endpoint | "new" | null>(null);
  const [created, setCreated] = useState<{ name: string; secret: string } | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const [del, setDel] = useState<Endpoint | null>(null);
  const [error, setError] = useState<unknown>(null);
  return (
    <div className="col gap-lg" data-testid="int-endpoints">
      {created ? (
        <Banner tone="ok" title={tr("mfg.integrationPages2.tpl.webhookSaved", { name: created.name })} testId="endpoint-secret">
          <div className="col" style={{ gap: 6 }}>
            <span>{tr("mfg.integrationPages2.text.giveThisSigningSecretTo")}</span>
            <code className="totp-secret">{created.secret}</code>
            <div className="row">
              <button type="button" className="btn sm" onClick={() => void navigator.clipboard?.writeText(created.secret)}>
                <Icon name="copy" /> {t("mfg.integrationPages2.btn.copy")}
              </button>
              <button type="button" className="btn sm ghost" onClick={() => setCreated(null)}>
                {t("mfg.integrationPages2.btn.done")}
              </button>
            </div>
          </div>
        </Banner>
      ) : null}
      <section className="card card-table">
        <div className="card-header">
          <h2>{t("mfg.integrationPages2.head.webhooks")}</h2>
          {can ? (
            <button type="button" className="btn sm primary" onClick={() => setEdit("new")} data-testid="endpoint-new">
              <Icon name="plus" /> {t("mfg.integrationPages2.btn.addWebhook")}
            </button>
          ) : null}
        </div>
        <MfgError error={error ?? eps.error} onRetry={eps.reload} />
        <DataTable
          rows={eps.data?.items ?? []}
          columns={[
            {
              key: "name",
              header: "Name",
              width: "minmax(150px, 1fr)",
              sortValue: (e) => e.name,
              exportValue: (e) => e.name,
              render: (e) => (
                <span>
                  <strong>{e.name}</strong>
                  {!e.active ? <span className="vt-sub">paused</span> : null}
                </span>
              ),
            },
            { key: "url", header: "Address", width: "minmax(220px, 2fr)", sortValue: (e) => e.url, render: (e) => <span className="mono small">{e.url}</span> },
            { key: "events", header: "Events", width: "110px", render: (e) => (e.event_types.length ? `${e.event_types.length} types` : "all events") },
            {
              key: "health",
              header: "Health",
              width: "minmax(190px, 1.4fr)",
              wrap: true,
              exportValue: (e) => (e.dead ? `${e.dead} failed` : e.pending ? `${e.pending} waiting` : "up to date"),
              render: (e) => (
                <span>
                  {e.dead ? (
                    <span className="badge danger">
                      <Icon name="alert" /> {e.dead} failed
                    </span>
                  ) : e.pending ? (
                    <span className="badge warn">
                      <Icon name="clock" /> {e.pending} waiting
                    </span>
                  ) : (
                    <span className="badge ok">
                      <Icon name="check" /> {t("mfg.integrationPages2.btn.upToDate")}
                    </span>
                  )}
                  <span className="vt-sub">{tr("mfg.integrationPages2.text.sentUpToEvent", { cursor: e.cursor })}</span>
                  {testResult[e.id] ? (
                    <span className="vt-sub" data-testid="endpoint-test-result">
                      {testResult[e.id]}
                    </span>
                  ) : null}
                </span>
              ),
            },
            ...(can
              ? [
                  {
                    key: "actions",
                    header: <span className="sr-only">{tr("mfg.integrationPages2.text.actions")}</span>,
                    label: "Actions",
                    width: "220px",
                    align: "right" as const,
                    exportValue: () => "",
                    render: (e: Endpoint) => (
                      <span className="row" style={{ justifyContent: "flex-end", gap: 4, flexWrap: "nowrap" }}>
                        <button
                          type="button"
                          className="btn sm"
                          disabled={testing === e.id}
                          title={tr("mfg.integrationPages2.attr.sendWhatIsWaitingFor")}
                          onClick={async () => {
                            setTesting(e.id);
                            try {
                              await testEndpoint(e.id);
                              setTestResult((x) => ({ ...x, [e.id]: "Sent; see Deliveries for the answers." }));
                              eps.reload();
                            } catch (err) {
                              setTestResult((x) => ({ ...x, [e.id]: `Could not send: ${(err as Error).message}` }));
                            } finally {
                              setTesting(null);
                            }
                          }}
                          data-testid="endpoint-test"
                        >
                          {tr("mfg.integrationPages2.text.sendNow")}
                        </button>
                        <button type="button" className="btn sm ghost" onClick={() => setEdit(e)}>
                          {t("mfg.integrationPages2.btn.edit")}
                        </button>
                        <button type="button" className="btn sm ghost" onClick={() => setDel(e)}>
                          {t("mfg.integrationPages2.btn.remove")}
                        </button>
                      </span>
                    ),
                  },
                ]
              : []),
          ]}
          rowKey={(e) => e.id}
          label={t("mfg.integrationPages2.label.webhooks")}
          tableId="int-webhooks"
          loading={eps.loading && !eps.data}
          rowExtras={(e) => ({ testId: "endpoint-row", className: e.active ? undefined : "faint" })}
          empty={t("mfg.integrationPages2.empty.noWebhooksEventsCanAlso")}
          card={{ title: "name", status: "health", actions: can ? "actions" : undefined, fields: ["url", "events"] }}
        />
      </section>
      {edit ? (
        <EndpointDialog
          ep={edit === "new" ? null : edit}
          onClose={() => setEdit(null)}
          onSaved={(x, secret) => {
            setEdit(null);
            if (secret) setCreated({ name: x.name, secret });
            eps.reload();
          }}
        />
      ) : null}
      {del ? (
        <ConfirmDialog
          title={tr("mfg.integrationPages2.tpl.removeWebhook", { name: del.name })}
          confirmLabel={t("mfg.integrationPages2.btn.remove")}
          danger
          onCancel={() => setDel(null)}
          onConfirm={async () => {
            try {
              await deleteEndpoint(del.id, del.row_version);
            } catch (e) {
              setError(e);
            } finally {
              setDel(null);
              eps.reload();
            }
          }}
        >
          <p style={{ margin: 0 }}>{t("mfg.integrationPages2.text.waitingDeliveriesToItAre")}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function EndpointDialog({ ep, onClose, onSaved }: { ep: Endpoint | null; onClose(): void; onSaved(x: Endpoint, secret: string | null): void }) {
  const [name, setName] = useState(ep?.name ?? "");
  const [url, setUrl] = useState(ep?.url ?? "https://");
  const [all, setAll] = useState(!ep || ep.event_types.length === 0);
  const [types, setTypes] = useState<Set<string>>(new Set(ep?.event_types ?? []));
  const [active, setActive] = useState(ep?.active ?? true);
  const [rotate, setRotate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const urlOk = /^https:\/\/[^\s/]+/.test(url.trim());
  return (
    <Dialog
      title={ep ? tr("mfg.integrationPages2.tpl.webhook", { name: ep.name }) : tr("mfg.integrationPages2.str.addWebhook")}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t("mfg.integrationPages2.btn.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !name.trim() || !urlOk || (!all && types.size === 0)}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                const secret = !ep || rotate ? newSecret() : null;
                const body = { name: name.trim(), url: url.trim(), event_types: all ? [] : [...types], active, ...(secret ? { secret } : {}) };
                onSaved(ep ? await updateEndpoint(ep.id, body, ep.row_version) : await createEndpoint(body), secret);
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
            data-testid="endpoint-save"
          >
            {ep ? tr("mfg.integrationPages2.str.save") : tr("mfg.integrationPages2.str.add")}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="ep-name">{t("mfg.integrationPages2.label.name")}</label>
          <input id="ep-name" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("mfg.integrationPages2.ph.egErpMiddleware")} data-testid="endpoint-name" />
        </div>
        <div className="field">
          <label htmlFor="ep-url">{t("mfg.integrationPages2.label.addressHttps")}</label>
          <input id="ep-url" className="input mono" value={url} onChange={(e) => setUrl(e.target.value)} aria-invalid={!urlOk} data-testid="endpoint-url" />
          <span className="hint">{urlOk ? tr("mfg.integrationPages2.str.eachEventIsSentAs") : "Use an https:// address."}</span>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />{" "}{tr("mfg.integrationPages2.text.allEvents")}
        </label>
        {!all ? (
          <div className="token-scopes">
            {EVENT_TYPES.map((t) => (
              <label key={t} className="checkbox">
                <input
                  type="checkbox"
                  checked={types.has(t)}
                  onChange={() =>
                    setTypes((s) => {
                      const n = new Set(s);
                      if (n.has(t)) n.delete(t);
                      else n.add(t);
                      return n;
                    })
                  }
                />
                <span className="mono small">{t}</span>
              </label>
            ))}
          </div>
        ) : null}
        <label className="checkbox">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />{" "}{tr("mfg.integrationPages2.text.activeOffPauseSendingEvents")}
        </label>
        {ep ? (
          <label className="checkbox">
            <input type="checkbox" checked={rotate} onChange={(e) => setRotate(e.target.checked)} />{" "}{tr("mfg.integrationPages2.text.makeANewSigningSecret")}
          </label>
        ) : (
          <span className="faint small">{tr("mfg.integrationPages2.text.aSigningSecretIsMade")}</span>
        )}
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- deliveries
type DeliveryView = "pending" | "retrying" | "delivered" | "dead";
const DELIVERY: Record<DeliveryView, { label: string; tone: string; icon: "check" | "clock" | "alert" | "refresh" }> = {
  pending: { label: tr("mfg.integrationPages2.str.waiting"), tone: "info", icon: "clock" },
  retrying: { label: tr("mfg.integrationPages2.str.retrying"), tone: "warn", icon: "refresh" },
  delivered: { label: tr("mfg.integrationPages2.str.delivered"), tone: "ok", icon: "check" },
  dead: { label: tr("mfg.integrationPages2.str.failedStopped"), tone: "danger", icon: "alert" },
};
const viewOf = (d: Delivery): DeliveryView => (d.status === "pending" && d.attempts > 0 ? "retrying" : d.status);

export function DeliveriesTab() {
  const can = useCan("integration_admin");
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const eps = useLoad((signal) => listEndpoints(signal).catch(() => null), []);
  const epName = (id: string) => eps.data?.items.find((e) => e.id === id)?.name ?? id;
  const data = usePaged<Delivery>((offset, limit, signal) => listDeliveries({ status: status || undefined, limit, offset }, signal), [status]);
  usePolling(data.reload, true, 15000);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusy(id);
    setError(null);
    try {
      await fn();
      data.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="col gap-lg" data-testid="int-deliveries">
      <FilterBar>
        <div className="field">
          <span className="field-label" id="dl-status-label">
            {tr("mfg.integrationPages2.text.status")}
          </span>
          <div className="btn-group" role="group" aria-labelledby="dl-status-label">
            {(["", "dead", "pending", "delivered"] as const).map((s) => (
              <button key={s || "all"} type="button" className="btn" aria-pressed={status === s} onClick={() => setSearchParam(setParams, "status", s)}>
                {s ? (s === "pending" ? tr("mfg.integrationPages2.str.waitingOrRetrying") : DELIVERY[s].label) : tr("mfg.integrationPages2.str.all")}
              </button>
            ))}
          </div>
        </div>
      </FilterBar>
      <p className="muted small" style={{ margin: 0 }}>
        {tr("mfg.integrationPages2.text.eventsGoToEachWebhook")}
      </p>
      <MfgError error={error ?? data.error} onRetry={data.reload} />
      <DataTable
        rows={data.rows}
        columns={[
          { key: "event", header: "Event", width: "minmax(200px, 1.4fr)", exportValue: (d) => `#${d.event_seq} ${d.event_type ?? ""}`, render: (d) => (<span><span className="mono">#{d.event_seq}</span> <span className="mono small">{d.event_type ?? ""}</span></span>) },
          { key: "endpoint", header: "Webhook", width: "minmax(150px, 1fr)", render: (d) => epName(d.endpoint_id) },
          {
            key: "status",
            header: "Status",
            width: "minmax(170px, 1fr)",
            wrap: true,
            exportValue: (d) => DELIVERY[viewOf(d)].label,
            render: (d) => {
              const v = viewOf(d);
              const m = DELIVERY[v];
              return (
                <span>
                  <span className={`badge ${m.tone}`}>
                    <Icon name={m.icon} /> {m.label}
                  </span>
                  {v === "retrying" && d.next_attempt_at ? <span className="vt-sub">{tr("mfg.integrationPages2.text.nextTry", { nextattemptat: when(d.next_attempt_at) })}</span> : null}
                  {d.delivered_at ? <span className="vt-sub">{when(d.delivered_at)}</span> : null}
                </span>
              );
            },
          },
          { key: "attempts", header: "Attempts", width: "90px", align: "right", sortValue: (d) => d.attempts, render: (d) => d.attempts },
          { key: "answer", header: "Last answer", width: "minmax(180px, 1.4fr)", wrap: true, render: (d) => `${d.last_status_code ? `HTTP ${d.last_status_code}` : ""} ${d.last_error ?? ""}`.trim() },
          {
            key: "actions",
            header: <span className="sr-only">{tr("mfg.integrationPages2.text.actions")}</span>,
            label: "Actions",
            width: "120px",
            align: "right",
            exportValue: () => "",
            render: (d) =>
              can && (d.status === "dead" || viewOf(d) === "retrying") ? (
                <button type="button" className="btn sm" disabled={busy === d.id} onClick={() => void act(d.id, () => retryDelivery(d.id))} data-testid="delivery-retry">
                  <Icon name="refresh" /> {t("mfg.integrationPages2.btn.retryNow")}
                </button>
              ) : null,
          },
        ]}
        rowKey={(d) => d.id}
        label={t("mfg.integrationPages2.label.webhookDeliveries")}
        testId="delivery-table"
        totalCount={data.total}
        loading={data.loading}
        exportName="webhook-deliveries"
        rowExtras={(d) => ({ testId: "delivery-row", data: { status: d.status } })}
        empty={status ? tr("mfg.integrationPages2.str.noDeliveriesWithThisStatus") : tr("mfg.integrationPages2.str.noDeliveriesYetEventsAre")}
        footer={<ShowMore shown={data.rows.length} total={data.total} noun="deliveries" loading={data.loading} onMore={data.onEndReached} />}
      />
    </div>
  );
}

// ---------------------------------------------------------------- data in (batches)
const BATCH_TONE: Record<Batch["status"], string> = { queued: "info", processing: "accent", completed: "ok", partial: "warn", failed: "danger" };

export function BatchesTab() {
  const data = usePaged<Batch>((offset, limit, signal) => listBatches({ limit, offset }, signal), []);
  usePolling(data.reload, data.rows.some((b) => b.status === "queued" || b.status === "processing"), 3000);
  return (
    <div className="col gap-lg" data-testid="int-batches">
      <p className="muted small" style={{ margin: 0 }}>
        {tr("mfg.integrationPages2.text.eachBatchFromTheErp")}
      </p>
      <MfgError error={data.error} onRetry={data.reload} />
      <DataTable
        rows={data.rows}
        columns={[
          { key: "received", header: "Received", width: "150px", exportValue: (b) => b.received_at, render: (b) => <Link to={mfgPaths.integrationBatch(b.id)}>{when(b.received_at)}</Link> },
          { key: "data", header: "Data", width: "minmax(150px, 1fr)", exportValue: (b) => `${b.entity} ${b.mode}`, render: (b) => (<span>{b.entity} <span className="faint small">{b.mode}</span></span>) },
          { key: "from", header: "From", width: "minmax(150px, 1fr)", wrap: true, exportValue: (b) => b.source ?? "REST", render: (b) => (<span>{b.source ?? "REST"}{b.filename ? <span className="vt-sub mono">{b.filename}</span> : null}</span>) },
          { key: "status", header: "Status", width: "110px", exportValue: (b) => b.status, render: (b) => <span className={`badge ${BATCH_TONE[b.status] ?? "info"}`}>{b.status}</span> },
          { key: "created", header: "Created", width: "88px", align: "right", render: (b) => b.counts.created ?? 0 },
          { key: "updated", header: "Updated", width: "88px", align: "right", render: (b) => b.counts.updated ?? 0 },
          { key: "unchanged", header: "Unchanged", width: "96px", align: "right", render: (b) => b.counts.unchanged ?? 0 },
          {
            key: "rejected",
            header: "Rejected",
            width: "96px",
            align: "right",
            exportValue: (b) => b.counts.rejected ?? 0,
            render: (b) =>
              b.counts.rejected ? (
                <span className="badge danger">
                  <Icon name="alert" /> {b.counts.rejected}
                </span>
              ) : (
                0
              ),
          },
        ]}
        rowKey={(b) => b.id}
        label={t("mfg.integrationPages2.label.dataReceived")}
        testId="batch-table"
        totalCount={data.total}
        loading={data.loading}
        exportName="integration-batches"
        rowExtras={(b) => ({ testId: "batch-row", data: { status: b.status } })}
        empty={t("mfg.integrationPages2.empty.noDataReceivedYetBatches")}
        footer={<ShowMore shown={data.rows.length} total={data.total} noun="batches" loading={data.loading} onMore={data.onEndReached} />}
        card={{ title: "received", status: "status", fields: ["data", "from", "rejected"] }}
      />
    </div>
  );
}

const ERROR_HELP: Record<string, string> = {
  INT_SOR_CONFLICT: tr("mfg.integrationPages2.str.thisDataIsOwnedBy"),
  INT_UNMAPPED_VALUE: tr("mfg.integrationPages2.str.aCodeFromTheErp"),
  INT_SCHEMA: tr("mfg.integrationPages2.str.theRecordDoesNotMatch"),
};

const REC_STATUS: Record<BatchRecordResult["status"], { tone: string; icon: "plus" | "refresh" | "check" | "alert" }> = {
  created: { tone: "ok", icon: "plus" },
  updated: { tone: "accent", icon: "refresh" },
  unchanged: { tone: "info", icon: "check" },
  rejected: { tone: "danger", icon: "alert" },
};

export function BatchPage() {
  const { batchId = "" } = useParams();
  const b = useLoad((signal) => getBatch(batchId, signal), [batchId]);
  usePolling(b.reload, Boolean(b.data && (b.data.status === "queued" || b.data.status === "processing")), 3000);
  const [only, setOnly] = useState<"" | BatchRecordResult["status"]>("");
  const d = b.data;
  if (b.loading && !d) return <Spinner />;
  if (!d) return <MfgError error={b.error} onRetry={b.reload} />;
  const results = d.results ?? [];
  const rows = results.filter((r) => !only || r.status === only);
  return (
    <div className="col gap-lg" data-testid="batch-page" data-status={d.status}>
      <nav className="breadcrumb" aria-label={t("mfg.integrationPages2.aria.breadcrumb")}>
        <Link to={mfgPaths.integration("batches")}>{tr("mfg.integrationPages2.text.dataIn")}</Link> <Icon name="chevron-right" size={12} /> <span>{when(d.received_at)}</span>
      </nav>
      <h2 style={{ margin: 0 }}>
        {d.entity} {d.source ? `from ${d.source}` : ""} <span className={`badge ${BATCH_TONE[d.status] ?? "info"}`}>{d.status}</span>
      </h2>
      <span className="muted small">
        {d.idempotency_key ? <>{tr("mfg.integrationPages2.text.key")}{" "}<span className="mono">{d.idempotency_key}</span> · </> : null}
        {d.filename ? <>{tr("mfg.integrationPages2.text.file")}{" "}<span className="mono">{d.filename}</span> · </> : null}
        {tr("mfg.integrationPages2.text.resendingTheSameBatchWith")}
      </span>
      <FilterBar>
        <div className="field">
          <span className="field-label" id="br-show-label">
            {tr("mfg.integrationPages2.text.show")}
          </span>
          <div className="btn-group" role="group" aria-labelledby="br-show-label">
            {(["", "rejected", "created", "updated", "unchanged"] as const).map((s) => (
              <button key={s || "all"} type="button" className="btn" aria-pressed={only === s} onClick={() => setOnly(s)} data-testid={`batch-filter-${s || "all"}`}>
                {s ? `${s[0].toUpperCase()}${s.slice(1)} (${d.counts[s] ?? 0})` : tr("mfg.integrationPages2.tpl.all", { length: results.length })}
              </button>
            ))}
          </div>
        </div>
      </FilterBar>
      <DataTable
        rows={rows}
        columns={[
          { key: "ref", header: "Record", width: "minmax(150px, 1fr)", sortValue: (r) => r.ref, render: (r) => <span className="mono">{r.ref}</span> },
          {
            key: "status",
            header: "Result",
            width: "130px",
            sortValue: (r) => r.status,
            exportValue: (r) => r.status,
            render: (r) => (
              <span className={`badge ${REC_STATUS[r.status].tone}`}>
                <Icon name={REC_STATUS[r.status].icon} /> {r.status}
              </span>
            ),
          },
          {
            key: "why",
            header: "Why",
            width: "minmax(280px, 3fr)",
            wrap: true,
            exportValue: (r) => r.errors.map((e) => `${e.field ? `${e.field}: ` : ""}${e.message} (${e.code})`).join("; "),
            render: (r) => (
              <span className="col small" style={{ gap: 2 }}>
                {r.errors.map((e, k) => (
                  <span key={k}>
                    {e.field ? <span className="mono">{e.field}: </span> : null}
                    {e.message} <span className="faint">({e.code})</span>
                    {ERROR_HELP[e.code] ? <span className="vt-sub">{ERROR_HELP[e.code]}</span> : null}
                    {e.code === "INT_UNMAPPED_VALUE" ? (
                      <span className="vt-sub">
                        <Link to={mfgPaths.integration("value-maps")}>{tr("mfg.integrationPages2.text.addACodeMapping")}</Link>
                      </span>
                    ) : null}
                  </span>
                ))}
              </span>
            ),
          },
        ]}
        rowKey={(r, i) => `${r.ref}-${i}`}
        label={t("mfg.integrationPages2.label.recordsInThisBatch")}
        testId="batch-results"
        exportName={`batch-${d.id}`}
        rowExtras={(r) => ({ testId: "batch-record", data: { status: r.status } })}
        empty={t("mfg.integrationPages2.empty.noRecordsWithThisResult")}
        card={{ title: "ref", status: "status", fields: ["why"] }}
      />
    </div>
  );
}

// ---------------------------------------------------------------- events out
export function EventsTab() {
  const [after, setAfter] = useState(0);
  const [type, setType] = useState("");
  const ev = useLoad((signal) => listEvents({ after, limit: 100, types: type || undefined }, signal), [after, type]);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="col gap-lg" data-testid="int-events">
      <p className="muted small" style={{ margin: 0 }}>
        {tr("mfg.integrationPages2.text.whatSuperplannerReportsToThe")}
      </p>
      <div className="toolbar">
        <div className="field">
          <label htmlFor="ev-type">{t("mfg.integrationPages2.label.type")}</label>
          <select id="ev-type" className="select sm" value={type} onChange={(e) => { setType(e.target.value); setAfter(0); }}>
            <option value="">{tr("mfg.integrationPages2.text.all")}</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="ev-after">{t("mfg.integrationPages2.label.afterEvent")}</label>
          <input id="ev-after" className="input sm" type="number" min={0} value={after} onChange={(e) => setAfter(Math.max(0, Number(e.target.value) || 0))} />
        </div>
      </div>
      <MfgError error={ev.error} onRetry={ev.reload} />
      <DataTable
        rows={ev.data?.items ?? []}
        columns={[
          { key: "seq", header: "Event", width: "90px", sortValue: (e) => e.seq, exportValue: (e) => e.seq, render: (e) => <span className="mono">#{e.seq}</span> },
          { key: "type", header: "Type", width: "minmax(180px, 1fr)", sortValue: (e) => e.type, render: (e) => <span className="mono small">{e.type}</span> },
          { key: "when", header: "When", width: "160px", sortValue: (e) => e.occurred_at, exportValue: (e) => e.occurred_at, render: (e) => when(e.occurred_at) },
          { key: "ref", header: "Record", width: "minmax(180px, 1fr)", render: (e) => <span className="mono small">{e.entity_ref ?? ""}</span> },
          {
            key: "actions",
            header: <span className="sr-only">{tr("mfg.integrationPages2.text.data")}</span>,
            label: "Data",
            width: "80px",
            align: "right",
            exportValue: () => "",
            render: (e) => (
              <button type="button" className="btn sm ghost" aria-expanded={open === e.seq} onClick={() => setOpen(open === e.seq ? null : e.seq)}>
                {t("mfg.integrationPages2.btn.data")}
              </button>
            ),
          },
        ]}
        rowKey={(e) => e.seq}
        label={t("mfg.integrationPages2.label.outgoingEvents")}
        testId="event-table"
        loading={ev.loading && !ev.data}
        exportName="integration-events"
        rowExtras={(e) => ({ testId: "event-row", className: open === e.seq ? "mfg-selected" : undefined })}
        empty={t("mfg.integrationPages2.empty.noEventsAfterThisNumber")}
        footer={
          ev.data && ev.data.items.length ? (
            <button type="button" className="btn sm" onClick={() => setAfter(ev.data!.next_after)}>
              {t("mfg.integrationPages2.btn.nextEvents")}
            </button>
          ) : undefined
        }
      />
      {open !== null && (ev.data?.items ?? []).some((e) => e.seq === open) ? (
        <section className="card">
          <div className="card-header">
            <h2>{tr("mfg.integrationPages2.text.event", { open: open })}</h2>
            <button type="button" className="btn sm ghost" onClick={() => setOpen(null)}>
              <Icon name="x" /> {t("mfg.integrationPages2.btn.close")}
            </button>
          </div>
          <pre className="int-json" style={{ margin: 0, border: 0 }}>
            {JSON.stringify((ev.data?.items ?? []).find((e) => e.seq === open)?.data, null, 2)}
          </pre>
        </section>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- file drop
export function FiledropTab() {
  const st = useLoad((signal) => getFiledropStatus(signal), []);
  const settings = useLoad((signal) => getIntegrationSettings(signal).catch(() => null), []);
  const profiles = useLoad((signal) => listMappingProfiles(signal), []);
  usePolling(st.reload, true, 30000);
  const s = st.data;
  const code = settings.data?.plant_code || tr("mfg.integrationPages2.str.plantCode");
  return (
    <div className="col gap-lg" data-testid="int-filedrop">
      <MfgError error={st.error} onRetry={st.reload} />
      {s ? (
        <>
          {!s.enabled ? <Banner tone="info" title={t("mfg.integrationPages2.title.fileDropIsOff")}>{tr("mfg.integrationPages2.text.turnItOnUnderSettings")}</Banner> : null}
          <p className="muted small" style={{ margin: 0 }}>
            {tr("mfg.integrationPages2.text.folder")}{" "}<span className="mono">{s.root ? `${s.root}/` : ""}{code}/inbox</span>. Files are read once their size stops changing (or a .done file appears), checked like an import, then moved to archive with a .result.json, or to error with a report.
            {s.last_poll_at ? tr("mfg.integrationPages2.tpl.lastCheck", { lastpollat: when(s.last_poll_at) }) : ""}
          </p>
          <section className="card card-table">
            <div className="card-header">
              <h2>{tr("mfg.integrationPages2.text.waitingInTheInbox", { length: s.inbox.length })}</h2>
            </div>
            <DataTable
              rows={s.inbox}
              columns={[
                { key: "file", header: "File", width: "minmax(200px, 2fr)", sortValue: (f) => f.name ?? f.file ?? "", exportValue: (f) => f.name ?? f.file ?? "", render: (f) => <span className="mono small">{f.name ?? f.file}</span> },
                { key: "size", header: "Size", width: "100px", align: "right", sortValue: (f) => f.size ?? null, render: (f) => (f.size !== undefined ? fmtBytes(f.size) : "") },
                { key: "at", header: "Arrived", width: "160px", sortValue: (f) => f.at ?? null, render: (f) => when(f.at) },
              ]}
              rowKey={(_, i) => i}
              label={t("mfg.integrationPages2.label.filesWaitingInTheInbox")}
              tableId="filedrop-inbox"
              columnSettings={false}
              empty={t("mfg.integrationPages2.empty.nothingWaiting")}
            />
          </section>
          <section className="card card-table">
            <div className="card-header">
              <h2>{t("mfg.integrationPages2.head.recentFiles")}</h2>
            </div>
            <DataTable
              rows={s.recent}
              columns={[
                { key: "file", header: "File", width: "minmax(200px, 2fr)", sortValue: (r) => r.file ?? r.name ?? "", exportValue: (r) => r.file ?? r.name ?? "", render: (r) => <span className="mono small">{r.file ?? r.name}</span> },
                {
                  key: "status",
                  header: "Status",
                  width: "120px",
                  sortValue: (r) => r.status ?? "",
                  exportValue: (r) => r.status ?? "",
                  render: (r) => (
                    <span className={`badge ${r.status === "error" ? "danger" : r.status === "archived" ? "ok" : "info"}`}>
                      <Icon name={r.status === "error" ? "alert" : r.status === "archived" ? "check" : "clock"} /> {r.status === "archived" ? "imported" : r.status ?? ""}
                    </span>
                  ),
                },
                { key: "counts", header: "Records", width: "minmax(160px, 1.4fr)", render: (r) => (r.counts ? Object.entries(r.counts).map(([k, v]) => `${v} ${k}`).join(" · ") : "") },
                { key: "errors", header: "Row errors", width: "110px", sortValue: (r) => r.errors ?? 0, render: (r) => (r.errors ? `${r.errors} row errors` : "") },
                { key: "at", header: "When", width: "160px", sortValue: (r) => r.at ?? null, render: (r) => when(r.at) },
                { key: "batch", header: <span className="sr-only">{tr("mfg.integrationPages2.text.results")}</span>, label: "Results", width: "90px", exportValue: () => "", render: (r) => (r.batch_id ? <Link to={mfgPaths.integrationBatch(r.batch_id)}>{tr("mfg.integrationPages2.text.results")}</Link> : null) },
              ]}
              rowKey={(_, i) => i}
              label={t("mfg.integrationPages2.label.recentFiles")}
              testId="filedrop-recent"
              exportName="file-drop-recent"
              empty={t("mfg.integrationPages2.empty.noFilesYet")}
              card={{ title: "file", status: "status", actions: "batch", fields: ["counts", "at"] }}
            />
          </section>
        </>
      ) : st.loading ? (
        <Spinner />
      ) : null}
      <section className="card card-table">
        <div className="card-header">
          <h2>{t("mfg.integrationPages2.head.mappingsByFileName")}</h2>
        </div>
        <MfgError error={profiles.error} onRetry={profiles.reload} />
        <DataTable
          rows={profiles.data?.items ?? []}
          columns={[
            { key: "name", header: "Mapping", width: "minmax(180px, 1fr)", sortValue: (p) => p.name, render: (p) => p.name },
            { key: "pattern", header: "File names", width: "minmax(200px, 1.4fr)", sortValue: (p) => p.file_pattern, render: (p) => <span className="mono small">{p.file_pattern}</span> },
          ]}
          rowKey={(p) => p.id}
          label={t("mfg.integrationPages2.label.mappingsByFileName")}
          tableId="filedrop-mappings"
          columnSettings={false}
          loading={profiles.loading && !profiles.data}
          empty={
            <>
              {tr("mfg.integrationPages2.text.noneSaveAMappingIn")}{" "}<Link to={mfgPaths.importStart()}>{tr("mfg.integrationPages2.text.import")}</Link>{" "}{tr("mfg.integrationPages2.text.forASampleFileFiles")}
            </>
          }
        />
      </section>
    </div>
  );
}

const fmtBytes = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n > 1024 ? `${Math.round(n / 1024)} kB` : `${n} B`);

// ---------------------------------------------------------------- code mappings
const DOMAINS = [
  { key: "uom", label: tr("mfg.integrationPages2.str.unitsOfMeasure"), hint: "e.g. NOS -> EA" },
  { key: "location", label: tr("mfg.integrationPages2.str.locations"), hint: tr("mfg.integrationPages2.str.erpStorageLocationLocationCode") },
  { key: "reason", label: tr("mfg.integrationPages2.str.reasonCodes"), hint: "" },
  { key: "status", label: tr("mfg.integrationPages2.str.statuses"), hint: "" },
];

export function ValueMapsTab() {
  const can = useCan("integration_admin");
  const vm = useLoad((signal) => getValueMaps(signal), []);
  const [rows, setRows] = useState<ValueMap[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (vm.data) setRows(vm.data.rows);
  }, [vm.data]);
  const set = (i: number, patch: Partial<ValueMap>) => {
    setSaved(false);
    setRows((r) => r.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  };
  return (
    <section className="card" data-testid="int-value-maps">
      <div className="card-header">
        <h2>{t("mfg.integrationPages2.head.codeMappings")}</h2>
        <span className="muted small">{tr("mfg.integrationPages2.text.translateTheErpSCodes")}</span>
      </div>
      <MfgError error={vm.error ?? error} onRetry={vm.reload} />
      <table className="table">
        <thead>
          <tr>
            <th>{t("mfg.integrationPages2.head.kind")}</th>
            <th>{t("mfg.integrationPages2.head.erpCode")}</th>
            <th>{t("mfg.integrationPages2.head.codeHere")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} data-testid="value-map-row">
              <td>
                <select className="select sm" aria-label={t("mfg.integrationPages2.aria.kind")} value={r.domain} disabled={!can} onChange={(e) => set(i, { domain: e.target.value })}>
                  {DOMAINS.map((d) => (
                    <option key={d.key} value={d.key}>
                      {d.label}
                    </option>
                  ))}
                  {!DOMAINS.some((d) => d.key === r.domain) ? <option value={r.domain}>{r.domain}</option> : null}
                </select>
              </td>
              <td>
                <input className="input sm mono" aria-label={t("mfg.integrationPages2.aria.erpCode")} value={r.external_value} disabled={!can} onChange={(e) => set(i, { external_value: e.target.value })} />
              </td>
              <td>
                <input className="input sm mono" aria-label={t("mfg.integrationPages2.aria.codeHere")} value={r.internal_value} disabled={!can} onChange={(e) => set(i, { internal_value: e.target.value })} />
              </td>
              <td>
                {can ? (
                  <button type="button" className="btn sm ghost icon" aria-label={t("mfg.integrationPages2.aria.removeMapping")} onClick={() => setRows((x) => x.filter((_, k) => k !== i))}>
                    <Icon name="trash" />
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {can ? (
        <div className="card-footer row">
          <button type="button" className="btn sm" onClick={() => setRows((r) => [...r, { domain: "uom", external_value: "", internal_value: "" }])} data-testid="value-map-add">
            <Icon name="plus" /> {t("mfg.integrationPages2.btn.addMapping")}
          </button>
          <button
            type="button"
            className="btn sm primary"
            disabled={busy || rows.some((r) => !r.external_value.trim() || !r.internal_value.trim())}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                const out = await putValueMaps(rows.map((r) => ({ ...r, external_value: r.external_value.trim(), internal_value: r.internal_value.trim() })));
                setRows(out.rows);
                setSaved(true);
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
            data-testid="value-map-save"
          >
            <Icon name="save" /> {t("mfg.integrationPages2.btn.save")}
          </button>
          {saved ? (
            <span className="badge ok">
              <Icon name="check" /> {t("mfg.integrationPages2.btn.saved")}
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------- reconciliation
const RECON_KIND: Record<ReconKind, string> = { missing_in_sp: tr("mfg.integrationPages2.str.onlyInTheErp"), missing_in_erp: tr("mfg.integrationPages2.str.onlyHere"), different: tr("mfg.integrationPages2.str.different") };

/** CSV (item_ref,location_code,lot_code,qty) or superplanner.v1 JSON (records or a batch) -> stock snapshot records */
function parseSnapshot(name: string, text: string): StockSnapshotV1[] {
  const now = new Date().toISOString();
  // every v1 record carries a stable `ref` and the time of the snapshot
  const fill = (r: StockSnapshotV1): StockSnapshotV1 => ({ ...r, ref: r.ref ?? `${r.item_ref}|${r.location_code}|${r.lot_code ?? ""}`, as_at: r.as_at ?? now });
  return parseRaw(name, text).map(fill);
}

function parseRaw(name: string, text: string): StockSnapshotV1[] {
  if (/\.json$/i.test(name) || text.trim().startsWith("{") || text.trim().startsWith("[")) {
    const j = JSON.parse(text) as unknown;
    const recs = Array.isArray(j) ? j : ((j as { records?: unknown[] }).records ?? []);
    return recs as StockSnapshotV1[];
  }
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  const head = lines[0].split(/[;,\t]/).map((h) => h.trim().toLowerCase());
  const col = (n: string[]) => head.findIndex((h) => n.includes(h));
  const ci = col(["item_ref", "item", "part_number", "external_ref"]);
  const cl = col(["location_code", "location"]);
  const clot = col(["lot_code", "lot"]);
  const cq = col(["qty", "quantity", "on_hand"]);
  if (ci < 0 || cl < 0 || cq < 0) throw new Error(tr("mfg.integrationPages2.str.theFileNeedsTheColumns"));
  return lines.slice(1).map((l) => {
    const c = l.split(/[;,\t]/).map((x) => x.trim());
    return { item_ref: c[ci], location_code: c[cl], lot_code: clot >= 0 ? c[clot] || null : null, qty: Number(c[cq]) };
  });
}

export function ReconciliationTab() {
  const can = useCan("integration_admin");
  const navigate = useNavigate();
  const list = useLoad((signal) => listReconciliations(signal), []);
  const [records, setRecords] = useState<StockSnapshotV1[] | null>(null);
  const [file, setFile] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <div className="col gap-lg" data-testid="int-recon">
      <section className="card">
        <div className="card-header">
          <h2>{t("mfg.integrationPages2.head.compareStockWithTheErp")}</h2>
        </div>
        <div className="card-body col">
          <p className="muted" style={{ margin: 0 }}>
            {tr("mfg.integrationPages2.text.loadTheErpSStock")}
          </p>
          <div className="field">
            <label htmlFor="rc-file">{t("mfg.integrationPages2.label.erpStockFile")}</label>
            <input
              id="rc-file"
              type="file"
              accept=".csv,.txt,.json"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                setError(null);
                setRecords(null);
                if (!f) return;
                try {
                  setRecords(parseSnapshot(f.name, await f.text()));
                  setFile(f.name);
                } catch (err) {
                  setError(err);
                }
              }}
              data-testid="recon-file"
            />
            {records ? <span className="hint">{tr("mfg.integrationPages2.text.stockLinesReadFrom", { length: records.length, file: file })}</span> : null}
          </div>
          <MfgError error={error} />
          <div>
            <button
              type="button"
              className="btn primary"
              disabled={!can || busy || !records?.length}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  const r = await startReconciliation({ entities: ["stock"], snapshot: "inline", records: { stock: records! } });
                  navigate(mfgPaths.integrationRecon(r.id));
                } catch (e) {
                  setError(e);
                  setBusy(false);
                }
              }}
              data-testid="recon-start"
            >
              <Icon name="compare" /> {t("mfg.integrationPages2.btn.compare")}
            </button>
          </div>
        </div>
      </section>
      <DataTable
        rows={list.data?.items ?? []}
        columns={[
          { key: "created", header: "Compared", width: "160px", sortValue: (r) => r.created_at, exportValue: (r) => r.created_at, render: (r) => <Link to={mfgPaths.integrationRecon(r.id)}>{when(r.created_at)}</Link> },
          { key: "entities", header: "Data", width: "minmax(140px, 1fr)", render: (r) => r.entities.join(", ") },
          { key: "status", header: "Status", width: "110px", sortValue: (r) => r.status, exportValue: (r) => r.status, render: (r) => <span className={`badge ${r.status === "completed" ? "ok" : r.status === "failed" ? "danger" : "info"}`}>{r.status}</span> },
          { key: "summary", header: "Result", width: "minmax(240px, 2fr)", wrap: true, render: (r) => summaryText(r.summary) },
        ]}
        rowKey={(r) => r.id}
        label={t("mfg.integrationPages2.label.earlierComparisons")}
        testId="recon-list"
        loading={list.loading && !list.data}
        exportName="reconciliations"
        empty={t("mfg.integrationPages2.empty.noComparisonsYetUploadAn")}
      />
    </div>
  );
}

function summaryText(sum: Record<string, Partial<Record<string, number>>> | null): string {
  if (!sum) return "";
  const parts: string[] = [];
  for (const [ent, m] of Object.entries(sum))
    for (const k of Object.keys(RECON_KIND) as ReconKind[]) if (m?.[k]) parts.push(`${ent}: ${m[k]} ${RECON_KIND[k].toLowerCase()}`);
  return parts.join(" · ") || tr("mfg.integrationPages2.str.everythingMatches");
}

export function ReconciliationPage() {
  const { reconId = "" } = useParams();
  const canCount = useCan("inventory");
  const navigate = useNavigate();
  const r = useLoad((signal) => getReconciliation(reconId, signal), [reconId]);
  usePolling(r.reload, Boolean(r.data && (r.data.status === "queued" || r.data.status === "running")), 3000);
  const [kind, setKind] = useState<"" | ReconKind>("");
  const d = r.data;
  if (r.loading && !d) return <Spinner />;
  if (!d) return <MfgError error={r.error} onRetry={r.reload} />;
  const rows: (ReconRow & { entity: string; kind: ReconKind })[] = [];
  for (const [ent, m] of Object.entries(d.results ?? {})) for (const k of Object.keys(RECON_KIND) as ReconKind[]) for (const x of m?.[k] ?? []) rows.push({ ...x, entity: ent, kind: k });
  const shown = rows.filter((x) => !kind || x.kind === kind);
  const count = (k: ReconKind) => rows.filter((x) => x.kind === k).length;
  const stockDiffs = rows.filter((x) => x.entity === "stock" && (x.kind === "different" || x.kind === "missing_in_sp") && x.item && x.erp_qty !== null && x.erp_qty !== undefined);
  const toCount = async () => {
    // reviewed count posting: the store keeper sees the ERP quantities prefilled; nothing is posted until confirmed
    const items = await Promise.all(stockDiffs.map((x) => findItemRef(String(x.item))));
    navigate(mfgPaths.post({ type: "count" }), {
      state: { prefill: { reason: "ERP_SYNC", note: `Reconciliation ${d.id}`, lines: stockDiffs.map((x, i) => ({ item: items[i], location_code: x.location, lot_code: x.lot || null, qty: x.erp_qty })).filter((l) => l.item) } },
    });
  };
  return (
    <div className="col gap-lg" data-testid="recon-page" data-status={d.status}>
      <nav className="breadcrumb" aria-label={t("mfg.integrationPages2.aria.breadcrumb")}>
        <Link to={mfgPaths.integration("reconciliation")}>{tr("mfg.integrationPages2.text.reconciliation")}</Link> <Icon name="chevron-right" size={12} /> <span>{when(d.created_at)}</span>
      </nav>
      {d.status === "queued" || d.status === "running" ? <Spinner label={t("mfg.integrationPages2.label.comparing")} /> : null}
      {d.status === "failed" ? <Banner tone="danger" title={t("mfg.integrationPages2.title.theComparisonFailed")}>{tr("mfg.integrationPages2.text.tryAgainIfItKeeps")}</Banner> : null}
      {d.status === "completed" ? (
        <div className="row wrap" role="group" aria-label={t("mfg.integrationPages2.aria.show")}>
          <button type="button" className={`btn sm${!kind ? " primary" : ""}`} aria-pressed={!kind} onClick={() => setKind("")}>
            {tr("mfg.integrationPages2.text.all2", { length: rows.length })}
          </button>
          {(Object.keys(RECON_KIND) as ReconKind[]).map((k) => (
            <button key={k} type="button" className={`btn sm${kind === k ? " primary" : ""}`} aria-pressed={kind === k} onClick={() => setKind(k)} data-testid={`recon-kind-${k}`} data-count={count(k)}>
              {RECON_KIND[k]}: {count(k)}
            </button>
          ))}
          <span className="grow" />
          {stockDiffs.length && canCount ? (
            <button type="button" className="btn sm primary" onClick={() => void toCount()} data-testid="recon-to-count" title={tr("mfg.integrationPages2.attr.opensACountPostingWith")}>
              {tr("mfg.integrationPages2.text.reviewAsStockCount", { length: stockDiffs.length })}
            </button>
          ) : null}
        </div>
      ) : null}
      {d.status === "completed" && !rows.length ? (
        <Banner tone="ok" title={t("mfg.integrationPages2.title.everythingMatches")} testId="recon-clean">
          {tr("mfg.integrationPages2.text.noDifferencesBetweenTheErp")}
        </Banner>
      ) : null}
      {shown.length ? (
        <DataTable
          rows={shown}
          columns={[
            { key: "entity", header: "Data", width: "110px", sortValue: (x) => x.entity, render: (x) => x.entity },
            { key: "item", header: "Item", width: "minmax(150px, 1fr)", sortValue: (x) => String(x.item ?? x.item_ref ?? ""), render: (x) => <span className="mono">{String(x.item ?? x.item_ref ?? "")}</span> },
            { key: "where", header: "Location / lot", width: "minmax(150px, 1fr)", render: (x) => [x.location, x.lot && `lot ${x.lot}`].filter(Boolean).join(" · ") },
            {
              key: "kind",
              header: "Finding",
              width: "minmax(170px, 1fr)",
              sortValue: (x) => x.kind,
              exportValue: (x) => RECON_KIND[x.kind],
              render: (x) => (
                <span>
                  <span className={`badge ${x.kind === "different" ? "warn" : "info"}`}>{RECON_KIND[x.kind]}</span>
                  {x.delta !== undefined ? <span className="small faint">{" "}{tr("mfg.integrationPages2.text.erp", { v: x.delta > 0 ? "+" : "" })}{x.delta}</span> : null}
                </span>
              ),
            },
            { key: "here", header: "Here", width: "100px", align: "right", sortValue: (x) => x.sp_qty ?? null, render: (x) => x.sp_qty ?? "" },
            { key: "erp", header: "ERP", width: "100px", align: "right", sortValue: (x) => x.erp_qty ?? null, render: (x) => x.erp_qty ?? "" },
          ]}
          rowKey={(_, i) => i}
          label={t("mfg.integrationPages2.label.differences")}
          testId="recon-results"
          exportName={`reconciliation-${d.id}`}
          rowExtras={(x) => ({ testId: "recon-row", data: { kind: x.kind } })}
          card={{ title: "item", status: "kind", fields: ["where", "here", "erp"] }}
        />
      ) : null}
    </div>
  );
}

async function findItemRef(partNumber: string) {
  const r = await listItems({ q: partNumber, limit: 5, offset: 0 });
  return r.items.find((x) => x.part_number === partNumber) ?? null;
}

export function PlantTokensTab() {
  const can = useCan("integration_admin");
  if (!can) return <p className="muted">{tr("mfg.integrationPages2.text.plantAdminsCreatePlantTokens")}</p>;
  return (
    <div className="col gap-lg">
      <p className="muted" style={{ margin: 0 }}>
        {tr("mfg.integrationPages2.text.aPlantTokenLetsThe")}
      </p>
      <TokenManager kind="plant" />
    </div>
  );
}

/** Integration console, part 2 (M5 4.3-4.8): webhooks, deliveries, data in, events out, file drop, code mappings, reconciliation, plant tokens. */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { TokenManager } from "../../../auth/TokensPage";
import { Banner } from "../../../components/Banner";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { saveBlob } from "../../api/client";
import {
  createEndpoint,
  deleteEndpoint,
  exportReconciliation,
  getBatch,
  getFiledropStatus,
  getReconciliation,
  getValueMaps,
  listBatches,
  listDeliveries,
  listEndpoints,
  listEvents,
  listMappingProfiles,
  listReconciliations,
  parkDelivery,
  putValueMaps,
  retryDelivery,
  startReconciliation,
  testEndpoint,
  updateEndpoint,
} from "../../api/clientM5";
import type { Batch, BatchRecordResult, Delivery, DeliveryStatus, Endpoint, EndpointCreated, ReconKind, ReconRow, ValueMap } from "../../api/typesM5";
import { MfgError, Spinner } from "../../components/Feedback";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { usePolling } from "../../lib/usePolling";

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

const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" }) : "");

// ---------------------------------------------------------------- webhooks
export function EndpointsTab() {
  const can = useCan("integration_admin");
  const eps = useLoad((signal) => listEndpoints(signal), []);
  const [edit, setEdit] = useState<Endpoint | "new" | null>(null);
  const [created, setCreated] = useState<EndpointCreated | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const [del, setDel] = useState<Endpoint | null>(null);
  return (
    <div className="col gap-lg" data-testid="int-endpoints">
      {created ? (
        <Banner tone="ok" title={`Webhook "${created.name}" added`} testId="endpoint-secret">
          <div className="col" style={{ gap: 6 }}>
            <span>Give this signing secret to the receiving system now; it is not shown again. The receiver checks the SP-Signature header with it.</span>
            <code className="totp-secret">{created.secret}</code>
            <div className="row">
              <button type="button" className="btn sm" onClick={() => void navigator.clipboard?.writeText(created.secret)}>
                <Icon name="copy" /> Copy
              </button>
              <button type="button" className="btn sm ghost" onClick={() => setCreated(null)}>
                Done
              </button>
            </div>
          </div>
        </Banner>
      ) : null}
      <section className="card">
        <div className="card-header">
          <h2>Webhooks</h2>
          {can ? (
            <button type="button" className="btn sm primary" onClick={() => setEdit("new")} data-testid="endpoint-new">
              <Icon name="plus" /> Add webhook
            </button>
          ) : null}
        </div>
        <MfgError error={eps.error} onRetry={eps.reload} />
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Address</th>
                <th>Events</th>
                <th>Health</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(eps.data?.items ?? []).length === 0 ? (
                <tr>
                  <td colSpan={5} className="muted">
                    No webhooks. Events can also be pulled by the ERP (Events out) or written as files.
                  </td>
                </tr>
              ) : null}
              {(eps.data?.items ?? []).map((e) => (
                <tr key={e.id} data-testid="endpoint-row" className={e.active ? undefined : "faint"}>
                  <td>
                    <strong>{e.name}</strong>
                    {!e.active ? <div className="small">paused</div> : null}
                  </td>
                  <td className="mono small" style={{ wordBreak: "break-all" }}>
                    {e.url}
                  </td>
                  <td className="small">{e.event_types.length ? `${e.event_types.length} types` : "all events"}</td>
                  <td className="small">
                    {e.stats?.dead ? (
                      <span className="badge danger">
                        <Icon name="alert" /> {e.stats.dead} failed
                      </span>
                    ) : e.stats?.blocked ? (
                      <span className="badge warn">
                        <Icon name="clock" /> retrying, later events wait
                      </span>
                    ) : (
                      <span className="badge ok">
                        <Icon name="check" /> ok
                      </span>
                    )}
                    {e.stats?.pending ? <div className="faint">{e.stats.pending} waiting</div> : null}
                    {e.stats?.last_error ? <div className="faint">{e.stats.last_error}</div> : null}
                    {testResult[e.id] ? <div data-testid="endpoint-test-result">{testResult[e.id]}</div> : null}
                  </td>
                  <td className="right">
                    {can ? (
                      <span className="row" style={{ justifyContent: "flex-end" }}>
                        <button
                          type="button"
                          className="btn sm"
                          disabled={testing === e.id}
                          onClick={async () => {
                            setTesting(e.id);
                            try {
                              const r = await testEndpoint(e.id);
                              setTestResult((x) => ({ ...x, [e.id]: r.ok ? `Test delivered (${r.status_code ?? "2xx"}${r.duration_ms ? `, ${r.duration_ms} ms` : ""})` : `Test failed: ${r.error ?? r.status_code}` }));
                            } catch (err) {
                              setTestResult((x) => ({ ...x, [e.id]: `Test failed: ${(err as Error).message}` }));
                            } finally {
                              setTesting(null);
                            }
                          }}
                          data-testid="endpoint-test"
                        >
                          Send test
                        </button>
                        <button type="button" className="btn sm ghost" onClick={() => setEdit(e)}>
                          Edit
                        </button>
                        <button type="button" className="btn sm ghost" onClick={() => setDel(e)}>
                          Remove
                        </button>
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {edit ? (
        <EndpointDialog
          ep={edit === "new" ? null : edit}
          onClose={() => setEdit(null)}
          onSaved={(x) => {
            setEdit(null);
            if ("secret" in x) setCreated(x as EndpointCreated);
            eps.reload();
          }}
        />
      ) : null}
      {del ? (
        <ConfirmDialog
          title={`Remove webhook "${del.name}"?`}
          confirmLabel="Remove"
          danger
          onCancel={() => setDel(null)}
          onConfirm={async () => {
            try {
              await deleteEndpoint(del.id);
            } finally {
              setDel(null);
              eps.reload();
            }
          }}
        >
          <p style={{ margin: 0 }}>Waiting deliveries to it are dropped. Events stay available in the event feed.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function EndpointDialog({ ep, onClose, onSaved }: { ep: Endpoint | null; onClose(): void; onSaved(x: Endpoint): void }) {
  const [name, setName] = useState(ep?.name ?? "");
  const [url, setUrl] = useState(ep?.url ?? "https://");
  const [all, setAll] = useState(!ep || ep.event_types.length === 0);
  const [types, setTypes] = useState<Set<string>>(new Set(ep?.event_types ?? []));
  const [active, setActive] = useState(ep?.active ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const urlOk = /^https:\/\/[^\s/]+/.test(url.trim());
  return (
    <Dialog
      title={ep ? `Webhook ${ep.name}` : "Add webhook"}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !name.trim() || !urlOk || (!all && types.size === 0)}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                const body = { name: name.trim(), url: url.trim(), event_types: all ? [] : [...types], active };
                onSaved(ep ? await updateEndpoint(ep.id, body) : await createEndpoint(body));
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
            data-testid="endpoint-save"
          >
            {ep ? "Save" : "Add"}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="ep-name">Name</label>
          <input id="ep-name" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. ERP middleware" data-testid="endpoint-name" />
        </div>
        <div className="field">
          <label htmlFor="ep-url">Address (https)</label>
          <input id="ep-url" className="input mono" value={url} onChange={(e) => setUrl(e.target.value)} aria-invalid={!urlOk} data-testid="endpoint-url" />
          <span className="hint">{urlOk ? "Each event is sent as a signed POST, in order; a failing event holds back later ones for this address." : "Use an https:// address."}</span>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> All events
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
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active (off = pause sending; events wait)
        </label>
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- deliveries
const DELIVERY: Record<DeliveryStatus, { label: string; tone: string; icon: "check" | "clock" | "alert" | "refresh" }> = {
  pending: { label: "Waiting", tone: "info", icon: "clock" },
  retrying: { label: "Retrying", tone: "warn", icon: "refresh" },
  delivered: { label: "Delivered", tone: "ok", icon: "check" },
  dead: { label: "Failed (stopped)", tone: "danger", icon: "alert" },
};

export function DeliveriesTab() {
  const can = useCan("integration_admin");
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
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
      <div className="row wrap" role="group" aria-label="Filter by status">
        {(["", "dead", "retrying", "pending", "delivered"] as const).map((s) => (
          <button key={s || "all"} type="button" className={`btn sm${status === s ? " primary" : ""}`} aria-pressed={status === s} onClick={() => setSearchParam(setParams, "status", s)}>
            {s ? DELIVERY[s].label : "All"}
          </button>
        ))}
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        Events go to each webhook one at a time, in order. A failing event is retried with growing pauses for up to 24 hours, then stops; events after it wait. Retry it after the receiver is fixed, or park it to let the rest through.
      </p>
      <MfgError error={error ?? data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="delivery-table">
          <thead>
            <tr>
              <th>Event</th>
              <th>Webhook</th>
              <th>Status</th>
              <th>Attempts</th>
              <th>Last answer</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="muted">
                  {data.loading ? "Loading…" : "Nothing here."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((d) => {
              const m = DELIVERY[d.status] ?? DELIVERY.pending;
              return (
                <tr key={d.id} data-testid="delivery-row" data-status={d.status}>
                  <td>
                    <span className="mono">#{d.event_seq}</span> <span className="mono small">{d.event_type}</span>
                  </td>
                  <td>{d.endpoint.name}</td>
                  <td>
                    <span className={`badge ${m.tone}`}>
                      <Icon name={m.icon} /> {m.label}
                    </span>
                    {d.blocked_by_seq ? <div className="small faint">waits for #{d.blocked_by_seq}</div> : null}
                    {d.status === "retrying" && d.next_attempt_at ? <div className="small faint">next try {when(d.next_attempt_at)}</div> : null}
                    {d.delivered_at ? <div className="small faint">{when(d.delivered_at)}</div> : null}
                  </td>
                  <td>{d.attempts}</td>
                  <td className="small">
                    {d.last_status_code ? `HTTP ${d.last_status_code}` : ""} {d.last_error ?? ""}
                  </td>
                  <td className="right">
                    {can && (d.status === "dead" || d.status === "retrying") ? (
                      <span className="row" style={{ justifyContent: "flex-end" }}>
                        <button type="button" className="btn sm" disabled={busy === d.id} onClick={() => void act(d.id, () => retryDelivery(d.id))} data-testid="delivery-retry">
                          <Icon name="refresh" /> Retry now
                        </button>
                        {d.status === "retrying" ? (
                          <button type="button" className="btn sm ghost" disabled={busy === d.id} onClick={() => void act(d.id, () => parkDelivery(d.id))} data-testid="delivery-park" title="Stop retrying this event so later events are sent">
                            Park
                          </button>
                        ) : null}
                      </span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {data.rows.length < data.total ? (
          <div className="card-footer">
            <button type="button" className="btn sm" onClick={data.onEndReached} disabled={data.loading}>
              Show more ({data.rows.length} of {data.total})
            </button>
          </div>
        ) : null}
      </div>
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
        Each batch from the ERP (REST, file drop or a publish from another plant) goes through the same checks as an edit here. Records that fail are rejected one by one; the rest are applied.
      </p>
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="batch-table">
          <thead>
            <tr>
              <th>Received</th>
              <th>Data</th>
              <th>From</th>
              <th>Status</th>
              <th className="right">Created</th>
              <th className="right">Updated</th>
              <th className="right">Unchanged</th>
              <th className="right">Rejected</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="muted">
                  {data.loading ? "Loading…" : "No data received yet."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((b) => (
              <tr key={b.id} data-testid="batch-row" data-status={b.status}>
                <td>
                  <Link to={mfgPaths.integrationBatch(b.id)}>{when(b.received_at)}</Link>
                </td>
                <td>
                  {b.entity} <span className="faint small">{b.mode}</span>
                </td>
                <td className="small">
                  {b.source}
                  {b.filename ? <div className="mono faint">{b.filename}</div> : null}
                </td>
                <td>
                  <span className={`badge ${BATCH_TONE[b.status] ?? "info"}`}>{b.status}</span>
                </td>
                <td className="right">{b.counts.created}</td>
                <td className="right">{b.counts.updated}</td>
                <td className="right">{b.counts.unchanged}</td>
                <td className="right">
                  {b.counts.rejected ? (
                    <span className="badge danger">
                      <Icon name="alert" /> {b.counts.rejected}
                    </span>
                  ) : (
                    0
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.rows.length < data.total ? (
          <div className="card-footer">
            <button type="button" className="btn sm" onClick={data.onEndReached} disabled={data.loading}>
              Show more ({data.rows.length} of {data.total})
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const ERROR_HELP: Record<string, string> = {
  INT_SOR_CONFLICT: "This data is owned by SuperPlanner in this plant, so the ERP may not change it.",
  INT_UNMAPPED_VALUE: "A code from the ERP has no mapping here. Add it under Code mappings and send the record again.",
  INT_SCHEMA: "The record does not match the superplanner.v1 format.",
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
  const rows = d.results.filter((r) => !only || r.status === only);
  return (
    <div className="col gap-lg" data-testid="batch-page" data-status={d.status}>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={mfgPaths.integration("batches")}>Data in</Link> <Icon name="chevron-right" size={12} /> <span>{when(d.received_at)}</span>
      </nav>
      <h2 style={{ margin: 0 }}>
        {d.entity} from {d.source} <span className={`badge ${BATCH_TONE[d.status] ?? "info"}`}>{d.status}</span>
      </h2>
      <span className="muted small">
        {d.idempotency_key ? <>Key <span className="mono">{d.idempotency_key}</span> · </> : null}
        {d.filename ? <>File <span className="mono">{d.filename}</span> · </> : null}
        resending the same batch with the same key changes nothing.
      </span>
      <div className="row wrap" role="group" aria-label="Show">
        {(["", "rejected", "created", "updated", "unchanged"] as const).map((s) => (
          <button key={s || "all"} type="button" className={`btn sm${only === s ? " primary" : ""}`} aria-pressed={only === s} onClick={() => setOnly(s)} data-testid={`batch-filter-${s || "all"}`}>
            {s ? `${s[0].toUpperCase()}${s.slice(1)} (${d.counts[s] ?? 0})` : `All (${d.results.length})`}
          </button>
        ))}
      </div>
      <div className="table-wrap card">
        <table className="table" data-testid="batch-results">
          <thead>
            <tr>
              <th>Record</th>
              <th>Result</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.ref}-${i}`} data-testid="batch-record" data-status={r.status}>
                <td className="mono">{r.ref}</td>
                <td>
                  <span className={`badge ${REC_STATUS[r.status].tone}`}>
                    <Icon name={REC_STATUS[r.status].icon} /> {r.status}
                  </span>
                </td>
                <td className="small">
                  {r.errors.map((e, k) => (
                    <div key={k}>
                      {e.field ? <span className="mono">{e.field}: </span> : null}
                      {e.message} <span className="faint">({e.code})</span>
                      {ERROR_HELP[e.code] ? <div className="faint">{ERROR_HELP[e.code]}</div> : null}
                      {e.code === "INT_UNMAPPED_VALUE" ? (
                        <div>
                          <Link to={mfgPaths.integration("value-maps")}>Add a code mapping</Link>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
        What SuperPlanner reports to the ERP, in order. The ERP can read this feed itself (GET /api/v1/integration/events?after=…) with a plant token, receive it by webhook, or as files.
      </p>
      <div className="toolbar">
        <div className="field">
          <label htmlFor="ev-type">Type</label>
          <select id="ev-type" className="select sm" value={type} onChange={(e) => { setType(e.target.value); setAfter(0); }}>
            <option value="">All</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="ev-after">After event #</label>
          <input id="ev-after" className="input sm" type="number" min={0} value={after} onChange={(e) => setAfter(Math.max(0, Number(e.target.value) || 0))} />
        </div>
      </div>
      <MfgError error={ev.error} onRetry={ev.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="event-table">
          <tbody>
            {(ev.data?.items ?? []).length === 0 ? (
              <tr>
                <td className="muted">{ev.loading ? "Loading…" : "No events after this number."}</td>
              </tr>
            ) : null}
            {(ev.data?.items ?? []).map((e) => [
              <tr key={e.seq} data-testid="event-row">
                <td className="mono">#{e.seq}</td>
                <td className="mono small">{e.type}</td>
                <td className="small">{when(e.occurred_at)}</td>
                <td className="small mono">{e.entity_ref ?? ""}</td>
                <td>
                  <button type="button" className="btn sm ghost" aria-expanded={open === e.seq} onClick={() => setOpen(open === e.seq ? null : e.seq)}>
                    Data
                  </button>
                </td>
              </tr>,
              open === e.seq ? (
                <tr key={`${e.seq}-d`}>
                  <td colSpan={5}>
                    <pre className="int-json">{JSON.stringify(e.data, null, 2)}</pre>
                  </td>
                </tr>
              ) : null,
            ])}
          </tbody>
        </table>
        {ev.data && ev.data.items.length ? (
          <div className="card-footer">
            <button type="button" className="btn sm" onClick={() => setAfter(ev.data!.next_after)}>
              Next events
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- file drop
export function FiledropTab() {
  const st = useLoad((signal) => getFiledropStatus(signal), []);
  const profiles = useLoad((signal) => listMappingProfiles(signal), []);
  usePolling(st.reload, true, 30000);
  const s = st.data;
  return (
    <div className="col gap-lg" data-testid="int-filedrop">
      <MfgError error={st.error} onRetry={st.reload} />
      {s ? (
        <>
          {!s.enabled ? <Banner tone="info" title="File drop is off">Turn it on under Settings, Files.</Banner> : null}
          <div className="kpis">
            <div className="card kpi">
              <div className="kpi-label">Waiting in the inbox</div>
              <div className="kpi-value">{s.counts.inbox}</div>
            </div>
            <div className="card kpi">
              <div className="kpi-label">Being read</div>
              <div className="kpi-value">{s.counts.processing}</div>
            </div>
            <div className="card kpi">
              <div className="kpi-label">In error</div>
              <div className="kpi-value" style={{ color: s.counts.error ? "var(--danger)" : undefined }}>
                {s.counts.error}
              </div>
            </div>
          </div>
          <p className="muted small" style={{ margin: 0 }}>
            Folder <span className="mono">{s.plant_code ?? "<plant code>"}/inbox</span> on the integration volume. Files are read once their size stops changing (or a .done file appears), checked like an import, then moved to archive with a .result.json, or to error with a report.
            {s.last_scan_at ? ` Last check ${when(s.last_scan_at)}.` : ""}
          </p>
          <section className="card">
            <div className="card-header">
              <h2>Recent files</h2>
            </div>
            <table className="table" data-testid="filedrop-recent">
              <tbody>
                {s.recent.length === 0 ? (
                  <tr>
                    <td className="muted">No files yet.</td>
                  </tr>
                ) : null}
                {s.recent.map((r) => (
                  <tr key={`${r.file}${r.at}`}>
                    <td className="mono small">{r.file}</td>
                    <td>
                      <span className={`badge ${r.status === "error" ? "danger" : r.status === "archived" ? "ok" : "info"}`}>
                        <Icon name={r.status === "error" ? "alert" : r.status === "archived" ? "check" : "clock"} /> {r.status === "archived" ? "imported" : r.status}
                      </span>
                    </td>
                    <td className="small">{r.counts ? Object.entries(r.counts).map(([k, v]) => `${v} ${k}`).join(" · ") : ""}</td>
                    <td className="small">{r.errors ? `${r.errors} row errors` : ""}</td>
                    <td className="small">{when(r.at)}</td>
                    <td>{r.batch_id ? <Link to={mfgPaths.integrationBatch(r.batch_id)}>Results</Link> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      ) : st.loading ? (
        <Spinner />
      ) : null}
      <section className="card">
        <div className="card-header">
          <h2>Mappings by file name</h2>
        </div>
        <MfgError error={profiles.error} onRetry={profiles.reload} />
        <table className="table">
          <tbody>
            {(profiles.data?.items ?? []).length === 0 ? (
              <tr>
                <td className="muted">
                  None. Save a mapping in <Link to={mfgPaths.importStart()}>Import</Link> for a sample file; files named like it use it. superplanner.v1 JSON needs no mapping.
                </td>
              </tr>
            ) : null}
            {(profiles.data?.items ?? []).map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td className="mono small">{p.file_pattern}</td>
                <td>{p.entity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- code mappings
const DOMAINS = [
  { key: "uom", label: "Units of measure", hint: "e.g. NOS -> EA" },
  { key: "location", label: "Locations", hint: "ERP storage location -> location code" },
  { key: "reason", label: "Reason codes", hint: "" },
  { key: "status", label: "Statuses", hint: "" },
];

export function ValueMapsTab() {
  const can = useCan("integration_admin");
  const vm = useLoad((signal) => getValueMaps(signal), []);
  const [rows, setRows] = useState<ValueMap[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (vm.data) setRows(vm.data.items);
  }, [vm.data]);
  const set = (i: number, patch: Partial<ValueMap>) => {
    setSaved(false);
    setRows((r) => r.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  };
  return (
    <section className="card" data-testid="int-value-maps">
      <div className="card-header">
        <h2>Code mappings</h2>
        <span className="muted small">Translate the ERP's codes to this plant's. Unmapped codes reject the record.</span>
      </div>
      <MfgError error={vm.error ?? error} onRetry={vm.reload} />
      <table className="table">
        <thead>
          <tr>
            <th>Kind</th>
            <th>ERP code</th>
            <th>Code here</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} data-testid="value-map-row">
              <td>
                <select className="select sm" aria-label="Kind" value={r.domain} disabled={!can} onChange={(e) => set(i, { domain: e.target.value })}>
                  {DOMAINS.map((d) => (
                    <option key={d.key} value={d.key}>
                      {d.label}
                    </option>
                  ))}
                  {!DOMAINS.some((d) => d.key === r.domain) ? <option value={r.domain}>{r.domain}</option> : null}
                </select>
              </td>
              <td>
                <input className="input sm mono" aria-label="ERP code" value={r.external_value} disabled={!can} onChange={(e) => set(i, { external_value: e.target.value })} />
              </td>
              <td>
                <input className="input sm mono" aria-label="Code here" value={r.internal_value} disabled={!can} onChange={(e) => set(i, { internal_value: e.target.value })} />
              </td>
              <td>
                {can ? (
                  <button type="button" className="btn sm ghost icon" aria-label="Remove mapping" onClick={() => setRows((x) => x.filter((_, k) => k !== i))}>
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
            <Icon name="plus" /> Add mapping
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
                setRows(out.items);
                setSaved(true);
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
            data-testid="value-map-save"
          >
            <Icon name="save" /> Save
          </button>
          {saved ? (
            <span className="badge ok">
              <Icon name="check" /> Saved
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------- reconciliation
const RECON_ENTITIES = [
  { key: "stock", label: "Stock" },
  { key: "purchase_orders", label: "Purchase orders" },
  { key: "items", label: "Items" },
];
const RECON_KIND: Record<ReconKind, string> = { missing_in_sp: "Only in the ERP", missing_in_erp: "Only here", different: "Different", sor_conflict: "Changed on both sides" };

export function ReconciliationTab() {
  const can = useCan("integration_admin");
  const navigate = useNavigate();
  const list = useLoad((signal) => listReconciliations(signal), []);
  usePolling(list.reload, (list.data?.items ?? []).some((r) => r.status === "queued" || r.status === "running"), 3000);
  const [ents, setEnts] = useState<Set<string>>(new Set(["stock"]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <div className="col gap-lg" data-testid="int-recon">
      <section className="card">
        <div className="card-header">
          <h2>Compare with the ERP</h2>
        </div>
        <div className="card-body col">
          <p className="muted" style={{ margin: 0 }}>
            Compares the ERP's latest snapshot with this plant: records missing on either side and differences (stock by item, location and lot). Nothing is changed; stock differences can be turned into a count posting after review.
          </p>
          <div className="row wrap">
            {RECON_ENTITIES.map((e) => (
              <label key={e.key} className="checkbox">
                <input
                  type="checkbox"
                  checked={ents.has(e.key)}
                  onChange={() =>
                    setEnts((s) => {
                      const n = new Set(s);
                      if (n.has(e.key)) n.delete(e.key);
                      else n.add(e.key);
                      return n;
                    })
                  }
                />
                {e.label}
              </label>
            ))}
          </div>
          <MfgError error={error} />
          <div>
            <button
              type="button"
              className="btn primary"
              disabled={!can || busy || ents.size === 0}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  const r = await startReconciliation({ entities: [...ents], snapshot: "adapter" });
                  navigate(mfgPaths.integrationRecon(r.id));
                } catch (e) {
                  setError(e);
                  setBusy(false);
                }
              }}
              data-testid="recon-start"
            >
              <Icon name="compare" /> Compare now
            </button>
          </div>
        </div>
      </section>
      <div className="table-wrap card">
        <table className="table" data-testid="recon-list">
          <tbody>
            {(list.data?.items ?? []).map((r) => (
              <tr key={r.id}>
                <td>
                  <Link to={mfgPaths.integrationRecon(r.id)}>{when(r.created_at)}</Link>
                </td>
                <td>{r.entities.join(", ")}</td>
                <td>
                  <span className={`badge ${r.status === "completed" ? "ok" : r.status === "failed" ? "danger" : "info"}`}>{r.status}</span>
                </td>
                <td className="small">{r.summary ? Object.entries(r.summary).filter(([, n]) => n).map(([k, n]) => `${n} ${RECON_KIND[k as ReconKind]?.toLowerCase() ?? k}`).join(" · ") || "all match" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
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
  const rows = (d.results ?? []).filter((x) => !kind || x.kind === kind);
  const stockDiffs = (d.results ?? []).filter((x) => x.entity === "stock" && x.kind === "different" && x.item);
  const toCount = () => {
    // reviewed count posting: the store keeper sees the ERP quantities prefilled in the posting form
    navigate(mfgPaths.post({ type: "count" }), {
      state: { prefill: { reason: "ERP_SYNC", note: `Reconciliation ${d.id}`, lines: stockDiffs.map((x: ReconRow) => ({ item: x.item, location_code: x.location_code, lot_code: x.lot_code, qty: x.qty_erp })) } },
    });
  };
  return (
    <div className="col gap-lg" data-testid="recon-page" data-status={d.status}>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={mfgPaths.integration("reconciliation")}>Reconciliation</Link> <Icon name="chevron-right" size={12} /> <span>{when(d.created_at)}</span>
      </nav>
      {d.status === "queued" || d.status === "running" ? <Spinner label="Comparing…" /> : null}
      {d.status === "failed" ? <Banner tone="danger" title="The comparison failed">{d.error?.message}</Banner> : null}
      {d.summary ? (
        <div className="row wrap" role="group" aria-label="Show">
          <button type="button" className={`btn sm${!kind ? " primary" : ""}`} aria-pressed={!kind} onClick={() => setKind("")}>
            All
          </button>
          {(Object.keys(RECON_KIND) as ReconKind[]).map((k) => (
            <button key={k} type="button" className={`btn sm${kind === k ? " primary" : ""}`} aria-pressed={kind === k} onClick={() => setKind(k)} data-testid={`recon-kind-${k}`}>
              {RECON_KIND[k]}: {d.summary?.[k] ?? 0}
            </button>
          ))}
          <span className="grow" />
          <button type="button" className="btn sm" onClick={async () => saveBlob(await exportReconciliation(d.id))}>
            <Icon name="download" /> Excel
          </button>
          {stockDiffs.length && canCount ? (
            <button type="button" className="btn sm primary" onClick={toCount} data-testid="recon-to-count" title="Opens a count posting with the ERP quantities for review; nothing is posted until you confirm">
              Review as stock count ({stockDiffs.length})
            </button>
          ) : null}
        </div>
      ) : null}
      {d.summary && !(d.results ?? []).length ? (
        <Banner tone="ok" title="Everything matches">
          No differences between the ERP and this plant.
        </Banner>
      ) : null}
      {rows.length ? (
        <div className="table-wrap card">
          <table className="table" data-testid="recon-results">
            <thead>
              <tr>
                <th>Data</th>
                <th>Record</th>
                <th>Finding</th>
                <th>Here</th>
                <th>ERP</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x, i) => (
                <tr key={i} data-testid="recon-row" data-kind={x.kind}>
                  <td>{x.entity}</td>
                  <td>
                    <span className="mono">{x.item?.part_number ?? x.ref}</span>
                    {x.label ? <div className="small">{x.label}</div> : null}
                    {x.location_code || x.lot_code ? <div className="small faint">{[x.location_code, x.lot_code && `lot ${x.lot_code}`].filter(Boolean).join(" · ")}</div> : null}
                  </td>
                  <td>
                    <span className={`badge ${x.kind === "different" ? "warn" : x.kind === "sor_conflict" ? "danger" : "info"}`}>{RECON_KIND[x.kind]}</span>
                    {x.fields?.length ? <div className="small faint">{x.fields.map((f) => f.field).join(", ")}</div> : null}
                  </td>
                  <td className="small">{x.qty_sp ?? (x.fields ? x.fields.map((f) => `${f.field}: ${String(f.sp)}`).join("; ") : "")}</td>
                  <td className="small">{x.qty_erp ?? (x.fields ? x.fields.map((f) => `${f.field}: ${String(f.erp)}`).join("; ") : "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

export function PlantTokensTab() {
  const can = useCan("integration_admin");
  if (!can) return <p className="muted">Plant admins create plant tokens.</p>;
  return (
    <div className="col gap-lg">
      <p className="muted" style={{ margin: 0 }}>
        A plant token lets the ERP or its middleware call SuperPlanner for this plant without a personal login: send batches (POST /api/v1/integration/batches with an Idempotency-Key) and read events.
      </p>
      <TokenManager kind="plant" />
    </div>
  );
}

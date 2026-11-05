/**
 * Audit trail (M5 7, owner / plant admin / org admin): every change with who (person, or API token for a person or
 * plant), when and what; export as JSON lines or CSV for an auditor; check the tamper-evident hash chain.
 */
import { useEffect, useState } from "react";
import { ApiError } from "../../../api/client";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { saveBlob } from "../../api/client";
import { exportAudit, listAudit, verifyAudit } from "../../api/clientM5";
import type { AuditEvent, AuditVerify } from "../../api/typesM5";
import { MfgError } from "../../components/Feedback";
import { usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";

export function AuditPage() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [entity, setEntity] = useState("");
  const [actor, setActor] = useState("");
  const de = useDebounced(entity.trim(), 300);
  const da = useDebounced(actor.trim(), 300);
  const q = { from: from ? `${from}T00:00:00Z` : undefined, to: to ? `${to}T23:59:59Z` : undefined, entity_type: de || undefined, actor: da || undefined };
  const data = usePaged<AuditEvent>((offset, limit, signal) => listAudit({ ...q, limit, offset }, signal), [from, to, de, da]);
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [verify, setVerify] = useState<AuditVerify | "unavailable" | null>(null);
  useEffect(() => {
    document.title = "Audit trail - SuperPlanner";
  }, []);
  const download = async (format: "jsonl" | "csv") => {
    setBusy(format);
    setError(null);
    try {
      saveBlob(await exportAudit({ format, from: q.from, to: q.to }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="col gap-lg" data-testid="audit-page">
      <div className="mfg-page-head">
        <div>
          <h1>Audit trail</h1>
          <p>Every change in this plant: who, when, what. Entries are chained by a hash so later tampering shows up.</p>
        </div>
        <div className="row wrap">
          <button type="button" className="btn" disabled={busy !== null} onClick={() => void download("csv")} data-testid="audit-export-csv">
            <Icon name="download" /> CSV
          </button>
          <button type="button" className="btn" disabled={busy !== null} onClick={() => void download("jsonl")} data-testid="audit-export-jsonl">
            <Icon name="download" /> JSON lines
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy !== null}
            onClick={async () => {
              setBusy("verify");
              setError(null);
              try {
                setVerify(await verifyAudit({ from: q.from, to: q.to }));
              } catch (e) {
                if (e instanceof ApiError && (e.status === 404 || e.status === 405)) setVerify("unavailable");
                else setError(e);
              } finally {
                setBusy(null);
              }
            }}
            data-testid="audit-verify"
          >
            <Icon name="check" /> Check the chain
          </button>
        </div>
      </div>
      {verify === "unavailable" ? (
        <Banner tone="info" title="The chain check runs on the server">An administrator runs manage.py audit-verify; the exports include each entry's chain hash so an auditor can check them independently.</Banner>
      ) : verify ? (
        verify.ok ? (
          <Banner tone="ok" title="The audit chain is intact" testId="audit-verify-ok">
            {verify.checked} entries checked; none was changed or removed.
          </Banner>
        ) : (
          <Banner tone="danger" title="The audit chain is broken" testId="audit-verify-broken">
            The first entry that does not match its chain is {verify.first_broken ? `${verify.first_broken.id} (${new Date(verify.first_broken.at).toLocaleString()})` : "unknown"}. Entries from there on cannot be trusted; contact your administrator.
          </Banner>
        )
      ) : null}
      <div className="toolbar mfg-filters" role="search">
        <div className="field">
          <label htmlFor="au-from">From</label>
          <input id="au-from" className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="au-to">To</label>
          <input id="au-to" className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="au-entity">What (kind)</label>
          <input id="au-entity" className="input" value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="e.g. item, work_order" />
        </div>
        <div className="field">
          <label htmlFor="au-actor">Who (user or token id)</label>
          <input id="au-actor" className="input mono" value={actor} onChange={(e) => setActor(e.target.value)} placeholder="usr_… or tok_…" />
        </div>
      </div>
      <MfgError error={error ?? data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="audit-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>Did</th>
              <th>To what</th>
              <th>Chain</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  {data.loading ? "Loading…" : "No entries."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((e) => [
              <tr key={e.id} data-testid="audit-row">
                <td className="small">{new Date(e.created_at).toLocaleString()}</td>
                <td className="small mono">
                  {e.actor_id ?? "system"}
                  {e.actor_id?.startsWith("tok_") ? <div className="faint">API token</div> : null}
                </td>
                <td>{e.action.replace(/_/g, " ")}</td>
                <td className="small">
                  {e.entity_type.replace(/_/g, " ")} <span className="mono faint">{e.entity_id ?? ""}</span>
                </td>
                <td>
                  <span className="mono small faint" title={e.chain_hash ?? "not chained (before M5)"}>
                    {e.chain_hash ? `${e.chain_hash.slice(0, 10)}…` : "—"}
                  </span>{" "}
                  {e.details && Object.keys(e.details).length ? (
                    <button type="button" className="btn sm ghost" aria-expanded={open === e.id} onClick={() => setOpen(open === e.id ? null : e.id)}>
                      Details
                    </button>
                  ) : null}
                </td>
              </tr>,
              open === e.id ? (
                <tr key={`${e.id}-d`}>
                  <td colSpan={5}>
                    <pre className="int-json">{JSON.stringify(e.details, null, 2)}</pre>
                  </td>
                </tr>
              ) : null,
            ])}
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

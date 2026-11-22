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
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";
import { formatDateTime } from "../../../lib/locale";
import { PageHeader } from "../../../components/PageHeader";
import { FilterBar } from "../../../components/FilterBar";
import { DateInput } from "../../../components/DateInput";
import { t } from "../../../lib/i18n";

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
  const openEvent = data.rows.find((e) => e.id === open) ?? null;
  const columns: Column<AuditEvent>[] = [
    { key: "when", header: "When", width: "160px", render: (e) => formatDateTime(e.created_at) },
    {
      key: "who",
      header: "Who",
      width: "minmax(170px, 1fr)",
      exportValue: (e) => e.actor_id ?? "system",
      render: (e) => (
        <span className="mono small">
          {e.actor_id ?? "system"}
          {e.actor_id?.startsWith("tok_") ? <span className="faint"> · API token</span> : null}
        </span>
      ),
    },
    { key: "did", header: "Did", width: "minmax(150px, 1fr)", render: (e) => e.action.replace(/_/g, " ") },
    {
      key: "what",
      header: "To what",
      width: "minmax(200px, 1.4fr)",
      exportValue: (e) => `${e.entity_type} ${e.entity_id ?? ""}`.trim(),
      render: (e) => (
        <span>
          {e.entity_type.replace(/_/g, " ")} <span className="mono faint">{e.entity_id ?? ""}</span>
        </span>
      ),
    },
    {
      key: "chain",
      header: "Chain",
      width: "200px",
      exportValue: (e) => e.chain_hash ?? "",
      render: (e) => (
        <>
          <span className="mono small faint" title={e.chain_hash ?? "not chained (before M5)"}>
            {e.chain_hash ? `${e.chain_hash.slice(0, 10)}…` : "—"}
          </span>
          {e.details && Object.keys(e.details).length ? (
            <button
              type="button"
              className="btn sm ghost"
              aria-expanded={open === e.id}
              onClick={(ev) => {
                ev.stopPropagation();
                setOpen(open === e.id ? null : e.id);
              }}
            >
              {t("mfg.auditPage.btn.details")}
            </button>
          ) : null}
        </>
      ),
    },
  ];
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
      <PageHeader
        title={t("mfg.auditPage.title.auditTrail")}
        description={t("mfg.auditPage.desc.everyChangeInThisPlant")}
        actions={
          <>
            <button type="button" className="btn" disabled={busy !== null} onClick={() => void download("csv")} data-testid="audit-export-csv">
            <Icon name="download" /> {t("mfg.auditPage.btn.csv")}
            </button>
            <button type="button" className="btn" disabled={busy !== null} onClick={() => void download("jsonl")} data-testid="audit-export-jsonl">
            <Icon name="download" /> {t("mfg.auditPage.btn.jsonLines")}
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
            <Icon name="check" /> {t("mfg.auditPage.btn.checkTheChain")}
            </button>
          </>
        }
      />
      {verify === "unavailable" ? (
        <Banner tone="info" title={t("mfg.auditPage.title.theChainCheckRunsOn")}>An administrator runs manage.py audit-verify; the exports include each entry's chain hash so an auditor can check them independently.</Banner>
      ) : verify ? (
        verify.ok ? (
          <Banner tone="ok" title={t("mfg.auditPage.title.theAuditChainIsIntact")} testId="audit-verify-ok">
            {verify.checked} entries checked; none was changed or removed.
          </Banner>
        ) : (
          <Banner tone="danger" title={t("mfg.auditPage.title.theAuditChainIsBroken")} testId="audit-verify-broken">
            The first entry that does not match its chain is {verify.first_broken ? `${verify.first_broken.id} (${formatDateTime(verify.first_broken.at)})` : "unknown"}. Entries from there on cannot be trusted; contact your administrator.
          </Banner>
        )
      ) : null}
      <FilterBar>
        <div className="field">
          <label htmlFor="au-from">{t("mfg.auditPage.label.from")}</label>
          <DateInput id="au-from" value={from} onChange={(v) => setFrom(v)} />
        </div>
        <div className="field">
          <label htmlFor="au-to">{t("mfg.auditPage.label.to")}</label>
          <DateInput id="au-to" value={to} onChange={(v) => setTo(v)} />
        </div>
        <div className="field">
          <label htmlFor="au-entity">{t("mfg.auditPage.label.whatKind")}</label>
          <input id="au-entity" className="input" value={entity} onChange={(e) => setEntity(e.target.value)} placeholder={t("mfg.auditPage.ph.egItemWorkorder")} />
        </div>
        <div className="field">
          <label htmlFor="au-actor">{t("mfg.auditPage.label.whoUserOrTokenId")}</label>
          <input id="au-actor" className="input mono" value={actor} onChange={(e) => setActor(e.target.value)} placeholder={t("mfg.auditPage.ph.usrOrTok")} />
        </div>
      </FilterBar>
      <MfgError error={error ?? data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(e) => e.id}
        label={t("mfg.auditPage.label.auditTrail")}
        testId="audit-table"
        totalCount={data.total}
        loading={data.loading}
        onEndReached={data.onEndReached}
        onRowClick={(e) => (e.details && Object.keys(e.details).length ? setOpen(e.id) : undefined)}
        onActivate={(e) => (e.details && Object.keys(e.details).length ? setOpen(open === e.id ? null : e.id) : undefined)}
        rowExtras={(e) => ({ testId: "audit-row", className: open === e.id ? "mfg-selected" : undefined })}
        empty={t("mfg.auditPage.empty.noEntriesChangesInThis")}
        footer={<span className="muted small">Showing {t("common.nOfM", { n: data.rows.length.toLocaleString("en-IN"), m: data.total.toLocaleString("en-IN") })} entries, newest first</span>}
        card={{ title: "when", fields: ["who", "did", "what"] }}
      />
      {openEvent ? (
        <section className="card" data-testid="audit-details">
          <div className="card-header">
            <h2>
              {openEvent.action.replace(/_/g, " ")} · {openEvent.entity_type.replace(/_/g, " ")} <span className="mono faint">{openEvent.entity_id ?? ""}</span>
            </h2>
            <button type="button" className="btn sm ghost" onClick={() => setOpen(null)}>
              <Icon name="x" /> {t("mfg.auditPage.btn.close")}
            </button>
          </div>
          <pre className="int-json" style={{ margin: 0, border: 0 }}>
            {JSON.stringify(openEvent.details, null, 2)}
          </pre>
        </section>
      ) : null}
    </div>
  );
}

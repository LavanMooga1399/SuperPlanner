/**
 * Record page anatomy shared by every quality record (M7 10): breadcrumb, header (number, status chip, key facts, one
 * primary action = the next step for this user), tabs Details | <record lines> | Links | Attachments | History |
 * Signatures, and the change-reason prompt of Part 11 plants. History is the record's audit trail (old -> new values,
 * reasons, signatures); Signatures lists the manifestations with a verify check per signature.
 */
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { Icon, type IconName } from "../../components/Icon";
import { toast } from "../../components/Toast";
import { saveBlob } from "../api/client";
import { createLink, deleteAttachment, deleteLink, downloadAttachment, getRecordAudit, uploadAttachment, verifySignature } from "../api/clientM7";
import type { AttachmentRef, LinkType, QaLink, RecordAuditEvent, SignatureManifest, VerifyResult } from "../api/typesM7";
import { MfgError } from "../components/Feedback";
import { DataTable, ShowMore } from "../components/DataTable";
import type { Column } from "../components/VirtualTable";
import { fmtBytes } from "../lib/importMapping";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { usePaged } from "../lib/usePaged";
import { formatDateTime } from "../../lib/locale";
import { savePref, syncPref } from "../../lib/serverPrefs";
import { plural, t, type StringKey } from "../../lib/i18n";
import { authText, manifestText, meaningText, recordTypeText } from "./labels";
import { usePart11 } from "./part11";
import "./qa.css";

// ---------------------------------------------------------------- header
export function RecordHeader({
  crumbs,
  number,
  title,
  status,
  chips,
  facts,
  actions,
  testId,
}: {
  crumbs: [string, string][];
  number: string;
  title?: string | null;
  status: ReactNode;
  chips?: ReactNode;
  facts: [string, ReactNode][];
  actions?: ReactNode;
  testId?: string;
}) {
  return (
    <header className="col" style={{ gap: 6 }} data-testid={testId}>
      <nav className="mfg-breadcrumb no-print" aria-label={t("qa.shell.aria.breadcrumb")}>
        {crumbs.map(([label, to]) => (
          <span key={to} className="row" style={{ gap: 4 }}>
            <Link to={to}>{label}</Link> <Icon name="chevron-right" size={12} />
          </span>
        ))}
        <span className="mono">{number}</span>
      </nav>
      <div className="qa-record-head">
        <div className="col" style={{ gap: 2, minWidth: 0, flex: "1 1 360px" }}>
          <div className="qa-record-title">
            <h1>
              <span className="mono">{number}</span>
              {title ? <span style={{ fontWeight: 600 }}> {title}</span> : null}
            </h1>
            {status}
            {chips}
          </div>
        </div>
        {actions ? (
          <div className="qa-record-actions no-print" role="group" aria-label={t("qa.shell.aria.actions")}>
            {actions}
          </div>
        ) : null}
      </div>
      {facts.length ? (
        <dl className="qa-facts">
          {facts.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v === null || v === undefined || v === "" ? <span className="faint">—</span> : v}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </header>
  );
}

// ---------------------------------------------------------------- tabs
export interface TabDef {
  key: string;
  label: string;
  count?: number;
  testId?: string;
}

/** WAI-ARIA tabs: arrow keys move between tabs, the panel follows. */
export function RecordTabs({ tabs, value, onChange, label }: { tabs: TabDef[]; value: string; onChange(k: string): void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const n = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
    if (n === null) return;
    e.preventDefault();
    const j = (n + tabs.length) % tabs.length;
    onChange(tabs[j].key);
    refs.current[j]?.focus();
  };
  return (
    <div className="tabs no-print" role="tablist" aria-label={label}>
      {tabs.map((tb, i) => (
        <button
          key={tb.key}
          ref={(el) => (refs.current[i] = el)}
          type="button"
          role="tab"
          id={`tab-${tb.key}`}
          aria-selected={value === tb.key}
          aria-controls={`panel-${tb.key}`}
          tabIndex={value === tb.key ? 0 : -1}
          className={`tab${value === tb.key ? " active" : ""}`}
          onClick={() => onChange(tb.key)}
          onKeyDown={(e) => onKey(e, i)}
          data-testid={tb.testId ?? `qa-tab-${tb.key}`}
        >
          {tb.label}
          {tb.count !== undefined && tb.count > 0 ? <span className="tab-count">{tb.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} className="qa-panel">
      {children}
    </div>
  );
}

/** The standard tabs after the record's own ones. */
export function standardTabs(rec: { links: QaLink[]; attachments: AttachmentRef[]; signatures: SignatureManifest[] }): TabDef[] {
  return [
    { key: "links", label: t("qa.shell.tab.links"), count: rec.links.length },
    { key: "attachments", label: t("qa.shell.tab.attachments"), count: rec.attachments.length },
    { key: "history", label: t("qa.shell.tab.history") },
    { key: "signatures", label: t("qa.shell.tab.signatures"), count: rec.signatures.length },
  ];
}

// ---------------------------------------------------------------- section card
export function Section({ title, actions, children, testId, flush }: { title: string; actions?: ReactNode; children: ReactNode; testId?: string; flush?: boolean }) {
  return (
    <section className={`card${flush ? " card-table" : ""}`} data-testid={testId}>
      <div className="card-header">
        <h2>{title}</h2>
        {actions ? <div className="row wrap" style={{ gap: 6 }}>{actions}</div> : null}
      </div>
      {flush ? children : <div className="card-body">{children}</div>}
    </section>
  );
}

/** Read-only key/value grid of a record's details. */
export function DetailGrid({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="qa-facts" style={{ borderTop: 0, paddingTop: 0, marginTop: 0 }}>
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v === null || v === undefined || v === "" ? <span className="faint">—</span> : v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function TextBlock({ label, text }: { label: string; text: string | null | undefined }) {
  return (
    <div className="col" style={{ gap: 2 }}>
      <span className="small muted">{label}</span>
      {text ? <p className="qa-text-block">{text}</p> : <span className="faint">—</span>}
    </div>
  );
}

// ---------------------------------------------------------------- history
function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? t("qa.shell.str.yes") : t("qa.shell.str.no");
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  return JSON.stringify(v);
}

const ACTION_WORDS: Record<string, StringKey> = {
  create: "qa.history.action.create",
  update: "qa.history.action.update",
  delete: "qa.history.action.delete",
  "esig.signed": "qa.history.action.signed",
  "esig.superseded": "qa.history.action.superseded",
  "esig.lockout": "qa.history.action.lockout",
};
const actionWords = (a: string) => (ACTION_WORDS[a] ? t(ACTION_WORDS[a]) : a.replace(/[._]/g, " "));

export function HistoryTab({ entityType, entityId }: { entityType: string; entityId: string }) {
  const canView = useCan("audit_view");
  const data = usePaged<RecordAuditEvent>(canView ? (offset, limit, signal) => getRecordAudit({ entity_type: entityType, entity_id: entityId, limit, offset }, signal) : null, [entityType, entityId, canView], 50);
  if (!canView)
    return (
      <Banner tone="info" icon="lock" title={t("qa.history.title.noAccess")}>
        {t("qa.history.text.noAccess")}
      </Banner>
    );
  return (
    <Section title={t("qa.history.head.title")} testId="qa-history" actions={<span className="small muted">{t("qa.history.text.oldestFirst")}</span>}>
      <MfgError error={data.error} onRetry={data.reload} />
      {data.loading && !data.rows.length ? (
        <div className="skel-rows" aria-busy="true">
          <div className="skel skel-row" />
          <div className="skel skel-row" />
        </div>
      ) : null}
      {!data.loading && !data.rows.length && !data.error ? <p className="muted" style={{ margin: 0 }}>{t("qa.history.empty")}</p> : null}
      <ol className="qa-history">
        {data.rows.map((e) => (
          <li key={e.id} data-testid="qa-history-event">
            <div className="qa-history-when">
              <strong>{formatDateTime(e.at)}</strong>
              {e.actor_name ?? e.actor_id ?? t("qa.history.str.system")}
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="row wrap" style={{ gap: 6 }}>
                <strong>{actionWords(e.action)}</strong>
                {e.record_version !== null ? <span className="small muted">{t("qa.esig.tpl.version", { v: e.record_version })}</span> : null}
                {e.signature ? (
                  <span className="badge accent" data-testid="esig-manifest">
                    <Icon name="lock" /> {manifestText(e.signature)}
                  </span>
                ) : null}
              </div>
              {e.reason ? (
                <p className="qa-reason">
                  <b>{t("qa.history.label.reason")}</b> {e.reason}
                </p>
              ) : null}
              {e.changes && e.changes.length ? (
                <table className="qa-changes">
                  <colgroup>
                    <col style={{ width: "34%" }} />
                    <col style={{ width: "33%" }} />
                    <col style={{ width: "33%" }} />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">{t("qa.history.head.field")}</th>
                      <th scope="col">{t("qa.history.head.old")}</th>
                      <th scope="col">{t("qa.history.head.new")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {e.changes.map((c, i) => (
                      <tr key={i}>
                        <td className="mono">{c.path}</td>
                        <td className="qa-old">{c.old_sha256 ? t("qa.history.tpl.truncated", { hash: c.old_sha256.slice(0, 12) }) : show(c.old)}</td>
                        <td className="qa-new">{c.new_sha256 ? t("qa.history.tpl.truncated", { hash: c.new_sha256.slice(0, 12) }) : show(c.new)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
      {data.total > data.rows.length ? <ShowMore shown={data.rows.length} total={data.total} noun={t("qa.history.str.events")} loading={data.loading} onMore={data.onEndReached} /> : null}
    </Section>
  );
}

// ---------------------------------------------------------------- signatures
function VerifyChips({ v }: { v: VerifyResult }) {
  const items: [boolean, StringKey, StringKey][] = [
    [v.mac_ok, "qa.sig.verify.macOk", "qa.sig.verify.macBad"],
    [v.chain_ok, "qa.sig.verify.chainOk", "qa.sig.verify.chainBad"],
    [v.content_hash_ok, "qa.sig.verify.hashOk", "qa.sig.verify.hashBad"],
    [v.content_matches_current, "qa.sig.verify.currentOk", "qa.sig.verify.currentBad"],
  ];
  return (
    <div className="qa-verify" data-testid="esig-verify">
      {items.map(([ok, a, b]) => (
        <span key={a} className={`badge ${ok ? "ok" : a === "qa.sig.verify.currentOk" ? "warn" : "danger"}`}>
          <Icon name={ok ? "check" : "alert"} /> {t(ok ? a : b)}
        </span>
      ))}
      <span className="small muted">{t("qa.sig.verify.versions", { signed: v.record_version_signed, current: v.record_version_current ?? "—" })}</span>
    </div>
  );
}

export function SignatureList({ signatures, compact }: { signatures: SignatureManifest[]; compact?: boolean }) {
  const canVerify = useCan("audit_view");
  const [results, setResults] = useState<Record<string, VerifyResult | "error" | "busy">>({});
  if (!signatures.length) return <p className="muted" style={{ margin: 0 }}>{t("qa.sig.empty")}</p>;
  return (
    <div>
      {signatures.map((s) => {
        const r = results[s.id];
        return (
          <div key={s.id} className="qa-manifest" data-testid="esig-manifest" data-status={s.status}>
            <Icon name={s.status === "valid" ? "lock" : "ban"} />
            <div className="qa-manifest-body">
              <div>
                <strong>{manifestText(s)}</strong>
              </div>
              <div className="qa-manifest-meta">
                {t("qa.sig.tpl.meta", { step: s.step, method: authText(s.auth_method) })}
                {s.status === "superseded" ? <span className="badge info" style={{ marginLeft: 6 }}>{t("qa.sig.str.superseded")}</span> : null}
                {!s.content_matches_current ? (
                  <span className="badge warn" style={{ marginLeft: 6 }} data-testid="esig-changed-since">
                    <Icon name="alert" /> {t("qa.sig.str.changedSince")}
                  </span>
                ) : null}
              </div>
              {r && r !== "busy" && r !== "error" ? <VerifyChips v={r} /> : null}
              {r === "error" ? <span className="field-error">{t("qa.sig.verify.failed")}</span> : null}
            </div>
            {canVerify && !compact ? (
              <button
                type="button"
                className="btn sm"
                disabled={r === "busy"}
                onClick={async () => {
                  setResults((x) => ({ ...x, [s.id]: "busy" }));
                  try {
                    const v = await verifySignature(s.id);
                    setResults((x) => ({ ...x, [s.id]: v }));
                  } catch {
                    setResults((x) => ({ ...x, [s.id]: "error" }));
                  }
                }}
                data-testid="esig-verify-btn"
              >
                <Icon name="shield" /> {t("qa.sig.btn.verify")}
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function SignaturesTab({ signatures, recordType, recordId }: { signatures: SignatureManifest[]; recordType: string; recordId: string }) {
  return (
    <Section
      title={t("qa.sig.head.title")}
      testId="qa-signatures"
      actions={
        <Link className="btn sm" to={mfgPaths.printQa(recordType, recordId)} target="_blank" rel="noopener">
          <Icon name="file" /> {t("qa.sig.btn.print")}
        </Link>
      }
    >
      <SignatureList signatures={signatures} />
    </Section>
  );
}

// ---------------------------------------------------------------- links
const LINK_TYPES: LinkType[] = ["ncr", "capa", "complaint", "field_action", "eco", "inspection_lot", "equipment"];
export function linkPath(type: string, id: string): string | null {
  switch (type) {
    case "ncr":
      return mfgPaths.qaNcr(id);
    case "capa":
      return mfgPaths.qaCapa(id);
    case "complaint":
      return mfgPaths.qaComplaint(id);
    case "field_action":
      return mfgPaths.qaFieldAction(id);
    case "eco":
      return mfgPaths.eco(id);
    case "inspection_lot":
      return mfgPaths.qaLot(id);
    case "equipment":
      return mfgPaths.qaEquipment(id);
    default:
      return null;
  }
}

export function LinksTab({ links, fromType, fromId, canEdit, onChanged }: { links: QaLink[]; fromType: string; fromId: string; canEdit: boolean; onChanged(): void }) {
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const other = (l: QaLink) => (l.from_type === fromType && l.from_id === fromId ? { type: l.to_type, id: l.to_id, out: true } : { type: l.from_type, id: l.from_id, out: false });
  const cols: Column<QaLink>[] = [
    {
      key: "rec",
      header: t("qa.links.head.record"),
      width: "minmax(220px, 2fr)",
      exportValue: (l) => `${recordTypeText(other(l).type)} ${l.label ?? other(l).id}`,
      render: (l) => {
        const o = other(l);
        const p = linkPath(o.type, o.id);
        const label = (
          <>
            {recordTypeText(o.type)} <span className="mono">{l.label ?? o.id}</span>
          </>
        );
        return p ? <Link to={p}>{label}</Link> : label;
      },
    },
    { key: "dir", header: t("qa.links.head.direction"), width: "150px", render: (l) => (other(l).out ? t("qa.links.str.linkedFromHere") : t("qa.links.str.linkedToHere")) },
    { key: "when", header: t("qa.links.head.created"), width: "170px", sortValue: (l) => l.created_at, render: (l) => formatDateTime(l.created_at) },
    {
      key: "x",
      header: "",
      label: t("qa.links.head.remove"),
      width: "56px",
      hideable: false,
      render: (l) =>
        canEdit && other(l).out ? (
          <button
            type="button"
            className="btn ghost sm icon"
            aria-label={t("qa.links.aria.remove", { what: l.label ?? other(l).id })}
            onClick={async () => {
              setError(null);
              try {
                await deleteLink(l.id);
                onChanged();
              } catch (e) {
                setError(e);
              }
            }}
          >
            <Icon name="trash" size={14} />
          </button>
        ) : null,
    },
  ];
  return (
    <Section
      title={t("qa.links.head.links")}
      flush
      testId="qa-links"
      actions={
        canEdit ? (
          <button type="button" className="btn sm" onClick={() => setAdding(true)} data-testid="qa-link-add">
            <Icon name="link" /> {t("qa.links.btn.add")}
          </button>
        ) : null
      }
    >
      <MfgError error={error} />
      <DataTable rows={links} columns={cols} rowKey={(l) => l.id} label={t("qa.links.head.links")} tableId="qa-links" empty={t("qa.links.empty")} columnSettings={false} />
      {adding ? <AddLinkDialog fromType={fromType} fromId={fromId} onClose={() => setAdding(false)} onSaved={() => (setAdding(false), onChanged())} /> : null}
    </Section>
  );
}

function AddLinkDialog({ fromType, fromId, onClose, onSaved }: { fromType: string; fromId: string; onClose(): void; onSaved(): void }) {
  const [type, setType] = useState<LinkType>("capa");
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Dialog
      title={t("qa.links.title.add")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !id.trim()}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await createLink({ from_type: fromType, from_id: fromId, to_type: type, to_id: id.trim() });
                toast(t("qa.links.toast.added"));
                onSaved();
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
          >
            {t("qa.links.btn.addLink")}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="ql-type">{t("qa.links.label.type")}</label>
          <select id="ql-type" className="select" value={type} onChange={(e) => setType(e.target.value as LinkType)}>
            {LINK_TYPES.filter((x) => x !== fromType).map((x) => (
              <option key={x} value={x}>
                {recordTypeText(x)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="ql-id">{t("qa.links.label.number")}</label>
          <input id="ql-id" className="input" value={id} onChange={(e) => setId(e.target.value)} placeholder={t("qa.links.ph.number")} />
          <span className="hint">{t("qa.links.hint.number")}</span>
        </div>
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- attachments
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.csv,.xlsx,.txt";
const MAX_BYTES = 10 * 1024 * 1024;

export function AttachmentsTab({ attachments, entityType, entityId, canEdit, locked, onChanged }: { attachments: AttachmentRef[]; entityType: string; entityId: string; canEdit: boolean; locked: boolean; onChanged(): void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [local, setLocal] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const editable = canEdit && !locked;
  const cols: Column<AttachmentRef>[] = [
    {
      key: "name",
      header: t("qa.att.head.file"),
      width: "minmax(220px, 2fr)",
      exportValue: (a) => a.filename,
      render: (a) => (
        <button type="button" className="btn ghost sm" style={{ padding: 0, height: "auto" }} onClick={async () => saveBlob(await downloadAttachment(a.id, a.filename))}>
          <Icon name="download" size={14} /> <span className="mfg-ellipsis">{a.filename}</span>
        </button>
      ),
    },
    { key: "size", header: t("qa.att.head.size"), width: "90px", align: "right", sortValue: (a) => a.size, render: (a) => fmtBytes(a.size) },
    { key: "sha", header: t("qa.att.head.sha"), width: "minmax(140px, 1fr)", exportValue: (a) => a.sha256, render: (a) => <span className="mono small faint" title={a.sha256}>{a.sha256.slice(0, 16)}…</span> },
    { key: "by", header: t("qa.att.head.uploaded"), width: "minmax(170px, 1fr)", render: (a) => `${a.uploaded_by ?? ""} · ${formatDateTime(a.uploaded_at)}` },
    {
      key: "x",
      header: "",
      label: t("qa.att.head.remove"),
      width: "56px",
      hideable: false,
      render: (a) =>
        editable ? (
          <button
            type="button"
            className="btn ghost sm icon"
            aria-label={t("qa.att.aria.remove", { name: a.filename })}
            onClick={async () => {
              setError(null);
              try {
                await deleteAttachment(a.id);
                onChanged();
              } catch (e) {
                setError(e);
              }
            }}
          >
            <Icon name="trash" size={14} />
          </button>
        ) : null,
    },
  ];
  return (
    <Section
      title={t("qa.att.head.title")}
      flush
      testId="qa-attachments"
      actions={
        editable ? (
          <>
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              hidden
              onChange={async (e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                setLocal(null);
                setError(null);
                if (f.size > MAX_BYTES) return setLocal(t("qa.att.err.tooLarge", { name: f.name }));
                if (attachments.length >= 50) return setLocal(t("qa.att.err.tooMany"));
                setBusy(true);
                try {
                  await uploadAttachment(entityType, entityId, f);
                  toast(t("qa.att.toast.uploaded", { name: f.name }));
                  onChanged();
                } catch (err) {
                  setError(err);
                } finally {
                  setBusy(false);
                }
              }}
            />
            <button type="button" className="btn sm" onClick={() => input.current?.click()} disabled={busy} data-testid="qa-attach">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="upload" />} {t("qa.att.btn.upload")}
            </button>
          </>
        ) : null
      }
    >
      {locked ? <p className="small muted" style={{ margin: "8px 16px" }}>{t("qa.att.text.locked")}</p> : null}
      {local ? <p className="field-error" style={{ margin: "8px 16px" }} role="alert">{local}</p> : null}
      <MfgError error={error} />
      <DataTable rows={attachments} columns={cols} rowKey={(a) => a.id} label={t("qa.att.head.title")} tableId="qa-attachments" empty={t("qa.att.empty")} columnSettings={false} />
      {editable ? <p className="small muted" style={{ margin: "8px 16px" }}>{t("qa.att.hint")}</p> : null}
    </Section>
  );
}

// ---------------------------------------------------------------- change reason (4.4)
const REASONS_PREF = "qa.reasons";
const REASONS_LOCAL = "sp.qa.reasons";
function recentReasons(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(REASONS_LOCAL) ?? "[]") as unknown;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, 6) : [];
  } catch {
    return [];
  }
}

/**
 * Part 11 plants: every save of a regulated record asks for a reason (sent as `X-SP-Change-Reason`). Outside Part
 * 11 mode `ask()` resolves at once with "" (no header). Recent reasons are offered (server preference `qa.reasons`).
 */
export function useChangeReason(): { ask(what: string): Promise<string | null>; dialog: ReactNode; required: boolean } {
  const { enabled } = usePart11();
  const [pending, setPending] = useState<{ what: string; resolve(v: string | null): void } | null>(null);
  useEffect(() => syncPref<string[]>(REASONS_PREF, REASONS_LOCAL, () => undefined), []);
  const ask = (what: string) => (enabled ? new Promise<string | null>((resolve) => setPending({ what, resolve })) : Promise.resolve(""));
  const dialog = pending ? (
    <ChangeReasonDialog
      what={pending.what}
      onDone={(v) => {
        if (v) savePref(REASONS_PREF, REASONS_LOCAL, [v, ...recentReasons().filter((x) => x !== v)].slice(0, 6));
        pending.resolve(v);
        setPending(null);
      }}
    />
  ) : null;
  return { ask, dialog, required: enabled };
}

function ChangeReasonDialog({ what, onDone }: { what: string; onDone(v: string | null): void }) {
  const [text, setText] = useState("");
  const recent = recentReasons();
  return (
    <Dialog
      title={t("qa.reason.title")}
      onClose={() => onDone(null)}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onDone(null)} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!text.trim()} onClick={() => onDone(text.trim())} data-testid="change-reason-save">
            {t("qa.reason.btn.save")}
          </button>
        </>
      }
    >
      <form
        className="col"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onDone(text.trim());
        }}
      >
        <p style={{ margin: 0 }}>{t("qa.reason.tpl.body", { what })}</p>
        <div className="field">
          <label htmlFor="qa-reason">{t("qa.reason.label")}</label>
          <textarea id="qa-reason" className="textarea" rows={3} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} data-testid="change-reason" data-autofocus />
          <span className="hint">{t("qa.esig.tpl.chars", { n: text.length })}</span>
        </div>
        {recent.length ? (
          <div className="col" style={{ gap: 4 }}>
            <span className="small muted">{t("qa.reason.recent")}</span>
            <div className="chips">
              {recent.map((r) => (
                <button key={r} type="button" className="chip" style={{ cursor: "pointer", border: 0 }} onClick={() => setText(r)}>
                  {r}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- misc
export function NextStepBanner({ text, icon = "flag" }: { text: string; icon?: IconName }) {
  return (
    <Banner tone="accent" icon={icon} testId="qa-next-step">
      {text}
    </Banner>
  );
}

export const countText = (n: number, one: StringKey, other: StringKey) => plural(n, t(one), t(other));
export { meaningText };

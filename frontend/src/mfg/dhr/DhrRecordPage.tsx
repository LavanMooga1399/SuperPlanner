/**
 * `/mfg/dhr/:dhrId` (M10 4, 11): one device history record version. Left: section navigation (exceptions first, the
 * twelve record sections with a badge of open exceptions each, versions, signatures, history). Review by exception:
 * each major / minor exception gets a disposition (accepted with a comment, an NCR or a deviation of the same lot / WO);
 * info exceptions are shown only. The release bar lists what still blocks release and starts the two-step signed
 * release (reviewed by QA, released by the final-release role; distinct people, authenticator code) or a rejection that
 * needs an NCR. Records are never edited: a late source change re-assembles into a new version.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { ApiError } from "../../api/client";
import { assembleDhr, dispositionException, exportDhr, getDhr, getDhrSection, releaseDhr, startDhrReview } from "../api/clientM10";
import { DHR_SECTIONS, type DhrBlocking, type DhrDisposition, type DhrException, type DhrRecord, type DhrSection, type DhrSectionKey, type DhrSectionTable, type ExcSeverity } from "../api/typesM10";
import { DataTable, ShowMore } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { errorCode, useLoad } from "../lib/useMfg";
import { ItemCell, usePersonName } from "../qa/common";
import { HistoryTab, linkPath, RecordHeader, SignatureList, useChangeReason } from "../qa/RecordShell";
import { DeviationSelect, NcrSelect } from "./pickers";
import { codeText10, colText, DhrStatusChip, DISPOSITION, dispositionText, excText, GxpChip, HashText, KV, OpenCounts, sectionText, SevChip, useDownload, valueText } from "./shared";

type View = "exceptions" | DhrSectionKey | "versions" | "signatures" | "history";
const SEV_ORDER: Record<ExcSeverity, number> = { major: 0, minor: 1, info: 2 };
const needsDisposition = (x: DhrException) => x.severity !== "info";
const isOpen = (x: DhrException) => needsDisposition(x) && !x.disposition;

export function DhrRecordPage() {
  const { dhrId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const rec = useLoad((s) => getDhr(dhrId, s), [dhrId]);
  const r = rec.data;
  const view = (params.get("section") as View | null) ?? "exceptions";
  const setView = (v: View) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (v === "exceptions") n.delete("section");
        else n.set("section", v);
        return n;
      },
      { replace: false },
    );
  const canReview = useCan("dhr_review");
  const navigate = useNavigate();
  const dl = useDownload();
  const [err, setErr] = useState<unknown>(null);
  const [reassemble, setReassemble] = useState(false);
  const [notice, setNotice] = useState<ReactNode>(null);
  useEffect(() => {
    if (r) document.title = `${r.number} v${r.version} - ${t("gxp.dhr.title")}`;
  }, [r]);
  if (rec.error && !r) return <MfgError error={rec.error} onRetry={rec.reload} />;
  if (!r) return <Spinner />;
  const closed = r.status === "released" || r.status === "rejected";
  const superseded = Boolean(r.superseded_by_id);
  const editable = canReview && !closed && !superseded;
  const latest = [...r.versions].sort((a, b) => b.version - a.version)[0];
  const exBySection = new Map<string, DhrException[]>();
  for (const x of r.exceptions) exBySection.set(x.section, [...(exBySection.get(x.section) ?? []), x]);
  const open = r.exceptions.filter(isOpen);
  const onUpdated = (x: DhrRecord) => rec.setData(x);
  return (
    <div className="col gap-lg" data-testid="dhr-record-page" data-status={r.status}>
      <RecordHeader
        testId="dhr-header"
        crumbs={[[t("gxp.dhr.title"), mfgPaths.dhr()]]}
        number={`${r.number}`}
        title={r.item ? `${r.item.part_number} ${r.item.name}` : null}
        status={<DhrStatusChip s={r.status} />}
        chips={
          <>
            <span className="badge info" data-testid="dhr-version">
              <Icon name="layers" /> {t("gxp.tpl.versionLong", { n: r.version })}
            </span>
            {r.changed_after_release ? (
              <span className="badge warn" data-testid="dhr-changed">
                <Icon name="refresh" /> {t("gxp.dhr.changedAfterRelease")}
              </span>
            ) : null}
            {r.hold_status === "held" ? (
              <span className="badge warn">
                <Icon name="lock" /> {t("gxp.dhr.held")}
              </span>
            ) : r.hold_status === "released" ? (
              <span className="badge ok">
                <Icon name="unlock" /> {t("gxp.dhr.holdReleased")}
              </span>
            ) : null}
          </>
        }
        facts={[
          [t("gxp.head.item"), <ItemCell key="i" item={r.item} id={r.item_id} />],
          [t("gxp.head.lot"), r.lot_code ? <span className="mono">{r.lot_code}</span> : null],
          [t("gxp.head.wos"), r.wos.length ? <span className="mono">{r.wos.map((w) => w.number).join(", ")}</span> : null],
          [t("gxp.dhr.head.assembled"), r.assembled_at ? formatDateTime(r.assembled_at) : null],
          [t("gxp.dhr.fact.open"), <OpenCounts key="o" major={r.counts.open_major} minor={r.counts.open_minor} />],
          [t("gxp.dhr.fact.hash"), <HashText key="h" h={r.content_sha256} />],
        ]}
        actions={
          <>
            {r.versions.length > 1 ? (
              <div className="field" style={{ minWidth: 150 }}>
                <label htmlFor="dhr-ver" className="sr-only">
                  {t("gxp.dhr.label.version")}
                </label>
                <select id="dhr-ver" className="select" value={r.id} onChange={(e) => navigate(mfgPaths.dhrRecord(e.target.value))} data-testid="dhr-version-switch">
                  {[...r.versions]
                    .sort((a, b) => b.version - a.version)
                    .map((v) => (
                      <option key={v.id} value={v.id}>
                        {t("gxp.tpl.versionLong", { n: v.version })}
                        {v.id === latest?.id ? ` (${t("gxp.dhr.latest")})` : ""}
                      </option>
                    ))}
                </select>
              </div>
            ) : null}
            <button type="button" className="btn" disabled={dl.busy !== null} onClick={() => void dl.run("pdf", () => exportDhr(r, "pdf"))} data-testid="dhr-export-pdf">
              {dl.busy === "pdf" ? <span className="spinner" aria-hidden /> : <Icon name="download" />} {t("gxp.btn.pdf")}
            </button>
            <button type="button" className="btn" disabled={dl.busy !== null} onClick={() => void dl.run("json", () => exportDhr(r, "json"))} data-testid="dhr-export-json">
              {dl.busy === "json" ? <span className="spinner" aria-hidden /> : <Icon name="download" />} {t("gxp.btn.json")}
            </button>
            {canReview && !superseded ? (
              <button type="button" className="btn" onClick={() => setReassemble(true)} data-testid="dhr-reassemble">
                <Icon name="refresh" /> {t("gxp.dhr.btn.reassemble")}
              </button>
            ) : null}
            {r.status === "assembled" && editable ? (
              <button
                type="button"
                className="btn"
                onClick={() =>
                  startDhrReview(r).then(
                    (x) => (onUpdated(x), toast(t("gxp.dhr.toast.reviewStarted"))),
                    (e: unknown) => setErr(e),
                  )
                }
                data-testid="dhr-start-review"
              >
                <Icon name="eye" /> {t("gxp.dhr.btn.startReview")}
              </button>
            ) : null}
          </>
        }
      />
      <MfgError error={err ?? dl.error} />
      {notice}
      {superseded ? (
        <Banner tone="warn" title={t("gxp.dhr.superseded")} testId="dhr-superseded">
          {t("gxp.dhr.supersededBody")}{" "}
          {latest ? <Link to={mfgPaths.dhrRecord(latest.id)}>{t("gxp.tpl.openVersion", { n: latest.version })}</Link> : null}
        </Banner>
      ) : null}
      {r.changed_after_release && !superseded ? (
        <Banner tone="warn" title={t("gxp.dhr.changedAfterRelease")}>
          {t("gxp.dhr.changedAfterReleaseHelp")}
        </Banner>
      ) : null}
      {r.reassemble_reason ? (
        <Banner tone="info" title={t("gxp.dhr.reassembledBecause")}>
          {r.reassemble_reason}
        </Banner>
      ) : null}
      {!r.dhr_required ? <Banner tone="info">{t("gxp.dhr.notRequired")}</Banner> : null}
      <div className="dhr-layout">
        <nav className="card dhr-nav" aria-label={t("gxp.dhr.aria.sections")} data-testid="dhr-nav">
          <span className="dhr-nav-group">{t("gxp.dhr.nav.review")}</span>
          <NavBtn cur={view} v="exceptions" onPick={setView} label={t("gxp.dhr.nav.exceptions")} badge={open.length ? { tone: "danger", text: String(open.length) } : { tone: "ok", text: "0" }} />
          <span className="dhr-nav-group">{t("gxp.dhr.nav.sections")}</span>
          {DHR_SECTIONS.filter((s) => s === "review" || r.content[s] !== undefined || exBySection.has(s)).map((s) => {
            const xs = exBySection.get(s) ?? [];
            const o = xs.filter(isOpen);
            const worst = o.some((x) => x.severity === "major") ? "danger" : o.length ? "warn" : null;
            return <NavBtn key={s} cur={view} v={s} onPick={setView} label={sectionText(s)} badge={worst ? { tone: worst, text: String(o.length) } : xs.length ? { tone: "ok", icon: true } : null} />;
          })}
          <span className="dhr-nav-group">{t("gxp.dhr.nav.record")}</span>
          <NavBtn cur={view} v="versions" onPick={setView} label={t("gxp.dhr.nav.versions")} badge={{ tone: "", text: String(r.versions.length) }} />
          <NavBtn cur={view} v="signatures" onPick={setView} label={t("gxp.dhr.nav.signatures")} badge={r.signatures.length ? { tone: "", text: String(r.signatures.length) } : null} />
          <NavBtn cur={view} v="history" onPick={setView} label={t("gxp.dhr.nav.history")} badge={null} />
        </nav>
        <div className="dhr-main" id="dhr-main">
          {view === "exceptions" ? (
            <ExceptionsView record={r} editable={editable} onUpdated={onUpdated} onSection={setView} />
          ) : view === "versions" ? (
            <VersionsView record={r} />
          ) : view === "signatures" ? (
            <section className="card">
              <div className="card-header">
                <h2>{t("gxp.dhr.nav.signatures")}</h2>
              </div>
              <div className="card-body">
                <SignatureList signatures={r.signatures} />
              </div>
            </section>
          ) : view === "history" ? (
            <HistoryTab entityType="dhr_record" entityId={r.id} />
          ) : (
            <SectionView record={r} section={view} exceptions={exBySection.get(view) ?? []} editable={editable} onUpdated={onUpdated} />
          )}
          {!superseded ? <ReleaseBar record={r} onDone={rec.reload} onNotice={setNotice} onOpenExceptions={() => setView("exceptions")} /> : null}
        </div>
      </div>
      {reassemble ? (
        <ReassembleDialog
          record={r}
          onClose={() => setReassemble(false)}
          onDone={(x) => {
            setReassemble(false);
            toast(t("gxp.dhr.toast.reassembled", { n: x.version }));
            if (x.id !== r.id) navigate(mfgPaths.dhrRecord(x.id));
            else rec.setData(x);
          }}
        />
      ) : null}
    </div>
  );
}

function NavBtn({ cur, v, onPick, label, badge }: { cur: View; v: View; onPick(v: View): void; label: string; badge: { tone: string; text?: string; icon?: boolean } | null }) {
  return (
    <button type="button" aria-current={cur === v ? "true" : undefined} onClick={() => onPick(v)} data-testid={`dhr-nav-${v}`}>
      <span className="dhr-nav-label">{label}</span>
      {badge ? (
        <span className={`dhr-nav-badge ${badge.tone}`}>
          {badge.icon ? <Icon name="check" size={12} /> : badge.tone === "danger" ? <Icon name="alert" size={12} /> : badge.tone === "warn" ? <Icon name="flag" size={12} /> : null}
          {badge.text ?? ""}
          {badge.icon ? <span className="sr-only">{t("gxp.str.allDispositioned")}</span> : badge.tone === "danger" || badge.tone === "warn" ? <span className="sr-only">{t("gxp.str.open")}</span> : null}
        </span>
      ) : null}
    </button>
  );
}

// ---------------------------------------------------------------- exceptions (review by exception)
function ExceptionsView({ record, editable, onUpdated, onSection }: { record: DhrRecord; editable: boolean; onUpdated(r: DhrRecord): void; onSection(s: View): void }) {
  const [filter, setFilter] = useState<"open" | "all" | ExcSeverity>(record.exceptions.some(isOpen) ? "open" : "all");
  const list = useMemo(
    () =>
      [...record.exceptions]
        .filter((x) => (filter === "all" ? true : filter === "open" ? isOpen(x) : x.severity === filter))
        .sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || Number(isOpen(b)) - Number(isOpen(a)) || a.code.localeCompare(b.code)),
    [record.exceptions, filter],
  );
  const c = record.counts;
  return (
    <section className="card" aria-labelledby="dhr-exc-h" data-testid="dhr-exceptions">
      <div className="card-header">
        <h2 id="dhr-exc-h">{t("gxp.dhr.nav.exceptions")}</h2>
        <div className="btn-group" role="group" aria-label={t("gxp.dhr.aria.excFilter")}>
          {(
            [
              ["open", t("gxp.tpl.filterOpen", { n: c.open })],
              ["all", t("gxp.tpl.filterAll", { n: record.exceptions.length })],
              ["major", t("gxp.tpl.filterMajor", { n: c.major })],
              ["minor", t("gxp.tpl.filterMinor", { n: c.minor })],
              ["info", t("gxp.tpl.filterInfo", { n: c.info })],
            ] as const
          ).map(([k, label]) => (
            <button key={k} type="button" className="btn sm" aria-pressed={filter === k} onClick={() => setFilter(k)} data-testid={`dhr-exc-filter-${k}`}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="card-body col" style={{ gap: 10 }}>
        <p className="muted small" style={{ margin: 0 }}>
          {t("gxp.dhr.excHelp")}
        </p>
        {list.length ? (
          list.map((x) => <ExceptionCard key={x.id} x={x} record={record} editable={editable} onUpdated={onUpdated} onSection={onSection} />)
        ) : (
          <p className="muted" style={{ margin: 0 }} data-testid="dhr-exc-empty">
            {filter === "open" ? t("gxp.dhr.excNoneOpen") : t("gxp.dhr.excNone")}
          </p>
        )}
      </div>
    </section>
  );
}

function RefLink({ type, id, number }: { type: string; id: string | null; number: string | null }) {
  if (!number && !id) return null;
  const to = id ? (type === "deviation" ? mfgPaths.deviation(id) : type === "print_job" || type === "label_job" ? mfgPaths.labelJob(id) : linkPath(type, id)) : null;
  return to ? (
    <Link to={to} className="mono">
      {number ?? id}
    </Link>
  ) : (
    <span className="mono">{number ?? id}</span>
  );
}

function ExceptionCard({ x, record, editable, onUpdated, onSection }: { x: DhrException; record: DhrRecord; editable: boolean; onUpdated(r: DhrRecord): void; onSection(s: View): void }) {
  const person = usePersonName();
  const [editing, setEditing] = useState(false);
  const data = Object.entries(x.data ?? {}).filter(([, v]) => v !== null && v !== undefined && typeof v !== "object");
  return (
    <article className="dhr-exc" data-severity={x.severity} data-code={x.code} data-open={isOpen(x)} data-testid="dhr-exc" aria-labelledby={`exc-${x.id}`}>
      <div className="dhr-exc-head">
        <SevChip s={x.severity} />
        <h3 id={`exc-${x.id}`}>{excText(x.code)}</h3>
        <button type="button" className="btn link sm" onClick={() => onSection(x.section)}>
          {sectionText(x.section)}
        </button>
        {x.ref_number || x.ref_id ? (
          <span className="small">
            <RefLink type={x.ref_type} id={x.ref_id} number={x.ref_number} />
          </span>
        ) : null}
        {x.carried ? (
          <span className="badge info" title={t("gxp.dhr.carriedHelp")}>
            <Icon name="copy" /> {t("gxp.dhr.carried")}
          </span>
        ) : null}
        <span style={{ flex: 1 }} />
        {x.disposition ? <GxpChip def={DISPOSITION[x.disposition]} value={x.disposition} testId="dhr-exc-disp" /> : needsDisposition(x) ? (
          <span className="badge warn" data-testid="dhr-exc-disp">
            <Icon name="circle" /> {t("gxp.dhr.needsDisposition")}
          </span>
        ) : (
          <span className="badge info">
            <Icon name="info" /> {t("gxp.dhr.infoOnly")}
          </span>
        )}
      </div>
      <p style={{ margin: 0 }}>{x.message}</p>
      {data.length ? <KV rows={data.map(([k, v]) => [colText(k), valueText(v)])} /> : null}
      {x.disposition && !editing ? (
        <div className="small col" style={{ gap: 2 }}>
          <span>
            <strong>{dispositionText(x.disposition)}</strong>
            {x.disposition_ref ? (
              <>
                {" · "}
                <RefLink type={x.disposition} id={x.disposition_ref} number={x.disposition_ref_number} />
              </>
            ) : null}
            {x.reviewed_by ? <span className="muted"> · {t("gxp.tpl.byAt", { who: person(x.reviewed_by), at: formatDateTime(x.reviewed_at) })}</span> : null}
          </span>
          {x.comment ? <span className="qa-text-block">{x.comment}</span> : null}
          {editable ? (
            <span>
              <button type="button" className="btn sm" onClick={() => setEditing(true)} data-testid="dhr-exc-change">
                <Icon name="refresh" /> {t("gxp.dhr.btn.changeDisposition")}
              </button>
            </span>
          ) : null}
        </div>
      ) : null}
      {needsDisposition(x) && editable && (!x.disposition || editing) ? <DispositionForm x={x} record={record} onCancel={x.disposition ? () => setEditing(false) : undefined} onSaved={(r) => (setEditing(false), onUpdated(r))} /> : null}
    </article>
  );
}

const MIN_COMMENT: Record<string, number> = { DHR_TIME_WINDOW: 20 };

function DispositionForm({ x, record, onSaved, onCancel }: { x: DhrException; record: DhrRecord; onSaved(r: DhrRecord): void; onCancel?(): void }) {
  const reason = useChangeReason();
  const [disp, setDisp] = useState<DhrDisposition | "">(x.disposition ?? (x.allowed.length === 1 ? x.allowed[0] : ""));
  const [ref, setRef] = useState(x.disposition_ref ?? "");
  const [comment, setComment] = useState(x.comment ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const min = disp === "accepted" ? (MIN_COMMENT[x.code] ?? 1) : 0;
  const ok = Boolean(disp) && (disp === "accepted" ? comment.trim().length >= min : Boolean(ref));
  const save = async () => {
    if (!disp) return;
    const why = await reason.ask(t("gxp.tpl.dispositionOf", { code: excText(x.code) }));
    if (why === null) return;
    setBusy(true);
    setErr(null);
    try {
      onSaved(await dispositionException(record.id, x, { disposition: disp, disposition_ref: disp === "accepted" ? null : ref, comment: comment.trim() }, why || comment.trim() || null));
      toast(t("gxp.dhr.toast.dispositioned"));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const fid = `disp-${x.id}`;
  return (
    <form
      className="dhr-exc-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok && !busy) void save();
      }}
      data-testid="dhr-disp-form"
    >
      {err ? (
        <div className="full">
          {errorCode(err) === "DHR_REF_SCOPE" ? <Banner tone="danger" role="alert">{t("gxp.code.DHR_REF_SCOPE")}</Banner> : errorCode(err) === "DHR_DISPOSITION" ? <Banner tone="danger" role="alert">{t("gxp.code.DHR_DISPOSITION")}</Banner> : <MfgError error={err} />}
        </div>
      ) : null}
      <div className="field">
        <label htmlFor={`${fid}-d`}>{t("gxp.dhr.label.disposition")}</label>
        <select id={`${fid}-d`} className="select" value={disp} onChange={(e) => (setDisp(e.target.value as DhrDisposition), setRef(""))} data-testid="dhr-disp-select">
          <option value="">{t("gxp.pick.choose")}</option>
          {x.allowed.map((d) => (
            <option key={d} value={d}>
              {dispositionText(d)}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        {disp === "ncr" ? (
          <>
            <label htmlFor={`${fid}-r`}>{t("gxp.dhr.label.ncr")}</label>
            <NcrSelect id={`${fid}-r`} itemId={record.item_id} lotId={record.lot_id} woIds={record.wo_ids} value={ref} onChange={setRef} testId="dhr-disp-ncr" />
            <span className="hint">
              {t("gxp.dhr.hint.ncr")} <Link to={mfgPaths.qaNcr("new")}>{t("gxp.dhr.link.newNcr")}</Link>
            </span>
          </>
        ) : disp === "deviation" ? (
          <>
            <label htmlFor={`${fid}-r`}>{t("gxp.dhr.label.deviation")}</label>
            <DeviationSelect id={`${fid}-r`} lotId={record.lot_id} itemId={record.item_id} value={ref} onChange={setRef} testId="dhr-disp-dev" />
            <span className="hint">
              {t("gxp.dhr.hint.deviation")}{" "}
              <Link to={mfgPaths.deviation("new", { exception: x.id, dhr: record.id, ...(record.lot_id ? { lot: record.lot_id } : {}), item: record.item_id })}>{t("gxp.dhr.link.newDeviation")}</Link>
            </span>
          </>
        ) : (
          <span className="hint" style={{ marginTop: 22 }}>
            {disp === "accepted" ? t("gxp.dhr.hint.accepted") : t("gxp.dhr.hint.choose")}
          </span>
        )}
      </div>
      <div className="field full">
        <label htmlFor={`${fid}-c`}>
          {t("gxp.dhr.label.comment")}
          {disp === "accepted" ? <span className="req" aria-hidden /> : null}
        </label>
        <textarea id={`${fid}-c`} className="textarea" rows={2} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} data-testid="dhr-disp-comment" />
        {min > 1 ? <span className="hint">{t("gxp.tpl.minChars", { n: min, have: comment.trim().length })}</span> : null}
      </div>
      <div className="full row" style={{ gap: 8, justifyContent: "flex-end" }}>
        {onCancel ? (
          <button type="button" className="btn" onClick={onCancel}>
            {t("common.cancel")}
          </button>
        ) : null}
        <button type="submit" className="btn primary" disabled={!ok || busy} data-testid="dhr-disp-save">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} {t("gxp.dhr.btn.saveDisposition")}
        </button>
      </div>
      {reason.dialog}
    </form>
  );
}

// ---------------------------------------------------------------- sections
function SectionView({ record, section, exceptions, editable, onUpdated }: { record: DhrRecord; section: DhrSectionKey; exceptions: DhrException[]; editable: boolean; onUpdated(r: DhrRecord): void }) {
  const body: DhrSection = record.content[section] ?? {};
  const { facts, tables, note, ...rest } = body;
  const scalarRest = Object.entries(rest).filter(([, v]) => v === null || typeof v !== "object" || (Array.isArray(v) && v.every((x) => typeof x !== "object")));
  const factRows: [string, ReactNode][] = [...Object.entries(facts ?? {}), ...scalarRest].map(([k, v]) => [colText(k), valueText(v)]);
  return (
    <section className="card" aria-labelledby="dhr-sec-h" data-testid={`dhr-section-${section}`}>
      <div className="card-header">
        <h2 id="dhr-sec-h">{sectionText(section)}</h2>
        <span className="small muted">
          {t("gxp.dhr.sectionHash")} <HashText h={record.section_hashes[section]} />
        </span>
      </div>
      <div className="card-body col" style={{ gap: 12 }}>
        {exceptions.length ? (
          <div className="col" style={{ gap: 8 }}>
            {exceptions.map((x) => (
              <ExceptionCard key={x.id} x={x} record={record} editable={editable} onUpdated={onUpdated} onSection={() => undefined} />
            ))}
          </div>
        ) : null}
        {section === "review" ? (
          <>
            <KV
              rows={[
                [t("gxp.dhr.fact.exceptions"), plural(record.exceptions.length, t("gxp.noun.exception"), t("gxp.noun.exceptions"))],
                [t("gxp.dhr.fact.open"), <OpenCounts key="o" major={record.counts.open_major} minor={record.counts.open_minor} />],
                [t("gxp.dhr.fact.decision"), record.decision ? <DhrStatusChip s={record.decision} /> : null],
                [t("gxp.dhr.fact.releasedAt"), record.released_at ? formatDateTime(record.released_at) : null],
              ]}
            />
            <SignatureList signatures={record.signatures} />
          </>
        ) : null}
        {factRows.length ? <KV rows={factRows} testId="dhr-section-facts" /> : null}
        {note ? <p className="small muted" style={{ margin: 0 }}>{note}</p> : null}
        {(tables ?? []).map((tb) => (
          <SectionTable key={tb.key} recordId={record.id} section={section} table={tb} />
        ))}
        {!factRows.length && !(tables ?? []).length && section !== "review" && !exceptions.length ? (
          <p className="muted" style={{ margin: 0 }}>
            {t("gxp.dhr.sectionEmpty")}
          </p>
        ) : null}
      </div>
    </section>
  );
}

function SectionTable({ recordId, section, table }: { recordId: string; section: DhrSectionKey; table: DhrSectionTable }) {
  const [rows, setRows] = useState(table.rows);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const total = table.total ?? table.rows.length;
  const columns = useMemo<Column<Record<string, unknown>>[]>(
    () =>
      table.columns.map((c, i) => ({
        key: c.key,
        header: colText(c.key, c.label),
        width: i === 0 ? "minmax(120px, 1fr)" : "minmax(90px, 1fr)",
        wrap: true,
        align: rows.length && typeof rows[0][c.key] === "number" ? ("right" as const) : undefined,
        sortValue: (r: Record<string, unknown>) => {
          const v = r[c.key];
          return typeof v === "number" || typeof v === "string" ? v : null;
        },
        exportValue: (r: Record<string, unknown>) => valueText(r[c.key], c.unit),
        render: (r: Record<string, unknown>) => <span className={typeof r[c.key] === "number" ? "pl-num" : undefined}>{valueText(r[c.key], c.unit)}</span>,
      })),
    [table.columns, rows],
  );
  const more = async () => {
    setBusy(true);
    setErr(null);
    try {
      const p = await getDhrSection(recordId, section, { table: table.key, page: page + 1 });
      setRows((x) => [...x, ...p.items]);
      setPage(p.page);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="col" style={{ gap: 4 }}>
      <h3 className="small" style={{ margin: 0 }}>
        {colText(table.key)}
      </h3>
      <MfgError error={err} />
      <div className="card card-table">
        <DataTable<Record<string, unknown>>
          rows={rows}
          columns={columns}
          rowKey={(r) => String(r.id ?? r.key ?? JSON.stringify(r))}
          label={colText(table.key)}
          testId={`dhr-table-${table.key}`}
          exportName={`dhr-${section}-${table.key}`}
          empty={t("gxp.dhr.tableEmpty")}
          footer={total > rows.length ? <ShowMore shown={rows.length} total={total} noun={t("gxp.noun.rows")} loading={busy} onMore={() => void more()} /> : undefined}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- versions
function VersionsView({ record }: { record: DhrRecord }) {
  const versions = [...record.versions].sort((a, b) => b.version - a.version);
  const other = versions.find((v) => v.id !== record.id) ?? null;
  const [cmpId, setCmpId] = useState(other?.id ?? "");
  const cmp = versions.find((v) => v.id === cmpId) ?? null;
  const cur = versions.find((v) => v.id === record.id) ?? null;
  return (
    <div className="col" style={{ gap: 12 }} data-testid="dhr-versions">
      <section className="card card-table">
        <div className="card-header">
          <h2>{t("gxp.dhr.nav.versions")}</h2>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">{t("gxp.dhr.head.version")}</th>
              <th scope="col">{t("gxp.head.status")}</th>
              <th scope="col">{t("gxp.dhr.head.assembled")}</th>
              <th scope="col">{t("gxp.dhr.fact.hash")}</th>
              <th scope="col">{t("gxp.dhr.head.reason")}</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id} aria-current={v.id === record.id ? "true" : undefined}>
                <td>
                  {v.id === record.id ? <strong>{t("gxp.tpl.versionLong", { n: v.version })}</strong> : <Link to={mfgPaths.dhrRecord(v.id)}>{t("gxp.tpl.versionLong", { n: v.version })}</Link>}
                </td>
                <td>
                  <span className="row" style={{ gap: 4 }}>
                    <DhrStatusChip s={v.status} />
                    {v.changed_after_release ? (
                      <span className="badge warn">
                        <Icon name="refresh" /> {t("gxp.dhr.changed")}
                      </span>
                    ) : null}
                  </span>
                </td>
                <td>{v.assembled_at ? formatDateTime(v.assembled_at) : "–"}</td>
                <td>
                  <HashText h={v.content_sha256} />
                </td>
                <td className="small">{v.reassemble_reason ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {cur && versions.length > 1 ? (
        <section className="card card-table">
          <div className="card-header">
            <h2>{t("gxp.dhr.compareTitle")}</h2>
            <div className="field" style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <label htmlFor="dhr-cmp">{t("gxp.dhr.label.compareWith")}</label>
              <select id="dhr-cmp" className="select" value={cmpId} onChange={(e) => setCmpId(e.target.value)} data-testid="dhr-compare">
                {versions
                  .filter((v) => v.id !== record.id)
                  .map((v) => (
                    <option key={v.id} value={v.id}>
                      {t("gxp.tpl.versionLong", { n: v.version })}
                    </option>
                  ))}
              </select>
            </div>
          </div>
          {cmp ? (
            <table className="table dhr-hash-diff" data-testid="dhr-hash-diff">
              <thead>
                <tr>
                  <th scope="col">{t("gxp.dhr.head.section")}</th>
                  <th scope="col">{t("gxp.tpl.versionLong", { n: cur.version })}</th>
                  <th scope="col">{t("gxp.tpl.versionLong", { n: cmp.version })}</th>
                  <th scope="col">{t("gxp.dhr.head.change")}</th>
                </tr>
              </thead>
              <tbody>
                {DHR_SECTIONS.map((s) => {
                  const a = cur.section_hashes[s] ?? null;
                  const b = cmp.section_hashes[s] ?? null;
                  const changed = a !== b;
                  return (
                    <tr key={s} data-changed={changed}>
                      <th scope="row">{sectionText(s)}</th>
                      <td>
                        <HashText h={a} />
                      </td>
                      <td>
                        <HashText h={b} />
                      </td>
                      <td className={changed ? "changed" : undefined}>
                        {changed ? (
                          <span className="badge warn">
                            <Icon name="refresh" /> {t("gxp.dhr.diff.changed")}
                          </span>
                        ) : (
                          <span className="muted small">
                            <Icon name="check" size={12} /> {t("gxp.dhr.diff.same")}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- release
function ReleaseBar({ record, onDone, onNotice, onOpenExceptions }: { record: DhrRecord; onDone(): void; onNotice(n: ReactNode): void; onOpenExceptions(): void }) {
  const [sign, setSign] = useState<null | "released" | "rejected">(null);
  const [blocking, setBlocking] = useState<DhrBlocking[] | null>(null);
  const [ncr, setNcr] = useState("");
  const [showBlock, setShowBlock] = useState(false);
  const canView = useCan("view");
  const valid = record.signatures.filter((s) => s.status === "valid" && s.action === "release");
  const block = blocking ?? record.releasable.blocking;
  const releasable = blocking ? false : record.releasable.ok;
  if (record.status === "released" || record.status === "rejected")
    return (
      <div className="dhr-release-bar" data-testid="dhr-release-bar" data-state="done">
        <span className="row" style={{ gap: 8 }}>
          <DhrStatusChip s={record.status} />
          <span className="small">{record.released_at ? t("gxp.tpl.decidedAt", { at: formatDateTime(record.released_at) }) : null}</span>
        </span>
        <SignatureList signatures={valid} compact />
      </div>
    );
  const step2 = valid.length > 0;
  return (
    <div className="dhr-release-bar" data-testid="dhr-release-bar" data-releasable={releasable}>
      <div className="col" style={{ gap: 4, minWidth: 0, flex: "1 1 320px" }}>
        {releasable ? (
          <span className="badge ok" data-testid="dhr-releasable">
            <Icon name="check" /> {t("gxp.dhr.releasable")}
          </span>
        ) : (
          <span className="row" style={{ gap: 6 }}>
            <span className="badge danger" data-testid="dhr-blocked">
              <Icon name="lock" /> {plural(block.length, t("gxp.noun.blocker"), t("gxp.noun.blockers"))}
            </span>
            <button type="button" className="btn link sm" aria-expanded={showBlock} onClick={() => setShowBlock((v) => !v)} data-testid="dhr-blocking-toggle">
              {showBlock ? t("gxp.dhr.btn.hideBlocking") : t("gxp.dhr.btn.showBlocking")}
            </button>
          </span>
        )}
        {!releasable && showBlock ? (
          <ul className="dhr-blocking" data-testid="dhr-blocking">
            {block.map((b, i) => (
              <li key={`${b.code}-${i}`}>
                {codeText10(b.code, b.message)}
                {b.ref_number || b.ref_id ? (
                  <>
                    {" · "}
                    <RefLink type={b.ref_type ?? ""} id={b.ref_id ?? null} number={b.ref_number ?? null} />
                  </>
                ) : null}
                {b.code === "DHR_UNDISPOSITIONED" ? (
                  <>
                    {" "}
                    <button type="button" className="btn link sm" onClick={onOpenExceptions}>
                      {t("gxp.dhr.btn.goExceptions")}
                    </button>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        <ol className="qa-steps small" aria-label={t("gxp.dhr.aria.steps")}>
          <li className="qa-step">
            <span className="qa-step-num">1</span> {t("gxp.dhr.step1")} {step2 ? <Icon name="check" size={12} /> : null}
          </li>
          <li className="qa-step">
            <Icon name="chevron-right" size={12} />
            <span className="qa-step-num">2</span> {t("gxp.dhr.step2")}
          </li>
        </ol>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button type="button" className="btn danger" disabled={!canView} onClick={() => setSign("rejected")} data-testid="dhr-reject">
          <Icon name="x" /> {t("gxp.dhr.btn.reject")}
        </button>
        <button type="button" className="btn primary" disabled={!releasable} title={releasable ? undefined : t("gxp.dhr.blockedHelp")} onClick={() => setSign("released")} data-testid="dhr-release">
          <Icon name="lock" /> {step2 ? t("gxp.dhr.btn.signRelease") : t("gxp.dhr.btn.signReview")}
        </button>
      </div>
      {sign ? (
        <SignatureDialog<DhrRecord>
          title={sign === "released" ? t("gxp.tpl.releaseTitle", { n: `${record.number} v${record.version}` }) : t("gxp.tpl.rejectTitle", { n: `${record.number} v${record.version}` })}
          recordType="dhr"
          recordId={record.id}
          recordLabel={`${record.number} v${record.version}`}
          action="release"
          decision={sign}
          danger={sign === "rejected"}
          submitLabel={sign === "rejected" ? t("gxp.dhr.btn.signReject") : step2 ? t("gxp.dhr.btn.signRelease") : t("gxp.dhr.btn.signReview")}
          plainLabel={sign === "rejected" ? t("gxp.dhr.btn.reject") : t("gxp.dhr.btn.release")}
          effect={sign === "rejected" ? t("gxp.dhr.effectReject") : step2 ? t("gxp.dhr.effectRelease") : t("gxp.dhr.effectReview")}
          canSubmit={sign === "released" || Boolean(ncr)}
          extraRows={[
            { label: t("gxp.head.item"), value: record.item ? `${record.item.part_number} ${record.item.name}` : record.item_id },
            { label: t("gxp.head.lot"), value: record.lot_code ?? "–" },
            { label: t("gxp.dhr.fact.exceptions"), value: t("gxp.tpl.excSummary", { major: record.counts.major, minor: record.counts.minor, info: record.counts.info }) },
            { label: t("gxp.dhr.fact.hash"), value: record.content_sha256.slice(0, 16) },
          ]}
          commentLabel={t("gxp.dhr.label.signComment")}
          perform={(sig, comment) =>
            releaseDhr(record, { decision: sign, ncr_id: sign === "rejected" ? ncr : null }, sig, comment).catch((e: unknown) => {
              const code = errorCode(e);
              if (code === "DHR_STALE") {
                setSign(null);
                onNotice(
                  <Banner tone="warn" role="alert" title={t("gxp.code.DHR_STALE")} testId="dhr-stale">
                    {t("gxp.dhr.staleBody")}
                  </Banner>,
                );
                onDone();
              } else if (code === "DHR_NOT_RELEASABLE" && e instanceof ApiError) {
                setSign(null);
                setBlocking(((e.details as { blocking?: DhrBlocking[] }).blocking ?? []) as DhrBlocking[]);
                setShowBlock(true);
              }
              throw e;
            })
          }
          onDone={(res) => {
            setSign(null);
            onNotice(null);
            toast(signedToast(res, sign === "released" ? t("gxp.tpl.releasedToast", { n: record.number }) : t("gxp.tpl.rejectedToast", { n: record.number })));
            onDone();
          }}
          onClose={() => setSign(null)}
        >
          {sign === "rejected" ? (
            <div className="field">
              <label htmlFor="dhr-rej-ncr">
                {t("gxp.dhr.label.rejectNcr")} <span className="req" aria-hidden />
              </label>
              <NcrSelect id="dhr-rej-ncr" itemId={record.item_id} lotId={record.lot_id} woIds={record.wo_ids} value={ncr} onChange={setNcr} testId="dhr-reject-ncr" />
              <span className="hint">{t("gxp.dhr.hint.rejectNcr")}</span>
            </div>
          ) : null}
        </SignatureDialog>
      ) : null}
    </div>
  );
}

function ReassembleDialog({ record, onClose, onDone }: { record: DhrRecord; onClose(): void; onDone(r: DhrRecord): void }) {
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <Dialog
      title={t("gxp.tpl.reassembleTitle", { n: record.number })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !why.trim()}
            onClick={() => {
              setBusy(true);
              setErr(null);
              assembleDhr(record.lot_id ? { lot_id: record.lot_id, reason: why.trim() } : { wo_id: record.wo_ids[0], reason: why.trim() })
                .then(onDone, (e: unknown) => setErr(e))
                .finally(() => setBusy(false));
            }}
            data-testid="dhr-reassemble-go"
          >
            <Icon name="refresh" /> {t("gxp.dhr.btn.reassemble")}
          </button>
        </>
      }
    >
      <div className="col" style={{ gap: 10 }}>
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{record.status === "released" ? t("gxp.dhr.reassembleReleased") : t("gxp.dhr.reassembleBody")}</p>
        <div className="field">
          <label htmlFor="dhr-rea-why">
            {t("gxp.dhr.label.reassembleReason")} <span className="req" aria-hidden />
          </label>
          <textarea id="dhr-rea-why" className="textarea" rows={2} maxLength={500} value={why} onChange={(e) => setWhy(e.target.value)} data-testid="dhr-reassemble-reason" />
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          {t("gxp.tpl.currentCounts", { n: formatNumber(record.exceptions.length) })}
        </p>
      </div>
    </Dialog>
  );
}


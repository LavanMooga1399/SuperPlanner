/**
 * Inspection (M7 5.2, 5.3, 10): the inspection-lot worklist, the lot record (results per characteristic with the live
 * verdict, usage decision signed per policy, cancel) and the holds list (manual holds placed and released here;
 * inspection and NCR holds are released by their document).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { listLots } from "../api/clientM2";
import { getInspectionLot, listEquipment, listHolds, listInspectionLots, listNcrs, placeHold, recordAction } from "../api/clientM7";
import type { CharacteristicInput, Equipment, Hold, InspectionLot, InspectionResult, ResultEntry } from "../api/typesM7";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import type { LotRecord } from "../api/typesM2";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { plural, t } from "../../lib/i18n";
import { batchId, DueCell, fmtQ, ItemCell, itemText, usePersonName, useSupplierName } from "./common";
import { HoldChip, HoldSourceChip, LotStatusChip, LOT_STATUS, labelOf, scopeText, SeverityChip, VerdictChip } from "./labels";
import { AttachmentsTab, HistoryTab, LinksTab, RecordHeader, RecordTabs, SignaturesTab, standardTabs, TabPanel } from "./RecordShell";
import { charStates, isDefective, nextOpenSample, submitResults, useResultQueue, type CharState } from "./results";
import { QaWorklist } from "./Worklist";
import "./qa.css";

// ---------------------------------------------------------------- worklist
export function InspectionLotsPage() {
  const supplier = useSupplierName();
  useEffect(() => {
    document.title = t("qa.lots.str.docTitle");
  }, []);
  const columns = useMemo<Column<InspectionLot>[]>(
    () => [
      {
        key: "number",
        header: t("qa.lots.head.lot"),
        width: "120px",
        sortKey: "number",
        sortKeyDesc: "-number",
        exportValue: (l) => l.number,
        render: (l) => (
          <Link to={mfgPaths.qaLot(l.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {l.number}
          </Link>
        ),
      },
      { key: "status", header: t("qa.lots.head.status"), width: "150px", exportValue: (l) => labelOf(LOT_STATUS, l.status), render: (l) => <LotStatusChip s={l.status} /> },
      { key: "scope", header: t("qa.lots.head.scope"), width: "100px", exportValue: (l) => scopeText(l.scope), render: (l) => scopeText(l.scope) },
      { key: "item", header: t("qa.lots.head.item"), width: "minmax(200px, 2fr)", exportValue: (l) => itemText(l.item), render: (l) => <ItemCell item={l.item} id={l.item_id} /> },
      {
        key: "lot",
        header: t("qa.lots.head.stockLot"),
        width: "minmax(170px, 1fr)",
        exportValue: (l) => l.lot_code ?? "",
        render: (l) => (
          <span className="row" style={{ gap: 4 }}>
            <span className="mono">{l.lot_code ?? (l.wo_number ? `${l.wo_number}${l.operation_seq ? `/${l.operation_seq}` : ""}` : "")}</span>
            <HoldChip on={l.hold} />
          </span>
        ),
      },
      { key: "size", header: t("qa.lots.head.size"), width: "90px", align: "right", exportValue: (l) => l.lot_size, render: (l) => fmtQ(l.lot_size) },
      { key: "source", header: t("qa.lots.head.from"), width: "minmax(130px, 1fr)", drop: 2, exportValue: (l) => (l.supplier_id ? supplier(l.supplier_id) : (l.customer ?? "")), render: (l) => <span className="mfg-ellipsis">{l.supplier_id ? supplier(l.supplier_id) : (l.customer ?? "")}</span> },
      { key: "due", header: t("qa.lots.head.due"), width: "200px", sortKey: "due_at", sortKeyDesc: "-due_at", exportValue: (l) => l.due_at ?? "", render: (l) => <DueCell at={l.due_at} overdue={l.overdue && !["accepted", "rejected", "cancelled"].includes(l.status)} /> },
    ],
    [supplier],
  );
  return (
    <QaWorklist<InspectionLot>
      title={t("qa.lots.title")}
      description={t("qa.lots.desc")}
      pageKey="qa-lots"
      testId="qa-lots-page"
      searchPlaceholder={t("qa.lots.ph.search")}
      views={[
        { key: "overdue", label: t("qa.lots.view.overdue"), query: { overdue: "true" } },
        { key: "ready", label: t("qa.lots.view.ready"), query: { status: "ready" } },
      ]}
      statusOptions={[
        { value: "", label: t("qa.lots.status.open") },
        { value: "open", label: t("qa.status.lot.open") },
        { value: "in_progress", label: t("qa.status.lot.inProgress") },
        { value: "ready", label: t("qa.status.lot.ready") },
        { value: "accepted", label: t("qa.status.lot.accepted") },
        { value: "rejected", label: t("qa.status.lot.rejected") },
        { value: "cancelled", label: t("qa.status.lot.cancelled") },
        { value: "all", label: t("qa.list.status.all") },
      ]}
      defaultStatus="open,in_progress,ready"
      filters={[
        {
          param: "scope",
          label: t("qa.lots.head.scope"),
          options: [
            { value: "", label: t("qa.list.any") },
            { value: "incoming", label: t("qa.scope.incoming") },
            { value: "in_process", label: t("qa.scope.inProcess") },
            { value: "final", label: t("qa.scope.final") },
          ],
        },
      ]}
      sortDefault="due_at"
      fetch={(q, signal) => listInspectionLots({ ...q, status: q.status === "all" ? undefined : q.status }, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["item", "lot", "due"] }}
      rowKey={(l) => l.id}
      rowExtras={(l) => ({ testId: "qa-lot-row", data: { status: l.status, number: l.number } })}
      rowPath={(l) => mfgPaths.qaLot(l.id)}
      empty={t("qa.lots.empty")}
      noun={t("qa.lots.str.noun")}
    />
  );
}

// ---------------------------------------------------------------- lot record
const SOURCE_LABEL: Record<string, "qa.lots.source.po_receipt" | "qa.lots.source.wo_receipt" | "qa.lots.source.floor" | "qa.lots.source.manual"> = {
  po_receipt: "qa.lots.source.po_receipt",
  wo_receipt: "qa.lots.source.wo_receipt",
  floor: "qa.lots.source.floor",
  floor_start: "qa.lots.source.floor",
  manual: "qa.lots.source.manual",
};

export function InspectionLotPage() {
  const { lotId = "" } = useParams();
  const rec = useLoad((s) => getInspectionLot(lotId, s), [lotId]);
  const canInspect = useCan("qa_inspect");
  const canDecide = useCan("qa_decide");
  const person = usePersonName();
  const supplier = useSupplierName();
  const [tab, setTab] = useState("results");
  const [deciding, setDeciding] = useState<null | "accept" | "reject">(null);
  const [cancelling, setCancelling] = useState(false);
  const lot = rec.data;
  useEffect(() => {
    if (lot) document.title = `${lot.number} - ${t("qa.lots.title")}`;
  }, [lot]);
  if (rec.loading && !lot) return <Spinner />;
  if (!lot) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const states = charStates(lot);
  const verdict = lot.verdict?.verdict ?? "pending";
  const open = ["open", "in_progress", "ready"].includes(lot.status);
  const decided = lot.status === "accepted" || lot.status === "rejected";
  const reload = () => rec.reload();
  const sourceKey = SOURCE_LABEL[lot.source];
  return (
    <div className="col gap-lg" data-testid="qa-lot-page" data-status={lot.status}>
      <RecordHeader
        crumbs={[[t("nav.mfg.section.qa-lots"), mfgPaths.qaLots()]]}
        number={lot.number}
        title={lot.item ? `${lot.item.part_number} ${lot.item.name}` : null}
        status={<LotStatusChip s={lot.status} />}
        chips={
          <>
            <HoldChip on={lot.hold} />
            {lot.overdue && open ? (
              <span className="badge danger">
                <Icon name="clock" /> {t("qa.common.str.overdue")}
              </span>
            ) : null}
          </>
        }
        facts={[
          [t("qa.lots.head.scope"), scopeText(lot.scope)],
          [t("qa.lots.head.stockLot"), lot.lot_code ? <span className="mono">{lot.lot_code}</span> : null],
          [t("qa.lots.head.size"), fmtQ(lot.lot_size)],
          [t("qa.lots.label.plan"), lot.plan_number ? <Link to={mfgPaths.qaPlan(lot.plan_id)}>{t("qa.lots.tpl.planVersion", { n: lot.plan_number, v: lot.plan_version })}</Link> : null],
          [t("qa.lots.label.source"), sourceKey ? t(sourceKey) : lot.source],
          [lot.supplier_id ? t("qa.lots.label.supplier") : lot.customer ? t("qa.lots.label.customer") : t("qa.lots.label.workOrder"), lot.supplier_id ? supplier(lot.supplier_id) : lot.customer ? lot.customer : lot.wo_id ? <Link to={mfgPaths.workOrder(lot.wo_id)} className="mono">{`${lot.wo_number ?? ""}${lot.operation_seq ? ` / ${lot.operation_seq}` : ""}`}</Link> : null],
          [t("qa.lots.head.due"), <DueCell key="d" at={lot.due_at} overdue={lot.overdue && open} />],
          [t("qa.lots.label.decision"), lot.decision ? t("qa.lots.tpl.decided", { what: lot.decision === "accept" ? t("qa.lots.str.accepted") : t("qa.lots.str.rejected"), who: person(lot.decided_by), when: formatDateTime(lot.decided_at) }) : null],
        ]}
        actions={
          <>
            {open && canInspect ? (
              <Link className="btn" to={mfgPaths.floorInspect(lot.id)} data-testid="qa-open-tablet">
                <Icon name="external" /> {t("qa.lots.btn.tablet")}
              </Link>
            ) : null}
            {open && canDecide ? (
              <button type="button" className="btn ghost" onClick={() => setCancelling(true)} data-testid="qa-lot-cancel">
                {t("qa.lots.btn.cancel")}
              </button>
            ) : null}
            <Link className="btn ghost" to={mfgPaths.printQa("inspection_lot", lot.id)} target="_blank" rel="noopener">
              <Icon name="file" /> {t("qa.common.btn.print")}
            </Link>
            {open && canDecide ? (
              <>
                <button type="button" className="btn" disabled={verdict !== "reject" && lot.status !== "ready"} onClick={() => setDeciding("reject")} data-testid="qa-decision-reject" title={t("qa.lots.attr.reject")}>
                  <Icon name="x" /> {t("qa.lots.btn.reject")}
                </button>
                <button type="button" className="btn primary" disabled={lot.status !== "ready"} onClick={() => setDeciding("accept")} data-testid="qa-decision-accept" title={lot.status !== "ready" ? t("qa.lots.attr.notReady") : undefined}>
                  <Icon name="check" /> {t("qa.lots.btn.accept")}
                </button>
              </>
            ) : null}
          </>
        }
      />
      <VerdictBanner lot={lot} states={states} />
      {lot.ncr_id ? (
        <Banner tone="info" icon="alert" title={t("qa.lots.title.ncr")} actions={<Link className="btn sm" to={mfgPaths.qaNcr(lot.ncr_id)}>{t("qa.lots.btn.openNcr")}</Link>}>
          {t("qa.lots.text.ncr")}
        </Banner>
      ) : null}
      {lot.decision && lot.decision_note ? (
        <p className="small" style={{ margin: 0 }}>
          <b>{t("qa.lots.label.decisionNote")}</b> {lot.decision_note}
        </p>
      ) : null}
      <RecordTabs label={t("qa.lots.aria.tabs")} value={tab} onChange={setTab} tabs={[{ key: "results", label: t("qa.lots.tab.results"), count: lot.results.filter((r) => !r.superseded).length }, ...standardTabs(lot)]} />
      {tab === "results" ? (
        <TabPanel id="results">
          <ResultsEntry lot={lot} states={states} editable={open && canInspect} onSaved={reload} />
        </TabPanel>
      ) : null}
      {tab === "links" ? (
        <TabPanel id="links">
          <LinksTab links={lot.links} fromType="inspection_lot" fromId={lot.id} canEdit={canDecide} onChanged={reload} />
        </TabPanel>
      ) : null}
      {tab === "attachments" ? (
        <TabPanel id="attachments">
          <AttachmentsTab attachments={lot.attachments} entityType="inspection_lot" entityId={lot.id} canEdit={canInspect} locked={decided} onChanged={reload} />
        </TabPanel>
      ) : null}
      {tab === "history" ? (
        <TabPanel id="history">
          <HistoryTab entityType="inspection_lot" entityId={lot.id} />
        </TabPanel>
      ) : null}
      {tab === "signatures" ? (
        <TabPanel id="signatures">
          <SignaturesTab signatures={lot.signatures} recordType="inspection_lot" recordId={lot.id} />
        </TabPanel>
      ) : null}
      {deciding ? <DecisionDialog lot={lot} decision={deciding} onClose={() => setDeciding(null)} onDone={(l) => (setDeciding(null), l ? rec.setData(l) : rec.reload())} /> : null}
      {cancelling ? (
        <SignatureDialog<InspectionLot>
          title={t("qa.lots.tpl.cancelTitle", { n: lot.number })}
          recordType="inspection_lot"
          recordId={lot.id}
          recordLabel={lot.number}
          action="cancel"
          signable={false}
          meaning="closed"
          danger
          submitLabel={t("qa.lots.btn.signCancel")}
          plainLabel={t("qa.lots.btn.cancelLot")}
          commentLabel={t("qa.lots.label.cancelReason")}
          commentRequired
          effect={t("qa.lots.text.cancelEffect")}
          perform={(sig, comment) => recordAction<InspectionLot>("inspection_lot", lot.id, "cancel", { reason: comment }, { version: lot.row_version, signature: sig })}
          onDone={(res) => {
            toast(signedToast(res, t("qa.lots.toast.cancelled")));
            setCancelling(false);
            rec.reload();
          }}
          onClose={() => setCancelling(false)}
        />
      ) : null}
    </div>
  );
}

function VerdictBanner({ lot, states }: { lot: InspectionLot; states: CharState[] }) {
  const v = lot.verdict?.verdict ?? "pending";
  const done = states.reduce((a, s) => a + Math.min(s.entered, s.n), 0);
  const all = states.reduce((a, s) => a + s.n, 0);
  if (lot.status === "cancelled") return null;
  return (
    <div className={`banner ${v === "accept" ? "ok" : v === "reject" ? "danger" : ""}`} data-testid="qa-verdict" data-verdict={v} role="status">
      <Icon name={v === "accept" ? "check" : v === "reject" ? "x" : "clock"} />
      <div className="banner-body">
        <strong>{v === "accept" ? t("qa.lots.verdict.accept") : v === "reject" ? t("qa.lots.verdict.reject") : t("qa.lots.verdict.pending")}</strong>
        <div className="small">{t("qa.lots.tpl.progress", { done: formatNumber(done), all: formatNumber(all), chars: plural(states.length, t("qa.lots.str.char"), t("qa.lots.str.chars")) })}</div>
      </div>
      <div className="qa-progress" style={{ flex: "0 0 160px", alignSelf: "center" }} aria-hidden>
        <span style={{ width: `${all ? Math.round((done / all) * 100) : 0}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- results entry (desktop)
function limitsText(c: CharacteristicInput): string {
  if (c.kind === "attribute") return t("qa.lots.str.passFail");
  const u = c.unit ? ` ${c.unit}` : "";
  const parts: string[] = [];
  if (c.lsl !== null) parts.push(t("qa.lots.tpl.min", { v: formatNumber(c.lsl) }));
  if (c.nominal !== null) parts.push(t("qa.lots.tpl.nominal", { v: formatNumber(c.nominal) }));
  if (c.usl !== null) parts.push(t("qa.lots.tpl.max", { v: formatNumber(c.usl) }));
  return parts.join(" · ") + u;
}

export function useGauges(cls: string | null) {
  return useLoad((s) => (cls ? listEquipment({ equipment_class: cls, limit: 200 }, s).then((p) => p.items) : null), [cls]);
}

export function gaugeLabel(e: Equipment): string {
  return `${e.code} ${e.name}${e.valid ? "" : ` (${t("qa.lots.str.notCalibrated")})`}`;
}

function ResultsEntry({ lot, states, editable, onSaved }: { lot: InspectionLot; states: CharState[]; editable: boolean; onSaved(): void }) {
  const queued = useResultQueue(lot.id);
  return (
    <>
      {queued.length ? (
        <Banner tone="warn" icon="refresh" title={t("qa.lots.title.queued")}>
          {t("qa.lots.tpl.queued", { n: plural(queued.length, t("qa.lots.str.batch"), t("qa.lots.str.batches")) })}
        </Banner>
      ) : null}
      {states.map((s) => (
        <CharCard key={s.c.id} lot={lot} s={s} editable={editable} onSaved={onSaved} />
      ))}
      {!states.length ? <p className="muted">{t("qa.lots.empty.chars")}</p> : null}
    </>
  );
}

function CharCard({ lot, s, editable, onSaved }: { lot: InspectionLot; s: CharState; editable: boolean; onSaved(): void }) {
  const c = s.c;
  const next = nextOpenSample(s);
  const [sample, setSample] = useState<number | null>(next);
  const [value, setValue] = useState("");
  const [gauge, setGauge] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [correct, setCorrect] = useState<InspectionResult | null>(null);
  const [reason, setReason] = useState("");
  const gauges = useGauges(c.equipment_class);
  const valueRef = useRef<HTMLInputElement>(null);
  useEffect(() => setSample(nextOpenSample(s)), [lot.row_version]); // eslint-disable-line react-hooks/exhaustive-deps
  const target = correct ? correct.sample_no : sample;
  const save = async (passed?: boolean) => {
    if (target === null) return;
    const num = value.trim() === "" ? null : Number(value.replace(",", "."));
    if (c.kind === "variable" && (num === null || !Number.isFinite(num))) return;
    if (c.equipment_class && !gauge) return setError(new ApiError(422, "QA_GAUGE", t("qa.lots.err.gauge", { cls: c.equipment_class })));
    if (correct && !reason.trim()) return;
    const entry: ResultEntry = {
      characteristic_id: c.id,
      sample_no: target,
      ...(c.kind === "variable" ? { value: num } : { passed: Boolean(passed), defects: passed ? 0 : 1 }),
      ...(gauge ? { equipment_id: gauge } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
      ...(correct ? { corrects_result_id: correct.id, reason: reason.trim() } : {}),
    };
    setBusy(true);
    setError(null);
    try {
      const r = await submitResults(lot.id, batchId(lot.number), [entry]);
      if (r.status === "queued") toast(t("qa.lots.toast.queued"), "warn");
      setValue("");
      setNote("");
      setCorrect(null);
      setReason("");
      onSaved();
      window.setTimeout(() => valueRef.current?.focus(), 0);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const cells = [];
  for (let i = 1; i <= s.n; i++) {
    const r = s.bySample.get(i);
    const bad = r ? isDefective(c, r) : false;
    cells.push(
      <button
        key={i}
        type="button"
        className={`qa-sample${r ? (bad ? " bad" : " good") : ""}`}
        aria-pressed={target === i}
        onClick={() => {
          if (!editable) return;
          if (r) {
            setCorrect(r);
            setValue(r.value !== null ? String(r.value) : "");
          } else {
            setCorrect(null);
            setSample(i);
          }
          window.setTimeout(() => valueRef.current?.focus(), 0);
        }}
        disabled={!editable && !r}
        data-testid="qa-result-cell"
        data-sample={i}
        data-defective={r ? String(bad) : undefined}
        aria-label={r ? t("qa.lots.tpl.cellDone", { n: i, v: r.value !== null ? formatNumber(r.value) : r.passed ? t("qa.lots.str.pass") : t("qa.lots.str.fail"), state: bad ? t("qa.lots.str.defective") : t("qa.lots.str.ok") }) : t("qa.lots.tpl.cellOpen", { n: i })}
      >
        <span className="qa-sample-no">{i}</span>
        <span className="qa-sample-val">
          {r ? (
            <>
              <Icon name={bad ? "x" : "check"} size={12} />
              {r.value !== null ? formatNumber(r.value) : r.passed ? t("qa.lots.str.pass") : t("qa.lots.str.fail")}
            </>
          ) : (
            <span className="faint">—</span>
          )}
        </span>
      </button>,
    );
  }
  return (
    <section className="card" data-testid="qa-char" data-code={c.code}>
      <div className="card-header qa-char-head">
        <div className="col" style={{ gap: 2 }}>
          <h2>
            <span className="mono">{c.code}</span> {c.name}
          </h2>
          <span className="qa-limits">
            {limitsText(c)}
            {c.method ? ` · ${c.method}` : ""}
            {c.equipment_class ? ` · ${t("qa.lots.tpl.gaugeClass", { cls: c.equipment_class })}` : ""}
          </span>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          <SeverityChip s={c.severity} />
          {c.destructive ? <span className="badge info">{t("qa.lots.str.destructive")}</span> : null}
          <span className="small muted">{t("qa.lots.tpl.sampling", { n: s.n, ac: s.ac, re: s.re })}</span>
          {s.tightened ? <span className="badge warn">{t("qa.lots.str.tightened")}</span> : null}
          <span className="small">{t("qa.lots.tpl.counts", { e: s.entered, n: s.n, d: s.defective })}</span>
          <VerdictChip s={s.verdict} testId="qa-char-verdict" />
        </div>
      </div>
      <div className="card-body col">
        <div className="qa-sample-grid" role="group" aria-label={t("qa.lots.tpl.samplesOf", { code: c.code })}>
          {cells}
        </div>
        {editable && (target !== null || correct) ? (
          <form
            className="col"
            style={{ gap: 8, borderTop: "1px solid var(--border)", paddingTop: 12 }}
            onSubmit={(e) => {
              e.preventDefault();
              void save(true);
            }}
          >
            <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
              <div className="field">
                <span className="field-label">{correct ? t("qa.lots.label.correcting") : t("qa.lots.label.sample")}</span>
                <strong className="mono" style={{ lineHeight: "28px" }}>
                  {t("qa.lots.tpl.sampleOf", { n: target ?? "", m: s.n })}
                </strong>
              </div>
              {c.kind === "variable" ? (
                <div className="field">
                  <label htmlFor={`v-${c.id}`}>{t("qa.lots.tpl.value", { unit: c.unit ?? "" })}</label>
                  <input ref={valueRef} id={`v-${c.id}`} className="input" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} style={{ width: 120 }} data-testid="qa-value" />
                </div>
              ) : null}
              {c.equipment_class ? (
                <div className="field">
                  <label htmlFor={`g-${c.id}`}>{t("qa.lots.label.gauge")}</label>
                  <select id={`g-${c.id}`} className="select" value={gauge} onChange={(e) => setGauge(e.target.value)} data-testid="qa-gauge">
                    <option value="">{t("qa.lots.str.chooseGauge")}</option>
                    {(gauges.data ?? []).map((g) => (
                      <option key={g.id} value={g.id} disabled={!g.valid}>
                        {gaugeLabel(g)}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              <div className="field grow" style={{ minWidth: 160 }}>
                <label htmlFor={`n-${c.id}`}>{t("qa.lots.label.note")}</label>
                <input id={`n-${c.id}`} className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
              </div>
              {correct ? (
                <div className="field grow" style={{ minWidth: 200 }}>
                  <label htmlFor={`r-${c.id}`}>{t("qa.lots.label.correctionReason")}</label>
                  <input id={`r-${c.id}`} className="input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} data-testid="qa-correction-reason" />
                </div>
              ) : null}
              {c.kind === "variable" ? (
                <button type="submit" className="btn primary" disabled={busy || !value.trim() || (Boolean(correct) && !reason.trim())} data-testid="qa-save-result">
                  {t("qa.lots.btn.save")}
                </button>
              ) : (
                <>
                  <button type="button" className="btn" disabled={busy || (Boolean(correct) && !reason.trim())} onClick={() => void save(true)} data-testid="qa-pass">
                    <Icon name="check" /> {t("qa.lots.str.pass")}
                  </button>
                  <button type="button" className="btn danger" disabled={busy || (Boolean(correct) && !reason.trim())} onClick={() => void save(false)} data-testid="qa-fail">
                    <Icon name="x" /> {t("qa.lots.str.fail")}
                  </button>
                </>
              )}
              {correct ? (
                <button type="button" className="btn ghost" onClick={() => (setCorrect(null), setValue(""), setReason(""))}>
                  {t("common.cancel")}
                </button>
              ) : null}
            </div>
            <MfgError error={error} />
          </form>
        ) : null}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- decision
function DecisionDialog({ lot, decision, onClose, onDone }: { lot: InspectionLot; decision: "accept" | "reject"; onClose(): void; onDone(l: InspectionLot | null): void }) {
  const [note, setNote] = useState("");
  const [ncrId, setNcrId] = useState("");
  const contradicts = decision === "accept" && lot.verdict?.verdict === "reject";
  const ncrs = useLoad((s) => (contradicts ? listNcrs({ q: lot.lot_code ?? lot.number, status: "approved,implemented", limit: 50 }, s) : null), [contradicts]);
  return (
    <SignatureDialog<InspectionLot>
      title={decision === "accept" ? t("qa.lots.tpl.acceptTitle", { n: lot.number }) : t("qa.lots.tpl.rejectTitle", { n: lot.number })}
      recordType="inspection_lot"
      recordId={lot.id}
      recordLabel={lot.number}
      action="decide"
      decision={decision}
      meaning={decision === "accept" ? "released" : "rejected"}
      danger={decision === "reject"}
      submitLabel={decision === "accept" ? t("qa.lots.btn.signAccept") : t("qa.lots.btn.signReject")}
      plainLabel={decision === "accept" ? t("qa.lots.btn.accept") : t("qa.lots.btn.reject")}
      canSubmit={!contradicts || Boolean(ncrId)}
      effect={decision === "accept" ? (lot.hold ? t("qa.lots.text.acceptEffectHold") : t("qa.lots.text.acceptEffect")) : t("qa.lots.text.rejectEffect")}
      perform={(sig, comment) => recordAction<InspectionLot>("inspection_lot", lot.id, "decision", { decision, note: note.trim() || comment, ...(ncrId ? { ncr_id: ncrId } : {}) }, { version: lot.row_version, signature: sig })}
      onDone={(res) => {
        toast(signedToast(res, decision === "accept" ? t("qa.lots.toast.accepted") : t("qa.lots.toast.rejected")));
        onDone(res.status === 200 ? res.record : null);
      }}
      onClose={onClose}
    >
      <div className="col" style={{ gap: 8 }}>
        {contradicts ? (
          <Banner tone="warn" title={t("qa.lots.title.contradicts")}>
            {t("qa.lots.text.contradicts")}
          </Banner>
        ) : null}
        {contradicts ? (
          <div className="field">
            <label htmlFor="dec-ncr">{t("qa.lots.label.ncr")}</label>
            <select id="dec-ncr" className="select" value={ncrId} onChange={(e) => setNcrId(e.target.value)}>
              <option value="">{t("qa.lots.str.chooseNcr")}</option>
              {(ncrs.data?.items ?? []).map((n) => (
                <option key={n.id} value={n.id}>
                  {n.number} {n.title}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="field">
          <label htmlFor="dec-note">{t("qa.lots.label.decisionNote")}</label>
          <input id="dec-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} data-testid="qa-decision-note" />
        </div>
      </div>
    </SignatureDialog>
  );
}

// ---------------------------------------------------------------- holds
const RELEASABLE = new Set(["manual", "recall", "field_action"]);

function sourcePath(h: Hold): string | null {
  if (!h.source_id) return null;
  if (h.source === "inspection") return mfgPaths.qaLot(h.source_id);
  if (h.source === "ncr") return mfgPaths.qaNcr(h.source_id);
  if (h.source === "recall") return mfgPaths.recall(h.source_id);
  if (h.source === "field_action") return mfgPaths.qaFieldAction(h.source_id);
  return null;
}

export function HoldsPage() {
  const canDecide = useCan("qa_decide");
  const person = usePersonName();
  const [release, setRelease] = useState<Hold | null>(null);
  const [placing, setPlacing] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    document.title = t("qa.holds.str.docTitle");
  }, []);
  const columns = useMemo<Column<Hold>[]>(
    () => [
      {
        key: "what",
        header: t("qa.holds.head.what"),
        width: "minmax(140px, 1fr)",
        exportValue: (h) => h.lot_code ?? h.serial ?? "",
        render: (h) => (
          <span className="row" style={{ gap: 4 }}>
            <span className="small muted">{h.serial ? t("qa.holds.str.serial") : t("qa.holds.str.lot")}</span>
            <span className="mono">{h.lot_code ?? h.serial}</span>
          </span>
        ),
      },
      { key: "item", header: t("qa.lots.head.item"), width: "minmax(200px, 2fr)", exportValue: (h) => itemText(h.item), render: (h) => <ItemCell item={h.item} id={h.item_id} /> },
      {
        key: "source",
        header: t("qa.holds.head.source"),
        width: "minmax(170px, 1fr)",
        exportValue: (h) => `${h.source} ${h.source_number ?? ""}`,
        render: (h) => {
          const p = sourcePath(h);
          return (
            <span className="row" style={{ gap: 6 }}>
              <HoldSourceChip s={h.source} />
              {h.source_number ? (p ? <Link to={p} className="mono" onClick={(e) => e.stopPropagation()}>{h.source_number}</Link> : <span className="mono">{h.source_number}</span>) : null}
            </span>
          );
        },
      },
      { key: "reason", header: t("qa.holds.head.reason"), width: "minmax(200px, 2fr)", render: (h) => <span className="mfg-ellipsis" title={h.reason}>{h.reason}</span> },
      { key: "placed", header: t("qa.holds.head.placed"), width: "170px", sortValue: (h) => h.placed_at, exportValue: (h) => h.placed_at, render: (h) => <span title={person(h.placed_by)}>{formatDateTime(h.placed_at)}</span> },
      {
        key: "state",
        header: t("qa.holds.head.state"),
        width: "minmax(160px, 1fr)",
        exportValue: (h) => (h.open ? t("qa.hold.chip") : t("qa.holds.str.released")),
        render: (h) =>
          h.open ? (
            RELEASABLE.has(h.source) && canDecide ? (
              <button
                type="button"
                className="btn sm"
                onClick={(e) => {
                  e.stopPropagation();
                  setRelease(h);
                }}
                data-testid="hold-release"
              >
                <Icon name="unlock" /> {t("qa.holds.btn.release")}
              </button>
            ) : (
              <span className="row" style={{ gap: 4 }}>
                <HoldChip on />
                {!RELEASABLE.has(h.source) ? <span className="small muted">{t("qa.holds.str.byDocument")}</span> : null}
              </span>
            )
          ) : (
            <span className="small">{t("qa.holds.tpl.released", { when: formatDateTime(h.released_at) })}</span>
          ),
      },
    ],
    [canDecide, person],
  );
  return (
    <>
      <QaWorklist<Hold>
        key={tick}
        title={t("qa.holds.title")}
        description={t("qa.holds.desc")}
        actions={
          canDecide ? (
            <button type="button" className="btn primary" onClick={() => setPlacing(true)} data-testid="hold-place">
              <Icon name="lock" /> {t("qa.holds.btn.place")}
            </button>
          ) : null
        }
        pageKey="qa-holds"
        testId="qa-holds-page"
        filters={[
          {
            param: "source",
            label: t("qa.holds.head.source"),
            options: [{ value: "", label: t("qa.list.any") }, ...["inspection", "ncr", "recall", "field_action", "manual"].map((s) => ({ value: s, label: t(s === "inspection" ? "qa.hold.source.inspection" : s === "ncr" ? "qa.hold.source.ncr" : s === "recall" ? "qa.hold.source.recall" : s === "field_action" ? "qa.hold.source.fieldAction" : "qa.hold.source.manual") }))],
          },
          { param: "state", label: t("qa.holds.head.state"), options: [{ value: "", label: t("qa.holds.str.openOnly") }, { value: "all", label: t("qa.holds.str.allHolds") }] },
        ]}
        fetch={(q, signal) => {
          const { state, status: _s, sort: _o, ...rest } = q;
          return listHolds({ ...rest, open: state === "all" ? undefined : true }, signal);
        }}
        columns={columns}
        card={{ title: "what", status: "state", fields: ["item", "source", "placed"] }}
        rowKey={(h) => h.id}
        rowExtras={(h) => ({ testId: "hold-row", data: { source: h.source, open: h.open } })}
        empty={t("qa.holds.empty")}
        noun={t("qa.holds.str.noun")}
      />
      {release ? (
        <SignatureDialog<Hold>
          title={t("qa.holds.tpl.releaseTitle", { what: release.lot_code ?? release.serial ?? "" })}
          recordType="hold"
          recordId={release.id}
          recordLabel={release.lot_code ?? release.serial ?? release.id}
          action="release"
          meaning="released"
          submitLabel={t("qa.holds.btn.signRelease")}
          plainLabel={t("qa.holds.btn.release")}
          effect={t("qa.holds.text.releaseEffect")}
          perform={(sig, comment) => recordAction<Hold>("hold", release.id, "release", { note: comment }, { signature: sig })}
          onDone={(res) => {
            toast(signedToast(res, t("qa.holds.toast.released")));
            setRelease(null);
            setTick((x) => x + 1);
          }}
          onClose={() => setRelease(null)}
        />
      ) : null}
      {placing ? <PlaceHoldDialog onClose={() => setPlacing(false)} onDone={() => (setPlacing(false), setTick((x) => x + 1))} /> : null}
    </>
  );
}

function PlaceHoldDialog({ onClose, onDone }: { onClose(): void; onDone(): void }) {
  const [q, setQ] = useState("");
  const [lot, setLot] = useState<LotRecord | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const lots = useLoad((s) => (q.trim().length >= 2 && !lot ? listLots({ q: q.trim(), limit: 20 }, s) : null), [q, lot]);
  return (
    <Dialog
      title={t("qa.holds.title.place")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !lot || !reason.trim()}
            onClick={async () => {
              if (!lot) return;
              setBusy(true);
              setError(null);
              try {
                await placeHold({ lot_id: lot.id, reason: reason.trim() });
                toast(t("qa.holds.toast.placed", { lot: lot.lot_code }));
                onDone();
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
            data-testid="hold-place-save"
          >
            <Icon name="lock" /> {t("qa.holds.btn.place")}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="hold-lot">{t("qa.holds.label.lot")}</label>
          {lot ? (
            <div className="row" style={{ gap: 8 }}>
              <span className="mono">{lot.lot_code}</span> <span className="muted">{lot.item.part_number}</span>
              <button type="button" className="btn ghost sm" onClick={() => (setLot(null), setQ(""))}>
                {t("qa.holds.btn.change")}
              </button>
            </div>
          ) : (
            <>
              <input id="hold-lot" className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("qa.holds.ph.lot")} data-testid="hold-lot-search" />
              {(lots.data?.items ?? []).length ? (
                <ul className="mfg-plain-list col" style={{ gap: 2, maxHeight: 200, overflow: "auto" }}>
                  {(lots.data?.items ?? []).map((l) => (
                    <li key={l.id}>
                      <button type="button" className="menu-item" onClick={() => setLot(l)}>
                        <span className="mono">{l.lot_code}</span> <span className="muted">{l.item.part_number}</span>
                        {l.hold ? <HoldChip on /> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          )}
        </div>
        <div className="field">
          <label htmlFor="hold-reason">{t("qa.holds.head.reason")}</label>
          <textarea id="hold-reason" className="textarea" rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="hold-reason" />
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          {t("qa.holds.text.placeEffect")}
        </p>
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}


/**
 * Kanban `/mfg/kanban` (M8 6.2, 12): the plant's loops (item, location, source, cards and their states, container,
 * lead time, sizing suggestion), a loop panel with its cards and their open signal (purchase request or work order),
 * new / edit loop, a scan box for `KB:` card codes, and the printable card sheet (`/mfg/print/kanban/:loopId`, one
 * QR code per card). Kanban items get no planned orders from MRP; an empty card is the replenishment signal.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { QrCode } from "../../components/QrCode";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { listLines } from "../api/client";
import { listLocations, listSuppliers } from "../api/clientM2";
import { createKanbanLoop, getKanbanLoop, listKanbanCards, listKanbanLoops, scanKanban, updateKanbanLoop } from "../api/clientM8";
import type { ItemRef } from "../api/types";
import type { KanbanCard, KanbanLoop, KanbanLoopInput, M8Page } from "../api/typesM8";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import { FormErrors } from "../components/Field";
import { ItemPicker } from "../components/ItemPicker";
import { VirtualTable, type Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { setSearchParam, usePaged } from "../lib/usePaged";
import { useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { CardChip, Facts, num } from "../forecast/shared";

const sourceText = (l: KanbanLoop) => (l.source === "buy" ? t("plan.kb.source.buy") : t("plan.kb.source.make"));

/** Card states as three counts with text (full / empty / in process), never colour alone. */
function CardStates({ l }: { l: KanbanLoop }) {
  const c = l.card_counts;
  return (
    <span className="pl-cards" aria-label={t("plan.kb.aria.states", { full: c.full ?? 0, empty: c.empty ?? 0, proc: c.in_process ?? 0 })}>
      <span className="pl-cards-n ok" title={t("plan.kb.state.full")}>
        <Icon name="check" size={12} />
        {c.full ?? 0}
      </span>
      <span className="pl-cards-n warn" title={t("plan.kb.state.empty")}>
        <Icon name="circle" size={12} />
        {c.empty ?? 0}
      </span>
      <span className="pl-cards-n accent" title={t("plan.kb.state.inProcess")}>
        <Icon name="truck" size={12} />
        {c.in_process ?? 0}
      </span>
    </span>
  );
}

function Sizing({ l }: { l: KanbanLoop }) {
  const s = l.sizing;
  if (!s.suggested_cards) return <span className="muted">–</span>;
  if (s.undersized)
    return (
      <span className="badge warn" title={t("plan.kb.hint.undersized")} data-testid="kb-undersized">
        <Icon name="alert" /> {t("plan.kb.tpl.suggest", { n: s.suggested_cards })}
      </span>
    );
  return <span className="pl-num muted">{t("plan.kb.tpl.suggest", { n: s.suggested_cards })}</span>;
}

export function KanbanPage() {
  const [params, setParams] = useSearchParams();
  const canEdit = useCan("kanban_edit");
  const canScan = useCan("kanban_scan");
  useEffect(() => {
    document.title = t("plan.kb.title");
  }, []);
  const loops = usePaged<KanbanLoop, M8Page<KanbanLoop>>((offset, limit, signal) => listKanbanLoops({ limit, offset }, signal), []);
  const loopId = params.get("loop") ?? "";
  const [editing, setEditing] = useState<KanbanLoop | "new" | null>(null);
  const columns = useMemo<Column<KanbanLoop>[]>(
    () => [
      { key: "number", header: t("plan.kb.head.loop"), width: "110px", sortValue: (l) => l.number, render: (l) => <span className="mono">{l.number}</span> },
      { key: "item", header: t("plan.fc.head.item"), width: "minmax(180px, 2fr)", sortValue: (l) => l.item?.part_number, exportValue: (l) => (l.item ? `${l.item.part_number} ${l.item.name}` : l.item_id), render: (l) => (l.item ? <span className="mfg-ellipsis"><span className="mono">{l.item.part_number}</span> <span className="muted">{l.item.name}</span></span> : l.item_id) },
      { key: "location", header: t("plan.kb.head.location"), width: "110px", drop: 2, sortValue: (l) => l.location_code, render: (l) => <span className="mono">{l.location_code ?? ""}</span> },
      { key: "source", header: t("plan.kb.head.source"), width: "90px", drop: 1, sortValue: (l) => l.source, render: (l) => sourceText(l) },
      { key: "cards", header: t("plan.kb.head.cards"), width: "150px", sortValue: (l) => l.card_counts.empty ?? 0, exportValue: (l) => `${l.card_counts.full ?? 0}/${l.card_counts.empty ?? 0}/${l.card_counts.in_process ?? 0}`, render: (l) => <CardStates l={l} /> },
      { key: "container", header: t("plan.kb.head.container"), width: "110px", align: "right", sortValue: (l) => l.container_qty, render: (l) => <span className="pl-num">{num(l.container_qty)}</span> },
      { key: "lt", header: t("plan.kb.head.lt"), width: "90px", align: "right", drop: 3, sortValue: (l) => l.lead_time_days, render: (l) => <span className="pl-num">{t("plan.tpl.days", { n: l.lead_time_days })}</span> },
      { key: "sizing", header: t("plan.kb.head.sizing"), width: "130px", sortValue: (l) => (l.sizing.undersized ? 1 : 0), exportValue: (l) => l.sizing.suggested_cards, render: (l) => <Sizing l={l} /> },
      { key: "status", header: t("plan.kb.head.status"), width: "90px", render: (l) => (l.status === "active" ? t("plan.kb.status.active") : <span className="muted">{t("plan.kb.status.inactive")}</span>) },
    ],
    [],
  );
  return (
    <div className="col gap-lg" data-testid="kb-page">
      <PageHeader
        title={t("plan.kb.title")}
        description={t("plan.kb.desc")}
        actions={
          <button type="button" className="btn primary" disabled={!canEdit} title={canEdit ? undefined : needsText("kanban_edit")} onClick={() => setEditing("new")} data-testid="kb-new">
            <Icon name="plus" /> {t("plan.kb.btn.new")}
          </button>
        }
      />
      {canScan ? <ScanBox onScanned={() => loops.reload()} /> : null}
      <MfgError error={loops.error} onRetry={loops.reload} />
      <div className="pl-split">
        <section className="card card-table pl-split-list" aria-label={t("plan.kb.aria.loops")}>
          <VirtualTable
            rows={loops.rows}
            columns={columns}
            rowKey={(l) => l.id}
            label={t("plan.kb.aria.loops")}
            testId="kb-loops"
            height="min(60vh, 560px)"
            loading={loops.loading && !loops.rows.length}
            totalCount={loops.total}
            onEndReached={loops.onEndReached}
            onRowClick={(l) => setSearchParam(setParams, "loop", l.id)}
            onActivate={(l) => setSearchParam(setParams, "loop", l.id)}
            rowExtras={(l) => ({ testId: "kb-loop-row", ariaSelected: l.id === loopId, className: l.id === loopId ? "mfg-selected" : undefined, data: { loop: l.number } })}
            exportName="kanban-loops"
            empty={t("plan.kb.empty")}
            card={{ title: "number", status: "status", fields: ["item", "cards", "sizing"] }}
          />
        </section>
        <section className="pl-split-panel">
          {loopId ? <LoopPanel key={loopId} loopId={loopId} canEdit={canEdit} onEdit={(l) => setEditing(l)} /> : <div className="card card-body muted">{t("plan.kb.text.pick")}</div>}
        </section>
      </div>
      {editing ? (
        <LoopDialog
          loop={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(l) => {
            setEditing(null);
            loops.reload();
            setSearchParam(setParams, "loop", l.id);
          }}
        />
      ) : null}
    </div>
  );
}

function ScanBox({ onScanned }: { onScanned(): void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const submit = async () => {
    const c = code.trim();
    if (!c) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await scanKanban(/^KB:/i.test(c) ? c : `KB:${c}`);
      toast(r.signal ? t("plan.kb.floor.signal", { n: r.card.card_no, doc: r.signal.number }) : t("plan.kb.floor.state", { n: r.card.card_no, state: t(r.card.state === "full" ? "plan.kb.state.full" : r.card.state === "empty" ? "plan.kb.state.empty" : "plan.kb.state.inProcess") }));
      setCode("");
      onScanned();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="card card-body pl-scan"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="field">
        <label htmlFor="kb-scan">{t("plan.kb.label.scan")}</label>
        <div className="row" style={{ gap: 8 }}>
          <input id="kb-scan" className="input mono" value={code} onChange={(e) => setCode(e.target.value)} placeholder="KB:…" autoComplete="off" data-testid="kb-scan" />
          <button type="submit" className="btn" disabled={busy || !code.trim()}>
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="barcode" />} {t("plan.kb.btn.scan")}
          </button>
        </div>
        <span className="hint">{t("plan.kb.hint.scan")}</span>
      </div>
      <MfgError error={err} />
    </form>
  );
}

function LoopPanel({ loopId, canEdit, onEdit }: { loopId: string; canEdit: boolean; onEdit(l: KanbanLoop): void }) {
  const loop = useLoad((s) => getKanbanLoop(loopId, s), [loopId]);
  const cards = useLoad((s) => listKanbanCards(loopId, s), [loopId]);
  const l = loop.data;
  if (loop.error && !l) return <MfgError error={loop.error} onRetry={loop.reload} />;
  if (!l) return <div className="card card-body"><Spinner /></div>;
  return (
    <div className="col pl-gap" data-testid="kb-panel">
      <section className="card">
        <div className="card-header pl-card-header">
          <h2 className="pl-h2">
            <span className="mono">{l.number}</span> {l.item ? <span className="muted">{`${l.item.part_number} ${l.item.name}`}</span> : null}
          </h2>
          <span className="row" style={{ gap: 6 }}>
            <Link className="btn sm" to={mfgPaths.kanbanCards(l.id)} target="_blank" data-testid="kb-print">
              <Icon name="file" /> {t("plan.kb.btn.print")}
            </Link>
            {canEdit ? (
              <button type="button" className="btn sm" onClick={() => onEdit(l)} data-testid="kb-edit">
                <Icon name="settings" /> {t("plan.kb.btn.edit")}
              </button>
            ) : null}
          </span>
        </div>
        <div className="card-body col pl-gap">
          <Facts
            rows={[
              [t("plan.kb.head.source"), sourceText(l)],
              [t("plan.kb.head.location"), l.location_code ?? "–"],
              [t("plan.kb.head.container"), num(l.container_qty)],
              [t("plan.kb.head.lt"), t("plan.tpl.days", { n: l.lead_time_days })],
              [t("plan.kb.head.trigger"), l.trigger === "scan" ? t("plan.kb.trigger.scan") : t("plan.kb.trigger.consumption")],
              [t("plan.kb.fact.daily"), num(l.sizing.daily_demand ?? null, 1)],
              [t("plan.kb.head.sizing"), <Sizing key="s" l={l} />],
              ...(l.trigger === "consumption" ? ([[t("plan.kb.fact.consumed"), num(l.consumed_since_signal)]] as [string, string][]) : []),
            ]}
          />
          {l.sizing.undersized ? (
            <p className="pl-note" style={{ margin: 0 }}>
              <Icon name="alert" size={14} /> {t("plan.kb.text.undersized", { n: l.cards, m: l.sizing.suggested_cards ?? 0 })}
            </p>
          ) : null}
        </div>
      </section>
      <section className="card card-table" aria-label={t("plan.kb.cards.title")}>
        <div className="card-header pl-card-header">
          <h3>{t("plan.kb.cards.title")}</h3>
          <CardStates l={l} />
        </div>
        <MfgError error={cards.error} onRetry={cards.reload} />
        <DataTable<KanbanCard>
          rows={cards.data?.items ?? []}
          rowKey={(c) => c.id}
          label={t("plan.kb.cards.title")}
          testId="kb-cards"
          loading={cards.loading && !cards.data}
          columnSettings={false}
          empty={t("plan.kb.cards.empty")}
          columns={[
            { key: "no", header: t("plan.kb.cards.no"), width: "70px", align: "right", render: (c) => <span className="pl-num">{c.card_no}</span> },
            { key: "status", header: t("plan.kb.head.status"), width: "130px", render: (c) => <CardChip s={c.state} /> },
            { key: "signal", header: t("plan.kb.cards.signal"), width: "minmax(120px, 1fr)", render: (c) => (c.doc_number ? <DocLink c={c} /> : <span className="muted">–</span>) },
            { key: "changed", header: t("plan.kb.cards.changed"), width: "150px", render: (c) => formatDateTime(c.changed_at) },
          ]}
        />
      </section>
    </div>
  );
}

function DocLink({ c }: { c: KanbanCard }) {
  if (!c.doc_id) return <span className="mono">{c.doc_number}</span>;
  const to = c.doc_type === "pr" ? `/mfg/purchasing/requests/${encodeURIComponent(c.doc_id)}` : mfgPaths.workOrder(c.doc_id);
  return (
    <Link to={to} className="mono">
      {c.doc_number}
    </Link>
  );
}

function LoopDialog({ loop, onClose, onSaved }: { loop: KanbanLoop | null; onClose(): void; onSaved(l: KanbanLoop): void }) {
  const reason = useChangeReason();
  const [f, setF] = useState<KanbanLoopInput>(
    loop
      ? { item_id: loop.item_id, location_id: loop.location_id, source: loop.source, supplier_id: loop.supplier_id, line_id: loop.line_id, cards: loop.cards, container_qty: loop.container_qty, lead_time_days: loop.lead_time_days, trigger: loop.trigger, status: loop.status }
      : { item_id: "", location_id: "", source: "buy", supplier_id: null, line_id: null, cards: 3, container_qty: 0, lead_time_days: 5, trigger: "scan", status: "active" },
  );
  const [item, setItem] = useState<ItemRef | null>(loop?.item ? ({ id: loop.item.id, part_number: loop.item.part_number, description: loop.item.name, revision: loop.item.revision ?? "", uom: "", make_buy: "buy", active: true } as ItemRef) : null);
  const locs = useLoad((s) => listLocations({ active: true }, s), []);
  const sups = useLoad((s) => (f.source === "buy" ? listSuppliers({ active: true }, s) : null), [f.source]);
  const lines = useLoad((s) => (f.source === "make" ? listLines({ active: true }, s) : null), [f.source]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const set = (x: Partial<KanbanLoopInput>) => setF({ ...f, ...x });
  const valid = f.item_id && f.location_id && f.cards >= 1 && f.container_qty > 0 && f.lead_time_days >= 0;
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      let saved: KanbanLoop;
      if (loop) {
        const r = await reason.ask(t("plan.kb.what", { n: loop.number }));
        if (r === null) return;
        saved = await updateKanbanLoop(loop.id, f, loop.row_version, r);
      } else saved = await createKanbanLoop(f);
      toast(loop ? t("plan.kb.toast.saved", { n: saved.number }) : t("plan.kb.toast.created", { n: saved.number }));
      onSaved(saved);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={loop ? t("plan.kb.dlg.editTitle", { n: loop.number }) : t("plan.kb.dlg.newTitle")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!valid || busy} onClick={() => void save()} data-testid="kb-save">
            {busy ? <span className="spinner" aria-hidden /> : null} {t("plan.kb.btn.save")}
          </button>
        </>
      }
    >
      <FormErrors error={err}>
        <div className="col pl-gap">
          <MfgError error={err} />
          <ItemPicker label={t("plan.fc.head.item")} value={item} disabled={Boolean(loop)} onChange={(it) => {
            setItem(it);
            set({ item_id: it.id });
          }} testId="kb-item" />
          <div className="pl-form-grid">
            <div className="field">
              <label htmlFor="kb-loc">{t("plan.kb.head.location")}</label>
              <select id="kb-loc" name="location_id" className="select" value={f.location_id} onChange={(e) => set({ location_id: e.target.value })} data-testid="kb-location">
                <option value="">{t("plan.kb.ph.choose")}</option>
                {(locs.data?.items ?? []).map((l) => (
                  <option key={l.id} value={l.id}>{`${l.code} ${l.name}`}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <span className="field-label" id="kb-src-l">{t("plan.kb.head.source")}</span>
              <div className="btn-group" role="group" aria-labelledby="kb-src-l">
                <button type="button" className="btn" aria-pressed={f.source === "buy"} onClick={() => set({ source: "buy", line_id: null })}>
                  {t("plan.kb.source.buy")}
                </button>
                <button type="button" className="btn" aria-pressed={f.source === "make"} onClick={() => set({ source: "make", supplier_id: null })}>
                  {t("plan.kb.source.make")}
                </button>
              </div>
            </div>
            {f.source === "buy" ? (
              <div className="field">
                <label htmlFor="kb-sup">{t("plan.kb.label.supplier")}</label>
                <select id="kb-sup" name="supplier_id" className="select" value={f.supplier_id ?? ""} onChange={(e) => set({ supplier_id: e.target.value || null })}>
                  <option value="">{t("plan.kb.ph.preferred")}</option>
                  {(sups.data?.items ?? []).map((s) => (
                    <option key={s.id} value={s.id}>{`${s.code} ${s.name}`}</option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="field">
                <label htmlFor="kb-line">{t("plan.kb.label.line")}</label>
                <select id="kb-line" name="line_id" className="select" value={f.line_id ?? ""} onChange={(e) => set({ line_id: e.target.value || null })}>
                  <option value="">{t("plan.kb.ph.routing")}</option>
                  {(lines.data?.items ?? []).map((l) => (
                    <option key={l.id} value={l.id}>{`${l.code} ${l.name}`}</option>
                  ))}
                </select>
              </div>
            )}
            <div className="field">
              <label htmlFor="kb-cards">{t("plan.kb.head.cards")}</label>
              <input id="kb-cards" name="cards" className="input" type="number" min={1} step={1} value={f.cards} onChange={(e) => set({ cards: Number(e.target.value) })} data-testid="kb-cards-n" />
              {loop?.sizing.suggested_cards ? <span className="hint">{t("plan.kb.tpl.suggestHint", { n: loop.sizing.suggested_cards })}</span> : null}
            </div>
            <div className="field">
              <label htmlFor="kb-cont">{t("plan.kb.head.container")}</label>
              <input id="kb-cont" name="container_qty" className="input" type="number" min={0} step="any" value={f.container_qty || ""} onChange={(e) => set({ container_qty: Number(e.target.value) })} data-testid="kb-container" />
            </div>
            <div className="field">
              <label htmlFor="kb-lt">{t("plan.kb.label.lt")}</label>
              <input id="kb-lt" name="lead_time_days" className="input" type="number" min={0} step={1} value={f.lead_time_days} onChange={(e) => set({ lead_time_days: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label htmlFor="kb-trig">{t("plan.kb.head.trigger")}</label>
              <select id="kb-trig" className="select" value={f.trigger} onChange={(e) => set({ trigger: e.target.value as KanbanLoopInput["trigger"] })}>
                <option value="scan">{t("plan.kb.trigger.scan")}</option>
                <option value="consumption">{t("plan.kb.trigger.consumption")}</option>
              </select>
            </div>
            {loop ? (
              <div className="field">
                <label htmlFor="kb-status">{t("plan.kb.head.status")}</label>
                <select id="kb-status" className="select" value={f.status} onChange={(e) => set({ status: e.target.value as KanbanLoopInput["status"] })}>
                  <option value="active">{t("plan.kb.status.active")}</option>
                  <option value="inactive">{t("plan.kb.status.inactive")}</option>
                </select>
              </div>
            ) : null}
          </div>
          <p className="muted small" style={{ margin: 0 }}>{t("plan.kb.hint.sizing")}</p>
        </div>
      </FormErrors>
      {reason.dialog}
    </Dialog>
  );
}

/** Printable card sheet: one card per kanban card with the `KB:` QR code, item, location, container quantity. */
export function KanbanCardsPrint() {
  const { loopId = "" } = useParams();
  const loop = useLoad((s) => getKanbanLoop(loopId, s), [loopId]);
  const cards = useLoad((s) => listKanbanCards(loopId, s), [loopId]);
  const l = loop.data;
  useEffect(() => {
    if (l) document.title = t("plan.kb.print.docTitle", { n: l.number });
  }, [l]);
  if (loop.error || cards.error) return <MfgError error={loop.error ?? cards.error} />;
  if (!l || !cards.data) return <Spinner />;
  return (
    <div className="pl-print" data-testid="kb-print-sheet">
      <div className="row between no-print" style={{ marginBottom: 12 }}>
        <span className="muted">{t("plan.kb.print.hint", { n: plural(cards.data.items.length, t("plan.noun.card"), t("plan.noun.cards")) })}</span>
        <button type="button" className="btn primary" onClick={() => window.print()}>
          <Icon name="file" /> {t("plan.kb.btn.printNow")}
        </button>
      </div>
      <div className="pl-print-grid">
        {cards.data.items.map((c) => (
          <article key={c.id} className="pl-kcard" data-testid="kb-print-card">
            <QrCode text={c.code} size={112} label={t("plan.kb.print.qr", { n: c.card_no })} />
            <div className="pl-kcard-body">
              <div className="pl-kcard-part mono">{l.item?.part_number ?? ""}</div>
              <div className="small">{l.item?.name ?? ""}</div>
              <dl>
                <dt>{t("plan.kb.head.container")}</dt>
                <dd>{formatNumber(l.container_qty)}</dd>
                <dt>{t("plan.kb.head.location")}</dt>
                <dd className="mono">{l.location_code ?? ""}</dd>
                <dt>{t("plan.kb.head.source")}</dt>
                <dd>{sourceText(l)}</dd>
              </dl>
              <div className="pl-kcard-foot">
                <span className="mono">{l.number}</span>
                <span>{t("common.nOfM", { n: c.card_no, m: l.cards })}</span>
              </div>
              <div className="mono small muted pl-kcard-code">{c.code}</div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

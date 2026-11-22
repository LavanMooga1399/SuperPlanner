/**
 * `/mfg/floor/events` (M4 12, #204): the append-only floor event log with filters. Supervisors correct an event
 * (a `correct` event that references it and replaces its quantities; the original stays visible) or reopen a
 * completed operation (reverses its automatic postings). Nothing is ever edited in place (decision 1).
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { listLines } from "../../api/client";
import { listFloorEvents, postFloorEvent } from "../../api/clientM4";
import type { FloorEventRecord, FloorEventType } from "../../api/typesM4";
import { MfgError } from "../../components/Feedback";
import { DataTable, ShowMore } from "../../components/DataTable";
import type { Column } from "../../components/VirtualTable";
import { EVENT_LABEL, floorErrorText, fmtQty, humanCode } from "../../floor/floorText";
import { newClientEventId } from "../../floor/offlineQueue";
import { usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { FilterBar } from "../../../components/FilterBar";
import { DateInput } from "../../../components/DateInput";
import { t } from "../../../lib/i18n";

const TYPES = Object.keys(EVENT_LABEL) as FloorEventType[];

export function FloorEvents() {
  const clock = usePlantClock();
  const canSupervise = useCan("floor_supervise");
  const [params, setParams] = useSearchParams();
  const line = params.get("line") ?? "";
  const type = params.get("type") ?? "";
  const wo = params.get("wo") ?? "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  const lines = useLoad((signal) => listLines({}, signal), []);
  const data = usePaged<FloorEventRecord>(
    (offset, limit, signal) =>
      listFloorEvents({ line_id: line || undefined, type: type || undefined, wo_id: wo || undefined, from: from ? clock.fromLocal(`${from}T00:00`) : undefined, to: to ? clock.fromLocal(`${to}T23:59`) : undefined, limit, offset }, signal),
    [line, type, wo, from, to],
  );
  const [correcting, setCorrecting] = useState<FloorEventRecord | null>(null);
  const [reopening, setReopening] = useState<FloorEventRecord | null>(null);

  const columns: Column<FloorEventRecord>[] = [
    {
      key: "when",
      header: "When",
      width: "176px",
      wrap: true,
      exportValue: (e) => e.event_at,
      render: (e) => (
        <span>
          {clock.dateTime(e.event_at)}
          {Math.abs(Date.parse(e.recorded_at) - Date.parse(e.event_at)) > 5 * 60000 ? <span className="vt-sub">recorded {clock.dateTime(e.recorded_at)}</span> : null}
        </span>
      ),
    },
    {
      key: "wo",
      header: "Work order / step",
      width: "160px",
      exportValue: (e) => `${e.wo_number ?? e.wo_id}${e.op_seq ? ` / ${e.op_seq}` : ""}`,
      render: (e) => (
        <span>
          <Link to={mfgPaths.workOrder(e.wo_id)} className="mono">
            {e.wo_number ?? e.wo_id}
          </Link>
          {e.op_seq ? ` / ${e.op_seq}` : ""}
        </span>
      ),
    },
    {
      key: "event",
      header: "Event",
      width: "minmax(200px, 1.5fr)",
      wrap: true,
      exportValue: (e) => EVENT_LABEL[e.event_type] ?? e.event_type,
      render: (e) => (
        <span>
          {EVENT_LABEL[e.event_type] ?? e.event_type}
          {e.corrects_event_id ? <span className="faint small"> · corrects an earlier event</span> : null}
          {e.corrected ? (
            <span className="small">
              {" "}
              · <Icon name="refresh" size={12} /> {t("mfg.floorEvents.btn.correctedLater")}
            </span>
          ) : null}
          {e.reason_code ? <span className="faint small"> · reason: {humanCode(e.reason_code)}</span> : null}
          {e.note ? <span className="faint small"> · {e.note}</span> : null}
        </span>
      ),
    },
    {
      key: "qty",
      header: "Quantities",
      width: "minmax(150px, 1fr)",
      wrap: true,
      render: (e) =>
        [
          e.qty_good !== null ? `${fmtQty(e.qty_good)} good` : "",
          e.qty_scrap ? `${fmtQty(e.qty_scrap)} scrap` : "",
          e.qty_rework ? `${fmtQty(e.qty_rework)} rework${e.rework_to_seq ? ` to ${e.rework_to_seq}` : ""}` : "",
          e.serials?.produced?.length ? `${e.serials.produced.length} serials` : "",
        ]
          .filter(Boolean)
          .join(" · "),
    },
    { key: "line", header: "Line", width: "90px", render: (e) => e.line?.code ?? "" },
    {
      key: "who",
      header: "Who",
      width: "minmax(150px, 1fr)",
      wrap: true,
      exportValue: (e) => e.operators.map((o) => o.name || o.code).join(", "),
      render: (e) =>
        [
          e.operators.map((o) => o.name || o.code).join(", "),
          e.actor?.name && !e.operators.some((o) => o.name === e.actor?.name) ? `by ${e.actor.name}` : "",
          e.forced ? `forced: ${e.forced.reason}` : "",
        ]
          .filter(Boolean)
          .join(" · "),
    },
  ];
  if (canSupervise)
    columns.push({
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      label: "Actions",
      width: "150px",
      exportValue: () => "",
      render: (e) => (
        <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
          {!e.corrected && ["report", "complete", "correct"].includes(e.event_type) ? (
            <button type="button" className="btn sm" onClick={() => setCorrecting(e)} data-testid="event-correct">
              {t("mfg.floorEvents.btn.correct")}
            </button>
          ) : null}
          {e.event_type === "complete" && !e.corrected ? (
            <button type="button" className="btn sm ghost" onClick={() => setReopening(e)} data-testid="event-reopen">
              {t("mfg.floorEvents.btn.reopen")}
            </button>
          ) : null}
        </span>
      ),
    });
  return (
    <div className="col gap-lg" data-testid="floor-events">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{t("mfg.floorEvents.head.floorEventLog")}</h1>
        <Link className="btn" to={mfgPaths.floorOverview()}>
          {t("mfg.floorEvents.btn.shopFloorOverview")}
        </Link>
      </div>
      <FilterBar pageKey="FloorEvents">
        <div className="field">
          <label htmlFor="fe-line">{t("mfg.floorEvents.label.line")}</label>
          <select id="fe-line" className="select" value={line} onChange={(e) => set("line", e.target.value)}>
            <option value="">All lines</option>
            {(lines.data?.items ?? []).map((l) => (
              <option key={l.id} value={l.id}>
                {l.code}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="fe-type">{t("mfg.floorEvents.label.event")}</label>
          <select id="fe-type" className="select" value={type} onChange={(e) => set("type", e.target.value)}>
            <option value="">All events</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {EVENT_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="fe-from">{t("mfg.floorEvents.label.from")}</label>
          <DateInput id="fe-from" value={from} onChange={(v) => set("from", v)} />
        </div>
        <div className="field">
          <label htmlFor="fe-to">{t("mfg.floorEvents.label.to")}</label>
          <DateInput id="fe-to" value={to} onChange={(v) => set("to", v)} />
        </div>
        {wo ? (
          <button type="button" className="btn ghost" style={{ alignSelf: "flex-end" }} onClick={() => set("wo", "")}>
            <Icon name="x" /> {t("mfg.floorEvents.btn.workOrderFilter")}
          </button>
        ) : null}
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <DataTable
        rows={data.rows}
        columns={columns}
        rowKey={(e) => e.id}
        label={t("mfg.floorEvents.label.shopFloorEvents")}
        testId="floor-event-table"
        totalCount={data.total}
        loading={data.loading}
        exportName="floor-events"
        rowExtras={(e) => ({ testId: "floor-event-row", data: { type: e.event_type }, className: e.corrected ? "faint" : undefined })}
        empty={t("mfg.floorEvents.empty.noEventsInThisPeriod")}
        footer={<ShowMore shown={data.rows.length} total={data.total} noun="events" loading={data.loading} onMore={data.onEndReached} />}
        card={{ title: "wo", status: "event", actions: "actions", fields: ["when", "qty", "who"] }}
      />
      {correcting ? (
        <CorrectDialog
          ev={correcting}
          onClose={() => setCorrecting(null)}
          onDone={() => {
            setCorrecting(null);
            data.reload();
          }}
        />
      ) : null}
      {reopening ? (
        <ReasonDialog
          title="Reopen this operation?"
          text="Its completion postings (receipt, backflush) are reversed and the operation goes back to paused."
          confirm="Reopen"
          onClose={() => setReopening(null)}
          onConfirm={async (reason) => {
            await postFloorEvent({ client_event_id: newClientEventId(), wo_operation_id: reopening.wo_operation_id, event_type: "reopen", note: reason, reason_code: "supervisor" });
            setReopening(null);
            data.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function CorrectDialog({ ev, onClose, onDone }: { ev: FloorEventRecord; onClose(): void; onDone(): void }) {
  const [good, setGood] = useState(String(ev.qty_good ?? ""));
  const [scrap, setScrap] = useState(String(ev.qty_scrap ?? ""));
  const [rework, setRework] = useState(String(ev.qty_rework ?? ""));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      await postFloorEvent({
        client_event_id: newClientEventId(),
        wo_operation_id: ev.wo_operation_id,
        event_type: "correct",
        corrects_event_id: ev.id,
        qty_good: Number(good) || 0,
        qty_scrap: Number(scrap) || 0,
        qty_rework: Number(rework) || 0,
        note,
      });
      onDone();
    } catch (e) {
      setError(floorErrorText(e));
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("mfg.floorEvents.title.correctTheEvent")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t("mfg.floorEvents.btn.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={busy || !note.trim()} onClick={() => void go()} data-testid="correct-submit">
            {t("mfg.floorEvents.btn.recordCorrection")}
          </button>
        </>
      }
    >
      <p className="muted" style={{ marginTop: 0 }}>
        The original event stays in the log; the correction replaces its quantities. Stock postings follow.
      </p>
      <div className="grid-3">
        <div className="field">
          <label htmlFor="cr-good">{t("mfg.floorEvents.label.good")}</label>
          <input id="cr-good" className="input" inputMode="decimal" value={good} onChange={(e) => setGood(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="cr-scrap">{t("mfg.floorEvents.label.scrap")}</label>
          <input id="cr-scrap" className="input" inputMode="decimal" value={scrap} onChange={(e) => setScrap(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="cr-rework">{t("mfg.floorEvents.label.rework")}</label>
          <input id="cr-rework" className="input" inputMode="decimal" value={rework} onChange={(e) => setRework(e.target.value)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="cr-note">{t("mfg.floorEvents.label.whyRequired")}</label>
        <input id="cr-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </div>
      {error ? <div className="banner danger">{error}</div> : null}
    </Dialog>
  );
}

export function ReasonDialog({ title, text, confirm, onClose, onConfirm }: { title: string; text: string; confirm: string; onClose(): void; onConfirm(reason: string): Promise<void> }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t("mfg.floorEvents.btn.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !reason.trim()}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm(reason.trim());
              } catch (e) {
                setError(floorErrorText(e));
                setBusy(false);
              }
            }}
            data-testid="reason-confirm"
          >
            {confirm}
          </button>
        </>
      }
    >
      <p style={{ marginTop: 0 }}>{text}</p>
      <div className="field">
        <label htmlFor="rd-reason">{t("mfg.floorEvents.label.reasonRequired")}</label>
        <input id="rd-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
      </div>
      {error ? <div className="banner danger">{error}</div> : null}
    </Dialog>
  );
}

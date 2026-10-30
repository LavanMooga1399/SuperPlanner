/**
 * Dispatch list (M3 12, 9.3) per line, day and shift: the operations in order with start/end, work order, item,
 * qty, setup from/to family, crew, tools, predecessor and material status, and "Done" (marks the WO operation
 * finished, `wo_edit`). Print view hides the app chrome. Store keepers and viewers can read it.
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { listLines } from "../../api/client";
import { getDispatch, setWoOperationDone } from "../../api/clientM3";
import type { DispatchRow } from "../../api/typesM3";
import { MfgError, Spinner } from "../../components/Feedback";
import { addDays, fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { setSearchParam } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { useApsRun } from "./ApsRunShell";

const MATERIAL: Record<string, { label: string; tone: string; icon: "check" | "alert" | "help" }> = {
  kitted: { label: "kit complete", tone: "ok", icon: "check" },
  available: { label: "material available", tone: "ok", icon: "check" },
  short: { label: "material short", tone: "danger", icon: "alert" },
  expected: { label: "material expected in time", tone: "info", icon: "help" },
  unknown: { label: "material not checked", tone: "warn", icon: "help" },
};

const PRED: Record<string, { label: string; tone: string }> = {
  done: { label: "previous step done", tone: "ok" },
  scheduled_before: { label: "previous step planned earlier", tone: "info" },
  not_started: { label: "previous step not started", tone: "warn" },
  none: { label: "first step", tone: "info" },
};

export function ApsDispatchTab() {
  const { run } = useApsRun();
  const clock = usePlantClock();
  const canDone = useCan("wo_edit");
  const [params, setParams] = useSearchParams();
  const lines = useLoad((signal) => listLines({ active: true }, signal), []);
  const lineId = params.get("line") ?? "";
  const date = params.get("date") ?? clock.day(run.as_of);
  const shift = params.get("shift") ?? "";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => {
    if (!lineId && lines.data?.items.length) set("line", lines.data.items[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines.data, lineId]);
  const disp = useLoad((signal) => (lineId ? getDispatch(run.id, { line_id: lineId, date, shift: shift || undefined }, signal) : null), [run.id, lineId, date, shift]);
  const [busyOp, setBusyOp] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [doneOps, setDoneOps] = useState<Set<number>>(new Set());
  const d = disp.data;
  const lineCode = (lines.data?.items ?? []).find((l) => l.id === lineId)?.code;
  // the day's shifts on this line (base and optional); kept while one is selected so the filter can be changed back
  const [dayShifts, setDayShifts] = useState<{ label: string; start: string; end: string; kind: string }[]>([]);
  useEffect(() => {
    if (!d?.shifts) return;
    const byLabel = new Map<string, { label: string; start: string; end: string; kind: string }>();
    for (const x of d.shifts) if (x.label && !byLabel.has(x.label)) byLabel.set(x.label, { ...x, label: x.label });
    if (byLabel.size || !shift) setDayShifts([...byLabel.values()]);
  }, [d, shift]);

  const markDone = async (r: DispatchRow) => {
    if (r.order.type !== "wo" || r.wo_row_version == null) return;
    setBusyOp(r.op_no);
    setError(null);
    try {
      await setWoOperationDone(r.order.id, r.seq, true, r.wo_row_version);
      setDoneOps((s) => new Set(s).add(r.op_no));
      disp.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusyOp(null);
    }
  };

  return (
    <div className="col gap-lg" data-testid="aps-dispatch">
      <div className="toolbar mfg-filters no-print">
        <div className="field">
          <label htmlFor="dp-line">Line</label>
          <select id="dp-line" className="select" value={lineId} onChange={(e) => set("line", e.target.value)} data-testid="dispatch-line">
            {(lines.data?.items ?? []).map((l) => (
              <option key={l.id} value={l.id}>
                {l.code} · {l.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="dp-date">Day</label>
          <div className="row" style={{ gap: 4 }}>
            <button type="button" className="btn sm icon" aria-label="Previous day" onClick={() => set("date", addDays(date, -1))}>
              <Icon name="chevron-right" style={{ transform: "rotate(180deg)" }} />
            </button>
            <input id="dp-date" className="input sm" type="date" value={date} onChange={(e) => e.target.value && set("date", e.target.value)} data-testid="dispatch-date" />
            <button type="button" className="btn sm icon" aria-label="Next day" onClick={() => set("date", addDays(date, 1))}>
              <Icon name="chevron-right" />
            </button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="dp-shift">Shift</label>
          <select id="dp-shift" className="select" value={shift} onChange={(e) => set("shift", e.target.value)} data-testid="dispatch-shift">
            <option value="">Whole day</option>
            {dayShifts.map((s) => (
              <option key={s.label} value={s.label}>
                {s.label} {clock.time(s.start)}–{clock.time(s.end)}
                {s.kind === "optional" ? " (overtime)" : ""}
              </option>
            ))}
            {shift && !dayShifts.some((s) => s.label === shift) ? <option value={shift}>{shift}</option> : null}
          </select>
        </div>
        <button type="button" className="btn" style={{ alignSelf: "flex-end" }} onClick={() => window.print()} data-testid="dispatch-print">
          <Icon name="file" /> Print
        </button>
      </div>
      {!run.is_published ? (
        <Banner tone="info" title="This run is not the published plan" >
          The shop floor works from the published schedule; this list shows what this run would ask for.
        </Banner>
      ) : null}
      <MfgError error={disp.error ?? error} onRetry={disp.reload} />
      {disp.loading && !d ? <Spinner /> : null}
      {d ? (
        <section className="card">
          <div className="card-header">
            <h2>
              {d.line.code || lineCode} · {fmtDate(d.date)}
              {d.shift ? ` · ${d.shift}` : ""}
            </h2>
            <span className="muted small">
              {d.items.length} operations · times in {clock.zoneLabel}
            </span>
          </div>
          <div className="table-wrap">
            <table className="table" data-testid="dispatch-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Start</th>
                  <th>End</th>
                  <th>Work order / step</th>
                  <th>Item</th>
                  <th className="right">Qty</th>
                  <th>Changeover</th>
                  <th>Crew / tools</th>
                  <th>Ready?</th>
                  <th className="no-print">Done</th>
                </tr>
              </thead>
              <tbody>
                {d.items.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="muted">
                      Nothing planned on this line in this period.
                    </td>
                  </tr>
                ) : null}
                {d.items.map((r, i) => {
                  const done = r.done || doneOps.has(r.op_no);
                  return (
                    <tr key={r.op_no} data-testid="dispatch-row" data-op={r.op_no} data-done={done}>
                      <td className="faint">{i + 1}</td>
                      <td className="mono">{clock.time(r.start)}</td>
                      <td className="mono">{clock.time(r.end)}</td>
                      <td>
                        {r.order.type === "wo" ? (
                          <Link to={mfgPaths.workOrder(r.order.id)} className="mono">
                            {r.order.number}
                          </Link>
                        ) : (
                          <span className="mono">{r.order.number}</span>
                        )}{" "}
                        / {r.seq} {r.name}
                      </td>
                      <td>
                        <span className="mono">{r.part_number}</span>
                        {r.shift_label && !shift ? <div className="faint small">{r.shift_label}</div> : null}
                      </td>
                      <td className="right">{fmtNum(r.qty)}</td>
                      <td className="small">
                        {r.setup_minutes ? `${r.setup_from_family || "start"} → ${r.family || "-"} (${fmtDuration(r.setup_minutes)})` : "none"}
                      </td>
                      <td className="small">
                        {r.crew.length ? `${r.crew.length} operator${r.crew.length === 1 ? "" : "s"}` : "unattended"}
                        {r.tools.length ? <div className="faint">{r.tools.length} tool pool{r.tools.length === 1 ? "" : "s"} ({r.tools.map((t) => `x${t.qty}`).join(", ")})</div> : null}
                      </td>
                      <td className="small">
                        <span className={`badge ${PRED[r.predecessor_status]?.tone ?? "info"}`}>{PRED[r.predecessor_status]?.label ?? r.predecessor_status}</span>
                        {r.material_status ? (
                          <span className={`badge ${MATERIAL[r.material_status]?.tone ?? "info"}`} data-testid="dispatch-material" data-status={r.material_status}>
                            <Icon name={MATERIAL[r.material_status]?.icon ?? "help"} /> {MATERIAL[r.material_status]?.label ?? r.material_status.replace(/_/g, " ")}
                          </span>
                        ) : null}
                      </td>
                      <td className="no-print">
                        {done ? (
                          <span className="badge ok">
                            <Icon name="check" /> Done
                          </span>
                        ) : canDone && r.order.type === "wo" && r.wo_row_version != null ? (
                          <button type="button" className="btn sm" onClick={() => void markDone(r)} disabled={busyOp === r.op_no} data-testid="op-done">
                            {busyOp === r.op_no ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Done
                          </button>
                        ) : (
                          <span className="faint small">{r.order.type === "planned" ? "planned order" : ""}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="print-only small">
            Printed {new Date().toLocaleString()} · schedule #{run.run_no}
            {run.is_published ? " (published)" : ""} · <span>{mfgPaths.apsDispatch(run.id)}</span>
          </p>
        </section>
      ) : null}
    </div>
  );
}

/**
 * `/mfg/schedule/runs/:runId/gantt?view=line|order|demand&group=&line=&order=&from=&to=&op=` (M3 12): canvas Gantt
 * with view switch, stage filter, date range and zoom; the selected operation's details (start reason, release,
 * crew, tools) with lock/unlock; drag edits with a preview and "Apply" -> child run (6.7). A refused edit (422
 * `APS_EDIT_INFEASIBLE`) lists the validator's violations next to the preview; a frozen operation needs "move it
 * anyway" (`override_freeze`).
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ApiError } from "../../../api/client";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { listGroups } from "../../api/client";
import { editApsRun, getApsOperation, getGantt, listApsOperations } from "../../api/clientM3";
import { lineIdOfRow, type GanttView, type OpDetail, type ScheduleEdit, type Violation } from "../../api/typesM3";
import { MfgError, Spinner } from "../../components/Feedback";
import { ProdGantt, ZOOMS, type DropProposal } from "../../components/ProdGantt";
import { addDays, fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { setSearchParam } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { useApsRun } from "./ApsRunShell";

const VIEWS: { key: GanttView; label: string }[] = [
  { key: "line", label: "By line" },
  { key: "order", label: "By order" },
  { key: "demand", label: "By demand order" },
];

export function ApsGanttTab() {
  const { run } = useApsRun();
  const clock = usePlantClock();
  const navigate = useNavigate();
  const canRun = useCan("schedule_run");
  const canEdit = canRun && run.status === "completed";
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") ?? "line") as GanttView;
  const group = params.get("group") ?? "";
  const line = params.get("line") ?? "";
  const order = params.get("order") ?? "";
  const asOfDay = clock.day(run.as_of);
  const fromDay = params.get("from") ?? asOfDay;
  const toDay = params.get("to") ?? addDays(fromDay, 14);
  const opParam = params.get("op");
  const [zoom, setZoom] = useState(3);
  const [selected, setSelected] = useState<number | null>(opParam ? Number(opParam) : null);
  const [preview, setPreview] = useState<DropProposal | null>(null);
  const [asOrder, setAsOrder] = useState(false);
  const [override, setOverride] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [violations, setViolations] = useState<Violation[] | null>(null);
  const reasons = useRef(new Map<number, string>());
  const [, setReasonTick] = useState(0);
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);

  const fromIso = clock.fromLocal(`${fromDay}T00:00`);
  const toIso = clock.fromLocal(`${toDay}T00:00`);
  const gantt = useLoad(
    (signal) => getGantt(run.id, { view, from: fromIso, to: toIso, group_id: group || undefined, line_id: line || undefined, order_id: order || undefined }, signal),
    [run.id, view, fromIso, toIso, group, line, order],
  );
  const groups = useLoad((signal) => listGroups({}, signal), []);
  // an empty window (e.g. the work starts after the default 14 days): find the next scheduled operation to jump to
  const emptyWindow = Boolean(gantt.data && gantt.data.bars.length === 0);
  const next = useLoad(
    (signal) =>
      emptyWindow
        ? listApsOperations(run.id, { status: "scheduled", sort: "start", limit: 1, offset: 0, group_id: group || undefined, line_id: line || undefined, order_id: order || undefined }, signal)
        : null,
    [run.id, emptyWindow, group, line, order],
  );
  const firstOp = next.data?.items.find((x) => Boolean(x.start)) ?? null;
  const firstStart = firstOp?.start ?? "";
  const detail = useLoad((signal) => (selected !== null ? getApsOperation(run.id, selected, signal) : null), [run.id, selected]);

  const onHover = useCallback(
    (opNo: number | null) => {
      if (opNo === null || reasons.current.has(opNo)) return;
      reasons.current.set(opNo, "");
      getApsOperation(run.id, opNo).then(
        (d) => {
          reasons.current.set(opNo, d.reason?.text || d.reason?.code || "");
          setReasonTick((t) => t + 1);
        },
        () => reasons.current.delete(opNo),
      );
    },
    [run.id],
  );
  const reasonOf = useCallback((opNo: number) => reasons.current.get(opNo) || null, []);

  const onDrop = useCallback((p: DropProposal) => {
    setPreview(p);
    setAsOrder(p.sameRow);
    setOverride(false);
    setViolations(null);
    setError(null);
  }, []);

  const apply = async (edits: ScheduleEdit[], keepPreview = true) => {
    setBusy(true);
    setError(null);
    setViolations(null);
    try {
      const child = await editApsRun(run.id, { edits, override_freeze: override });
      navigate(`${mfgPaths.apsGantt(child.id)}?${params.toString()}`);
    } catch (e) {
      if (e instanceof ApiError && Array.isArray(e.details.violations)) setViolations(e.details.violations as Violation[]);
      else setError(e);
      if (!keepPreview) setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const previewEdits: ScheduleEdit[] = useMemo(() => {
    if (!preview) return [];
    const lineId = lineIdOfRow(preview.row.key);
    if (preview.sameRow && asOrder && lineId) return [{ kind: "resequence", line_id: lineId, op_nos: preview.order }];
    return [{ kind: "move", op_no: preview.bar.op_no, line_id: view === "line" ? lineId : null, start: preview.start }];
  }, [preview, asOrder, view]);

  const det = detail.data as OpDetail | null;
  const d = det?.op ?? null;
  const reason = det?.reason ?? d?.reason ?? null;
  const release = det?.release ?? d?.release ?? null;
  const nb = det?.neighbours ?? null;
  const g = gantt.data;
  const from = Date.parse(fromIso);
  const to = Date.parse(toIso);
  const frozenEditCode = error instanceof ApiError && error.code === "APS_EDIT_FROZEN";

  return (
    <div className="col gap-lg" data-testid="aps-gantt">
      <div className="toolbar mfg-filters">
        <div className="row" role="group" aria-label="Rows">
          {VIEWS.map((v) => (
            <button key={v.key} type="button" className={`btn sm${v.key === view ? " primary" : ""}`} aria-pressed={v.key === view} onClick={() => set("view", v.key === "line" ? "" : v.key)} data-testid={`gantt-view-${v.key}`}>
              {v.label}
            </button>
          ))}
        </div>
        <div className="field">
          <label htmlFor="gg-group">Stage</label>
          <select id="gg-group" className="select sm" value={group} onChange={(e) => set("group", e.target.value)} data-testid="gantt-group">
            <option value="">All stages</option>
            {(groups.data?.items ?? []).map((x) => (
              <option key={x.id} value={x.id}>
                {x.code} · {x.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="gg-from">From</label>
          <input id="gg-from" className="input sm" type="date" value={fromDay} onChange={(e) => e.target.value && set("from", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="gg-to">To</label>
          <input id="gg-to" className="input sm" type="date" value={toDay} min={addDays(fromDay, 1)} onChange={(e) => e.target.value && set("to", e.target.value)} />
        </div>
        <div className="row" role="group" aria-label="Zoom" style={{ alignSelf: "flex-end" }}>
          <button type="button" className="btn sm icon" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0, z - 1))} disabled={zoom === 0} data-testid="gantt-zoom-out">
            <Icon name="zoom-out" />
          </button>
          <span className="small muted" style={{ minWidth: 70, textAlign: "center" }}>
            {ZOOMS[zoom] >= 48 ? "hours" : ZOOMS[zoom] >= 12 ? "shifts" : ZOOMS[zoom] >= 3 ? "days" : "weeks"}
          </span>
          <button type="button" className="btn sm icon" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(ZOOMS.length - 1, z + 1))} disabled={zoom === ZOOMS.length - 1} data-testid="gantt-zoom-in">
            <Icon name="zoom-in" />
          </button>
        </div>
        {line || order ? (
          <button
            type="button"
            className="btn sm ghost"
            style={{ alignSelf: "flex-end" }}
            onClick={() =>
              setParams(
                (p) => {
                  const n = new URLSearchParams(p);
                  n.delete("line");
                  n.delete("order");
                  return n;
                },
                { replace: true },
              )
            }
          >
            <Icon name="x" /> Clear line/order filter
          </button>
        ) : null}
      </div>
      <div className="pg-legend" aria-label="Legend">
        <span>
          <span className="pg-swatch" style={{ background: "var(--bar)" }} /> scheduled
        </span>
        <span>
          <span className="pg-swatch" style={{ background: "var(--danger)", outline: "2px solid var(--danger)" }} /> late (thick outline, "!")
        </span>
        <span>
          <span className="pg-swatch" style={{ background: "var(--bar-alt)", border: "1px dashed var(--text)" }} /> frozen ("F")
        </span>
        <span>"L" locked · "1/2" split part · striped start = setup</span>
        <span>
          <span className="pg-swatch" style={{ background: "var(--shade)" }} /> shift open
        </span>
        <span>
          <span className="pg-swatch" style={{ border: "1px dashed var(--warn)" }} /> overtime suggested
        </span>
        <span>
          <span className="pg-swatch" style={{ border: "1px solid var(--warn)", background: "var(--shade)" }} /> overtime opened
        </span>
        <span>hatched = closed / absence</span>
      </div>
      {canEdit ? (
        <p className="faint small" style={{ margin: 0 }}>
          Drag a bar to another line or time to change the plan; drop it on its own line to change the order. Nothing changes until you apply; applying creates an edited copy of this run.
        </p>
      ) : !canRun ? (
        <p className="faint small" style={{ margin: 0 }}>
          {needsText("schedule_run")}
        </p>
      ) : null}
      <MfgError error={gantt.error} onRetry={gantt.reload} />
      {g?.truncated ? <Banner tone="warn" title="Only the first 5,000 operations are drawn">Narrow the dates or pick a stage.</Banner> : null}
      {gantt.loading && !g ? <Spinner label="Loading the Gantt…" /> : null}
      {g && g.bars.length === 0 ? (
        <div className="card card-body row wrap" role="status" data-testid="gantt-empty">
          <span>
            Nothing is scheduled between {fmtDate(fromDay)} and {fmtDate(toDay)}
            {firstOp ? `; the first operation starts ${clock.dateTime(firstStart)}.` : next.loading ? "." : next.data ? " (nothing is scheduled in this run for this selection)." : "."}
          </span>
          {firstOp ? (
            <button
              type="button"
              className="btn sm primary"
              onClick={() => {
                const d = clock.day(firstStart);
                setParams((p) => {
                  const q = new URLSearchParams(p);
                  q.set("from", d);
                  q.set("to", addDays(d, 14));
                  return q;
                });
              }}
              data-testid="gantt-jump-first"
            >
              Go to {fmtDate(clock.day(firstStart))}
            </button>
          ) : null}
        </div>
      ) : null}
      {g ? (
        <ProdGantt
          data={g}
          clock={clock}
          from={from}
          to={to}
          zoom={zoom}
          onZoom={setZoom}
          editable={canEdit}
          rowsAreLines={view === "line"}
          selected={selected}
          onSelect={setSelected}
          onDrop={onDrop}
          preview={preview}
          reasonOf={reasonOf}
          onHover={onHover}
        />
      ) : null}

      {preview ? (
        <section className="card mfg-inline-form" data-testid="gantt-drop-preview" aria-live="polite">
          <div className="card-header">
            <h3>Change the plan?</h3>
          </div>
          <div className="card-body col">
            <p style={{ margin: 0 }}>
              <strong>{preview.bar.label}</strong> ({preview.bar.item_part_number} x {fmtNum(preview.bar.qty)}){" "}
              {preview.sameRow && asOrder ? (
                <>is put in a new order on {preview.row.label}: the operations start at their earliest feasible times in that order.</>
              ) : (
                <>
                  moves to <strong>{preview.row.label}</strong> starting <strong>{clock.dateTime(preview.start)}</strong> and is locked there.
                </>
              )}{" "}
              The other operations are re-placed around it and the result is fully checked.
            </p>
            {preview.sameRow && lineIdOfRow(preview.row.key) ? (
              <div className="row wrap" role="radiogroup" aria-label="Meaning of the drop">
                <label className="checkbox">
                  <input type="radio" name="drop-kind" checked={asOrder} onChange={() => setAsOrder(true)} data-testid="gantt-drop-resequence" /> Change the order on this line
                </label>
                <label className="checkbox">
                  <input type="radio" name="drop-kind" checked={!asOrder} onChange={() => setAsOrder(false)} data-testid="gantt-drop-move" /> Move to exactly this time
                </label>
              </div>
            ) : null}
            {preview.bar.frozen || frozenEditCode ? (
              <label className="checkbox">
                <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} data-testid="gantt-override-freeze" /> This operation is frozen (published, starting soon): move it anyway
              </label>
            ) : null}
            {violations ? (
              <div className="banner danger" role="alert" data-testid="edit-violations">
                <Icon name="x" />
                <div className="banner-body">
                  <strong>Not possible: it would break these rules</strong>
                  <ul className="mfg-plain-list">
                    {violations.map((v, i) => (
                      <li key={i} data-code={v.code}>
                        {v.message} <code className="faint small">{v.code}</code>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : null}
            <MfgError error={error} title="The change was not applied" />
            <div className="row">
              <button type="button" className="btn primary" onClick={() => void apply(previewEdits)} disabled={busy || (preview.bar.frozen && !override)} data-testid="gantt-drop-apply">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Apply (creates an edited copy)
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setPreview(null);
                  setViolations(null);
                  setError(null);
                }}
                data-testid="gantt-drop-cancel"
              >
                Cancel
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {selected !== null && !preview ? (
        <section className="card" data-testid="gantt-op-panel" data-op={selected}>
          <div className="card-header">
            <h3>
              Operation {selected}
              {d ? ` · ${d.order.number} / ${d.seq} ${d.name}` : ""}
            </h3>
            <div className="mfg-actions">
              {d && canEdit ? (
                <button type="button" className="btn sm" onClick={() => void apply([{ kind: d.locked ? "unlock" : "lock", op_no: d.op_no }], false)} disabled={busy} data-testid="gantt-lock-toggle">
                  <Icon name={d.locked ? "unlock" : "lock"} /> {d.locked ? "Unlock" : "Lock here"}
                </button>
              ) : null}
              <button type="button" className="btn sm ghost" onClick={() => setSelected(null)} aria-label="Close details">
                <Icon name="x" />
              </button>
            </div>
          </div>
          <div className="card-body">
            <MfgError error={detail.error} />
            {d ? (
              <dl className="mfg-dl">
                <dt>Item</dt>
                <dd>
                  <span className="mono">{d.item.part_number}</span> x {fmtNum(d.qty)} {d.split.count > 1 ? `(part ${d.split.index + 1} of ${d.split.count})` : ""}
                </dd>
                <dt>Where and when</dt>
                <dd>
                  {d.line?.code ?? "not scheduled"} · {clock.dateTime(d.start)} – {clock.dateTime(d.end)} · setup {fmtDuration(d.setup_minutes) || "0"}, run {fmtDuration(d.run_minutes)}
                  {d.pieces.length > 1 ? ` · in ${d.pieces.length} pieces (pauses outside shifts)` : ""}
                </dd>
                <dt>Why it starts then</dt>
                <dd data-testid="gantt-op-reason" data-reason={reason?.code}>
                  {reason?.text}
                  {reason?.refs?.length ? (
                    <span className="faint small"> ({reason.refs.map((x) => (x.link ? <Link key={x.label} to={x.link}>{x.label} </Link> : `${x.label} `))})</span>
                  ) : null}
                </dd>
                {release?.material_at ? (
                  <>
                    <dt>Material ready</dt>
                    <dd>
                      {clock.dateTime(release.material_at)}
                      {release.refs.length ? <span className="faint small"> ({release.refs.map((x) => x.label).join(", ")})</span> : null}
                    </dd>
                  </>
                ) : null}
                <dt>Crew and tools</dt>
                <dd>
                  {d.crew.length ? `${d.crew.length} operator${d.crew.length === 1 ? "" : "s"}` : "none (unattended)"}
                  {d.tools.length ? ` · ${d.tools.length} tool pool${d.tools.length === 1 ? "" : "s"} (${d.tools.map((t) => `x${t.qty}`).join(", ")})` : ""}
                  {d.family ? ` · family ${d.family}${d.setup_from_family ? ` (changeover from ${d.setup_from_family})` : ""}` : ""}
                </dd>
                <dt>Due</dt>
                <dd>
                  {clock.dateTime(d.due)} {d.late_minutes > 0 ? <span className="badge danger">{fmtDuration(d.late_minutes)} late</span> : null}
                  {d.frozen ? <span className="badge info">Frozen</span> : null}
                  {d.locked ? <span className="badge info">Locked</span> : null}
                </dd>
                {nb ? (
                  <>
                    <dt>On the line</dt>
                    <dd className="small">
                      before: {nb.before ? `${nb.before.order.number}/${nb.before.seq}` : "nothing"} · after: {nb.after ? `${nb.after.order.number}/${nb.after.seq}` : "nothing"}
                    </dd>
                  </>
                ) : null}
              </dl>
            ) : detail.loading ? (
              <span className="muted">Loading…</span>
            ) : null}
            {d ? (
              <div className="row" style={{ marginTop: 8 }}>
                {d.order.type === "wo" ? (
                  <Link className="btn sm" to={mfgPaths.workOrder(d.order.id)}>
                    Work order {d.order.number}
                  </Link>
                ) : null}
                {d.line && d.start ? (
                  <Link className="btn sm" to={mfgPaths.apsDispatch(run.id, { line: d.line.id, date: clock.day(d.start) })}>
                    Dispatch list {d.line.code} {fmtDate(clock.day(d.start))}
                  </Link>
                ) : null}
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

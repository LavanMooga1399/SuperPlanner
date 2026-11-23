/**
 * Operations table of a routing (M 11.2): HTML5 drag handle **and** "Move up/down" buttons (keyboard), inline
 * edit, add/remove; reordering renumbers 10, 20, ... and warns when BOM lines reference operation numbers.
 * Advanced fields of an operation open in a detail row ("More").
 */
import { LineRates } from "./LineRates";
import { Fragment, useEffect, useRef, useState, type DragEvent } from "react";
import { Icon } from "../../components/Icon";
import type { GroupRecord, Labor, OperationRecord, RunPer, SkillRecord, ToolPoolRecord } from "../api/types";
import { t as tr } from "../../lib/i18n";

export interface OpDraft {
  key: string;
  id: string | null;
  seq: number;
  name: string;
  description: string;
  group_id: string;
  setup_minutes: string;
  run_minutes: string;
  run_per: RunPer;
  units_per_panel: string;
  units_per_batch: string;
  queue_minutes: string;
  move_minutes: string;
  wait_minutes: string;
  labor: Labor;
  crew_size: string;
  skill_id: string;
  tools: { tool_pool_id: string; qty: string }[];
  transfer_batch: string;
  yield_pct: string;
  inspection_gate: boolean;
  interruptible: boolean;
  /** M4 10: serial point; undefined when the server does not know the field (not sent back) */
  capture_serial?: boolean;
}

let seqKey = 0;
const k = () => `op${++seqKey}`;
const t = (v: number | null) => (v === null ? "" : String(v));

export function opToDraft(o: OperationRecord): OpDraft {
  return {
    key: k(),
    id: o.id,
    seq: o.seq,
    name: o.name,
    description: o.description,
    group_id: o.group_id,
    setup_minutes: String(o.setup_minutes),
    run_minutes: String(o.run_minutes),
    run_per: o.run_per,
    units_per_panel: t(o.units_per_panel),
    units_per_batch: t(o.units_per_batch),
    queue_minutes: String(o.queue_minutes),
    move_minutes: String(o.move_minutes),
    wait_minutes: String(o.wait_minutes),
    labor: o.labor,
    crew_size: String(o.crew_size),
    skill_id: o.skill_id ?? "",
    tools: o.tools.map((x) => ({ tool_pool_id: x.tool_pool_id, qty: String(x.qty) })),
    transfer_batch: t(o.transfer_batch),
    yield_pct: String(o.yield_pct),
    inspection_gate: o.inspection_gate,
    interruptible: o.interruptible,
    ...("capture_serial" in o ? { capture_serial: Boolean((o as { capture_serial?: boolean }).capture_serial) } : {}),
  };
}

export function blankOp(ops: OpDraft[], groupId: string): OpDraft {
  const max = ops.reduce((m, o) => Math.max(m, o.seq), 0);
  return {
    key: k(),
    id: null,
    seq: Math.floor(max / 10) * 10 + 10,
    name: "",
    description: "",
    group_id: groupId,
    setup_minutes: "0",
    run_minutes: "0",
    run_per: "unit",
    units_per_panel: "",
    units_per_batch: "",
    queue_minutes: "0",
    move_minutes: "0",
    wait_minutes: "0",
    labor: "attended",
    crew_size: "1",
    skill_id: "",
    tools: [],
    transfer_batch: "",
    yield_pct: "100",
    inspection_gate: false,
    interruptible: true,
    ...(ops.some((x) => x.capture_serial !== undefined) ? { capture_serial: false } : {}),
  };
}

export function opProblems(o: OpDraft): string[] {
  const p: string[] = [];
  if (!o.name.trim()) p.push(tr("mfg.routingEditor.str.nameIsRequired"));
  if (!o.group_id) p.push(tr("mfg.routingEditor.str.pickAStage"));
  if (o.run_per === "panel" && !(Number(o.units_per_panel) >= 1)) p.push(tr("mfg.routingEditor.str.unitsPerPanelIsRequired"));
  if (o.run_per === "batch" && !(Number(o.units_per_batch) >= 1)) p.push(tr("mfg.routingEditor.str.unitsPerBatchIsRequired"));
  const y = Number(o.yield_pct);
  if (!(y > 0 && y <= 100)) p.push(tr("mfg.routingEditor.str.yieldMustBeMoreThan"));
  if (o.labor === "attended" && Number(o.crew_size) < 1) p.push(tr("mfg.routingEditor.str.attendedWorkNeedsACrew"));
  return p;
}

/** Renumber 10, 20, 30... in the current order. */
export function renumber(ops: OpDraft[]): OpDraft[] {
  return ops.map((o, i) => ({ ...o, seq: (i + 1) * 10 }));
}

export function RoutingEditor({
  ops,
  onChange,
  readOnly,
  groups,
  skills,
  tools,
  selectedSeq,
  referencedSeqs,
}: {
  ops: OpDraft[];
  onChange(next: OpDraft[], reordered?: boolean): void;
  readOnly: boolean;
  groups: GroupRecord[];
  skills: SkillRecord[];
  tools: ToolPoolRecord[];
  selectedSeq: number | null;
  referencedSeqs: Set<number>;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [overKey, setOverKey] = useState<string | null>(null);
  const focusAfterMove = useRef<{ key: string; dir: "up" | "down" } | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  useEffect(() => {
    if (selectedSeq === null) return;
    const o = ops.find((x) => x.seq === selectedSeq);
    if (!o) return;
    setOpen((s) => new Set(s).add(o.key));
    const row = tableRef.current?.querySelector<HTMLElement>(`[data-key="${o.key}"]`);
    row?.scrollIntoView({ block: "center" });
    // only when the selection or the loaded routing changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSeq, ops.length > 0]);

  useEffect(() => {
    const f = focusAfterMove.current;
    if (!f) return;
    focusAfterMove.current = null;
    const btn = tableRef.current?.querySelector<HTMLButtonElement>(`[data-key="${f.key}"] [data-move="${f.dir}"]`);
    if (btn && !btn.disabled) btn.focus();
    else tableRef.current?.querySelector<HTMLButtonElement>(`[data-key="${f.key}"] [data-move="${f.dir === "up" ? "down" : "up"}"]`)?.focus();
  });

  const update = (i: number, patch: Partial<OpDraft>) => onChange(ops.map((o, j) => (j === i ? { ...o, ...patch } : o)));

  const move = (from: number, to: number) => {
    if (to < 0 || to >= ops.length || from === to) return;
    const next = [...ops];
    const [m] = next.splice(from, 1);
    next.splice(to, 0, m);
    onChange(renumber(next), true);
  };

  const onDrop = (e: DragEvent, toKey: string) => {
    e.preventDefault();
    const from = ops.findIndex((o) => o.key === dragKey);
    const to = ops.findIndex((o) => o.key === toKey);
    setDragKey(null);
    setOverKey(null);
    if (from >= 0 && to >= 0) move(from, to);
  };

  const num = (i: number, field: keyof OpDraft, label: string, width = 70) => (
    <input
      className="input sm"
      type="number"
      step="any"
      min={0}
      style={{ width }}
      aria-label={`${label}, operation ${ops[i].seq}`}
      value={String(ops[i][field])}
      readOnly={readOnly}
      onChange={(e) => update(i, { [field]: e.target.value })}
    />
  );

  return (
    <div className="table-wrap">
      <table className="table mfg-ops-table" ref={tableRef} data-testid="routing-ops">
        <thead>
          <tr>
            {readOnly ? null : (
              <th>
                <span className="sr-only">{tr("mfg.routingEditor.text.reorder")}</span>
              </th>
            )}
            <th>{tr("mfg.routingEditor.head.op")}</th>
            <th>{tr("mfg.routingEditor.head.name")}</th>
            <th>{tr("mfg.routingEditor.head.stage")}</th>
            <th className="num">{tr("mfg.routingEditor.head.setupMin")}</th>
            <th className="num">{tr("mfg.routingEditor.head.runMin")}</th>
            <th>{tr("mfg.routingEditor.head.per")}</th>
            <th className="num">{tr("mfg.routingEditor.head.yield")}</th>
            <th>{tr("mfg.routingEditor.head.work")}</th>
            <th>
              <span className="sr-only">{tr("mfg.routingEditor.text.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {ops.length === 0 ? (
            <tr>
              <td colSpan={10} className="muted">
                {tr("mfg.routingEditor.text.noOperationsYetAddThe")}
              </td>
            </tr>
          ) : null}
          {ops.map((o, i) => {
            const isOpen = open.has(o.key);
            const probs = opProblems(o);
            const selected = selectedSeq !== null && o.seq === selectedSeq;
            return (
              <Fragment key={o.key}>
                <tr
                  data-key={o.key}
                  data-seq={o.seq}
                  data-testid="routing-op-row"
                  className={[selected ? "mfg-selected" : "", overKey === o.key ? "mfg-drop-target" : "", probs.length ? "mfg-row-error" : ""].filter(Boolean).join(" ")}
                  aria-selected={selected || undefined}
                  title={probs.join("; ") || undefined}
                  onDragOver={(e) => {
                    if (!dragKey) return;
                    e.preventDefault();
                    setOverKey(o.key);
                  }}
                  onDragLeave={() => setOverKey((x) => (x === o.key ? null : x))}
                  onDrop={(e) => onDrop(e, o.key)}
                >
                  {readOnly ? null : (
                    <td>
                      <span
                        className="mfg-drag"
                        draggable
                        aria-hidden
                        title={tr("mfg.routingEditor.attr.dragToReorderOrUse")}
                        data-testid="op-drag-handle"
                        onDragStart={(e) => {
                          setDragKey(o.key);
                          e.dataTransfer.effectAllowed = "move";
                          e.dataTransfer.setData("text/plain", o.key);
                        }}
                        onDragEnd={() => {
                          setDragKey(null);
                          setOverKey(null);
                        }}
                      >
                        <Icon name="list" />
                      </span>
                    </td>
                  )}
                  <td className="mono">
                    {o.seq}
                    {referencedSeqs.has(o.seq) ? (
                      <span className="sr-only">{" "}{tr("mfg.routingEditor.text.bomLinesAreConsumedHere")}</span>
                    ) : null}
                    {referencedSeqs.has(o.seq) ? <span title={tr("mfg.routingEditor.attr.bomLinesAreConsumedAt")}> <Icon name="layers" size={12} /></span> : null}
                  </td>
                  <td>
                    <input className="input sm" style={{ minWidth: 140 }} aria-label={tr("mfg.routingEditor.tpl.nameOperation", { seq: o.seq })} value={o.name} readOnly={readOnly} maxLength={100} onChange={(e) => update(i, { name: e.target.value })} data-testid="op-name" />
                  </td>
                  <td>
                    <select className="select sm" aria-label={tr("mfg.routingEditor.tpl.stageOperation", { seq: o.seq })} value={o.group_id} disabled={readOnly} onChange={(e) => update(i, { group_id: e.target.value })} style={{ minWidth: 110 }}>
                      {o.group_id ? null : <option value="">{tr("mfg.routingEditor.text.pickAStage")}</option>}
                      {groups.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.code} - {g.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="num">{num(i, "setup_minutes", tr("mfg.routingEditor.str.setupMinutes"))}</td>
                  <td className="num">{num(i, "run_minutes", tr("mfg.routingEditor.str.runMinutes"))}</td>
                  <td>
                    <span className="row" style={{ gap: 4 }}>
                      <select className="select sm" aria-label={tr("mfg.routingEditor.tpl.runTimePerOperation", { seq: o.seq })} value={o.run_per} disabled={readOnly} onChange={(e) => update(i, { run_per: e.target.value as RunPer })} style={{ width: 82 }}>
                        <option value="unit">unit</option>
                        <option value="panel">panel</option>
                        <option value="batch">batch</option>
                      </select>
                      {o.run_per === "panel" ? (
                        <label className="row small" style={{ gap: 2 }}>
                          of {num(i, "units_per_panel", tr("mfg.routingEditor.str.unitsPerPanel"), 56)}
                        </label>
                      ) : null}
                      {o.run_per === "batch" ? (
                        <label className="row small" style={{ gap: 2 }}>
                          of {num(i, "units_per_batch", tr("mfg.routingEditor.str.unitsPerBatch"), 64)}
                        </label>
                      ) : null}
                    </span>
                  </td>
                  <td className="num">{num(i, "yield_pct", tr("mfg.routingEditor.str.yieldPercent"), 62)}</td>
                  <td className="small">
                    {o.labor === "unattended" ? tr("mfg.routingEditor.str.unattended") : tr("mfg.routingEditor.tpl.crew", { v: o.crew_size || 0 })}
                    {o.inspection_gate ? " · gate" : ""}
                    {!o.interruptible ? tr("mfg.routingEditor.str.noPause") : ""}
                  </td>
                  <td>
                    <span className="row nowrap" style={{ gap: 2 }}>
                      {readOnly ? null : (
                        <>
                          <button
                            type="button"
                            className="btn sm ghost icon"
                            aria-label={tr("mfg.routingEditor.tpl.moveOperationUp", { seq: o.seq })}
                            title={tr("mfg.routingEditor.attr.moveUp")}
                            disabled={i === 0}
                            data-move="up"
                            data-testid="op-move-up"
                            onClick={() => {
                              focusAfterMove.current = { key: o.key, dir: "up" };
                              move(i, i - 1);
                            }}
                          >
                            <Icon name="chevron-right" style={{ transform: "rotate(-90deg)" }} />
                          </button>
                          <button
                            type="button"
                            className="btn sm ghost icon"
                            aria-label={tr("mfg.routingEditor.tpl.moveOperationDown", { seq: o.seq })}
                            title={tr("mfg.routingEditor.attr.moveDown")}
                            disabled={i === ops.length - 1}
                            data-move="down"
                            data-testid="op-move-down"
                            onClick={() => {
                              focusAfterMove.current = { key: o.key, dir: "down" };
                              move(i, i + 1);
                            }}
                          >
                            <Icon name="chevron-down" />
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        className="btn sm ghost"
                        aria-expanded={isOpen}
                        onClick={() =>
                          setOpen((s) => {
                            const n = new Set(s);
                            if (n.has(o.key)) n.delete(o.key);
                            else n.add(o.key);
                            return n;
                          })
                        }
                        data-testid="op-more"
                      >
                        {tr("mfg.routingEditor.text.more")}
                      </button>
                      {readOnly ? null : (
                        <button type="button" className="btn sm ghost icon" aria-label={tr("mfg.routingEditor.tpl.deleteOperation", { seq: o.seq })} onClick={() => onChange(ops.filter((_, j) => j !== i))} data-testid="op-delete">
                          <Icon name="trash" />
                        </button>
                      )}
                    </span>
                  </td>
                </tr>
                {isOpen ? (
                  <tr className="expand-row">
                    <td colSpan={10}>
                      <OpDetails o={o} readOnly={readOnly} skills={skills} tools={tools} onPatch={(p) => update(i, p)} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function OpDetails({
  o,
  readOnly,
  skills,
  tools,
  onPatch,
}: {
  o: OpDraft;
  readOnly: boolean;
  skills: SkillRecord[];
  tools: ToolPoolRecord[];
  onPatch(p: Partial<OpDraft>): void;
}) {
  const id = `op-${o.key}`;
  const numField = (field: keyof OpDraft, label: string, hint?: string) => (
    <div className="field">
      <label htmlFor={`${id}-${field}`}>{label}</label>
      <input id={`${id}-${field}`} className="input sm" type="number" step="any" min={0} value={String(o[field])} readOnly={readOnly} onChange={(e) => onPatch({ [field]: e.target.value })} />
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
  return (
    <div className="col" style={{ padding: "4px 0" }} data-testid="op-details">
      <div className="form-grid">
        <div className="field">
          <label htmlFor={`${id}-labor`}>{tr("mfg.routingEditor.text.work")}</label>
          <select id={`${id}-labor`} className="select sm" value={o.labor} disabled={readOnly} onChange={(e) => onPatch({ labor: e.target.value as Labor, crew_size: e.target.value === "unattended" && o.crew_size === "1" ? "0" : o.crew_size })}>
            <option value="attended">{tr("mfg.routingEditor.text.attendedOperatorsPresent")}</option>
            <option value="unattended">{tr("mfg.routingEditor.text.unattendedMachineRunsAlone")}</option>
          </select>
        </div>
        {numField("crew_size", tr("mfg.routingEditor.str.crewSize"), tr("mfg.routingEditor.str.operatorsNeededWhileRunning"))}
        <div className="field">
          <label htmlFor={`${id}-skill`}>{tr("mfg.routingEditor.text.requiredSkill")}</label>
          <select id={`${id}-skill`} className="select sm" value={o.skill_id} disabled={readOnly} onChange={(e) => onPatch({ skill_id: e.target.value })}>
            <option value="">{tr("mfg.routingEditor.text.none")}</option>
            {skills.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} - {s.name}
              </option>
            ))}
          </select>
        </div>
        {numField("queue_minutes", tr("mfg.routingEditor.str.waitBeforeMin"), tr("mfg.routingEditor.str.queueTimeNoMachine"))}
        {numField("move_minutes", tr("mfg.routingEditor.str.moveAfterMin"))}
        {numField("wait_minutes", tr("mfg.routingEditor.str.waitAfterMin"), "e.g. cool-down")}
        {numField("transfer_batch", tr("mfg.routingEditor.str.passOnAfterUnits"), tr("mfg.routingEditor.str.emptyWhenTheWholeLot"))}
        <label className="checkbox">
          <input type="checkbox" checked={o.inspection_gate} disabled={readOnly} onChange={(e) => onPatch({ inspection_gate: e.target.checked })} />
          {tr("mfg.routingEditor.text.qualityGateInspection")}
        </label>
        {o.capture_serial !== undefined ? (
          <label className="checkbox" title={tr("mfg.routingEditor.attr.operatorsScanOrTypeOne")}>
            <input type="checkbox" checked={o.capture_serial} disabled={readOnly} onChange={(e) => onPatch({ capture_serial: e.target.checked })} data-testid="op-capture-serial" />
            {tr("mfg.routingEditor.text.captureSerialNumbersHere")}
          </label>
        ) : null}
        <label className="checkbox">
          <input type="checkbox" checked={!o.interruptible} disabled={readOnly} onChange={(e) => onPatch({ interruptible: !e.target.checked })} />
          {tr("mfg.routingEditor.text.mustNotPauseOneContinuous")}
        </label>
      </div>
      <div className="field">
        <label htmlFor={`${id}-desc`}>{tr("mfg.routingEditor.text.description")}</label>
        <input id={`${id}-desc`} className="input sm" value={o.description} maxLength={500} readOnly={readOnly} onChange={(e) => onPatch({ description: e.target.value })} />
      </div>
      <fieldset className="mfg-fieldset">
        <legend>{tr("mfg.routingEditor.head.toolingHeldDuringTheOperation")}</legend>
        {o.tools.map((tl, j) => (
          <div className="row" key={j}>
            <select
              className="select sm"
              aria-label={tr("mfg.routingEditor.tpl.tool", { v: j + 1 })}
              value={tl.tool_pool_id}
              disabled={readOnly}
              onChange={(e) => onPatch({ tools: o.tools.map((x, n) => (n === j ? { ...x, tool_pool_id: e.target.value } : x)) })}
              style={{ maxWidth: 320 }}
            >
              {tl.tool_pool_id ? null : <option value="">{tr("mfg.routingEditor.text.pickATool")}</option>}
              {tools.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} - {p.name} ({p.quantity} available)
                </option>
              ))}
            </select>
            <input
              className="input sm"
              type="number"
              min={1}
              style={{ width: 70 }}
              aria-label={tr("mfg.routingEditor.tpl.toolQuantity", { v: j + 1 })}
              value={tl.qty}
              readOnly={readOnly}
              onChange={(e) => onPatch({ tools: o.tools.map((x, n) => (n === j ? { ...x, qty: e.target.value } : x)) })}
            />
            {readOnly ? null : (
              <button type="button" className="btn sm ghost icon" aria-label={tr("mfg.routingEditor.tpl.removeTool", { v: j + 1 })} onClick={() => onPatch({ tools: o.tools.filter((_, n) => n !== j) })}>
                <Icon name="trash" />
              </button>
            )}
          </div>
        ))}
        {readOnly ? (
          o.tools.length === 0 ? <span className="muted small">{tr("mfg.routingEditor.text.none")}</span> : null
        ) : (
          <div>
            <button type="button" className="btn sm" onClick={() => onPatch({ tools: [...o.tools, { tool_pool_id: tools[0]?.id ?? "", qty: "1" }] })} disabled={tools.length === 0}>
              <Icon name="plus" /> {tr("mfg.routingEditor.btn.addTool")}
            </button>
          </div>
        )}
      </fieldset>
      <LineRates operationId={o.id} groupId={o.group_id} readOnly={readOnly} />
    </div>
  );
}

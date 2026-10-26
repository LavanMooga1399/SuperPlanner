/**
 * `/mfg/items/:itemId/routing` (`?routing=&op=`, M 11.1): routing list (priority, status, effectivity),
 * `RoutingEditor` for the selected routing (draft: editable; released/obsolete: read-only banner + Copy) and
 * `OperationTimePreview`.
 */
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import {
  copyRouting,
  createRouting,
  deleteRouting,
  getBom,
  getRouting,
  listGroups,
  listItemBoms,
  listItemRoutings,
  listSkills,
  listToolPools,
  obsoleteRouting,
  releaseRouting,
  updateRouting,
} from "../api/client";
import type { GroupRecord, OperationInput, RoutingInput, RoutingRecord, RoutingSummary, SkillRecord, ToolPoolRecord } from "../api/types";
import { ReleaseDialog } from "../components/DocumentActions";
import { EffectivityBadge } from "../components/EffectivityBadge";
import { ConflictBanner, MfgError, SaveState, Spinner } from "../components/Feedback";
import { numOrNull, TextField } from "../components/Field";
import { OperationTimePreview } from "../components/OperationTimePreview";
import { blankOp, opProblems, opToDraft, RoutingEditor, type OpDraft } from "../components/RoutingEditor";
import { StatusChip } from "../components/StatusChip";
import { isConflict, todayInOffset, useLoad, usePlant } from "../lib/useMfg";
import { useItem } from "./ItemShell";

interface RHeader {
  code: string;
  priority: string;
  revision: string;
  version: string;
  note: string;
}

function toHeader(r: RoutingRecord): RHeader {
  return { code: r.code, priority: String(r.priority), revision: r.revision, version: String(r.version), note: r.note };
}

function opInput(o: OpDraft): OperationInput {
  const n = (s: string) => numOrNull(s) ?? 0;
  return {
    ...(o.id ? { id: o.id } : {}),
    seq: o.seq,
    name: o.name.trim(),
    description: o.description,
    group_id: o.group_id,
    setup_minutes: n(o.setup_minutes),
    run_minutes: n(o.run_minutes),
    run_per: o.run_per,
    units_per_panel: o.run_per === "panel" ? numOrNull(o.units_per_panel) : null,
    units_per_batch: o.run_per === "batch" ? numOrNull(o.units_per_batch) : null,
    queue_minutes: n(o.queue_minutes),
    move_minutes: n(o.move_minutes),
    wait_minutes: n(o.wait_minutes),
    labor: o.labor,
    crew_size: n(o.crew_size),
    skill_id: o.skill_id || null,
    tools: o.tools.filter((t) => t.tool_pool_id).map((t) => ({ tool_pool_id: t.tool_pool_id, qty: numOrNull(t.qty) ?? 1 })),
    transfer_batch: numOrNull(o.transfer_batch),
    yield_pct: numOrNull(o.yield_pct) ?? 100,
    inspection_gate: o.inspection_gate,
    interruptible: o.interruptible,
  };
}

function toInput(r: RoutingRecord, h: RHeader, ops: OpDraft[]): RoutingInput {
  return {
    item_id: r.item_id,
    revision: h.revision.trim() || r.revision,
    code: h.code.trim() || r.code,
    version: numOrNull(h.version) ?? r.version,
    priority: numOrNull(h.priority) ?? r.priority,
    effective_from: r.effective_from,
    effective_to: r.effective_to,
    serial_from: r.serial_from,
    serial_to: r.serial_to,
    note: h.note,
    operations: ops.map(opInput),
  };
}

type Pending = { kind: "release" | "obsolete" | "delete"; r: RoutingSummary } | null;

export function RoutingTab() {
  const { item } = useItem();
  const [params, setParams] = useSearchParams();
  const plant = usePlant();
  const routingParam = params.get("routing");
  const opParam = params.get("op");
  const list = useLoad((signal) => (item.make_buy === "make" ? listItemRoutings(item.id, signal) : null), [item.id]);
  const groups = useLoad((signal) => listGroups({}, signal), []);
  const skills = useLoad((signal) => listSkills(signal), []);
  const tools = useLoad((signal) => listToolPools(signal), []);
  const boms = useLoad((signal) => listItemBoms(item.id, signal), [item.id]);
  const [referenced, setReferenced] = useState<Set<number>>(new Set());
  const [pending, setPending] = useState<Pending>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  /** Id of the routing whose editor has unsaved edits (reported by `RoutingDocument`). */
  const [dirtyId, setDirtyId] = useState<string | null>(null);
  const [discardFor, setDiscardFor] = useState<string | null>(null);

  const routings = list.data?.items ?? [];
  const selectedId = routingParam ?? routings.find((r) => r.status === "released" && r.priority === 1)?.id ?? routings[0]?.id ?? null;
  // Release / Copy / Obsolete / Delete reload the list and remount the editor, which would drop unsaved operation
  // edits; they are disabled until the edits are saved or undone (like Release on the BOM editor).
  const dirty = dirtyId !== null && dirtyId === selectedId;
  const selectedCode = routings.find((r) => r.id === selectedId);
  const selected = useLoad((signal) => (selectedId ? getRouting(selectedId, signal) : null), [selectedId, list.data]);

  // Operation numbers that this item's BOM lines consume at (for the reorder warning).
  useEffect(() => {
    const docs = (boms.data?.items ?? []).filter((b) => b.status !== "obsolete");
    if (!docs.length) return;
    let alive = true;
    Promise.all(docs.map((b) => getBom(b.id))).then(
      (full) => {
        if (!alive) return;
        const s = new Set<number>();
        for (const b of full) for (const l of b.lines) if (l.operation_seq !== null) s.add(l.operation_seq);
        setReferenced(s);
      },
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [boms.data]);

  const select = (id: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("routing", id);
        next.delete("op");
        return next;
      },
      { replace: true },
    );
  /** Picking another routing while the open one has unsaved edits asks first. */
  const requestSelect = (id: string) => {
    if (dirty && id !== selectedId) setDiscardFor(id);
    else select(id);
  };

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      list.reload();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
      setPending(null);
    }
  };

  if (item.make_buy !== "make")
    return (
      <Banner tone="info" title={item.make_buy === "buy" ? "Bought items have no routing" : "Phantom items have no routing"}>
        A routing lists the production steps of a make item. {item.part_number} is {item.make_buy === "buy" ? "bought" : "a phantom kit"}; change it to Make on the Details tab if it is produced here.
      </Banner>
    );

  return (
    <div className="col gap-lg">
      <section className="card" aria-labelledby="rtg-list-title">
        <div className="card-header">
          <h2 id="rtg-list-title">Routings</h2>
          <button
            type="button"
            className="btn sm primary"
            disabled={busy || dirty}
            title={dirty ? "Save or undo the changes of the open routing first" : undefined}
            onClick={() =>
              void act(async () => {
                const r = await createRouting({ item_id: item.id, operations: [] });
                select(r.id);
              })
            }
            data-testid="routing-new"
          >
            <Icon name="plus" /> New routing
          </button>
        </div>
        <MfgError error={list.error} onRetry={list.reload} />
        <MfgError error={actionError} title="The action failed" />
        {dirty ? (
          <p className="small mfg-problem-list" role="status" style={{ margin: 0, padding: "8px 16px" }} data-testid="routing-unsaved-hint">
            <Icon name="alert" size={12} /> {selectedCode ? `${selectedCode.code} v${selectedCode.version}` : "The open routing"} has unsaved changes. Save or undo
            them before releasing, copying or removing a routing.
          </p>
        ) : null}
        {routings.length === 0 && !list.loading ? <div className="card-body muted">No routing yet. Create one to describe how this item is made, step by step.</div> : null}
        <ul className="mfg-plain-list mfg-version-list">
          {routings.map((r) => (
            <li key={r.id} className={`mfg-version${r.id === selectedId ? " mfg-selected" : ""}`} data-testid={`routing-version-${r.id}`} data-status={r.status}>
              <button type="button" className="mfg-version-main" onClick={() => requestSelect(r.id)} aria-pressed={r.id === selectedId}>
                <strong>
                  {r.code} v{r.version}
                </strong>
                <span className="chip" title={r.priority === 1 ? "Primary routing" : "Alternate routing (the planner may choose it)"}>
                  {r.priority === 1 ? "Primary" : `Alternate ${r.priority}`}
                </span>
                <StatusChip status={r.status} />
                <EffectivityBadge from={r.effective_from} to={r.effective_to} serialFrom={r.serial_from} serialTo={r.serial_to} />
                <span className="muted small">{r.operation_count} operations</span>
              </button>
              <span className="row">
                {r.status === "draft" ? (
                  <button type="button" className="btn sm" onClick={() => setPending({ kind: "release", r })} disabled={busy || dirty} title={dirty ? "Save or undo your changes first" : undefined} data-testid="routing-release">
                    <Icon name="check" /> Release
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn sm"
                  disabled={busy || dirty}
                  title={dirty ? "Save or undo your changes first" : undefined}
                  onClick={() =>
                    void act(async () => {
                      const c = await copyRouting(r.id, { revision: null, code: null }, r.row_version);
                      select(c.id);
                    })
                  }
                  data-testid="routing-copy"
                >
                  <Icon name="copy" /> Copy
                </button>
                {r.status === "released" ? (
                  <button type="button" className="btn sm ghost" onClick={() => setPending({ kind: "obsolete", r })} disabled={busy || dirty} title={dirty ? "Save or undo your changes first" : undefined} data-testid="routing-obsolete">
                    <Icon name="ban" /> Make obsolete
                  </button>
                ) : (
                  <button type="button" className="btn sm ghost icon" onClick={() => setPending({ kind: "delete", r })} disabled={busy || dirty} title={dirty ? "Save or undo your changes first" : undefined} aria-label={`Delete ${r.code} v${r.version}`} data-testid="routing-delete">
                    <Icon name="trash" />
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {selected.loading && !selected.data ? <Spinner label="Loading routing…" /> : null}
      <MfgError error={selected.error} onRetry={selected.reload} />
      {selected.data && selected.data.id === selectedId ? (
        <RoutingDocument
          key={`${selected.data.id}-${selected.data.row_version}`}
          routing={selected.data}
          groups={groups.data?.items ?? []}
          skills={skills.data?.items ?? []}
          tools={tools.data?.items ?? []}
          selectedSeq={opParam ? Number(opParam) : null}
          referenced={referenced}
          onSaved={() => list.reload()}
          onDirtyChange={(id, d) => setDirtyId((cur) => (d ? id : cur === id ? null : cur))}
          onCopied={(id) => {
            list.reload();
            select(id);
          }}
        />
      ) : null}

      {discardFor ? (
        <ConfirmDialog
          title="Discard unsaved changes?"
          confirmLabel="Discard changes"
          danger
          onCancel={() => setDiscardFor(null)}
          onConfirm={() => {
            const id = discardFor;
            setDiscardFor(null);
            setDirtyId(null);
            select(id);
          }}
        >
          <p style={{ margin: 0 }}>The open routing has operation edits that are not saved yet.</p>
        </ConfirmDialog>
      ) : null}
      {pending?.kind === "release" ? (
        <ReleaseDialog
          what={`${pending.r.code} v${pending.r.version}`}
          defaultFrom={todayInOffset(plant.data?.utc_offset)}
          hasReleased={routings.some((r) => r.status === "released" && r.priority === pending.r.priority && r.id !== pending.r.id)}
          onClose={() => setPending(null)}
          onRelease={async (body) => {
            await releaseRouting(pending.r.id, body, pending.r.row_version);
            setPending(null);
            list.reload();
          }}
        />
      ) : null}
      {pending?.kind === "obsolete" ? (
        <ConfirmDialog title={`Make ${pending.r.code} v${pending.r.version} obsolete?`} confirmLabel="Make obsolete" busy={busy} onCancel={() => setPending(null)} onConfirm={() => void act(() => obsoleteRouting(pending.r.id, pending.r.row_version))}>
          <p style={{ margin: 0 }}>It stops being used for planning and stays in the history (read-only).</p>
        </ConfirmDialog>
      ) : null}
      {pending?.kind === "delete" ? (
        <ConfirmDialog title={`Delete ${pending.r.code} v${pending.r.version}?`} confirmLabel="Delete" danger busy={busy} onCancel={() => setPending(null)} onConfirm={() => void act(() => deleteRouting(pending.r.id, pending.r.row_version))}>
          <p style={{ margin: 0 }}>The routing and its operations are deleted.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function RoutingDocument({
  routing,
  groups,
  skills,
  tools,
  selectedSeq,
  referenced,
  onSaved,
  onCopied,
  onDirtyChange,
}: {
  routing: RoutingRecord;
  groups: GroupRecord[];
  skills: SkillRecord[];
  tools: ToolPoolRecord[];
  selectedSeq: number | null;
  referenced: Set<number>;
  onSaved(): void;
  onCopied(id: string): void;
  onDirtyChange(routingId: string, dirty: boolean): void;
}) {
  const [base, setBase] = useState(routing);
  const [header, setHeader] = useState(() => toHeader(routing));
  const [ops, setOps] = useState<OpDraft[]>(() => routing.operations.map(opToDraft));
  const [reordered, setReordered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [settings, setSettings] = useState(false);
  const readOnly = base.status !== "draft";

  const reset = (r: RoutingRecord) => {
    setBase(r);
    setHeader(toHeader(r));
    setOps(r.operations.map(opToDraft));
    setReordered(false);
    setConflict(false);
  };

  const input = toInput(base, header, ops);
  const dirty = JSON.stringify(input) !== JSON.stringify(toInput(base, toHeader(base), base.operations.map(opToDraft)));
  const dirtyRef = useRef(onDirtyChange);
  dirtyRef.current = onDirtyChange;
  useEffect(() => {
    dirtyRef.current(base.id, dirty);
  }, [base.id, dirty]);
  useEffect(() => {
    const id = base.id;
    return () => dirtyRef.current(id, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const problems = ops.map((o) => ({ seq: o.seq, p: opProblems(o) })).filter((x) => x.p.length);
  const seqs = ops.map((o) => o.seq);
  const duplicateSeq = seqs.some((s, i) => seqs.indexOf(s) !== i);
  const movedRefs = reordered ? [...referenced].filter((s) => {
    const before = base.operations.find((o) => o.seq === s);
    const after = ops.find((o) => o.seq === s);
    return (before?.id ?? null) !== (after?.id ?? null);
  }) : [];

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await updateRouting(base.id, input, base.row_version);
      reset(next);
      setSaved(true);
      onSaved();
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const reload = async () => {
    try {
      reset(await getRouting(base.id));
      setError(null);
    } catch (e) {
      setError(e);
    }
  };

  const copy = async () => {
    try {
      const c = await copyRouting(base.id, { revision: null, code: null }, base.row_version);
      onCopied(c.id);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div className="col gap-lg" data-testid="routing-editor">
      <section className="card">
        <div className="card-header">
          <h2>
            {base.code} v{base.version} <span className="muted small">rev. {base.revision}</span>
          </h2>
          <span className="row">
            <StatusChip status={base.status} />
            <button type="button" className="btn sm ghost" aria-expanded={settings} onClick={() => setSettings((s) => !s)}>
              <Icon name="settings" /> Routing settings
            </button>
          </span>
        </div>
        <div className="card-body col">
          {readOnly ? (
            <Banner
              tone="info"
              icon="lock"
              testId="routing-readonly"
              title={base.status === "released" ? "Released - copy to a new version to edit" : "Obsolete - copy to a new version to edit"}
              actions={
                <button type="button" className="btn sm primary" onClick={() => void copy()} data-testid="routing-copy-banner">
                  <Icon name="copy" /> Copy to a new version
                </button>
              }
            />
          ) : null}
          {conflict ? <ConflictBanner onReload={() => void reload()} what="this routing" /> : null}
          <MfgError error={error} title="Could not save the routing" />
          {settings ? (
            <div className="form-grid">
              <TextField label="Routing code" value={header.code} onChange={(v) => setHeader({ ...header, code: v })} maxLength={32} disabled={readOnly} hint="Tells alternate routings apart, e.g. STD, WAVE." />
              <TextField label="Priority" type="number" value={header.priority} onChange={(v) => setHeader({ ...header, priority: v })} disabled={readOnly} hint="1 = primary; 2-9 = alternates." />
              <TextField label="Revision" value={header.revision} onChange={(v) => setHeader({ ...header, revision: v })} maxLength={16} disabled={readOnly} />
              <TextField label="Version" type="number" value={header.version} onChange={(v) => setHeader({ ...header, version: v })} disabled={readOnly} />
              <TextField label="Note" value={header.note} onChange={(v) => setHeader({ ...header, note: v })} maxLength={500} disabled={readOnly} />
            </div>
          ) : null}
          {movedRefs.length ? (
            <Banner tone="warn" testId="routing-renumber-warning" title="Check the BOM after reordering">
              BOM lines of this item are consumed at operation {movedRefs.join(", ")}. After renumbering, that number now
              belongs to a different step. Update the "At op." column of the BOM if needed.
            </Banner>
          ) : null}
          <RoutingEditor
            ops={ops}
            onChange={(next, re) => {
              setOps(next);
              if (re) setReordered(true);
              setSaved(false);
            }}
            readOnly={readOnly}
            groups={groups}
            skills={skills}
            tools={tools}
            selectedSeq={selectedSeq}
            referencedSeqs={referenced}
          />
          {!readOnly ? (
            <div className="row wrap">
              <button type="button" className="btn sm" onClick={() => setOps([...ops, blankOp(ops, groups[0]?.id ?? "")])} data-testid="op-add">
                <Icon name="plus" /> Add operation
              </button>
              {groups.length === 0 ? <span className="small muted">Create stages under Plant first; every operation runs on a stage.</span> : null}
            </div>
          ) : null}
          {!readOnly && (problems.length || duplicateSeq) ? (
            <ul className="small mfg-problem-list" role="status">
              {duplicateSeq ? (
                <li>
                  <Icon name="alert" size={12} /> Two operations have the same number.
                </li>
              ) : null}
              {problems.map((x) => (
                <li key={x.seq}>
                  <Icon name="alert" size={12} /> Operation {x.seq}: {x.p.join("; ")}
                </li>
              ))}
            </ul>
          ) : null}
          {!readOnly ? (
            <div className="row">
              <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || !dirty || problems.length > 0 || duplicateSeq} data-testid="routing-save">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} Save routing
              </button>
              <button type="button" className="btn" onClick={() => reset(base)} disabled={!dirty || busy}>
                Undo changes
              </button>
              <SaveState busy={false} saved={saved && !dirty} />
            </div>
          ) : null}
        </div>
      </section>
      <OperationTimePreview routingId={base.id} version={base.row_version} />
    </div>
  );
}

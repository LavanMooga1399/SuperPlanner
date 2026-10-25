/**
 * `/mfg/plant/groups` (`?group=`, `?line=`, M 11.1/11.3): stages (work-center groups) with their lines; the
 * selected stage or line is highlighted, scrolled into view and opened in the side panel for editing.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import {
  createGroup,
  createLine,
  deleteGroup,
  deleteLine,
  getGroup,
  getLine,
  listGroups,
  listLines,
  updateGroup,
  updateLine,
} from "../api/client";
import type { GroupInput, GroupRecord, ItemRef, LineInput, LineRecord } from "../api/types";
import { ConflictBanner, MfgError, SaveState, Spinner } from "../components/Feedback";
import { CheckField, numOr, SelectField, strOrNull, TextField } from "../components/Field";
import { ItemPicker } from "../components/ItemPicker";
import { ActiveBadge, KindBadge } from "../components/StatusChip";
import { effectivityText } from "../components/EffectivityBadge";
import { mfgPaths } from "../lib/paths";
import { isConflict, useLoad } from "../lib/useMfg";

type Panel = { kind: "group"; id: string } | { kind: "line"; id: string } | { kind: "new-group" } | { kind: "new-line"; groupId: string } | null;

export function GroupsPage() {
  const [params, setParams] = useSearchParams();
  const groupParam = params.get("group");
  const lineParam = params.get("line");
  const groups = useLoad((signal) => listGroups({}, signal), []);
  const lines = useLoad((signal) => listLines({}, signal), []);
  const [creating, setCreating] = useState<Panel>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const panel: Panel = creating ?? (lineParam ? { kind: "line", id: lineParam } : groupParam ? { kind: "group", id: groupParam } : null);

  const byGroup = useMemo(() => {
    const m = new Map<string, LineRecord[]>();
    for (const l of lines.data?.items ?? []) m.set(l.group_id, [...(m.get(l.group_id) ?? []), l]);
    return m;
  }, [lines.data]);

  const selectedKey = lineParam ? `line-${lineParam}` : groupParam ? `group-${groupParam}` : null;
  useEffect(() => {
    if (!selectedKey) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-key="${selectedKey}"]`);
    el?.scrollIntoView({ block: "center" });
  }, [selectedKey, groups.data, lines.data]);

  const select = (p: { group?: string; line?: string }) => {
    setCreating(null);
    const next = new URLSearchParams();
    if (p.group) next.set("group", p.group);
    if (p.line) next.set("line", p.line);
    setParams(next, { replace: false });
  };

  const refresh = () => {
    groups.reload();
    lines.reload();
  };

  return (
    <div className="split mfg-split">
      <section className="card" aria-labelledby="groups-title">
        <div className="card-header">
          <h2 id="groups-title">Stages and lines</h2>
          <button type="button" className="btn sm primary" onClick={() => setCreating({ kind: "new-group" })} data-testid="group-new">
            <Icon name="plus" /> New stage
          </button>
        </div>
        <p className="muted small" style={{ margin: "8px 16px 0" }}>
          A stage (work-center group) is a kind of work, e.g. SMT or final test. Its lines are the machines or benches
          that can do it; the planner picks the line.
        </p>
        <MfgError error={groups.error ?? lines.error} onRetry={refresh} />
        {groups.loading && !groups.data ? <Spinner /> : null}
        <div className="mfg-tree-list" ref={listRef} data-testid="groups-list">
          {(groups.data?.items ?? []).length === 0 && groups.data ? <p className="muted" style={{ padding: 16, margin: 0 }}>No stages yet.</p> : null}
          {(groups.data?.items ?? []).map((g) => {
            const gl = byGroup.get(g.id) ?? [];
            const gSel = groupParam === g.id && !lineParam;
            return (
              <div key={g.id} className="mfg-group-block">
                <button
                  type="button"
                  className={`mfg-list-row mfg-group-row${gSel ? " mfg-selected" : ""}`}
                  data-key={`group-${g.id}`}
                  data-testid="group-row"
                  data-group-id={g.id}
                  data-code={g.code}
                  aria-current={gSel ? "true" : undefined}
                  onClick={() => select({ group: g.id })}
                >
                  <Icon name="layers" />
                  <strong className="mono">{g.code}</strong>
                  <span className="grow mfg-ellipsis">{g.name}</span>
                  <span className="muted small">{g.line_count} lines</span>
                  <ActiveBadge active={g.active} />
                </button>
                <ul className="mfg-plain-list">
                  {gl.map((l) => {
                    const lSel = lineParam === l.id;
                    return (
                      <li key={l.id}>
                        <button
                          type="button"
                          className={`mfg-list-row mfg-line-row${lSel ? " mfg-selected" : ""}`}
                          data-key={`line-${l.id}`}
                          data-testid="line-row"
                          data-line-id={l.id}
                          data-code={l.code}
                          aria-current={lSel ? "true" : undefined}
                          onClick={() => select({ line: l.id })}
                        >
                          <span className="mono">{l.code}</span>
                          <span className="grow mfg-ellipsis">{l.name}</span>
                          <span className="muted small" title="Speed factor">
                            ×{l.speed_factor}
                          </span>
                          {l.parallel_capacity > 1 ? <span className="chip" title="Runs this many jobs at once">{l.parallel_capacity} at once</span> : null}
                          <ActiveBadge active={l.active} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      </section>

      <aside className="col" aria-label="Details">
        {panel === null ? (
          <div className="card card-body muted">Select a stage or a line to see and edit it.</div>
        ) : panel.kind === "new-group" ? (
          <GroupEditor
            key="new-group"
            group={null}
            onSaved={(g) => {
              refresh();
              select({ group: g.id });
            }}
            onCancel={() => setCreating(null)}
          />
        ) : panel.kind === "group" ? (
          <GroupPanel key={panel.id} id={panel.id} onChanged={refresh} onDeleted={() => { refresh(); select({}); }} onAddLine={() => setCreating({ kind: "new-line", groupId: panel.id })} />
        ) : panel.kind === "new-line" ? (
          <LineEditor
            key="new-line"
            line={null}
            groupId={panel.groupId}
            groups={groups.data?.items ?? []}
            onSaved={(l) => {
              refresh();
              select({ line: l.id });
            }}
            onCancel={() => setCreating(null)}
          />
        ) : (
          <LinePanel key={panel.id} id={panel.id} groups={groups.data?.items ?? []} onChanged={refresh} onDeleted={() => { refresh(); select({}); }} />
        )}
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------- stage
function GroupPanel({ id, onChanged, onDeleted, onAddLine }: { id: string; onChanged(): void; onDeleted(): void; onAddLine(): void }) {
  const g = useLoad((signal) => getGroup(id, signal), [id]);
  if (g.error) return <MfgError error={g.error} onRetry={g.reload} />;
  if (!g.data) return <Spinner />;
  const d = g.data;
  return (
    <div className="col" data-testid="group-panel" data-group-id={d.id}>
      <GroupEditor
        group={d}
        onSaved={() => {
          g.reload();
          onChanged();
        }}
        onDeleted={onDeleted}
      />
      <section className="card">
        <div className="card-header">
          <h3>Lines of {d.code}</h3>
          <button type="button" className="btn sm" onClick={onAddLine} data-testid="line-new">
            <Icon name="plus" /> Add line
          </button>
        </div>
        <div className="card-body">
          {d.lines.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No lines yet. Operations on this stage cannot be planned until it has an active line.</p> : null}
          <ul className="mfg-plain-list">
            {d.lines.map((l) => (
              <li key={l.id} className="row">
                <Link to={mfgPaths.groups({ line: l.id })} className="mono">
                  {l.code}
                </Link>
                <span className="grow muted">{l.name}</span>
                <ActiveBadge active={l.active} />
              </li>
            ))}
          </ul>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <h3>Shifts</h3>
          <Link to={mfgPaths.shifts()} className="btn sm ghost">
            Manage shifts <Icon name="arrow-right" />
          </Link>
        </div>
        <div className="card-body">
          {d.assignments.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No shift assigned to this stage or its lines.</p> : null}
          <ul className="mfg-plain-list">
            {d.assignments.map((a) => (
              <li key={a.id} className="row wrap">
                <KindBadge kind={a.kind} />
                <Link to={mfgPaths.shifts({ assignment: a.id })} className="mono">
                  {a.template.code}
                </Link>
                <span className="muted small">
                  on {a.target.type === "group" ? "stage" : "line"} {a.target.code} · {effectivityText(a.effective_from, a.effective_to)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}

function GroupEditor({ group, onSaved, onCancel, onDeleted }: { group: GroupRecord | null; onSaved(g: GroupRecord): void; onCancel?(): void; onDeleted?(): void }) {
  const init = (x: GroupRecord | null) => ({ code: x?.code ?? "", name: x?.name ?? "", description: x?.description ?? "", kind: x?.kind ?? "", active: x?.active ?? true });
  const [f, setF] = useState(() => init(group));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [version, setVersion] = useState(group?.row_version ?? 0);
  const body = (): GroupInput => ({ code: f.code.trim(), name: f.name.trim(), description: f.description, kind: strOrNull(f.kind), active: f.active });
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const g = group ? await updateGroup(group.id, body(), version) : await createGroup(body());
      setVersion(g.row_version);
      setSaved(true);
      setConflict(false);
      onSaved(g);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };
  const reload = async () => {
    if (!group) return;
    try {
      const fresh = await getGroup(group.id);
      setF(init(fresh));
      setVersion(fresh.row_version);
      setConflict(false);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="group-form"
    >
      <div className="card-header">
        <h3>{group ? `Stage ${group.code}` : "New stage"}</h3>
      </div>
      <div className="card-body col">
        {conflict ? <ConflictBanner onReload={() => void reload()} what="this stage" /> : null}
        <MfgError error={error} title="Could not save" />
        <div className="form-grid">
          <TextField label="Code" value={f.code} onChange={(v) => setF({ ...f, code: v })} required maxLength={32} testId="group-code" />
          <TextField label="Name" value={f.name} onChange={(v) => setF({ ...f, name: v })} required testId="group-name" />
          <TextField label="Kind" value={f.kind} onChange={(v) => setF({ ...f, kind: v })} maxLength={32} hint="Optional, e.g. machine, bench, oven, test" />
        </div>
        <TextField label="Description" value={f.description} onChange={(v) => setF({ ...f, description: v })} maxLength={500} />
        <CheckField label="Active" checked={f.active} onChange={(v) => setF({ ...f, active: v })} />
        <div className="row">
          <button type="submit" className="btn primary sm" disabled={busy || !f.code.trim() || !f.name.trim()} data-testid="group-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {group ? "Save stage" : "Create stage"}
          </button>
          {onCancel ? (
            <button type="button" className="btn sm" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
          <SaveState busy={false} saved={saved} />
          <span className="grow" />
          {group && onDeleted ? (
            <button type="button" className="btn sm danger" onClick={() => setConfirm(true)} data-testid="group-delete">
              <Icon name="trash" /> Delete
            </button>
          ) : null}
        </div>
      </div>
      {confirm && group && onDeleted ? (
        <ConfirmDialog
          title={`Delete stage ${group.code}?`}
          confirmLabel="Delete stage"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            deleteGroup(group.id, version).then(onDeleted, setError);
          }}
        >
          <p style={{ margin: 0 }}>A stage with lines, or used by operations, cannot be deleted. Its shift assignments and calendar entries are removed.</p>
        </ConfirmDialog>
      ) : null}
    </form>
  );
}

// ---------------------------------------------------------------- line
function LinePanel({ id, groups, onChanged, onDeleted }: { id: string; groups: GroupRecord[]; onChanged(): void; onDeleted(): void }) {
  const l = useLoad((signal) => getLine(id, signal), [id]);
  if (l.error) return <MfgError error={l.error} onRetry={l.reload} />;
  if (!l.data) return <Spinner />;
  return (
    <div className="col" data-testid="line-panel" data-line-id={l.data.id}>
      <LineEditor
        line={l.data}
        groupId={l.data.group_id}
        groups={groups}
        onSaved={() => {
          l.reload();
          onChanged();
        }}
        onDeleted={onDeleted}
      />
      <div className="row wrap">
        <Link className="btn sm" to={mfgPaths.calendar({ line: l.data.id })} data-testid="line-calendar-link">
          <Icon name="calendar" /> Working time of {l.data.code}
        </Link>
        <Link className="btn sm ghost" to={mfgPaths.groups({ group: l.data.group_id })}>
          Stage {l.data.group.code}
        </Link>
      </div>
    </div>
  );
}

function LineEditor({
  line,
  groupId,
  groups,
  onSaved,
  onCancel,
  onDeleted,
}: {
  line: LineRecord | null;
  groupId: string;
  groups: GroupRecord[];
  onSaved(l: LineRecord): void;
  onCancel?(): void;
  onDeleted?(): void;
}) {
  const init = (x: LineRecord | null) => ({
    group_id: x?.group_id ?? groupId,
    code: x?.code ?? "",
    name: x?.name ?? "",
    speed_factor: String(x?.speed_factor ?? 1),
    parallel_capacity: String(x?.parallel_capacity ?? 1),
    setup_family: x?.setup_family ?? "",
    families: (x?.eligible_families ?? []).join(", "),
    items: x?.eligible_items ?? ([] as ItemRef[]),
    cost_per_hour: String(x?.cost_per_hour ?? 0),
    active: x?.active ?? true,
  });
  const [f, setF] = useState(() => init(line));
  const [version, setVersion] = useState(line?.row_version ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [saved, setSaved] = useState(false);
  const [more, setMore] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const body = (): LineInput => ({
    group_id: f.group_id,
    code: f.code.trim(),
    name: f.name.trim(),
    speed_factor: numOr(f.speed_factor, 1),
    parallel_capacity: numOr(f.parallel_capacity, 1),
    setup_family: strOrNull(f.setup_family),
    eligible_families: [...new Set(f.families.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean))],
    eligible_item_ids: f.items.map((i) => i.id),
    cost_per_hour: numOr(f.cost_per_hour, 0),
    active: f.active,
  });
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const l = line ? await updateLine(line.id, body(), version) : await createLine(body());
      setVersion(l.row_version);
      setSaved(true);
      setConflict(false);
      onSaved(l);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };
  const reload = async () => {
    if (!line) return;
    try {
      const fresh = await getLine(line.id);
      setF(init(fresh));
      setVersion(fresh.row_version);
      setConflict(false);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="line-form"
    >
      <div className="card-header">
        <h3>{line ? `Line ${line.code}` : "New line"}</h3>
      </div>
      <div className="card-body col">
        {conflict ? <ConflictBanner onReload={() => void reload()} what="this line" /> : null}
        <MfgError error={error} title="Could not save" />
        <div className="form-grid">
          <TextField label="Code" value={f.code} onChange={(v) => setF({ ...f, code: v })} required maxLength={32} testId="line-code" />
          <TextField label="Name" value={f.name} onChange={(v) => setF({ ...f, name: v })} required testId="line-name" />
          <SelectField label="Stage" value={f.group_id} onChange={(v) => setF({ ...f, group_id: v })} options={groups.map((g) => ({ value: g.id, label: `${g.code} - ${g.name}` }))} />
          <TextField label="Speed factor" type="number" value={f.speed_factor} onChange={(v) => setF({ ...f, speed_factor: v })} hint="1 = normal; 0.7 = 30 % slower; 1.2 = 20 % faster" testId="line-speed" />
          <TextField label="Jobs at once" type="number" value={f.parallel_capacity} onChange={(v) => setF({ ...f, parallel_capacity: v })} hint="e.g. an oven holding 4 batches" />
        </div>
        <CheckField label="Active" checked={f.active} onChange={(v) => setF({ ...f, active: v })} testId="line-active" hint="Inactive lines are not used for planning." />
        <fieldset className="mfg-fieldset">
          <legend>What this line can make</legend>
          <p className="hint" style={{ margin: 0 }}>
            Leave both empty if the line can make everything of its stage.
          </p>
          <TextField label="Item families" value={f.families} onChange={(v) => setF({ ...f, families: v })} hint="Comma separated, e.g. PCBA-STD, HARNESS" testId="line-families" />
          <div className="col" style={{ gap: 4 }}>
            <span className="field-label">Specific items</span>
            <ul className="mfg-plain-list row wrap">
              {f.items.map((it) => (
                <li key={it.id} className="chip">
                  <span className="mono">{it.part_number}</span>
                  <button type="button" className="btn sm ghost icon" aria-label={`Remove ${it.part_number}`} onClick={() => setF({ ...f, items: f.items.filter((x) => x.id !== it.id) })}>
                    <Icon name="x" size={12} />
                  </button>
                </li>
              ))}
            </ul>
            <div style={{ maxWidth: 320 }}>
              <ItemPicker value={null} label="Add an item" hideLabel placeholder="Add an item…" onChange={(it) => !f.items.some((x) => x.id === it.id) && setF({ ...f, items: [...f.items, it] })} />
            </div>
          </div>
        </fieldset>
        <div>
          <button type="button" className="btn ghost sm" aria-expanded={more} onClick={() => setMore((m) => !m)}>
            <Icon name={more ? "chevron-down" : "chevron-right"} /> More settings (cost, setup family)
          </button>
        </div>
        {more ? (
          <div className="form-grid">
            <TextField label="Running cost per hour" type="number" value={f.cost_per_hour} onChange={(v) => setF({ ...f, cost_per_hour: v })} />
            <TextField label="Setup family" value={f.setup_family} onChange={(v) => setF({ ...f, setup_family: v })} maxLength={32} hint="Lines with the same value share changeover times." />
          </div>
        ) : null}
        <div className="row">
          <button type="submit" className="btn primary sm" disabled={busy || !f.code.trim() || !f.name.trim() || !f.group_id} data-testid="line-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {line ? "Save line" : "Create line"}
          </button>
          {onCancel ? (
            <button type="button" className="btn sm" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
          <SaveState busy={false} saved={saved} />
          <span className="grow" />
          {line && onDeleted ? (
            <button type="button" className="btn sm danger" onClick={() => setConfirm(true)} data-testid="line-delete">
              <Icon name="trash" /> Delete
            </button>
          ) : null}
        </div>
      </div>
      {confirm && line && onDeleted ? (
        <ConfirmDialog
          title={`Delete line ${line.code}?`}
          confirmLabel="Delete line"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            deleteLine(line.id, version).then(onDeleted, setError);
          }}
        >
          <p style={{ margin: 0 }}>Its shift assignments and calendar entries are removed too.</p>
        </ConfirmDialog>
      ) : null}
    </form>
  );
}

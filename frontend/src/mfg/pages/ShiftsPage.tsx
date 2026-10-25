/**
 * `/mfg/plant/shifts` (`?template=`, `?assignment=`, M 11.1/11.3): shift templates with a live weekly preview,
 * and the assignments that give stages or single lines their base / optional shifts.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import {
  createShiftAssignment,
  createShiftTemplate,
  deleteShiftAssignment,
  deleteShiftTemplate,
  listGroups,
  listLines,
  listShiftAssignments,
  listShiftTemplates,
  updateShiftAssignment,
  updateShiftTemplate,
} from "../api/client";
import type {
  AssignmentKind,
  GroupRecord,
  LineRecord,
  ShiftAssignmentInput,
  ShiftAssignmentRecord,
  ShiftDef,
  ShiftTemplateInput,
  ShiftTemplateRecord,
  TargetType,
} from "../api/types";
import { EffectivityBadge } from "../components/EffectivityBadge";
import { EntityFormDialog } from "../components/EntityFormDialog";
import { ConflictBanner, MfgError, SaveState, Spinner } from "../components/Feedback";
import { numOrNull, SelectField, TextField } from "../components/Field";
import { ShiftTemplateEditor, SHIFT_PATTERNS, shiftProblems } from "../components/ShiftTemplateEditor";
import { ShiftWeekPreview } from "../components/ShiftWeekPreview";
import { KindBadge } from "../components/StatusChip";
import { fmtQty } from "../lib/format";
import { isConflict, todayInOffset, useLoad, usePlant } from "../lib/useMfg";

export function ShiftsPage() {
  const [params, setParams] = useSearchParams();
  const templateParam = params.get("template");
  const assignmentParam = params.get("assignment");
  const templates = useLoad((signal) => listShiftTemplates(signal), []);
  const assignments = useLoad((signal) => listShiftAssignments({}, signal), []);
  const groups = useLoad((signal) => listGroups({}, signal), []);
  const lines = useLoad((signal) => listLines({}, signal), []);
  const [creating, setCreating] = useState(false);

  const list = templates.data?.items ?? [];
  const selected = creating ? null : list.find((t) => t.id === templateParam) ?? null;
  const setParam = (k: string, v: string | null) =>
    setParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        if (v) n.set(k, v);
        else n.delete(k);
        return n;
      },
      { replace: false },
    );

  return (
    <div className="col gap-lg">
      <div className="split mfg-split-wide">
        <section className="card" aria-labelledby="tpl-title">
          <div className="card-header">
            <h2 id="tpl-title">Shift templates</h2>
            <button
              type="button"
              className="btn sm primary"
              onClick={() => {
                setCreating(true);
                setParam("template", null);
              }}
              data-testid="template-new"
            >
              <Icon name="plus" /> New template
            </button>
          </div>
          <MfgError error={templates.error} onRetry={templates.reload} />
          {templates.loading && !templates.data ? <Spinner /> : null}
          {templates.data && list.length === 0 ? <p className="muted" style={{ padding: 16, margin: 0 }}>No shift templates yet. A template is a weekly working pattern, e.g. "Day shift Mon-Fri".</p> : null}
          <ul className="mfg-plain-list">
            {list.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  className={`mfg-list-row${t.id === templateParam && !creating ? " mfg-selected" : ""}`}
                  aria-current={t.id === templateParam ? "true" : undefined}
                  onClick={() => {
                    setCreating(false);
                    setParam("template", t.id);
                  }}
                  data-testid="template-row"
                  data-template-id={t.id}
                  data-code={t.code}
                >
                  <Icon name="clock" />
                  <strong className="mono">{t.code}</strong>
                  <span className="grow mfg-ellipsis">{t.name}</span>
                  <span className="muted small" title="Used by assignments / operators">
                    {t.assignment_count} uses · {t.operator_count} people
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <div>
          {creating ? (
            <TemplateDocument
              key="new"
              template={null}
              onSaved={(t) => {
                templates.reload();
                setCreating(false);
                setParam("template", t.id);
              }}
              onCancel={() => setCreating(false)}
            />
          ) : selected ? (
            <TemplateDocument
              key={selected.id}
              template={selected}
              onSaved={() => templates.reload()}
              onDeleted={() => {
                templates.reload();
                setParam("template", null);
              }}
            />
          ) : (
            <div className="card card-body muted">Select a template to see its week, or create a new one.</div>
          )}
        </div>
      </div>

      <AssignmentsCard
        assignments={assignments.data?.items ?? []}
        loading={assignments.loading}
        error={assignments.error}
        reload={() => {
          assignments.reload();
          templates.reload();
        }}
        templates={list}
        groups={groups.data?.items ?? []}
        lines={lines.data?.items ?? []}
        selectedId={assignmentParam}
        onSelect={(id) => setParam("assignment", id)}
      />
    </div>
  );
}

function TemplateDocument({ template, onSaved, onCancel, onDeleted }: { template: ShiftTemplateRecord | null; onSaved(t: ShiftTemplateRecord): void; onCancel?(): void; onDeleted?(): void }) {
  const [code, setCode] = useState(template?.code ?? "");
  const [name, setName] = useState(template?.name ?? "");
  const [description, setDescription] = useState(template?.description ?? "");
  const [shifts, setShifts] = useState<ShiftDef[]>(template?.shifts ?? SHIFT_PATTERNS[0].shifts);
  const [version, setVersion] = useState(template?.row_version ?? 0);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const input: ShiftTemplateInput = { code: code.trim(), name: name.trim(), description, shifts };
  const problems = shifts.flatMap(shiftProblems);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const t = template ? await updateShiftTemplate(template.id, input, version) : await createShiftTemplate(input);
      setVersion(t.row_version);
      setSaved(true);
      setConflict(false);
      onSaved(t);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="template-form"
    >
      <div className="card-header">
        <h2>{template ? `Template ${template.code}` : "New shift template"}</h2>
        <SaveState busy={false} saved={saved} />
      </div>
      <div className="card-body col">
        {conflict ? <ConflictBanner onReload={() => window.location.reload()} what="this template" /> : null}
        <MfgError error={error} title="Could not save the template" />
        {!template ? (
          <div className="field">
            <label htmlFor="tpl-pattern">Start from</label>
            <select id="tpl-pattern" className="select" defaultValue="day" onChange={(e) => setShifts(SHIFT_PATTERNS.find((p) => p.id === e.target.value)?.shifts ?? [])} data-testid="template-pattern">
              {SHIFT_PATTERNS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="form-grid">
          <TextField label="Code" value={code} onChange={setCode} required maxLength={32} testId="template-code" />
          <TextField label="Name" value={name} onChange={setName} required testId="template-name" />
          <TextField label="Description" value={description} onChange={setDescription} maxLength={500} />
        </div>
        <ShiftTemplateEditor shifts={shifts} onChange={setShifts} />
        <h3>Week preview</h3>
        <ShiftWeekPreview template={input} />
        <div className="row">
          <button type="submit" className="btn primary" disabled={busy || !code.trim() || !name.trim() || shifts.length === 0 || problems.length > 0} data-testid="template-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {template ? "Save template" : "Create template"}
          </button>
          {onCancel ? (
            <button type="button" className="btn" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
          <span className="grow" />
          {template && onDeleted ? (
            <button type="button" className="btn danger sm" onClick={() => setConfirm(true)} data-testid="template-delete">
              <Icon name="trash" /> Delete
            </button>
          ) : null}
        </div>
      </div>
      {confirm && template && onDeleted ? (
        <ConfirmDialog
          title={`Delete template ${template.code}?`}
          confirmLabel="Delete template"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            deleteShiftTemplate(template.id, version).then(onDeleted, setError);
          }}
        >
          <p style={{ margin: 0 }}>A template used by assignments or operators cannot be deleted.</p>
        </ConfirmDialog>
      ) : null}
    </form>
  );
}

function AssignmentsCard({
  assignments,
  loading,
  error,
  reload,
  templates,
  groups,
  lines,
  selectedId,
  onSelect,
}: {
  assignments: ShiftAssignmentRecord[];
  loading: boolean;
  error: unknown;
  reload(): void;
  templates: ShiftTemplateRecord[];
  groups: GroupRecord[];
  lines: LineRecord[];
  selectedId: string | null;
  onSelect(id: string | null): void;
}) {
  const [editing, setEditing] = useState<ShiftAssignmentRecord | "new" | null>(null);
  const [filter, setFilter] = useState("");
  const [del, setDel] = useState<ShiftAssignmentRecord | null>(null);
  const [delError, setDelError] = useState<unknown>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  useEffect(() => {
    if (!selectedId) return;
    tableRef.current?.querySelector(`[data-assignment-id="${selectedId}"]`)?.scrollIntoView({ block: "center" });
  }, [selectedId, assignments]);

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const rows = f ? assignments.filter((a) => `${a.template.code} ${a.target.code} ${a.target.name}`.toLowerCase().includes(f)) : assignments;
    return [...rows].sort((a, b) => a.target.code.localeCompare(b.target.code) || a.kind.localeCompare(b.kind));
  }, [assignments, filter]);

  return (
    <section className="card" aria-labelledby="asg-title">
      <div className="card-header">
        <h2 id="asg-title">Who works which shifts</h2>
        <div className="row">
          <input className="input sm" type="search" placeholder="Filter by stage, line or template" aria-label="Filter assignments" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 240 }} />
          <button type="button" className="btn sm primary" onClick={() => setEditing("new")} disabled={templates.length === 0} data-testid="assignment-new">
            <Icon name="plus" /> Assign shifts
          </button>
        </div>
      </div>
      <div className="card-body col">
        <p className="muted small" style={{ margin: 0 }}>
          Assign a template to a whole stage, or to one line to override its stage. Base shifts are normal working
          time; optional shifts (overtime, weekends) are only opened by the planner when needed, at their extra cost.
        </p>
        <MfgError error={error} onRetry={reload} />
        <MfgError error={delError} title="Could not delete" />
        {loading && assignments.length === 0 ? <Spinner /> : null}
        <div className="table-wrap">
          <table className="table" ref={tableRef} data-testid="assignments-table">
            <thead>
              <tr>
                <th>Applies to</th>
                <th>Kind</th>
                <th>Template</th>
                <th>Shifts</th>
                <th>When</th>
                <th className="num">Extra cost / h</th>
                <th className="num">Max h / week</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 ? (
                <tr>
                  <td colSpan={8} className="muted">
                    No shifts assigned yet.
                  </td>
                </tr>
              ) : null}
              {shown.map((a) => (
                <tr key={a.id} data-testid="assignment-row" data-assignment-id={a.id} className={a.id === selectedId ? "mfg-selected" : undefined} aria-selected={a.id === selectedId || undefined}>
                  <td>
                    <span className="muted small">{a.target.type === "group" ? "Stage" : "Line"}</span> <span className="mono">{a.target.code}</span>
                  </td>
                  <td>
                    <KindBadge kind={a.kind} />
                  </td>
                  <td className="mono">{a.template.code}</td>
                  <td className="small">{a.shift_names.length ? a.shift_names.join(", ") : "All"}</td>
                  <td>
                    <EffectivityBadge from={a.effective_from} to={a.effective_to} />
                  </td>
                  <td className="num">{a.cost_per_hour === null ? "" : fmtQty(a.cost_per_hour)}</td>
                  <td className="num">{a.max_hours_per_week === null ? "" : fmtQty(a.max_hours_per_week)}</td>
                  <td className="nowrap">
                    <button
                      type="button"
                      className="btn sm"
                      onClick={() => {
                        onSelect(a.id);
                        setEditing(a);
                      }}
                      data-testid="assignment-edit"
                    >
                      Edit
                    </button>
                    <button type="button" className="btn sm ghost icon" aria-label={`Delete assignment of ${a.template.code} to ${a.target.code}`} onClick={() => setDel(a)}>
                      <Icon name="trash" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {editing ? (
        <AssignmentDialog
          assignment={editing === "new" ? null : editing}
          templates={templates}
          groups={groups}
          lines={lines}
          onClose={() => setEditing(null)}
          onSaved={(a) => {
            setEditing(null);
            onSelect(a.id);
            reload();
          }}
        />
      ) : null}
      <OpenSelected selectedId={selectedId} assignments={assignments} editing={editing} onOpen={setEditing} />
      {del ? (
        <ConfirmDialog
          title="Remove this shift assignment?"
          confirmLabel="Remove"
          danger
          onCancel={() => setDel(null)}
          onConfirm={() => {
            const a = del;
            setDel(null);
            setDelError(null);
            deleteShiftAssignment(a.id, a.row_version).then(() => {
              if (selectedId === a.id) onSelect(null);
              reload();
            }, setDelError);
          }}
        >
          <p style={{ margin: 0 }}>
            {del.template.code} will no longer apply to {del.target.code}.
          </p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}

/** `?assignment=` from a health link opens that assignment's form once. */
function OpenSelected({
  selectedId,
  assignments,
  editing,
  onOpen,
}: {
  selectedId: string | null;
  assignments: ShiftAssignmentRecord[];
  editing: unknown;
  onOpen(a: ShiftAssignmentRecord): void;
}) {
  const opened = useRef<string | null>(null);
  useEffect(() => {
    if (!selectedId || editing || opened.current === selectedId) return;
    const a = assignments.find((x) => x.id === selectedId);
    if (a) {
      opened.current = selectedId;
      onOpen(a);
    }
  }, [selectedId, assignments, editing, onOpen]);
  return null;
}

function AssignmentDialog({
  assignment,
  templates,
  groups,
  lines,
  onClose,
  onSaved,
}: {
  assignment: ShiftAssignmentRecord | null;
  templates: ShiftTemplateRecord[];
  groups: GroupRecord[];
  lines: LineRecord[];
  onClose(): void;
  onSaved(a: ShiftAssignmentRecord): void;
}) {
  const plant = usePlant();
  const [templateId, setTemplateId] = useState(assignment?.shift_template_id ?? templates[0]?.id ?? "");
  const [targetType, setTargetType] = useState<TargetType>(assignment?.target_type ?? "group");
  const [groupId, setGroupId] = useState(assignment?.group_id ?? groups[0]?.id ?? "");
  const [lineId, setLineId] = useState(assignment?.line_id ?? lines[0]?.id ?? "");
  const [kind, setKind] = useState<AssignmentKind>(assignment?.kind ?? "base");
  const [names, setNames] = useState<string[]>(assignment?.shift_names ?? []);
  const [from, setFrom] = useState(assignment?.effective_from ?? "");
  const [to, setTo] = useState(assignment?.effective_to ?? "");
  const [cost, setCost] = useState(assignment?.cost_per_hour === null || assignment?.cost_per_hour === undefined ? "" : String(assignment.cost_per_hour));
  const [maxH, setMaxH] = useState(assignment?.max_hours_per_week === null || assignment?.max_hours_per_week === undefined ? "" : String(assignment.max_hours_per_week));
  const [note, setNote] = useState(assignment?.note ?? "");
  const [conflict, setConflict] = useState(false);
  const template = templates.find((t) => t.id === templateId);
  const effFrom = from || todayInOffset(plant.data?.utc_offset);

  const body = (): ShiftAssignmentInput => ({
    shift_template_id: templateId,
    target_type: targetType,
    group_id: targetType === "group" ? groupId : null,
    line_id: targetType === "line" ? lineId : null,
    kind,
    shift_names: names.filter((n) => template?.shifts.some((s) => s.name === n)),
    effective_from: effFrom,
    effective_to: to || null,
    cost_per_hour: kind === "optional" ? numOrNull(cost) : null,
    max_hours_per_week: kind === "optional" ? numOrNull(maxH) : null,
    note,
  });

  return (
    <EntityFormDialog
      title={assignment ? "Edit shift assignment" : "Assign shifts"}
      submitLabel={assignment ? "Save" : "Assign"}
      onClose={onClose}
      wide
      testId="assignment-form"
      disabled={!templateId || (targetType === "group" ? !groupId : !lineId)}
      onSubmit={async () => {
        try {
          const a = assignment ? await updateShiftAssignment(assignment.id, body(), assignment.row_version) : await createShiftAssignment(body());
          onSaved(a);
        } catch (e) {
          if (isConflict(e)) setConflict(true);
          throw e;
        }
      }}
    >
      {conflict ? <ConflictBanner onReload={() => window.location.reload()} what="this assignment" /> : null}
      <div className="form-grid">
        <SelectField label="Shift template" value={templateId} onChange={setTemplateId} options={templates.map((t) => ({ value: t.id, label: `${t.code} - ${t.name}` }))} testId="assignment-template" />
        <SelectField
          label="Applies to"
          value={targetType}
          onChange={setTargetType}
          options={[
            { value: "group", label: "A whole stage" },
            { value: "line", label: "One line (overrides its stage)" },
          ]}
          testId="assignment-target-type"
        />
        {targetType === "group" ? (
          <SelectField label="Stage" value={groupId} onChange={setGroupId} options={groups.map((g) => ({ value: g.id, label: `${g.code} - ${g.name}` }))} testId="assignment-group" />
        ) : (
          <SelectField label="Line" value={lineId} onChange={setLineId} options={lines.map((l) => ({ value: l.id, label: `${l.code} - ${l.name} (${l.group.code})` }))} testId="assignment-line" />
        )}
        <SelectField
          label="Kind"
          value={kind}
          onChange={setKind}
          options={[
            { value: "base", label: "Base - normal working time" },
            { value: "optional", label: "Optional - overtime, opened when needed" },
          ]}
          testId="assignment-kind"
        />
      </div>
      {template ? (
        <fieldset className="mfg-fieldset">
          <legend>Shifts of {template.code}</legend>
          <div className="row wrap">
            {template.shifts.map((s) => (
              <label key={s.name} className="checkbox">
                <input type="checkbox" checked={names.includes(s.name)} onChange={(e) => setNames(e.target.checked ? [...names, s.name] : names.filter((n) => n !== s.name))} />
                {s.name} ({s.start}-{s.end})
              </label>
            ))}
          </div>
          <span className="hint">None ticked = all shifts of the template.</span>
        </fieldset>
      ) : null}
      <div className="form-grid">
        <TextField label="From" type="date" value={from} onChange={setFrom} hint={from ? undefined : `Empty = today (${effFrom})`} testId="assignment-from" />
        <TextField label="Until" type="date" value={to} onChange={setTo} hint="Exclusive; empty = no end" />
        {kind === "optional" ? (
          <>
            <TextField label="Extra cost per hour" type="number" value={cost} onChange={setCost} hint="Lets the planner weigh overtime" testId="assignment-cost" />
            <TextField label="Max hours per week" type="number" value={maxH} onChange={setMaxH} />
          </>
        ) : null}
      </div>
      <TextField label="Note" value={note} onChange={setNote} maxLength={500} />
    </EntityFormDialog>
  );
}

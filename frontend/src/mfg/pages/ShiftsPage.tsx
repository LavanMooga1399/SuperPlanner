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
import { t, t as tr } from "../../lib/i18n";

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
            <h2 id="tpl-title">{t("mfg.shiftsPage.head.shiftTemplates")}</h2>
            <button
              type="button"
              className="btn sm primary"
              onClick={() => {
                setCreating(true);
                setParam("template", null);
              }}
              data-testid="template-new"
            >
              <Icon name="plus" /> {t("mfg.shiftsPage.btn.newTemplate")}
            </button>
          </div>
          <MfgError error={templates.error} onRetry={templates.reload} />
          {templates.loading && !templates.data ? <Spinner /> : null}
          {templates.data && list.length === 0 ? <p className="muted" style={{ padding: 16, margin: 0 }}>{tr("mfg.shiftsPage.text.noShiftTemplatesYetA")}</p> : null}
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
                  <span className="muted small" title={tr("mfg.shiftsPage.attr.usedByAssignmentsOperators")}>
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
            <div className="card card-body muted">{tr("mfg.shiftsPage.text.selectATemplateToSee")}</div>
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
        <h2>{template ? tr("mfg.shiftsPage.tpl.template", { code: template.code }) : tr("mfg.shiftsPage.str.newShiftTemplate")}</h2>
        <SaveState busy={false} saved={saved} />
      </div>
      <div className="card-body col">
        {conflict ? <ConflictBanner onReload={() => window.location.reload()} what={tr("mfg.shiftsPage.attr.thisTemplate")} /> : null}
        <MfgError error={error} title={tr("mfg.shiftsPage.attr.couldNotSaveTheTemplate")} />
        {!template ? (
          <div className="field">
            <label htmlFor="tpl-pattern">{t("mfg.shiftsPage.label.startFrom")}</label>
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
          <TextField label={t("mfg.shiftsPage.label.code")} value={code} onChange={setCode} required maxLength={32} testId="template-code" />
          <TextField label={t("mfg.shiftsPage.label.name")} value={name} onChange={setName} required testId="template-name" />
          <TextField label={t("mfg.shiftsPage.label.description")} value={description} onChange={setDescription} maxLength={500} />
        </div>
        <ShiftTemplateEditor shifts={shifts} onChange={setShifts} />
        <h3>{t("mfg.shiftsPage.head.weekPreview")}</h3>
        <ShiftWeekPreview template={input} />
        <div className="row">
          <button type="submit" className="btn primary" disabled={busy || !code.trim() || !name.trim() || shifts.length === 0 || problems.length > 0} data-testid="template-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {template ? tr("mfg.shiftsPage.str.saveTemplate") : tr("mfg.shiftsPage.str.createTemplate")}
          </button>
          {onCancel ? (
            <button type="button" className="btn" onClick={onCancel}>
              {t("mfg.shiftsPage.btn.cancel")}
            </button>
          ) : null}
          <span className="grow" />
          {template && onDeleted ? (
            <button type="button" className="btn danger sm" onClick={() => setConfirm(true)} data-testid="template-delete">
              <Icon name="trash" /> {t("mfg.shiftsPage.btn.delete")}
            </button>
          ) : null}
        </div>
      </div>
      {confirm && template && onDeleted ? (
        <ConfirmDialog
          title={tr("mfg.shiftsPage.tpl.deleteTemplate", { code: template.code })}
          confirmLabel={t("mfg.shiftsPage.btn.deleteTemplate")}
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            deleteShiftTemplate(template.id, version).then(onDeleted, setError);
          }}
        >
          <p style={{ margin: 0 }}>{t("mfg.shiftsPage.text.aTemplateUsedByAssignments")}</p>
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
  /**
   * `?assignment=` ids already handled. Ids selected from inside this page are added before the URL changes, so
   * they only highlight their row; the URL update is asynchronous, so the previous selection must stay marked too.
   */
  const handled = useRef<Set<string>>(new Set());
  const selectInPage = (id: string) => {
    handled.current.add(id);
    onSelect(id);
  };

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
        <h2 id="asg-title">{t("mfg.shiftsPage.head.whoWorksWhichShifts")}</h2>
        <div className="row">
          <input className="input sm" type="search" placeholder={t("mfg.shiftsPage.ph.filterByStageLineOr")} aria-label={t("mfg.shiftsPage.aria.filterAssignments")} value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 240 }} />
          <button type="button" className="btn sm primary" onClick={() => setEditing("new")} disabled={templates.length === 0} data-testid="assignment-new">
            <Icon name="plus" /> {t("mfg.shiftsPage.btn.assignShifts")}
          </button>
        </div>
      </div>
      <div className="card-body col">
        <p className="muted small" style={{ margin: 0 }}>
          {tr("mfg.shiftsPage.text.assignATemplateToA")}
        </p>
        <MfgError error={error} onRetry={reload} />
        <MfgError error={delError} title={tr("mfg.shiftsPage.attr.couldNotDelete")} />
        {loading && assignments.length === 0 ? <Spinner /> : null}
        <div className="table-wrap">
          <table className="table" ref={tableRef} data-testid="assignments-table">
            <thead>
              <tr>
                <th>{t("mfg.shiftsPage.head.appliesTo")}</th>
                <th>{t("mfg.shiftsPage.head.kind")}</th>
                <th>{t("mfg.shiftsPage.head.template")}</th>
                <th>{t("mfg.shiftsPage.head.shifts")}</th>
                <th>{t("mfg.shiftsPage.head.when")}</th>
                <th className="num">{t("mfg.shiftsPage.head.extraCostH")}</th>
                <th className="num">{t("mfg.shiftsPage.head.maxHWeek")}</th>
                <th>
                  <span className="sr-only">{tr("mfg.shiftsPage.text.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 ? (
                <tr>
                  <td colSpan={8} className="muted">
                    {tr("mfg.shiftsPage.text.noShiftsAssignedYet")}
                  </td>
                </tr>
              ) : null}
              {shown.map((a) => (
                <tr key={a.id} data-testid="assignment-row" data-assignment-id={a.id} className={a.id === selectedId ? "mfg-selected" : undefined} aria-selected={a.id === selectedId || undefined}>
                  <td>
                    <span className="muted small">{a.target.type === "group" ? tr("mfg.shiftsPage.str.stage") : tr("mfg.shiftsPage.str.line")}</span> <span className="mono">{a.target.code}</span>
                  </td>
                  <td>
                    <KindBadge kind={a.kind} />
                  </td>
                  <td className="mono">{a.template.code}</td>
                  <td className="small">{a.shift_names.length ? a.shift_names.join(", ") : tr("mfg.shiftsPage.str.all")}</td>
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
                        selectInPage(a.id);
                        setEditing(a);
                      }}
                      data-testid="assignment-edit"
                    >
                      {t("mfg.shiftsPage.btn.edit")}
                    </button>
                    <button type="button" className="btn sm ghost icon" aria-label={tr("mfg.shiftsPage.tpl.deleteAssignmentOfTo", { code: a.template.code, code2: a.target.code })} onClick={() => setDel(a)}>
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
            // highlight the new / edited row; do not reopen it for editing
            selectInPage(a.id);
            reload();
          }}
        />
      ) : null}
      <OpenSelected selectedId={selectedId} assignments={assignments} editing={editing} handled={handled} onOpen={setEditing} />
      {del ? (
        <ConfirmDialog
          title={t("mfg.shiftsPage.title.removeThisShiftAssignment")}
          confirmLabel={t("mfg.shiftsPage.btn.remove")}
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
            {tr("mfg.shiftsPage.text.willNoLongerApplyTo", { code: del.template.code, code2: del.target.code })}
          </p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}

/**
 * `?assignment=` from a health link (deep link) opens that assignment's form once. Selections made inside the page
 * (after Assign / Save / Edit) are recorded in `handled` beforehand, so they only highlight the row.
 */
function OpenSelected({
  selectedId,
  assignments,
  editing,
  handled,
  onOpen,
}: {
  selectedId: string | null;
  assignments: ShiftAssignmentRecord[];
  editing: unknown;
  handled: { current: Set<string> };
  onOpen(a: ShiftAssignmentRecord): void;
}) {
  useEffect(() => {
    if (!selectedId || editing || handled.current.has(selectedId)) return;
    const a = assignments.find((x) => x.id === selectedId);
    if (a) {
      handled.current.add(selectedId);
      onOpen(a);
    }
  }, [selectedId, assignments, editing, handled, onOpen]);
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
      title={assignment ? tr("mfg.shiftsPage.str.editShiftAssignment") : tr("mfg.shiftsPage.str.assignShifts")}
      submitLabel={assignment ? tr("mfg.shiftsPage.str.save") : tr("mfg.shiftsPage.str.assign")}
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
      {conflict ? <ConflictBanner onReload={() => window.location.reload()} what={tr("mfg.shiftsPage.attr.thisAssignment")} /> : null}
      <div className="form-grid">
        <SelectField label={t("mfg.shiftsPage.label.shiftTemplate")} value={templateId} onChange={setTemplateId} options={templates.map((t) => ({ value: t.id, label: `${t.code} - ${t.name}` }))} testId="assignment-template" />
        <SelectField
          label={t("mfg.shiftsPage.label.appliesTo")}
          value={targetType}
          onChange={setTargetType}
          options={[
            { value: "group", label: "A whole stage" },
            { value: "line", label: "One line (overrides its stage)" },
          ]}
          testId="assignment-target-type"
        />
        {targetType === "group" ? (
          <SelectField label={t("mfg.shiftsPage.label.stage")} value={groupId} onChange={setGroupId} options={groups.map((g) => ({ value: g.id, label: `${g.code} - ${g.name}` }))} testId="assignment-group" />
        ) : (
          <SelectField label={t("mfg.shiftsPage.label.line")} value={lineId} onChange={setLineId} options={lines.map((l) => ({ value: l.id, label: `${l.code} - ${l.name} (${l.group.code})` }))} testId="assignment-line" />
        )}
        <SelectField
          label={t("mfg.shiftsPage.label.kind")}
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
          <legend>{tr("mfg.shiftsPage.text.shiftsOf", { code: template.code })}</legend>
          <div className="row wrap">
            {template.shifts.map((s) => (
              <label key={s.name} className="checkbox">
                <input type="checkbox" checked={names.includes(s.name)} onChange={(e) => setNames(e.target.checked ? [...names, s.name] : names.filter((n) => n !== s.name))} />
                {s.name} ({s.start}-{s.end})
              </label>
            ))}
          </div>
          <span className="hint">{tr("mfg.shiftsPage.text.noneTickedAllShiftsOf")}</span>
        </fieldset>
      ) : null}
      <div className="form-grid">
        <TextField label={t("mfg.shiftsPage.label.from")} type="date" value={from} onChange={setFrom} hint={from ? undefined : tr("mfg.shiftsPage.tpl.emptyToday", { effFrom: effFrom })} testId="assignment-from" />
        <TextField label={t("mfg.shiftsPage.label.until")} type="date" value={to} onChange={setTo} hint={t("mfg.shiftsPage.hint.exclusiveEmptyNoEnd")} />
        {kind === "optional" ? (
          <>
            <TextField label={t("mfg.shiftsPage.label.extraCostPerHour")} type="number" value={cost} onChange={setCost} hint={t("mfg.shiftsPage.hint.letsThePlannerWeighOvertime")} testId="assignment-cost" />
            <TextField label={t("mfg.shiftsPage.label.maxHoursPerWeek")} type="number" value={maxH} onChange={setMaxH} />
          </>
        ) : null}
      </div>
      <TextField label={t("mfg.shiftsPage.label.note")} value={note} onChange={setNote} maxLength={500} />
    </EntityFormDialog>
  );
}

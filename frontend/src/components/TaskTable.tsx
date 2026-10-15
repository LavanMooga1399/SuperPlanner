import { Fragment, useEffect, useState } from "react";
import type { Dependency, DependencyType, Problem, Task } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, fmtIso, offsetMinutesOf } from "../lib/time";
import { removeDependency, setDependency, updateTask } from "../lib/planEdit";
import { Icon } from "./Icon";
import { DurationInput, NumberInput, PlanDateTimeInput, TextInput } from "./Inputs";
import { RequirementEditor } from "./RequirementEditor";

export const DEP_TYPE_LABEL: Record<DependencyType, string> = {
  FS: "Finish → Start",
  SS: "Start → Start",
  FF: "Finish → Finish",
  SF: "Start → Finish",
};

export const DEP_TYPE_HELP: Record<DependencyType, string> = {
  FS: "starts after the other finishes",
  SS: "starts after the other starts",
  FF: "finishes after the other finishes",
  SF: "finishes after the other starts",
};

function PredecessorEditor({
  task,
  draft,
  onChange,
  terms,
}: {
  task: Task;
  draft: Problem;
  onChange(fn: (p: Problem) => Problem): void;
  terms: Terms;
}) {
  const deps = draft.dependencies.filter((d) => d.successor === task.id);
  const names = new Map(draft.tasks.map((t) => [t.id, t.name]));
  const taken = new Set(deps.map((d) => d.predecessor));
  const candidates = draft.tasks.filter((t) => t.id !== task.id && !taken.has(t.id));
  const [pick, setPick] = useState("");
  const set = (d: Dependency) => onChange((p) => setDependency(p, d));
  return (
    <div className="col">
      {deps.length === 0 ? <div className="small muted">Can start without waiting for another {terms.taskL}.</div> : null}
      {deps.map((d) => (
        <div className="row wrap" key={d.predecessor}>
          <span className="small muted nowrap">After</span>
          <strong className="small">{names.get(d.predecessor) ?? <span style={{ color: "var(--danger)" }}>{d.predecessor} (missing)</span>}</strong>
          <select
            className="select sm"
            style={{ width: 150 }}
            aria-label={`Dependency type after ${names.get(d.predecessor) ?? d.predecessor}`}
            value={d.type}
            onChange={(e) => set({ ...d, type: e.target.value as DependencyType })}
          >
            {(Object.keys(DEP_TYPE_LABEL) as DependencyType[]).map((t) => (
              <option key={t} value={t}>
                {DEP_TYPE_LABEL[t]}
              </option>
            ))}
          </select>
          <span className="small muted">lag</span>
          <NumberInput
            value={d.lag_minutes}
            width={80}
            label={`Lag in minutes after ${names.get(d.predecessor) ?? d.predecessor}`}
            onChange={(v) => set({ ...d, lag_minutes: v })}
          />
          <span className="small faint">min ({fmtDuration(d.lag_minutes)})</span>
          <button
            type="button"
            className="btn ghost sm icon"
            aria-label={`Remove dependency on ${names.get(d.predecessor) ?? d.predecessor}`}
            onClick={() => onChange((p) => removeDependency(p, d.predecessor, task.id))}
          >
            <Icon name="x" />
          </button>
        </div>
      ))}
      <div className="row wrap">
        <select className="select sm" style={{ width: 240 }} value={pick} onChange={(e) => setPick(e.target.value)} aria-label={`Add a predecessor to ${task.name}`}>
          <option value="">Add predecessor…</option>
          {candidates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.id})
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn sm"
          disabled={!pick}
          onClick={() => {
            set({ predecessor: pick, successor: task.id, type: "FS", lag_minutes: 0 });
            setPick("");
          }}
        >
          <Icon name="plus" /> Add
        </button>
      </div>
    </div>
  );
}

function LockEditor({ task, draft, onChange, terms }: { task: Task; draft: Problem; onChange(t: Task): void; terms: Terms }) {
  const off = offsetMinutesOf(draft.horizon_start);
  const names = new Map(draft.resources.map((r) => [r.id, r.name]));
  const lock = task.locked;
  return (
    <div className="col">
      <label className="switch">
        <input
          type="checkbox"
          checked={!!lock}
          onChange={(e) =>
            onChange({
              ...task,
              locked: e.target.checked ? { start: task.earliest_start ?? draft.horizon_start, resource_ids: null } : null,
            })
          }
        />
        <span>Fix this {terms.taskL} at a set time</span>
      </label>
      {lock ? (
        <div className="row wrap">
          <PlanDateTimeInput
            value={lock.start}
            offsetMin={off}
            allowEmpty={false}
            label={`Locked start of ${task.name}`}
            onChange={(v) => v && onChange({ ...task, locked: { ...lock, start: v } })}
          />
          {task.requirements.length > 0 ? (
            <label className="checkbox small">
              <input
                type="checkbox"
                checked={lock.resource_ids !== null}
                onChange={(e) =>
                  onChange({
                    ...task,
                    locked: {
                      ...lock,
                      resource_ids: e.target.checked ? task.requirements.map((r) => r.alternatives[0]) : null,
                    },
                  })
                }
              />
              Also fix the {terms.resourcesL}
            </label>
          ) : null}
          {lock.resource_ids
            ? task.requirements.map((req, i) => (
                <select
                  key={i}
                  className="select sm"
                  style={{ width: 160 }}
                  aria-label={`Locked ${terms.resourceL} for requirement ${i + 1}`}
                  value={lock.resource_ids?.[i] ?? ""}
                  onChange={(e) => {
                    const ids = [...(lock.resource_ids ?? [])];
                    ids[i] = e.target.value;
                    onChange({ ...task, locked: { ...lock, resource_ids: ids } });
                  }}
                >
                  {req.alternatives.map((a) => (
                    <option key={a} value={a}>
                      {names.get(a) ?? a}
                    </option>
                  ))}
                </select>
              ))
            : null}
        </div>
      ) : (
        <div className="small faint">The optimizer decides when it runs.</div>
      )}
    </div>
  );
}

export interface TaskTableProps {
  draft: Problem;
  tasks: Task[];
  terms: Terms;
  update(fn: (p: Problem) => Problem): void;
  onDelete(t: Task): void;
  focusId?: string | null;
  expandedInit?: string | null;
}

export function TaskTable({ draft, tasks, terms, update, onDelete, focusId, expandedInit }: TaskTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(expandedInit ? [expandedInit] : []));
  const off = offsetMinutesOf(draft.horizon_start);
  const resNames = new Map(draft.resources.map((r) => [r.id, r.name]));
  const taskNames = new Map(draft.tasks.map((t) => [t.id, t.name]));
  const groups = Array.from(new Set(draft.tasks.map((t) => t.group).filter((g): g is string => !!g)));

  useEffect(() => {
    if (focusId) {
      setExpanded((s) => new Set(s).add(focusId));
      const el = document.querySelector(`[data-testid="task-row-${CSS.escape(focusId)}"]`);
      el?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [focusId]);

  const setTask = (id: string, fn: (t: Task) => Task) => update((p) => updateTask(p, id, fn));
  const toggle = (id: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div className="table-wrap" style={{ maxHeight: "70vh" }}>
      <datalist id="group-options">
        {groups.map((g) => (
          <option key={g} value={g} />
        ))}
      </datalist>
      <table className="table">
        <thead>
          <tr>
            <th style={{ width: 28 }}>
              <span className="sr-only">Details</span>
            </th>
            <th>Id</th>
            <th>Name</th>
            <th>{terms.group}</th>
            <th>Type</th>
            <th>Duration</th>
            <th title="10 = most important">Priority</th>
            <th>Earliest start</th>
            <th>{terms.deadline}</th>
            <th>{terms.resources}</th>
            <th>After</th>
            <th>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => {
            const open = expanded.has(t.id);
            const preds = draft.dependencies.filter((d) => d.successor === t.id);
            const isMilestone = t.type === "milestone";
            return (
              <Fragment key={t.id}>
                <tr data-testid={`task-row-${t.id}`} className={focusId === t.id ? "highlight" : undefined}>
                  <td>
                    <button
                      type="button"
                      className="btn ghost sm icon"
                      aria-expanded={open}
                      aria-label={`${open ? "Hide" : "Show"} details of ${t.name}`}
                      onClick={() => toggle(t.id)}
                    >
                      <Icon name={open ? "chevron-down" : "chevron-right"} />
                    </button>
                  </td>
                  <td className="mono faint nowrap">{t.id}</td>
                  <td style={{ minWidth: 180 }}>
                    <div className="row">
                      {t.locked ? <Icon name="lock" title="Fixed time" /> : null}
                      <TextInput
                        value={t.name}
                        required
                        label={`Name of ${t.id}`}
                        className="input sm"
                        onChange={(v) => setTask(t.id, (x) => ({ ...x, name: v }))}
                      />
                    </div>
                  </td>
                  <td style={{ minWidth: 100 }}>
                    <input
                      className="input sm"
                      list="group-options"
                      defaultValue={t.group ?? ""}
                      key={t.group ?? ""}
                      aria-label={`${terms.group} of ${t.name}`}
                      onBlur={(e) => {
                        const v = e.target.value.trim() || null;
                        if (v !== t.group) setTask(t.id, (x) => ({ ...x, group: v }));
                      }}
                    />
                  </td>
                  <td>
                    <select
                      className="select sm"
                      style={{ width: 110 }}
                      value={t.type}
                      aria-label={`Type of ${t.name}`}
                      onChange={(e) => {
                        const type = e.target.value as Task["type"];
                        setTask(t.id, (x) =>
                          type === "milestone"
                            ? { ...x, type, duration_minutes: 0, requirements: [], locked: x.locked ? { ...x.locked, resource_ids: null } : null }
                            : { ...x, type, duration_minutes: x.duration_minutes || 60 },
                        );
                      }}
                    >
                      <option value="activity">{terms.task}</option>
                      <option value="milestone">{terms.milestone}</option>
                    </select>
                  </td>
                  <td>
                    {isMilestone ? (
                      <span className="faint small">-</span>
                    ) : (
                      <DurationInput
                        value={t.duration_minutes}
                        label={`Duration of ${t.name}`}
                        onChange={(v) => setTask(t.id, (x) => ({ ...x, duration_minutes: v }))}
                      />
                    )}
                  </td>
                  <td>
                    <NumberInput
                      value={t.priority}
                      min={1}
                      max={10}
                      width={58}
                      label={`Priority of ${t.name}`}
                      onChange={(v) => setTask(t.id, (x) => ({ ...x, priority: v }))}
                    />
                  </td>
                  <td>
                    <PlanDateTimeInput
                      value={t.earliest_start}
                      offsetMin={off}
                      label={`Earliest start of ${t.name}`}
                      onChange={(v) => setTask(t.id, (x) => ({ ...x, earliest_start: v }))}
                    />
                  </td>
                  <td>
                    <div className="row">
                      <PlanDateTimeInput
                        value={t.deadline}
                        offsetMin={off}
                        label={`${terms.deadline} of ${t.name}`}
                        onChange={(v) => setTask(t.id, (x) => ({ ...x, deadline: v, deadline_hard: v ? x.deadline_hard : false }))}
                      />
                      <label className="checkbox small" title="A hard deadline must be met; a soft one may be missed (counts as lateness).">
                        <input
                          type="checkbox"
                          checked={t.deadline_hard}
                          disabled={!t.deadline}
                          onChange={(e) => setTask(t.id, (x) => ({ ...x, deadline_hard: e.target.checked }))}
                        />
                        Must
                      </label>
                    </div>
                  </td>
                  <td className="small" style={{ maxWidth: 200 }}>
                    {isMilestone ? (
                      <span className="faint">-</span>
                    ) : t.requirements.length === 0 ? (
                      <button type="button" className="btn ghost sm" onClick={() => toggle(t.id)}>
                        <span className="faint">None</span>
                      </button>
                    ) : (
                      <button type="button" className="btn ghost sm" onClick={() => toggle(t.id)} style={{ maxWidth: 200 }}>
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                          {t.requirements
                            .map((r) => (r.units > 1 ? `${r.units}× ` : "") + r.alternatives.map((a) => resNames.get(a) ?? `${a}?`).join(" / "))
                            .join(" + ")}
                        </span>
                      </button>
                    )}
                  </td>
                  <td className="small" style={{ maxWidth: 180 }}>
                    <button type="button" className="btn ghost sm" onClick={() => toggle(t.id)} style={{ maxWidth: 180 }}>
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis" }} className={preds.length ? "" : "faint"}>
                        {preds.length ? preds.map((d) => taskNames.get(d.predecessor) ?? `${d.predecessor}?`).join(", ") : "None"}
                      </span>
                    </button>
                  </td>
                  <td>
                    <button type="button" className="btn ghost sm icon" aria-label={`Delete ${t.name}`} title="Delete" onClick={() => onDelete(t)}>
                      <Icon name="trash" />
                    </button>
                  </td>
                </tr>
                {open ? (
                  <tr className="expand-row">
                    <td />
                    <td colSpan={11}>
                      <div className="grid-2" style={{ padding: "8px 0" }}>
                        <div className="col">
                          <h3>{terms.resources} needed</h3>
                          {isMilestone ? (
                            <div className="small muted">A {terms.milestone.toLowerCase()} takes no time and needs no {terms.resourceL}.</div>
                          ) : (
                            <RequirementEditor
                              value={t.requirements}
                              resources={draft.resources}
                              terms={terms}
                              taskName={t.name}
                              onChange={(reqs) =>
                                setTask(t.id, (x) => ({
                                  ...x,
                                  requirements: reqs,
                                  locked: x.locked && x.locked.resource_ids && x.locked.resource_ids.length !== reqs.length ? { ...x.locked, resource_ids: null } : x.locked,
                                }))
                              }
                            />
                          )}
                          <h3 className="mt">Description</h3>
                          <textarea
                            className="textarea"
                            defaultValue={t.description}
                            key={t.description}
                            aria-label={`Description of ${t.name}`}
                            onBlur={(e) => e.target.value !== t.description && setTask(t.id, (x) => ({ ...x, description: e.target.value }))}
                          />
                        </div>
                        <div className="col">
                          <h3>Waits for</h3>
                          <PredecessorEditor task={t} draft={draft} onChange={update} terms={terms} />
                          <h3 className="mt">Fixed time</h3>
                          <LockEditor task={t} draft={draft} terms={terms} onChange={(nt) => setTask(t.id, () => nt)} />
                          {t.locked ? <div className="small faint">Fixed at {fmtIso(t.locked.start, off)}</div> : null}
                        </div>
                      </div>
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

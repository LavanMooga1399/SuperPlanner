import { Fragment, useEffect, useState } from "react";
import { WEEKDAYS, type Calendar, type Problem, type Resource } from "../api/types";
import type { Terms } from "../lib/terms";
import { hhmmToMin, updateResource } from "../lib/planEdit";
import { fmtDuration, offsetMinutesOf } from "../lib/time";
import { CalendarEditor } from "./CalendarEditor";
import { Icon } from "./Icon";
import { NumberInput, TextInput } from "./Inputs";

const KINDS = ["generic", "person", "machine", "room", "team", "time"];

export function calendarSummary(cal: Calendar | null): string {
  if (!cal) return "Always available";
  const blocked = cal.blocked.length ? `, ${cal.blocked.length} blocked` : "";
  if (cal.weekly === null) return `24/7${blocked}`;
  let minutes = 0;
  let days = 0;
  for (const d of WEEKDAYS) {
    const w = cal.weekly[d] ?? [];
    if (w.length) days++;
    for (const [a, b] of w) minutes += Math.max(0, hhmmToMin(b) - hhmmToMin(a));
  }
  return `${days} day${days === 1 ? "" : "s"}, ${fmtDuration(minutes)}/week${blocked}`;
}

export function ResourceTable({
  draft,
  terms,
  update,
  onDelete,
  focusId,
}: {
  draft: Problem;
  terms: Terms;
  update(fn: (p: Problem) => Problem): void;
  onDelete(r: Resource): void;
  focusId?: string | null;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(focusId ? [focusId] : []));
  const off = offsetMinutesOf(draft.horizon_start);
  const usage = new Map<string, number>();
  for (const t of draft.tasks) for (const r of t.requirements) for (const a of r.alternatives) usage.set(a, (usage.get(a) ?? 0) + 1);

  useEffect(() => {
    if (focusId) {
      setExpanded((s) => new Set(s).add(focusId));
      document.querySelector(`[data-testid="resource-row-${CSS.escape(focusId)}"]`)?.scrollIntoView({ block: "center" });
    }
  }, [focusId]);

  const setRes = (id: string, fn: (r: Resource) => Resource) => update((p) => updateResource(p, id, fn));
  const toggle = (id: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div className="table-wrap" style={{ maxHeight: "72vh" }}>
      <table className="table">
        <thead>
          <tr>
            <th style={{ width: 28 }}><span className="sr-only">Details</span></th>
            <th>Id</th>
            <th>Name</th>
            <th>Kind</th>
            <th className="num" title="How many can be used at the same time">Capacity</th>
            <th className="num">Cost / hour ({draft.currency})</th>
            <th>Availability</th>
            <th className="num">Used by</th>
            <th><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {draft.resources.map((r) => {
            const open = expanded.has(r.id);
            const used = usage.get(r.id) ?? 0;
            return (
              <Fragment key={r.id}>
                <tr data-testid={`resource-row-${r.id}`} className={focusId === r.id ? "highlight" : undefined}>
                  <td>
                    <button type="button" className="btn ghost sm icon" aria-expanded={open} aria-label={`${open ? "Hide" : "Show"} availability of ${r.name}`} onClick={() => toggle(r.id)}>
                      <Icon name={open ? "chevron-down" : "chevron-right"} />
                    </button>
                  </td>
                  <td className="mono faint">{r.id}</td>
                  <td style={{ minWidth: 180 }}>
                    <TextInput value={r.name} required label={`Name of ${r.id}`} onChange={(v) => setRes(r.id, (x) => ({ ...x, name: v }))} />
                  </td>
                  <td>
                    <select className="select sm" style={{ width: 110 }} value={KINDS.includes(r.kind) ? r.kind : "__other"} aria-label={`Kind of ${r.name}`} onChange={(e) => e.target.value !== "__other" && setRes(r.id, (x) => ({ ...x, kind: e.target.value }))}>
                      {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                      {!KINDS.includes(r.kind) ? <option value="__other">{r.kind}</option> : null}
                    </select>
                  </td>
                  <td className="num">
                    <NumberInput value={r.capacity} min={1} max={1000} width={70} label={`Capacity of ${r.name}`} onChange={(v) => setRes(r.id, (x) => ({ ...x, capacity: v }))} />
                  </td>
                  <td className="num">
                    <NumberInput value={r.cost_per_hour} min={0} step={0.01} width={96} label={`Cost per hour of ${r.name}`} onChange={(v) => setRes(r.id, (x) => ({ ...x, cost_per_hour: v }))} />
                  </td>
                  <td>
                    <button type="button" className="btn ghost sm" onClick={() => toggle(r.id)}>
                      <Icon name="calendar" /> {calendarSummary(r.calendar)}
                    </button>
                  </td>
                  <td className="num">
                    {used ? `${used} ${used === 1 ? terms.taskL : terms.tasksL}` : <span className="badge warn"><Icon name="alert" /> Unused</span>}
                  </td>
                  <td>
                    <button type="button" className="btn ghost sm icon" aria-label={`Delete ${r.name}`} title="Delete" onClick={() => onDelete(r)}>
                      <Icon name="trash" />
                    </button>
                  </td>
                </tr>
                {open ? (
                  <tr className="expand-row">
                    <td />
                    <td colSpan={8}>
                      <div style={{ padding: "8px 0", maxWidth: 820 }}>
                        <CalendarEditor value={r.calendar} offsetMin={off} resourceName={r.name} onChange={(c) => setRes(r.id, (x) => ({ ...x, calendar: c }))} />
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

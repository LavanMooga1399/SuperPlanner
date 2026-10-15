import type { Requirement, Resource } from "../api/types";
import type { Terms } from "../lib/terms";
import { Icon } from "./Icon";
import { MultiSelect, NumberInput } from "./Inputs";

/**
 * One row per requirement: which resources may do it (alternatives, in preference
 * order) and how many units it needs. A task needs all requirements at once.
 */
export function RequirementEditor({
  value,
  onChange,
  resources,
  terms,
  taskName,
}: {
  value: Requirement[];
  onChange(v: Requirement[]): void;
  resources: Resource[];
  terms: Terms;
  taskName: string;
}) {
  const options = resources.map((r) => ({ value: r.id, label: r.name, hint: r.capacity > 1 ? `cap ${r.capacity}` : undefined }));
  const known = new Set(resources.map((r) => r.id));
  const set = (i: number, r: Requirement) => onChange(value.map((x, k) => (k === i ? r : x)));
  return (
    <div className="col">
      {value.length === 0 ? (
        <div className="small muted">No {terms.resourceL} needed. This {terms.taskL} is not bound to any calendar.</div>
      ) : null}
      {value.map((req, i) => {
        const unknown = req.alternatives.filter((a) => !known.has(a));
        return (
          <div className="row wrap" key={i}>
            <span className="small muted nowrap" style={{ width: 92 }}>
              Needs {i === 0 ? "" : "also "}
            </span>
            <NumberInput
              value={req.units}
              min={1}
              max={1000}
              width={60}
              label={`${taskName}: units for requirement ${i + 1}`}
              onChange={(u) => set(i, { ...req, units: u })}
            />
            <span className="small muted">× one of</span>
            <MultiSelect
              label={`${taskName}: ${terms.resources} for requirement ${i + 1}`}
              options={options}
              value={req.alternatives.filter((a) => known.has(a))}
              ordered
              placeholder={`Choose ${terms.resourcesL}`}
              onChange={(alts) => {
                const next = [...alts, ...unknown];
                if (next.length === 0) onChange(value.filter((_, k) => k !== i));
                else set(i, { ...req, alternatives: next });
              }}
            />
            {unknown.length ? (
              <span className="badge danger" title="These ids do not match any resource">
                <Icon name="alert" /> Unknown: {unknown.join(", ")}
              </span>
            ) : null}
            <button
              type="button"
              className="btn ghost sm icon"
              aria-label={`Remove requirement ${i + 1} of ${taskName}`}
              onClick={() => onChange(value.filter((_, k) => k !== i))}
            >
              <Icon name="x" />
            </button>
          </div>
        );
      })}
      <div>
        <button
          type="button"
          className="btn sm"
          disabled={resources.length === 0}
          title={resources.length === 0 ? `Add ${terms.resourcesL} first` : undefined}
          onClick={() => {
            const used = new Set(value.flatMap((r) => r.alternatives));
            const first = resources.find((r) => !used.has(r.id)) ?? resources[0];
            onChange([...value, { alternatives: [first.id], units: 1 }]);
          }}
        >
          <Icon name="plus" /> Add {terms.resourceL} requirement
        </button>
      </div>
      {value.length > 1 ? (
        <div className="small faint">The {terms.taskL} needs all of these at the same time, each from a different {terms.resourceL}.</div>
      ) : null}
    </div>
  );
}

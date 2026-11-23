import type { Requirement, Resource } from "../api/types";
import type { Terms } from "../lib/terms";
import { Icon } from "./Icon";
import { MultiSelect, NumberInput } from "./Inputs";
import { t } from "../lib/i18n";

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
        <div className="small muted">{t("studio.requirementEditor.text.noNeededThisIsNot", { resourceL: terms.resourceL, taskL: terms.taskL })}</div>
      ) : null}
      {value.map((req, i) => {
        const unknown = req.alternatives.filter((a) => !known.has(a));
        return (
          <div className="row wrap" key={i}>
            <span className="small muted nowrap" style={{ width: 92 }}>
              {t("studio.requirementEditor.text.needs", { v: i === 0 ? "" : "also " })}
            </span>
            <NumberInput
              value={req.units}
              min={1}
              max={1000}
              width={60}
              label={t("studio.requirementEditor.tpl.unitsForRequirement", { taskName: taskName, v: i + 1 })}
              onChange={(u) => set(i, { ...req, units: u })}
            />
            <span className="small muted">{t("studio.requirementEditor.text.oneOf")}</span>
            <MultiSelect
              label={t("studio.requirementEditor.tpl.forRequirement", { taskName: taskName, resources: terms.resources, v: i + 1 })}
              options={options}
              value={req.alternatives.filter((a) => known.has(a))}
              ordered
              placeholder={t("studio.requirementEditor.tpl.choose", { resourcesL: terms.resourcesL })}
              onChange={(alts) => {
                const next = [...alts, ...unknown];
                if (next.length === 0) onChange(value.filter((_, k) => k !== i));
                else set(i, { ...req, alternatives: next });
              }}
            />
            {unknown.length ? (
              <span className="badge danger" title={t("studio.requirementEditor.attr.theseIdsDoNotMatch")}>
                <Icon name="alert" />{" "}{t("studio.requirementEditor.text.unknown", { unknown: unknown.join(", ") })}
              </span>
            ) : null}
            <button
              type="button"
              className="btn ghost sm icon"
              aria-label={t("studio.requirementEditor.tpl.removeRequirement", { t: t("common.nOfM", { n: i + 1, m: taskName }) })}
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
          title={resources.length === 0 ? t("studio.requirementEditor.tpl.addFirst", { resourcesL: terms.resourcesL }) : undefined}
          onClick={() => {
            const used = new Set(value.flatMap((r) => r.alternatives));
            const first = resources.find((r) => !used.has(r.id)) ?? resources[0];
            onChange([...value, { alternatives: [first.id], units: 1 }]);
          }}
        >
          <Icon name="plus" />{" "}{t("studio.requirementEditor.text.addRequirement", { resourceL: terms.resourceL })}
        </button>
      </div>
      {value.length > 1 ? (
        <div className="small faint">{t("studio.requirementEditor.text.theNeedsAllOfThese", { taskL: terms.taskL, resourceL: terms.resourceL })}</div>
      ) : null}
    </div>
  );
}

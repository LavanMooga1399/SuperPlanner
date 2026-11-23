import { PRESET_WEIGHTS, type Objectives, type Preset, type Weights } from "../api/types";
import type { Terms } from "../lib/terms";
import { Icon, type IconName } from "./Icon";
import { t, t as tr } from "../lib/i18n";

const PRESETS: Array<{ id: Exclude<Preset, "custom">; label: string; icon: IconName; desc: (t: Terms) => string }> = [
  { id: "balanced", label: tr("studio.goalPresetPicker.str.balanced"), icon: "star", desc: (t) => tr("studio.goalPresetPicker.tpl.finishEarlyKeepSAnd", { deadlineL: t.deadlineL }) },
  { id: "finish_asap", label: tr("studio.goalPresetPicker.str.finishAsap"), icon: "play", desc: (t) => tr("studio.goalPresetPicker.tpl.completeAllAsEarlyAs", { tasksL: t.tasksL }) },
  { id: "meet_deadlines", label: tr("studio.goalPresetPicker.str.meetDeadlines"), icon: "flag", desc: (t) => tr("studio.goalPresetPicker.tpl.avoidLateImportantOnesFirst", { tasksL: t.tasksL }) },
  { id: "lowest_cost", label: tr("studio.goalPresetPicker.str.lowestCost"), icon: "briefcase", desc: (t) => tr("studio.goalPresetPicker.tpl.preferCheaperEvenIfIt", { resourcesL: t.resourcesL }) },
];

export function GoalPresetPicker({
  value,
  onChange,
  terms,
  expert,
}: {
  value: Objectives;
  onChange(o: Objectives): void;
  terms: Terms;
  expert: boolean;
}) {
  const setWeight = (k: keyof Weights, v: number) => onChange({ preset: "custom", weights: { ...value.weights, [k]: v } });
  const allZero = value.preset === "custom" && value.weights.makespan <= 0 && value.weights.tardiness <= 0 && value.weights.cost <= 0;
  return (
    <div className="col">
      <div className="preset-grid" role="radiogroup" aria-label={t("studio.goalPresetPicker.aria.goal")}>
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            role="radio"
            aria-checked={value.preset === p.id}
            className="preset"
            data-testid={`preset-${p.id}`}
            onClick={() => onChange({ preset: p.id, weights: { ...PRESET_WEIGHTS[p.id] } })}
          >
            <span className="preset-title">
              <Icon name={value.preset === p.id ? "check" : p.icon} />
              {p.label}
            </span>
            <span className="preset-desc">{p.desc(terms)}</span>
          </button>
        ))}
        {expert ? (
          <button
            type="button"
            role="radio"
            aria-checked={value.preset === "custom"}
            className="preset"
            onClick={() => onChange({ preset: "custom", weights: value.preset === "custom" ? value.weights : { ...PRESET_WEIGHTS[value.preset] } })}
          >
            <span className="preset-title">
              <Icon name={value.preset === "custom" ? "check" : "settings"} />
              {tr("studio.goalPresetPicker.text.customWeights")}
            </span>
            <span className="preset-desc">{tr("studio.goalPresetPicker.text.setYourOwnBalanceBetween")}</span>
          </button>
        ) : null}
      </div>
      {expert && value.preset === "custom" ? (
        <div className="form-grid">
          {(
            [
              ["makespan", tr("studio.goalPresetPicker.str.totalDuration")],
              ["tardiness", tr("studio.goalPresetPicker.str.latenessWeightedByPriority")],
              ["cost", tr("studio.goalPresetPicker.str.cost")],
            ] as Array<[keyof Weights, string]>
          ).map(([k, label]) => (
            <div className="field" key={k}>
              <label htmlFor={`w-${k}`}>
                {label}: {value.weights[k].toFixed(1)}
              </label>
              <input id={`w-${k}`} type="range" min={0} max={2} step={0.1} value={value.weights[k]} onChange={(e) => setWeight(k, Number(e.target.value))} />
            </div>
          ))}
          {allZero ? (
            <div className="small" style={{ color: "var(--danger)" }} role="alert">
              {tr("studio.goalPresetPicker.text.atLeastOneWeightMust")}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

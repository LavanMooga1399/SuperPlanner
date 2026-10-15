import { PRESET_WEIGHTS, type Objectives, type Preset, type Weights } from "../api/types";
import type { Terms } from "../lib/terms";
import { Icon, type IconName } from "./Icon";

const PRESETS: Array<{ id: Exclude<Preset, "custom">; label: string; icon: IconName; desc: (t: Terms) => string }> = [
  { id: "balanced", label: "Balanced", icon: "star", desc: (t) => `Finish early, keep ${t.deadlineL}s and watch costs - a sensible default.` },
  { id: "finish_asap", label: "Finish ASAP", icon: "play", desc: (t) => `Complete all ${t.tasksL} as early as possible.` },
  { id: "meet_deadlines", label: "Meet deadlines", icon: "flag", desc: (t) => `Avoid late ${t.tasksL}, important ones first.` },
  { id: "lowest_cost", label: "Lowest cost", icon: "briefcase", desc: (t) => `Prefer cheaper ${t.resourcesL}, even if it takes longer.` },
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
      <div className="preset-grid" role="radiogroup" aria-label="Goal">
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
              Custom weights
            </span>
            <span className="preset-desc">Set your own balance between duration, lateness and cost.</span>
          </button>
        ) : null}
      </div>
      {expert && value.preset === "custom" ? (
        <div className="form-grid">
          {(
            [
              ["makespan", "Total duration"],
              ["tardiness", "Lateness (weighted by priority)"],
              ["cost", "Cost"],
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
              At least one weight must be above zero.
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

import { DEFAULT_CPSAT_PARAMS, DEFAULT_GA_PARAMS, type CpSatParams, type GaParams, type Strategy } from "../api/types";
import { NumberInput } from "./Inputs";

export interface ExpertValues {
  strategy: Strategy;
  seed: number;
  max_alternatives: number;
  ga: GaParams;
  cpsat: CpSatParams;
}

export const DEFAULT_EXPERT: ExpertValues = {
  strategy: "auto",
  seed: 0,
  max_alternatives: 2,
  ga: { ...DEFAULT_GA_PARAMS },
  cpsat: { ...DEFAULT_CPSAT_PARAMS },
};

const STRATEGIES: Array<{ id: Strategy; label: string; desc: string }> = [
  { id: "auto", label: "Automatic", desc: "Picks a method from the problem size and time budget (recommended)." },
  { id: "heuristic", label: "Priority rules only", desc: "Very fast, good first schedule." },
  { id: "cpsat", label: "Constraint solver (CP-SAT)", desc: "Exact; can prove a schedule is optimal on small and medium plans." },
  { id: "ga", label: "Genetic algorithm", desc: "Scales to large plans; improves over generations." },
  { id: "hybrid", label: "Hybrid", desc: "Constraint solver for 60% of the budget, then the genetic algorithm." },
];

const GA_FIELDS: Array<{ k: keyof GaParams; label: string; min: number; max: number; step: number }> = [
  { k: "max_generations", label: "Max generations", min: 1, max: 10000, step: 1 },
  { k: "stagnation_generations", label: "Stop after no improvement for", min: 5, max: 1000, step: 1 },
  { k: "crossover_rate", label: "Crossover rate", min: 0, max: 1, step: 0.05 },
  { k: "mutation_rate", label: "Mutation rate", min: 0.01, max: 0.5, step: 0.01 },
  { k: "mutation_sigma", label: "Mutation sigma", min: 0.01, max: 0.5, step: 0.01 },
  { k: "swap_rate", label: "Swap rate", min: 0, max: 1, step: 0.05 },
  { k: "elite_count", label: "Elite count", min: 0, max: 10, step: 1 },
  { k: "tournament_size", label: "Tournament size", min: 2, max: 10, step: 1 },
  { k: "archive_size", label: "Archive size", min: 1, max: 50, step: 1 },
];

export function ExpertSettings({ value, onChange }: { value: ExpertValues; onChange(v: ExpertValues): void }) {
  const showGa = value.strategy === "ga" || value.strategy === "hybrid" || value.strategy === "auto";
  const showCp = value.strategy === "cpsat" || value.strategy === "hybrid" || value.strategy === "auto";
  return (
    <div className="col" data-testid="expert-settings">
      <div className="form-grid">
        <div className="field" style={{ gridColumn: "span 2" }}>
          <label htmlFor="ex-strategy">Method</label>
          <select id="ex-strategy" className="select" value={value.strategy} onChange={(e) => onChange({ ...value, strategy: e.target.value as Strategy })}>
            {STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <span className="hint">{STRATEGIES.find((s) => s.id === value.strategy)?.desc}</span>
        </div>
        <div className="field">
          <label htmlFor="ex-seed">Random seed</label>
          <NumberInput id="ex-seed" className="input" value={value.seed} width={120} label="Random seed" onChange={(v) => onChange({ ...value, seed: v })} />
          <span className="hint">Same seed, same result (when stopped by generations).</span>
        </div>
        <div className="field">
          <label htmlFor="ex-alt">Alternative schedules</label>
          <NumberInput id="ex-alt" className="input" value={value.max_alternatives} min={0} max={5} width={120} label="Alternative schedules" onChange={(v) => onChange({ ...value, max_alternatives: v })} />
        </div>
      </div>
      {showCp ? (
        <fieldset className="card card-body" style={{ margin: 0 }}>
          <legend className="field-label">Constraint solver</legend>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="ex-workers">Workers</label>
              <NumberInput id="ex-workers" className="input" value={value.cpsat.num_workers} min={1} max={64} width={120} label="CP-SAT workers" onChange={(v) => onChange({ ...value, cpsat: { ...value.cpsat, num_workers: v } })} />
            </div>
            <div className="field">
              <label htmlFor="ex-gap">Accept gap</label>
              <NumberInput id="ex-gap" className="input" value={value.cpsat.relative_gap} min={0} max={1} step={0.01} width={120} label="CP-SAT relative gap" onChange={(v) => onChange({ ...value, cpsat: { ...value.cpsat, relative_gap: v } })} />
              <span className="hint">0 = prove optimal</span>
            </div>
          </div>
        </fieldset>
      ) : null}
      {showGa ? (
        <fieldset className="card card-body" style={{ margin: 0 }}>
          <legend className="field-label">Genetic algorithm</legend>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="ex-pop">Population size</label>
              <input
                id="ex-pop"
                className="input"
                type="number"
                min={10}
                max={300}
                placeholder="auto"
                value={value.ga.population_size ?? ""}
                onChange={(e) => onChange({ ...value, ga: { ...value.ga, population_size: e.target.value === "" ? null : Math.max(10, Math.min(300, Number(e.target.value))) } })}
              />
              <span className="hint">Empty = automatic</span>
            </div>
            {GA_FIELDS.map((f) => (
              <div className="field" key={f.k}>
                <label htmlFor={`ex-ga-${f.k}`}>{f.label}</label>
                <NumberInput
                  id={`ex-ga-${f.k}`}
                  className="input"
                  value={value.ga[f.k] as number}
                  min={f.min}
                  max={f.max}
                  step={f.step}
                  width={120}
                  label={f.label}
                  onChange={(v) => onChange({ ...value, ga: { ...value.ga, [f.k]: v } })}
                />
              </div>
            ))}
          </div>
        </fieldset>
      ) : null}
      <div>
        <button type="button" className="btn sm ghost" onClick={() => onChange({ ...DEFAULT_EXPERT, ga: { ...DEFAULT_GA_PARAMS }, cpsat: { ...DEFAULT_CPSAT_PARAMS } })}>
          Reset to defaults
        </button>
      </div>
    </div>
  );
}

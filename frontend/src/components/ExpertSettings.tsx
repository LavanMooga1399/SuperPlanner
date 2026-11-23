import { DEFAULT_CPSAT_PARAMS, DEFAULT_GA_PARAMS, type CpSatParams, type GaParams, type Strategy } from "../api/types";
import { NumberInput } from "./Inputs";
import { t } from "../lib/i18n";

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
  { id: "auto", label: t("studio.expertSettings.str.automatic"), desc: t("studio.expertSettings.str.picksAMethodFromThe") },
  { id: "heuristic", label: t("studio.expertSettings.str.priorityRulesOnly"), desc: t("studio.expertSettings.str.veryFastGoodFirstSchedule") },
  { id: "cpsat", label: t("studio.expertSettings.str.constraintSolverCpSat"), desc: t("studio.expertSettings.str.exactCanProveASchedule") },
  { id: "ga", label: t("studio.expertSettings.str.geneticAlgorithm"), desc: t("studio.expertSettings.str.scalesToLargePlansImproves") },
  { id: "hybrid", label: t("studio.expertSettings.str.hybrid"), desc: t("studio.expertSettings.str.constraintSolverFor60Of") },
];

const GA_FIELDS: Array<{ k: keyof GaParams; label: string; min: number; max: number; step: number }> = [
  { k: "max_generations", label: t("studio.expertSettings.str.maxGenerations"), min: 1, max: 10000, step: 1 },
  { k: "stagnation_generations", label: t("studio.expertSettings.str.stopAfterNoImprovementFor"), min: 5, max: 1000, step: 1 },
  { k: "crossover_rate", label: t("studio.expertSettings.str.crossoverRate"), min: 0, max: 1, step: 0.05 },
  { k: "mutation_rate", label: t("studio.expertSettings.str.mutationRate"), min: 0.01, max: 0.5, step: 0.01 },
  { k: "mutation_sigma", label: t("studio.expertSettings.str.mutationSigma"), min: 0.01, max: 0.5, step: 0.01 },
  { k: "swap_rate", label: t("studio.expertSettings.str.swapRate"), min: 0, max: 1, step: 0.05 },
  { k: "elite_count", label: t("studio.expertSettings.str.eliteCount"), min: 0, max: 10, step: 1 },
  { k: "tournament_size", label: t("studio.expertSettings.str.tournamentSize"), min: 2, max: 10, step: 1 },
  { k: "archive_size", label: t("studio.expertSettings.str.archiveSize"), min: 1, max: 50, step: 1 },
];

export function ExpertSettings({ value, onChange }: { value: ExpertValues; onChange(v: ExpertValues): void }) {
  const showGa = value.strategy === "ga" || value.strategy === "hybrid" || value.strategy === "auto";
  const showCp = value.strategy === "cpsat" || value.strategy === "hybrid" || value.strategy === "auto";
  return (
    <div className="col" data-testid="expert-settings">
      <div className="form-grid">
        <div className="field" style={{ gridColumn: "span 2" }}>
          <label htmlFor="ex-strategy">{t("studio.expertSettings.label.method")}</label>
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
          <label htmlFor="ex-seed">{t("studio.expertSettings.label.randomSeed")}</label>
          <NumberInput id="ex-seed" className="input" value={value.seed} width={120} label={t("studio.expertSettings.label.randomSeed")} onChange={(v) => onChange({ ...value, seed: v })} />
          <span className="hint">{t("studio.expertSettings.text.sameSeedSameResultWhen")}</span>
        </div>
        <div className="field">
          <label htmlFor="ex-alt">{t("studio.expertSettings.label.alternativeSchedules")}</label>
          <NumberInput id="ex-alt" className="input" value={value.max_alternatives} min={0} max={5} width={120} label={t("studio.expertSettings.label.alternativeSchedules")} onChange={(v) => onChange({ ...value, max_alternatives: v })} />
        </div>
      </div>
      {showCp ? (
        <fieldset className="card card-body" style={{ margin: 0 }}>
          <legend className="field-label">{t("studio.expertSettings.head.constraintSolver")}</legend>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="ex-workers">{t("studio.expertSettings.label.workers")}</label>
              <NumberInput id="ex-workers" className="input" value={value.cpsat.num_workers} min={1} max={64} width={120} label={t("studio.expertSettings.label.cpsatWorkers")} onChange={(v) => onChange({ ...value, cpsat: { ...value.cpsat, num_workers: v } })} />
            </div>
            <div className="field">
              <label htmlFor="ex-gap">{t("studio.expertSettings.label.acceptGap")}</label>
              <NumberInput id="ex-gap" className="input" value={value.cpsat.relative_gap} min={0} max={1} step={0.01} width={120} label={t("studio.expertSettings.label.cpsatRelativeGap")} onChange={(v) => onChange({ ...value, cpsat: { ...value.cpsat, relative_gap: v } })} />
              <span className="hint">{t("studio.expertSettings.text.0ProveOptimal")}</span>
            </div>
          </div>
        </fieldset>
      ) : null}
      {showGa ? (
        <fieldset className="card card-body" style={{ margin: 0 }}>
          <legend className="field-label">{t("studio.expertSettings.head.geneticAlgorithm")}</legend>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="ex-pop">{t("studio.expertSettings.label.populationSize")}</label>
              <input
                id="ex-pop"
                className="input"
                type="number"
                min={10}
                max={300}
                placeholder={t("studio.expertSettings.ph.auto")}
                value={value.ga.population_size ?? ""}
                onChange={(e) => onChange({ ...value, ga: { ...value.ga, population_size: e.target.value === "" ? null : Math.max(10, Math.min(300, Number(e.target.value))) } })}
              />
              <span className="hint">{t("studio.expertSettings.text.emptyAutomatic")}</span>
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
          {t("studio.expertSettings.btn.resetToDefaults")}
        </button>
      </div>
    </div>
  );
}

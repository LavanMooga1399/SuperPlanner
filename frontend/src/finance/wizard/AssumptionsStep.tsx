import { useState } from "react";
import { Term } from "../../components/Term";
import { errorMessage } from "../../api/client";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { getFinanceDefaults } from "../api/client";
import type { CautionSettings, GlideStep } from "../api/types";
import { AssetClassTable } from "../components/AssetClassTable";
import type { StepProps } from "./common";
import { Field, FinNumber, FinOptionalNumber, MoneyInput, Select } from "./fields";
import { HelpText } from "./HelpText";

/** Server defaults of PHASE2 1.5, used when a stored plan has no `caution` yet. */
const DEFAULT_CAUTION: CautionSettings = { floor_share: 0.5, floor_start_years: 3, floor_full_years: 10, floor_step_pct_per_z: 2 };

const LEVELS = [
  { v: 1, title: "Very cautious", desc: "Steady value matters most. Little in growth assets." },
  { v: 2, title: "Cautious", desc: "Some ups and downs are fine for long goals." },
  { v: 3, title: "Balanced", desc: "A mix of growth and stability." },
  { v: 4, title: "Growth", desc: "Accept bigger swings for higher expected growth." },
  { v: 5, title: "High growth", desc: "Comfortable with large temporary falls." },
];

export function AssumptionsStep({ plan, update, expert }: StepProps) {
  const a = plan.assumptions;
  const c = plan.constraints;
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const caps = a.risky_cap_by_tolerance_pct;

  const [confirmReset, setConfirmReset] = useState(false);
  const caution = a.caution ?? DEFAULT_CAUTION;
  const setCaution = (patch: Partial<CautionSettings>) =>
    update((p) => ({ ...p, assumptions: { ...p.assumptions, caution: { ...(p.assumptions.caution ?? DEFAULT_CAUTION), ...patch } } }));

  /** PHASE2 1.13 / 3.4: replace asset classes, inflation and caution with the current defaults. */
  const reset = async () => {
    setResetting(true);
    setError(null);
    try {
      const d = await getFinanceDefaults();
      const da = d.plan.assumptions;
      update((p) => {
        const ids = new Set(da.asset_classes.map((x) => x.id));
        const maxClass = Object.fromEntries(Object.entries(p.constraints.max_class_pct).filter(([k]) => ids.has(k)));
        return {
          ...p,
          assumptions: {
            ...p.assumptions,
            asset_classes: da.asset_classes,
            correlations: da.correlations,
            cash_class_id: da.cash_class_id,
            inflation_pct: da.inflation_pct,
            inflation_volatility_pct: da.inflation_volatility_pct,
            caution: da.caution ?? DEFAULT_CAUTION,
            source_note: da.source_note,
          },
          constraints: { ...p.constraints, max_class_pct: maxClass },
        };
      });
      setConfirmReset(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setResetting(false);
    }
  };

  const setGlide = (steps: GlideStep[]) => update((p) => ({ ...p, assumptions: { ...p.assumptions, glide_path: steps } }));

  return (
    <div className="col gap-lg">
      <HelpText>
        These are illustrative assumptions, not forecasts. The plan uses <Term k="cautious_return">cautious</Term> versions of these returns, then tests thousands of possible
        market outcomes to estimate the chance of each goal. Change them to match your own view.
      </HelpText>
      <section className="col" aria-labelledby="fin-risk-h">
        <h2 id="fin-risk-h">How much ups and downs can you live with?</h2>
        <div className="risk-levels" role="radiogroup" aria-labelledby="fin-risk-h">
          {LEVELS.map((l) => (
            <button
              key={l.v}
              type="button"
              role="radio"
              aria-checked={plan.profile.risk_tolerance === l.v}
              className="preset"
              data-testid={`risk-level-${l.v}`}
              onClick={() => update((p) => ({ ...p, profile: { ...p.profile, risk_tolerance: l.v } }))}
            >
              <span className="preset-title">
                {plan.profile.risk_tolerance === l.v ? <Icon name="check" /> : null}
                {l.v}. {l.title}
              </span>
              <span className="preset-desc">{l.desc}</span>
              <span className="small faint">Up to {caps[l.v - 1] ?? "-"}% in growth assets for long goals</span>
            </button>
          ))}
        </div>
      </section>

      <section className="col" aria-labelledby="fin-assume-h">
        <div className="row between wrap">
          <h2 id="fin-assume-h">Assumptions</h2>
          <button type="button" className="btn sm" onClick={() => setConfirmReset(true)} disabled={resetting} data-testid="fin-reset-assumptions">
            <Icon name="refresh" /> Reset to current defaults
          </button>
        </div>
        {confirmReset ? (
          <ConfirmDialog
            title="Reset to current defaults?"
            confirmLabel="Reset"
            busy={resetting}
            onConfirm={() => void reset()}
            onCancel={() => setConfirmReset(false)}
          >
            <p>
              This replaces your asset classes and their returns, the inflation figures and the caution settings with the planner's current
              defaults. Your income, spending, savings and goals stay as they are.
            </p>
            {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
          </ConfirmDialog>
        ) : null}
        {error && !confirmReset ? <Banner tone="danger" role="alert">{error}</Banner> : null}
        <div className="fin-form">
          <Field label="Inflation % a year" hint="Your assumption">
            {(id) => <FinNumber id={id} value={a.inflation_pct} min={-2} max={25} step={0.1} onChange={(v) => update((p) => ({ ...p, assumptions: { ...p.assumptions, inflation_pct: v } }))} />}
          </Field>
          {expert ? (
            <Field label="Inflation ups and downs %" hint="Used in the market tests">
              {(id) => (
                <FinNumber id={id} value={a.inflation_volatility_pct} min={0} max={10} step={0.1} onChange={(v) => update((p) => ({ ...p, assumptions: { ...p.assumptions, inflation_volatility_pct: v } }))} />
              )}
            </Field>
          ) : null}
        </div>
        <AssetClassTable
          classes={a.asset_classes}
          inflationPct={a.inflation_pct}
          expert={expert}
          onChange={(asset_classes) => update((p) => ({ ...p, assumptions: { ...p.assumptions, asset_classes } }))}
        />
        <p className="small muted" style={{ margin: 0 }}>{a.source_note}</p>
      </section>

      {expert ? (
        <>
          <section className="col" aria-labelledby="fin-limits-h">
            <h2 id="fin-limits-h">Limits</h2>
            <div className="fin-form">
              <Field label="Max equity share % (optional)" hint="Across all goals">
                {(id) => <FinOptionalNumber id={id} value={c.max_equity_pct} min={0} max={100} onChange={(v) => update((p) => ({ ...p, constraints: { ...p.constraints, max_equity_pct: v } }))} />}
              </Field>
              <Field label="Always keep in cash" hint="Money that is never invested">
                {(id) => (
                  <MoneyInput id={id} value={c.min_cash_buffer} currency={plan.profile.currency} locale={plan.profile.locale} onChange={(v) => update((p) => ({ ...p, constraints: { ...p.constraints, min_cash_buffer: v } }))} />
                )}
              </Field>
              <Field label="Change amounts every">
                {(id) => (
                  <Select
                    id={id}
                    value={String(c.contribution_block_months) as "6" | "12"}
                    options={[{ value: "12", label: "12 months" }, { value: "6", label: "6 months" }]}
                    onChange={(v) => update((p) => ({ ...p, constraints: { ...p.constraints, contribution_block_months: v === "6" ? 6 : 12 } }))}
                  />
                )}
              </Field>
              <Field label="Cost when moving money %">
                {(id) => <FinNumber id={id} value={c.rebalance_cost_pct} min={0} max={2} step={0.05} onChange={(v) => update((p) => ({ ...p, constraints: { ...p.constraints, rebalance_cost_pct: v } }))} />}
              </Field>
            </div>
            <div className="fin-form">
              {caps.map((cap, i) => (
                <Field key={i} label={`Growth cap at risk level ${i + 1} (%)`}>
                  {(id) => (
                    <FinNumber
                      id={id}
                      value={cap}
                      min={i > 0 ? caps[i - 1] : 0}
                      max={i < 4 ? caps[i + 1] : 100}
                      onChange={(v) => update((p) => ({ ...p, assumptions: { ...p.assumptions, risky_cap_by_tolerance_pct: p.assumptions.risky_cap_by_tolerance_pct.map((x, j) => (j === i ? v : x)) } }))}
                    />
                  )}
                </Field>
              ))}
            </div>
          </section>
          <section className="col" aria-labelledby="fin-caution-h" data-testid="fin-caution-settings">
            <h2 id="fin-caution-h">Advanced: how cautious the plan is</h2>
            <p className="small muted" style={{ margin: 0 }}>
              The plan assumes lower returns than expected so it does not rely on good luck. For long goals it still counts on part of the
              typical growth, so growth assets stay useful.
            </p>
            <div className="fin-form">
              <Field label={`Keep at least this share of growth for goals ${Math.round(caution.floor_full_years)}+ years away (%)`} hint="0 = no minimum">
                {(id) => <FinNumber id={id} value={Math.round(caution.floor_share * 100)} min={0} max={100} step={5} onChange={(v) => setCaution({ floor_share: v / 100 })} />}
              </Field>
              <Field label="No minimum for goals up to this many years away">
                {(id) => <FinNumber id={id} value={caution.floor_start_years} min={0} max={Math.min(49.5, caution.floor_full_years - 0.5)} step={0.5} onChange={(v) => setCaution({ floor_start_years: v })} />}
              </Field>
              <Field label="Full minimum from this many years away">
                {(id) => <FinNumber id={id} value={caution.floor_full_years} min={Math.max(0.5, caution.floor_start_years + 0.5)} max={50} step={0.5} onChange={(v) => setCaution({ floor_full_years: v })} />}
              </Field>
              <Field label="Extra safety margin for more important goals (% points)" hint="Taken off the yearly growth for each step of extra caution">
                {(id) => <FinNumber id={id} value={caution.floor_step_pct_per_z} min={0} max={10} step={0.5} onChange={(v) => setCaution({ floor_step_pct_per_z: v })} />}
              </Field>
            </div>
          </section>
          <section className="col" aria-labelledby="fin-glide-h">
            <h2 id="fin-glide-h">Getting safer near a goal (glide path)</h2>
            <p className="small muted" style={{ margin: 0 }}>
              From the given number of months before a goal, the growth cap is multiplied by this factor. The 0-month step is required.
            </p>
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Glide path steps</caption>
                <thead>
                  <tr>
                    <th scope="col">Months before the goal (at least)</th>
                    <th scope="col">Share of the growth cap (%)</th>
                    <th scope="col"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {a.glide_path.map((s, i) => (
                    <tr key={i}>
                      <td>
                        {s.min_months_to_goal === 0 ? (
                          "0"
                        ) : (
                          <FinNumber label="Months before the goal" value={s.min_months_to_goal} min={1} max={600} onChange={(v) => setGlide(a.glide_path.map((x, j) => (j === i ? { ...x, min_months_to_goal: Math.round(v) } : x)))} />
                        )}
                      </td>
                      <td>
                        <FinNumber label="Share of the growth cap" value={Math.round(s.multiplier * 100)} min={0} max={100} onChange={(v) => setGlide(a.glide_path.map((x, j) => (j === i ? { ...x, multiplier: v / 100 } : x)))} />
                      </td>
                      <td className="right">
                        {s.min_months_to_goal !== 0 ? (
                          <button type="button" className="btn sm ghost" aria-label="Remove step" onClick={() => setGlide(a.glide_path.filter((_, j) => j !== i))}>
                            <Icon name="trash" />
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <button
                type="button"
                className="btn sm"
                disabled={a.glide_path.length >= 12}
                onClick={() => {
                  const used = new Set(a.glide_path.map((s) => s.min_months_to_goal));
                  let m = 6;
                  while (used.has(m)) m += 6;
                  setGlide([...a.glide_path, { min_months_to_goal: m, multiplier: 0.5 }].sort((x, y) => y.min_months_to_goal - x.min_months_to_goal));
                }}
              >
                <Icon name="plus" /> Add step
              </button>
            </div>
          </section>
        </>
      ) : (
        <p className="small muted" style={{ margin: 0 }}>Limits, caps, the glide path and the caution settings are under "Show expert settings".</p>
      )}
    </div>
  );
}

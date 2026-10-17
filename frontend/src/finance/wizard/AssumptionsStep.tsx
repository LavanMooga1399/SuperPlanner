import { useState } from "react";
import { Term } from "../../components/Term";
import { errorMessage } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { getFinanceDefaults } from "../api/client";
import type { GlideStep } from "../api/types";
import { AssetClassTable } from "../components/AssetClassTable";
import type { StepProps } from "./common";
import { Field, FinNumber, FinOptionalNumber, MoneyInput, Select } from "./fields";
import { HelpText } from "./HelpText";

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

  const reset = async () => {
    setResetting(true);
    setError(null);
    try {
      const d = await getFinanceDefaults();
      update((p) => ({ ...p, assumptions: d.plan.assumptions, constraints: d.plan.constraints }));
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
          <button type="button" className="btn sm" onClick={() => void reset()} disabled={resetting} data-testid="fin-reset-assumptions">
            {resetting ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} Reset to defaults
          </button>
        </div>
        {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
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
        <p className="small muted" style={{ margin: 0 }}>Limits, caps and the glide path are under "Show expert settings".</p>
      )}
    </div>
  );
}

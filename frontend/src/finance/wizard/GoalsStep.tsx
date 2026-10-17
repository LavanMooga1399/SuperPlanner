import { Icon } from "../../components/Icon";
import { Term } from "../../components/Term";
import type { Earmark, Goal, GoalKind, Priority } from "../api/types";
import { currentUtcMonth, fmtMonth, monthInYears, yearsFromStart } from "../lib/months";
import { addItem, patchItem, removeItem, type StepProps } from "./common";
import { Field, FinNumber, FinOptionalNumber, FinText, MonthInput, MoneyInput, Select, Toggle } from "./fields";
import { goalFromPreset, presets } from "./goalPresets";
import { HelpText } from "./HelpText";
import { ListEditor } from "./ListEditor";

const KINDS: { value: GoalKind; label: string }[] = [
  { value: "retirement", label: "Retirement" },
  { value: "education", label: "Education" },
  { value: "home", label: "Home" },
  { value: "vehicle", label: "Vehicle" },
  { value: "travel", label: "Travel" },
  { value: "wedding", label: "Wedding" },
  { value: "business", label: "Business" },
  { value: "other", label: "Other" },
];

const PRIORITIES: { value: Priority; label: string }[] = [
  { value: "must", label: "Must have" },
  { value: "should", label: "Should have" },
  { value: "nice", label: "Nice to have" },
];

export function GoalsStep({ plan, update, expert }: StepProps) {
  const cur = plan.profile.currency;
  const loc = plan.profile.locale;
  const start = plan.start_month ?? currentUtcMonth();
  const ps = presets(plan);
  return (
    <div className="col gap-lg">
      <HelpText>
        What are you saving for? Enter the cost in <Term k="todays_money">today's money</Term>; the plan adds inflation. Priority decides who gets money first when it is
        short: <strong>must have</strong> goals are funded first, then <strong>should have</strong>, then <strong>nice to have</strong>.
        Should and nice-to-have goals start after your emergency fund is complete.
      </HelpText>
      <div className="col">
        <span className="field-label" id="fin-goal-presets">Add a goal</span>
        <div className="preset-grid" role="group" aria-labelledby="fin-goal-presets">
          {ps.map((p) => (
            <button
              key={p.key}
              type="button"
              className="preset"
              disabled={plan.goals.length >= 12}
              data-testid={`goal-preset-${p.key}`}
              onClick={() => update((pl) => addItem(pl, "goals", goalFromPreset(pl, p)))}
            >
              <span className="preset-title">
                <Icon name="plus" /> {p.label}
              </span>
              <span className="preset-desc">{p.description}</span>
            </button>
          ))}
        </div>
      </div>
      <ListEditor
        items={plan.goals}
        rowTestId="goal"
        addLabel="Add other goal"
        emptyText="No goals yet. Pick one above."
        max={12}
        onAdd={() => update((pl) => addItem(pl, "goals", goalFromPreset(pl, ps[ps.length - 1])))}
        onRemove={(i) => update((p) => removeItem(p, "goals", i))}
        renderRow={(g, i) => {
          const set = (patch: Partial<Goal>) => update((p) => patchItem(p, "goals", i, patch));
          const years = yearsFromStart(start, g.target_month);
          return (
            <>
              <div className="fin-form">
                <Field label="Name">{(id) => <FinText id={id} value={g.name} onChange={(v) => set({ name: v })} testId={`goal-name-${g.id}`} />}</Field>
                <Field label="Type">{(id) => <Select id={id} value={g.kind} options={KINDS} onChange={(v) => set({ kind: v })} />}</Field>
                <Field label="Cost in today's money">
                  {(id) => <MoneyInput id={id} value={g.target_amount} min={1} currency={cur} locale={loc} onChange={(v) => v > 0 && set({ target_amount: v })} testId={`goal-amount-${g.id}`} />}
                </Field>
                <Field label="In how many years" hint={`Needed by ${fmtMonth(g.target_month)}`}>
                  {(id) => <FinNumber id={id} value={years} min={0.1} max={50} step={0.5} onChange={(v) => set({ target_month: monthInYears(start, v) })} testId={`goal-years-${g.id}`} />}
                </Field>
                <Field label="Or the exact month">
                  {(id) => <MonthInput id={id} value={g.target_month} onChange={(v) => v && set({ target_month: v })} testId={`goal-month-${g.id}`} />}
                </Field>
                <Field label="Priority">{(id) => <Select id={id} value={g.priority} options={PRIORITIES} onChange={(v) => set({ priority: v })} testId={`goal-priority-${g.id}`} />}</Field>
                <Field label="Could wait (months)" hint="Acceptable delay if money is short">
                  {(id) => <FinNumber id={id} value={g.flexibility_months} min={0} max={120} onChange={(v) => set({ flexibility_months: Math.round(v) })} />}
                </Field>
                <div className="fin-check-row">
                  <Toggle checked={g.enabled} onChange={(v) => set({ enabled: v })} label="Include in the plan" />
                </div>
              </div>
              {expert ? (
                <>
                  <div className="fin-form">
                    <Field label="Minimum chance (%)" hint={`Empty = default for ${g.priority === "must" ? "must have (85)" : g.priority === "should" ? "should have (70)" : "nice to have (50)"}`}>
                      {(id) => (
                        <FinOptionalNumber
                          id={id}
                          value={g.min_success_probability === null ? null : Math.round(g.min_success_probability * 100)}
                          min={50}
                          max={99}
                          onChange={(v) => set({ min_success_probability: v === null ? null : v / 100 })}
                        />
                      )}
                    </Field>
                    <Field label="Own inflation % (optional)">
                      {(id) => <FinOptionalNumber id={id} value={g.inflation_pct} min={-5} max={30} step={0.5} onChange={(v) => set({ inflation_pct: v })} />}
                    </Field>
                    <Field label="Own risk level 1-5 (optional)">
                      {(id) => (
                        <FinOptionalNumber id={id} value={g.risk_tolerance} min={1} max={5} onChange={(v) => set({ risk_tolerance: v === null ? null : Math.round(v) })} />
                      )}
                    </Field>
                  </div>
                  <EarmarkEditor goal={g} holdings={plan.holdings.map((h) => ({ value: h.id, label: h.name }))} onChange={(earmarked) => set({ earmarked })} currency={cur} locale={loc} />
                </>
              ) : null}
            </>
          );
        }}
      />
    </div>
  );
}

function EarmarkEditor({
  goal,
  holdings,
  onChange,
  currency,
  locale,
}: {
  goal: Goal;
  holdings: { value: string; label: string }[];
  onChange(e: Earmark[]): void;
  currency: string;
  locale: string;
}) {
  if (!holdings.length) return <span className="small muted">Add savings in the previous step to set money aside for this goal.</span>;
  return (
    <div className="col">
      <span className="field-label">Existing savings set aside for this goal</span>
      {goal.earmarked.map((e, i) => (
        <div className="row wrap" key={i}>
          <Select label="Savings" value={e.holding_id} options={holdings} onChange={(v) => onChange(goal.earmarked.map((x, j) => (j === i ? { ...x, holding_id: v } : x)))} />
          <MoneyInput label="Amount set aside" value={e.amount} currency={currency} locale={locale} onChange={(v) => onChange(goal.earmarked.map((x, j) => (j === i ? { ...x, amount: v } : x)))} />
          <button type="button" className="btn sm ghost" aria-label="Remove set-aside amount" onClick={() => onChange(goal.earmarked.filter((_, j) => j !== i))}>
            <Icon name="trash" />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn sm" disabled={goal.earmarked.length >= 20} onClick={() => onChange([...goal.earmarked, { holding_id: holdings[0].value, amount: 0 }])}>
          <Icon name="plus" /> Set aside savings
        </button>
      </div>
    </div>
  );
}

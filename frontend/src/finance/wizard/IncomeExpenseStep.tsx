import { Icon } from "../../components/Icon";
import type { AmountRange, Expense, IncomeKind, IncomeStream, OneOff } from "../api/types";
import { nextId } from "../lib/ids";
import { formatMoney, roundDisplay } from "../lib/money";
import { addMonths, currentUtcMonth } from "../lib/months";
import { addItem, patchItem, removeItem, type StepProps } from "./common";
import { Field, FinNumber, FinOptionalNumber, FinText, FREQUENCY_OPTIONS, MonthInput, MoneyInput, Select, Toggle } from "./fields";
import { HelpText } from "./HelpText";
import { ListEditor } from "./ListEditor";

const INCOME_KINDS: { value: IncomeKind; label: string }[] = [
  { value: "salary", label: "Salary" },
  { value: "business", label: "Business" },
  { value: "rental", label: "Rent received" },
  { value: "pension", label: "Pension" },
  { value: "interest", label: "Interest" },
  { value: "other", label: "Other" },
];

/** PHASE2 3.4: "range 70,000-80,000, using 75,000" for items that came with an amount range. */
export function RangeChip({ range, used, locale, testId }: { range: AmountRange | null | undefined; used: number; locale: string; testId?: string }) {
  if (!range) return null;
  const n = (v: number) => Math.round(v).toLocaleString(locale);
  return (
    <div className="fin-check-row">
      <span className="chip" data-testid={testId} title="You gave a range; the plan uses this amount">
        <Icon name="info" /> range {n(range.low)}-{n(range.high)}, using {n(used)}
      </span>
    </div>
  );
}

export function InvestablePreview({ preview, currency, locale }: Pick<StepProps, "preview"> & { currency: string; locale: string }) {
  const cf = preview.data?.cashflow ?? null;
  const v = cf?.avg_monthly_surplus_first_year ?? null;
  return (
    <div className="preview-figure" role="status" aria-live="polite" data-testid="fin-preview-investable">
      <Icon name="info" />
      {v === null ? (
        <span className="muted">{preview.loading ? "Calculating what you can invest…" : "Add your income and expenses to see what you can invest."}</span>
      ) : v >= 0 ? (
        <>
          <span>You can invest about</span>
          <strong>{formatMoney(roundDisplay(v), currency, locale)}</strong>
          <span>a month in the first year (after expenses and loan payments).</span>
        </>
      ) : (
        <>
          <span>Your expenses are higher than your income by about</span>
          <strong style={{ color: "var(--danger)" }}>{formatMoney(roundDisplay(-v), currency, locale)}</strong>
          <span>a month.</span>
        </>
      )}
      {preview.loading && v !== null ? <span className="spinner" aria-label="Updating" /> : null}
    </div>
  );
}

export function IncomeExpenseStep({ plan, update, preview, expert }: StepProps) {
  const cur = plan.profile.currency;
  const loc = plan.profile.locale;
  const start = plan.start_month ?? currentUtcMonth();

  const newIncome = (): IncomeStream => ({
    id: nextId(plan, "inc"),
    name: plan.incomes.length ? `Income ${plan.incomes.length + 1}` : "Salary",
    kind: plan.incomes.length ? "other" : "salary",
    amount: 0,
    frequency: "monthly",
    growth_pct: 0,
    start_month: null,
    end_month: null,
    interruptible: true,
    inflation_linked: false,
  });
  const newExpense = (name: string, essential: boolean, category = "other"): Expense => ({
    id: nextId(plan, "exp"),
    name,
    category,
    amount: 0,
    frequency: "monthly",
    essential,
    inflation_linked: true,
    inflation_pct: null,
    start_month: null,
    end_month: null,
  });
  const newOneOff = (): OneOff => ({
    id: nextId(plan, "oo"),
    name: `One-off ${plan.one_offs.length + 1}`,
    kind: "expense",
    month: addMonths(start, 12),
    amount: 0,
    inflation_linked: true,
  });

  return (
    <div className="col gap-lg">
      <HelpText>
        Enter take-home income (after tax) and your regular spending. Essentials (rent, food, school fees, insurance) set the size of your
        emergency fund; other spending is where small cuts can help. Amounts are in today's money.
      </HelpText>
      <InvestablePreview preview={preview} currency={cur} locale={loc} />

      <section className="col" aria-labelledby="fin-incomes-h">
        <h2 id="fin-incomes-h">Income</h2>
        <ListEditor
          items={plan.incomes}
          rowTestId="income"
          addLabel="Add income"
          emptyText="No income yet. Add your take-home pay."
          max={20}
          onAdd={() => update((p) => addItem(p, "incomes", newIncome()))}
          onRemove={(i) => update((p) => removeItem(p, "incomes", i))}
          renderRow={(it, i) => {
            const set = (patch: Partial<IncomeStream>) => update((p) => patchItem(p, "incomes", i, patch));
            return (
              <div className="fin-form">
                <Field label="Name">{(id) => <FinText id={id} value={it.name} onChange={(v) => set({ name: v })} />}</Field>
                <Field label="Type">{(id) => <Select id={id} value={it.kind} options={INCOME_KINDS} onChange={(v) => set({ kind: v })} />}</Field>
                <Field label="Take-home amount">
                  {(id) => <MoneyInput id={id} value={it.amount} currency={cur} locale={loc} onChange={(v) => set({ amount: v })} testId={`income-amount-${it.id}`} />}
                </Field>
                <Field label="How often">{(id) => <Select id={id} value={it.frequency} options={FREQUENCY_OPTIONS} onChange={(v) => set({ frequency: v })} />}</Field>
                <RangeChip range={it.amount_range} used={it.amount} locale={loc} testId={`income-range-${it.id}`} />
                <Field label={it.inflation_linked ? "Yearly raise above inflation (%)" : "Yearly raise (%)"} hint="Typical salary increase">
                  {(id) => <FinNumber id={id} value={it.growth_pct} min={-50} max={50} step={0.5} onChange={(v) => set({ growth_pct: v })} />}
                </Field>
                <div className="fin-check-row">
                  <Toggle
                    checked={it.inflation_linked ?? false}
                    onChange={(v) => set({ inflation_linked: v })}
                    label="Rises with inflation"
                    hint="On = the amount is in today's money and the raise is on top of inflation"
                  />
                </div>
                {expert ? (
                  <>
                    <Field label="Starts (optional)">{(id) => <MonthInput id={id} value={it.start_month} optional onChange={(v) => set({ start_month: v })} />}</Field>
                    <Field label="Ends (optional)">{(id) => <MonthInput id={id} value={it.end_month} optional onChange={(v) => set({ end_month: v })} />}</Field>
                    <div className="fin-check-row">
                      <Toggle checked={it.interruptible} onChange={(v) => set({ interruptible: v })} label="Could stop for a while" hint="Used when testing job-loss scenarios" />
                    </div>
                  </>
                ) : null}
              </div>
            );
          }}
        />
      </section>

      <section className="col" aria-labelledby="fin-expenses-h">
        <h2 id="fin-expenses-h">Expenses</h2>
        <ListEditor
          items={plan.expenses}
          rowTestId="expense"
          addLabel="Add expense"
          emptyText="No expenses yet. A single 'Essentials' line is enough to start."
          max={100}
          onAdd={() => update((p) => addItem(p, "expenses", newExpense(p.expenses.length ? `Expense ${p.expenses.length + 1}` : "Essentials", true)))}
          onRemove={(i) => update((p) => removeItem(p, "expenses", i))}
          addExtra={
            <button type="button" className="btn sm ghost" onClick={() => update((p) => addItem(p, "expenses", newExpense("Lifestyle", false, "lifestyle")))}>
              <Icon name="plus" /> Add other spending
            </button>
          }
          renderRow={(it, i) => {
            const set = (patch: Partial<Expense>) => update((p) => patchItem(p, "expenses", i, patch));
            return (
              <div className="fin-form">
                <Field label="Name">{(id) => <FinText id={id} value={it.name} onChange={(v) => set({ name: v })} />}</Field>
                <Field label="Category" hint="Free label, e.g. rent, food">
                  {(id) => <FinText id={id} value={it.category} maxLength={64} onChange={(v) => set({ category: v })} />}
                </Field>
                <Field label="Amount">
                  {(id) => <MoneyInput id={id} value={it.amount} currency={cur} locale={loc} onChange={(v) => set({ amount: v })} testId={`expense-amount-${it.id}`} />}
                </Field>
                <Field label="How often">{(id) => <Select id={id} value={it.frequency} options={FREQUENCY_OPTIONS} onChange={(v) => set({ frequency: v })} />}</Field>
                <RangeChip range={it.amount_range} used={it.amount} locale={loc} testId={`expense-range-${it.id}`} />
                <div className="fin-check-row wide">
                  <Toggle checked={it.essential} onChange={(v) => set({ essential: v })} label="Essential" hint="Essentials size the emergency fund" />
                  <Toggle checked={it.inflation_linked} onChange={(v) => set({ inflation_linked: v })} label="Rises with inflation" />
                </div>
                {expert ? (
                  <>
                    <Field label="Own inflation % (optional)" hint="e.g. school fees 9">
                      {(id) => <FinOptionalNumber id={id} value={it.inflation_pct} min={-5} max={30} step={0.5} onChange={(v) => set({ inflation_pct: v })} />}
                    </Field>
                    <Field label="Starts (optional)">{(id) => <MonthInput id={id} value={it.start_month} optional onChange={(v) => set({ start_month: v })} />}</Field>
                    <Field label="Ends (optional)">{(id) => <MonthInput id={id} value={it.end_month} optional onChange={(v) => set({ end_month: v })} />}</Field>
                  </>
                ) : null}
              </div>
            );
          }}
        />
      </section>

      <details className="card" open={plan.one_offs.length > 0}>
        <summary className="card-header" style={{ cursor: "pointer" }}>
          <h2>Known future expenses or windfalls</h2>
          <span className="small muted">{plan.one_offs.length} item{plan.one_offs.length === 1 ? "" : "s"}</span>
        </summary>
        <div className="card-body">
          <ListEditor
            items={plan.one_offs}
            rowTestId="oneoff"
            addLabel="Add one-off"
            emptyText="For example a wedding gift you will pay, a bonus or a maturing deposit. The plan saves ahead for one-off expenses."
            max={200}
            onAdd={() => update((p) => addItem(p, "one_offs", newOneOff()))}
            onRemove={(i) => update((p) => removeItem(p, "one_offs", i))}
            renderRow={(it, i) => {
              const set = (patch: Partial<OneOff>) => update((p) => patchItem(p, "one_offs", i, patch));
              return (
                <div className="fin-form">
                  <Field label="Name">{(id) => <FinText id={id} value={it.name} onChange={(v) => set({ name: v })} />}</Field>
                  <Field label="Type">
                    {(id) => (
                      <Select id={id} value={it.kind} options={[{ value: "expense", label: "Expense (money out)" }, { value: "inflow", label: "Windfall (money in)" }]} onChange={(v) => set({ kind: v })} />
                    )}
                  </Field>
                  <Field label="Month">{(id) => <MonthInput id={id} value={it.month} min={start} onChange={(v) => v && set({ month: v })} />}</Field>
                  <Field label="Amount">{(id) => <MoneyInput id={id} value={it.amount} currency={cur} locale={loc} onChange={(v) => set({ amount: v })} />}</Field>
                  <div className="fin-check-row">
                    <Toggle checked={it.inflation_linked} onChange={(v) => set({ inflation_linked: v })} label="In today's money" hint="Off = the exact future amount" />
                  </div>
                </div>
              );
            }}
          />
        </div>
      </details>
    </div>
  );
}

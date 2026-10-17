import type { Debt, DebtKind } from "../api/types";
import { nextId } from "../lib/ids";
import { fmtMonth } from "../lib/months";
import { addItem, patchItem, removeItem, type StepProps } from "./common";
import { Field, FinNumber, FinOptionalNumber, FinText, MoneyInput, Select } from "./fields";
import { HelpText } from "./HelpText";
import { ListEditor } from "./ListEditor";

const DEBT_KINDS: { value: DebtKind; label: string }[] = [
  { value: "home", label: "Home loan" },
  { value: "vehicle", label: "Vehicle loan" },
  { value: "education", label: "Education loan" },
  { value: "personal", label: "Personal loan" },
  { value: "credit_card", label: "Credit card" },
  { value: "other", label: "Other" },
];

export function DebtsStep({ plan, update, preview, expert }: StepProps) {
  const cur = plan.profile.currency;
  const loc = plan.profile.locale;
  const payoff = new Map((preview.data?.cashflow?.debts_paid_off ?? []).map((d) => [d.debt_id, d.month]));
  const newDebt = (): Debt => ({
    id: nextId(plan, "debt"),
    name: `Loan ${plan.debts.length + 1}`,
    kind: "other",
    balance: 0,
    interest_rate_pct: 10,
    emi: 0,
    remaining_months: null,
  });
  return (
    <div className="col gap-lg">
      <HelpText>
        List loans you are paying off. The monthly instalment (EMI) is paid before anything is invested; when a loan ends, that money becomes
        available for your goals. No loans? Just press Next.
      </HelpText>
      <ListEditor
        items={plan.debts}
        rowTestId="debt"
        addLabel="Add loan"
        emptyText="No loans. Add one if you pay a monthly instalment on a home, car or other loan."
        max={20}
        onAdd={() => update((p) => addItem(p, "debts", newDebt()))}
        onRemove={(i) => update((p) => removeItem(p, "debts", i))}
        renderRow={(it, i) => {
          const set = (patch: Partial<Debt>) => update((p) => patchItem(p, "debts", i, patch));
          const m = payoff.get(it.id);
          return (
            <>
              <div className="fin-form">
                <Field label="Name">{(id) => <FinText id={id} value={it.name} onChange={(v) => set({ name: v })} />}</Field>
                <Field label="Type">{(id) => <Select id={id} value={it.kind} options={DEBT_KINDS} onChange={(v) => set({ kind: v })} />}</Field>
                <Field label="Amount still owed">{(id) => <MoneyInput id={id} value={it.balance} currency={cur} locale={loc} onChange={(v) => set({ balance: v })} />}</Field>
                <Field label="Interest % a year">{(id) => <FinNumber id={id} value={it.interest_rate_pct} min={0} max={60} step={0.1} onChange={(v) => set({ interest_rate_pct: v })} />}</Field>
                <Field label="Monthly instalment (EMI)">{(id) => <MoneyInput id={id} value={it.emi} currency={cur} locale={loc} onChange={(v) => set({ emi: v })} />}</Field>
                {expert ? (
                  <Field label="Months left (optional)" hint="Only used to double-check">
                    {(id) => <FinOptionalNumber id={id} value={it.remaining_months} min={1} max={600} onChange={(v) => set({ remaining_months: v === null ? null : Math.round(v) })} />}
                  </Field>
                ) : null}
              </div>
              <span className="small muted" role="status">
                {payoff.has(it.id) ? (m ? `Paid off by ${fmtMonth(m)}.` : "Not paid off within the plan.") : "Payoff month appears after a moment."}
              </span>
            </>
          );
        }}
      />
    </div>
  );
}

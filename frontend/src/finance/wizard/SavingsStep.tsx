import type { Holding } from "../api/types";
import { nextId } from "../lib/ids";
import { formatMoney, roundDisplay } from "../lib/money";
import { fmtMonth } from "../lib/months";
import { addItem, patchItem, removeItem, type StepProps } from "./common";
import { Field, FinNumber, FinText, MonthInput, MoneyInput, Select } from "./fields";
import { HelpText } from "./HelpText";
import { ListEditor } from "./ListEditor";

export function SavingsStep({ plan, update, preview, expert }: StepProps) {
  const cur = plan.profile.currency;
  const loc = plan.profile.locale;
  const classes = plan.assumptions.asset_classes;
  const classOptions = classes.map((c) => ({ value: c.id, label: c.name }));
  const efOptions = classes.filter((c) => c.lock_in_months === 0 && c.liquidity_days <= 7).map((c) => ({ value: c.id, label: c.name }));
  const cf = preview.data?.cashflow ?? null;
  const ef = plan.emergency_fund;
  const newHolding = (): Holding => ({
    id: nextId(plan, "h"),
    name: plan.holdings.length ? `Savings ${plan.holdings.length + 1}` : "Savings account",
    asset_class_id: classes.some((c) => c.id === plan.assumptions.cash_class_id) ? plan.assumptions.cash_class_id : classes[0]?.id ?? "cash",
    amount: 0,
    locked_until_month: null,
  });
  return (
    <div className="col gap-lg">
      <HelpText>
        Add money you already have: savings accounts, deposits, investments. Pick the closest asset class; product names are not needed.
        Existing savings first fill your emergency fund; the rest can go towards goals.
      </HelpText>
      <section className="col" aria-labelledby="fin-holdings-h">
        <h2 id="fin-holdings-h">Savings and investments you have</h2>
        <ListEditor
          items={plan.holdings}
          rowTestId="holding"
          addLabel="Add savings"
          emptyText="No savings yet."
          max={50}
          onAdd={() => update((p) => addItem(p, "holdings", newHolding()))}
          onRemove={(i) => update((p) => removeItem(p, "holdings", i))}
          renderRow={(it, i) => {
            const set = (patch: Partial<Holding>) => update((p) => patchItem(p, "holdings", i, patch));
            return (
              <div className="fin-form">
                <Field label="Name">{(id) => <FinText id={id} value={it.name} onChange={(v) => set({ name: v })} />}</Field>
                <Field label="Asset class">{(id) => <Select id={id} value={it.asset_class_id} options={classOptions} onChange={(v) => set({ asset_class_id: v })} />}</Field>
                <Field label="Current value">{(id) => <MoneyInput id={id} value={it.amount} currency={cur} locale={loc} onChange={(v) => set({ amount: v })} />}</Field>
                <Field label="Locked until (optional)" hint="Cannot be sold before this month">
                  {(id) => <MonthInput id={id} value={it.locked_until_month} optional onChange={(v) => set({ locked_until_month: v })} />}
                </Field>
              </div>
            );
          }}
        />
      </section>
      <section className="col" aria-labelledby="fin-ef-h">
        <h2 id="fin-ef-h">Emergency fund</h2>
        <p className="muted" style={{ margin: 0 }} role="status" aria-live="polite" data-testid="fin-ef-target">
          {cf
            ? cf.ef_target > 0
              ? `Your emergency fund target is ${formatMoney(roundDisplay(cf.ef_target), cur, loc)} (${ef.months_of_essentials} months of essentials + loan payments). ${
                  cf.ef_complete_month ? `It is complete by ${fmtMonth(cf.ef_complete_month)}.` : "It is not completed within the plan."
                }`
              : "No emergency fund is planned."
            : "The emergency fund target appears after a moment."}
        </p>
        <div className="fin-form">
          <Field label="Months of essentials" hint="6 is a common choice; 0 turns it off">
            {(id) => (
              <FinNumber id={id} value={ef.months_of_essentials} min={0} max={24} step={0.5} onChange={(v) => update((p) => ({ ...p, emergency_fund: { ...p.emergency_fund, months_of_essentials: v } }))} />
            )}
          </Field>
          <Field label="Kept in">
            {(id) => (
              <Select
                id={id}
                value={ef.asset_class_id}
                options={efOptions.some((o) => o.value === ef.asset_class_id) ? efOptions : [{ value: ef.asset_class_id, label: ef.asset_class_id }, ...efOptions]}
                onChange={(v) => update((p) => ({ ...p, emergency_fund: { ...p.emergency_fund, asset_class_id: v } }))}
              />
            )}
          </Field>
          {expert ? (
            <Field label="Share of savings while building (%)" hint="100 = build it as fast as possible">
              {(id) => (
                <FinNumber
                  id={id}
                  value={Math.round(ef.build_share * 100)}
                  min={10}
                  max={100}
                  step={5}
                  onChange={(v) => update((p) => ({ ...p, emergency_fund: { ...p.emergency_fund, build_share: v / 100 } }))}
                />
              )}
            </Field>
          ) : null}
        </div>
      </section>
    </div>
  );
}

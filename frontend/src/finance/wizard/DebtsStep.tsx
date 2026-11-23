import type { Debt, DebtKind } from "../api/types";
import { nextId } from "../lib/ids";
import { fmtMonth } from "../lib/months";
import { addItem, patchItem, removeItem, type StepProps } from "./common";
import { Field, FinNumber, FinOptionalNumber, FinText, MoneyInput, Select } from "./fields";
import { HelpText } from "./HelpText";
import { ListEditor } from "./ListEditor";
import { t } from "../../lib/i18n";

const DEBT_KINDS: { value: DebtKind; label: string }[] = [
  { value: "home", label: t("finance.debtsStep.str.homeLoan") },
  { value: "vehicle", label: t("finance.debtsStep.str.vehicleLoan") },
  { value: "education", label: t("finance.debtsStep.str.educationLoan") },
  { value: "personal", label: t("finance.debtsStep.str.personalLoan") },
  { value: "credit_card", label: t("finance.debtsStep.str.creditCard") },
  { value: "other", label: t("finance.debtsStep.str.other") },
];

export function DebtsStep({ plan, update, preview, expert }: StepProps) {
  const cur = plan.profile.currency;
  const loc = plan.profile.locale;
  const payoff = new Map((preview.data?.cashflow?.debts_paid_off ?? []).map((d) => [d.debt_id, d.month]));
  const newDebt = (): Debt => ({
    id: nextId(plan, "debt"),
    name: t("finance.debtsStep.tpl.loan", { v: plan.debts.length + 1 }),
    kind: "other",
    balance: 0,
    interest_rate_pct: 10,
    emi: 0,
    remaining_months: null,
  });
  return (
    <div className="col gap-lg">
      <HelpText>
        {t("finance.debtsStep.text.listLoansYouArePaying")}
      </HelpText>
      <ListEditor
        items={plan.debts}
        rowTestId="debt"
        addLabel="Add loan"
        emptyText={t("finance.debtsStep.attr.noLoansAddOneIf")}
        max={20}
        onAdd={() => update((p) => addItem(p, "debts", newDebt()))}
        onRemove={(i) => update((p) => removeItem(p, "debts", i))}
        renderRow={(it, i) => {
          const set = (patch: Partial<Debt>) => update((p) => patchItem(p, "debts", i, patch));
          const m = payoff.get(it.id);
          return (
            <>
              <div className="fin-form">
                <Field label={t("finance.debtsStep.label.name")}>{(id) => <FinText id={id} value={it.name} onChange={(v) => set({ name: v })} />}</Field>
                <Field label={t("finance.debtsStep.label.type")}>{(id) => <Select id={id} value={it.kind} options={DEBT_KINDS} onChange={(v) => set({ kind: v })} />}</Field>
                <Field label={t("finance.debtsStep.label.amountStillOwed")}>{(id) => <MoneyInput id={id} value={it.balance} currency={cur} locale={loc} onChange={(v) => set({ balance: v })} />}</Field>
                <Field label={t("finance.debtsStep.label.interestAYear")}>{(id) => <FinNumber id={id} value={it.interest_rate_pct} min={0} max={60} step={0.1} onChange={(v) => set({ interest_rate_pct: v })} />}</Field>
                <Field label={t("finance.debtsStep.label.monthlyInstalmentEmi")}>{(id) => <MoneyInput id={id} value={it.emi} currency={cur} locale={loc} onChange={(v) => set({ emi: v })} />}</Field>
                {expert ? (
                  <Field label={t("finance.debtsStep.label.monthsLeftOptional")} hint={t("finance.debtsStep.hint.onlyUsedToDoublecheck")}>
                    {(id) => <FinOptionalNumber id={id} value={it.remaining_months} min={1} max={600} onChange={(v) => set({ remaining_months: v === null ? null : Math.round(v) })} />}
                  </Field>
                ) : null}
              </div>
              <span className="small muted" role="status">
                {payoff.has(it.id) ? (m ? t("finance.debtsStep.tpl.paidOffBy", { m: fmtMonth(m) }) : t("finance.debtsStep.str.notPaidOffWithinThe")) : t("finance.debtsStep.str.payoffMonthAppearsAfterA")}
              </span>
            </>
          );
        }}
      />
    </div>
  );
}

import { useState, type ReactNode } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { TextInput } from "../../components/Inputs";
import { Term } from "../../components/Term";
import { getFinanceDefaults } from "../../finance/api/client";
import { formatMoney } from "../../finance/lib/money";
import { useAsync } from "../../lib/useAsync";
import type {
  DebtKind,
  DraftAmount,
  DraftDebt,
  DraftExpense,
  DraftGoal,
  DraftHolding,
  DraftIncome,
  FinanceDraft,
  Frequency,
  GoalKind,
  IncomeKind,
  Priority,
} from "../api/types";
import { draftProblems, dropProvenance, nextKey } from "../lib/draft";
import { useIntake } from "../state/IntakeContext";
import { LinkedField } from "./LinkedField";
import { AmountRangeInput, NumField } from "./fields";
import { t } from "../../lib/i18n";

const FREQ: { v: Frequency; label: string }[] = [
  { v: "monthly", label: t("studio.financeDraftEditor.str.eachMonth") },
  { v: "quarterly", label: t("studio.financeDraftEditor.str.eachQuarter") },
  { v: "half_yearly", label: t("studio.financeDraftEditor.str.twiceAYear") },
  { v: "yearly", label: t("studio.financeDraftEditor.str.eachYear") },
  { v: "once", label: t("studio.financeDraftEditor.str.once") },
];
const INCOME_KINDS: { v: IncomeKind; label: string }[] = [
  { v: "salary", label: t("studio.financeDraftEditor.str.salary") },
  { v: "business", label: t("studio.financeDraftEditor.str.business") },
  { v: "rental", label: t("studio.financeDraftEditor.str.rentReceived") },
  { v: "pension", label: t("studio.financeDraftEditor.str.pension") },
  { v: "interest", label: t("studio.financeDraftEditor.str.interest") },
  { v: "other", label: t("studio.financeDraftEditor.str.other") },
];
const DEBT_KINDS: { v: DebtKind; label: string }[] = [
  { v: "home", label: t("studio.financeDraftEditor.str.homeLoan") },
  { v: "vehicle", label: t("studio.financeDraftEditor.str.vehicleLoan") },
  { v: "education", label: t("studio.financeDraftEditor.str.educationLoan") },
  { v: "personal", label: t("studio.financeDraftEditor.str.personalLoan") },
  { v: "credit_card", label: t("studio.financeDraftEditor.str.creditCard") },
  { v: "other", label: t("studio.financeDraftEditor.str.other") },
];
const GOAL_KINDS: { v: GoalKind; label: string }[] = [
  { v: "retirement", label: t("studio.financeDraftEditor.str.retirement") },
  { v: "education", label: t("studio.financeDraftEditor.str.education") },
  { v: "home", label: "Home" },
  { v: "vehicle", label: t("studio.financeDraftEditor.str.vehicle") },
  { v: "travel", label: t("studio.financeDraftEditor.str.travel") },
  { v: "wedding", label: t("studio.financeDraftEditor.str.wedding") },
  { v: "business", label: t("studio.financeDraftEditor.str.business") },
  { v: "other", label: t("studio.financeDraftEditor.str.other") },
];
const PRIORITIES: { v: Priority; label: string }[] = [
  { v: "must", label: t("studio.financeDraftEditor.str.mustHave") },
  { v: "should", label: t("studio.financeDraftEditor.str.shouldHave") },
  { v: "nice", label: t("studio.financeDraftEditor.str.niceToHave") },
];
const RISK = [
  { v: 1, label: t("studio.financeDraftEditor.str.1VeryCareful") },
  { v: 2, label: "2 - Careful" },
  { v: 3, label: "3 - Balanced" },
  { v: 4, label: "4 - Growth" },
  { v: 5, label: t("studio.financeDraftEditor.str.5ComfortableWithBigSwings") },
];

function Select<T extends string | number>({
  value,
  options,
  onChange,
  label,
  empty,
}: {
  value: T | null;
  options: { v: T; label: string }[];
  onChange(v: T | null): void;
  label: string;
  empty?: string;
}) {
  return (
    <select
      className="select sm"
      aria-label={label}
      value={value === null ? "" : String(value)}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === "") return onChange(null);
        const o = options.find((x) => String(x.v) === raw);
        onChange(o ? o.v : null);
      }}
    >
      {empty !== undefined || value === null ? <option value="">{empty ?? t("studio.financeDraftEditor.str.notSet")}</option> : null}
      {options.map((o) => (
        <option key={String(o.v)} value={String(o.v)}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function Section({
  id,
  title,
  term,
  onAdd,
  addLabel,
  emptyText,
  count,
  children,
}: {
  id: string;
  title: string;
  term?: ReactNode;
  onAdd?(): void;
  addLabel?: string;
  emptyText?: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-title`} className="col" style={{ gap: 8 }}>
      <div className="row">
        <h3 id={`${id}-title`} className="section-title grow">
          {title} {term}
        </h3>
        {onAdd ? (
          <button type="button" className="btn sm" onClick={onAdd} data-testid={`draft-add-${id}`}>
            <Icon name="plus" /> {addLabel}
          </button>
        ) : null}
      </div>
      {count === 0 && emptyText ? (
        <p className="small muted" style={{ margin: 0 }}>
          {emptyText}
        </p>
      ) : (
        children
      )}
    </section>
  );
}

type ListName = "incomes" | "expenses" | "debts" | "holdings" | "goals";

/** About you, income, spending, loans, savings and goals of a finance draft; amounts as "from - to" (PHASE2.md 3.3). */
export function FinanceDraftEditor({ draft }: { draft: FinanceDraft }) {
  const { editDraft } = useIntake();
  const defaults = useAsync((signal) => getFinanceDefaults(signal), []);
  const [pending, setPending] = useState<{ name: string; run(): void } | null>(null);
  const classes = (defaults.data?.plan.assumptions.asset_classes ?? []).map((c) => ({ v: c.id, label: c.name }));
  const problems = draftProblems(draft);
  const errOf = (path: string) => problems.find((p) => p.path === path)?.message ?? null;
  const cur = draft.profile.currency || "INR";
  const loc = draft.profile.locale || "en-IN";

  function setItem<K extends ListName>(list: K, key: string, patch: Partial<FinanceDraft[K][number]>, fields: string[]) {
    const items = (draft[list] as { key: string }[]).map((x) => (x.key === key ? { ...x, ...patch } : x));
    editDraft(
      { ...draft, [list]: items } as FinanceDraft,
      fields.map((f) => `/${list}/${key}/${f}`),
    );
  }
  function removeItem(list: ListName, key: string, name: string) {
    setPending({
      name,
      run: () =>
        editDraft(
          dropProvenance(
            { ...draft, [list]: (draft[list] as { key: string }[]).filter((x) => x.key !== key) } as FinanceDraft,
            `/${list}/${key}/`,
          ),
          [],
        ),
    });
  }
  function addItem<K extends ListName>(list: K, prefix: string, item: Omit<FinanceDraft[K][number], "key">) {
    const key = nextKey(
      prefix,
      (draft[list] as { key: string }[]).map((x) => x.key),
    );
    editDraft({ ...draft, [list]: [...(draft[list] as object[]), { ...item, key }] } as FinanceDraft, [`/${list}/${key}/name`]);
  }
  const setProfile = (patch: Partial<FinanceDraft["profile"]>, field: string) =>
    editDraft({ ...draft, profile: { ...draft.profile, ...patch } }, [`/profile/${field}`]);

  const amountCell = (path: string, label: string, value: DraftAmount | null, onChange: (v: DraftAmount | null) => void) => {
    const err = errOf(path);
    const errId = `err-${path.replace(/\W/g, "-")}`;
    return (
      <LinkedField path={path} error={err} errorId={errId}>
        <span className="col" style={{ gap: 2 }}>
          <AmountRangeInput value={value} label={label} onChange={onChange} describedBy={err ? errId : undefined} invalid={!!err} />
          {value && value.low < value.high ? (
            <span className="chip range-chip">
              {t("studio.financeDraftEditor.text.rangeUsing", { low: formatMoney(value.low, cur, loc), high: formatMoney(value.high, cur, loc), v: " ", formatMoney: formatMoney((value.low + value.high) / 2, cur, loc) })}
            </span>
          ) : null}
        </span>
      </LinkedField>
    );
  };
  const nameCell = (list: ListName, key: string, name: string, label: string) => (
    <LinkedField path={`/${list}/${key}/name`} error={errOf(`/${list}/${key}/name`)}>
      <TextInput
        label={label}
        value={name}
        required
        style={{ minWidth: 140 }}
        onChange={(v) => setItem(list, key, { name: v } as never, ["name"])}
      />
    </LinkedField>
  );
  const removeBtn = (list: ListName, key: string, name: string) => (
    <button type="button" className="btn sm icon ghost" aria-label={t("studio.financeDraftEditor.tpl.remove", { name: name })} onClick={() => removeItem(list, key, name)}>
      <Icon name="trash" />
    </button>
  );

  return (
    <div className="col" style={{ gap: 18 }}>
      <Section id="profile" title={t("studio.financeDraftEditor.attr.aboutYou")}>
        <div className="form-grid">
          <LinkedField path="/name" error={errOf("/name")}>
            <div className="field grow">
              <label htmlFor="fin-draft-name">{t("studio.financeDraftEditor.label.planName")}</label>
              <TextInput
                id="fin-draft-name"
                className="input"
                label={t("studio.financeDraftEditor.label.planName")}
                value={draft.name}
                required
                onChange={(v) => editDraft({ ...draft, name: v }, ["/name"])}
              />
            </div>
          </LinkedField>
          <LinkedField path="/profile/age">
            <div className="field">
              <span className="field-label">{t("studio.financeDraftEditor.text.yourAge")}</span>
              <NumField
                label={t("studio.financeDraftEditor.label.yourAge")}
                value={draft.profile.age}
                onChange={(v) => setProfile({ age: v === null ? null : Math.round(v) }, "age")}
              />
            </div>
          </LinkedField>
          <LinkedField path="/profile/retirement_age">
            <div className="field">
              <span className="field-label">{t("studio.financeDraftEditor.text.retireAtAge")}</span>
              <NumField
                label={t("studio.financeDraftEditor.label.retireAtAge")}
                value={draft.profile.retirement_age}
                onChange={(v) => setProfile({ retirement_age: v === null ? null : Math.round(v) }, "retirement_age")}
              />
            </div>
          </LinkedField>
          <LinkedField path="/profile/risk_tolerance">
            <div className="field">
              <span className="field-label">
                {t("studio.financeDraftEditor.text.riskLevel")}{" "}<Term k="risk_level" bare />
              </span>
              <Select
                label={t("studio.financeDraftEditor.label.riskLevel")}
                value={draft.profile.risk_tolerance}
                options={RISK}
                onChange={(v) => setProfile({ risk_tolerance: v }, "risk_tolerance")}
              />
            </div>
          </LinkedField>
          <LinkedField path="/emergency_fund_months">
            <div className="field">
              <span className="field-label">
                {t("studio.financeDraftEditor.text.emergencyFundMonths")}{" "}<Term k="emergency_fund" bare />
              </span>
              <NumField
                label={t("studio.financeDraftEditor.label.emergencyFundInMonthsOf")}
                value={draft.emergency_fund_months}
                onChange={(v) => editDraft({ ...draft, emergency_fund_months: v }, ["/emergency_fund_months"])}
              />
            </div>
          </LinkedField>
        </div>
      </Section>

      <Section
        id="incomes"
        title={t("studio.financeDraftEditor.attr.income")}
        count={draft.incomes.length}
        emptyText={t("studio.financeDraftEditor.attr.noIncomeYetAddWhat")}
        addLabel="Add income"
        onAdd={() =>
          addItem("incomes", "i", {
            name: "Income",
            kind: "salary",
            amount: null,
            frequency: "monthly",
            growth_pct: null,
            inflation_linked: true,
            interruptible: true,
            end_month: null,
          } as Omit<DraftIncome, "key">)
        }
      >
        <ul className="draft-items">
          {draft.incomes.map((i) => (
            <li key={i.key} className="draft-item">
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.name")}</span>
                {nameCell("incomes", i.key, i.name, t("studio.financeDraftEditor.str.incomeName"))}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.type")}</span>
                <Select
                  label={`${i.name}: type`}
                  value={i.kind}
                  options={INCOME_KINDS}
                  onChange={(v) => v && setItem("incomes", i.key, { kind: v }, ["kind"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.amountAfterTax")}</span>
                {amountCell(`/incomes/${i.key}/amount`, `${i.name}: amount`, i.amount, (v) =>
                  setItem("incomes", i.key, { amount: v }, ["amount"]),
                )}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.howOften")}</span>
                <Select
                  label={t("studio.financeDraftEditor.tpl.howOften", { name: i.name })}
                  value={i.frequency}
                  options={FREQ}
                  onChange={(v) => v && setItem("incomes", i.key, { frequency: v }, ["frequency"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.risesWithInflation")}</span>
                <LinkedField path={`/incomes/${i.key}/inflation_linked`}>
                  <label className="checkbox small">
                    <input
                      type="checkbox"
                      checked={i.inflation_linked}
                      onChange={(e) => setItem("incomes", i.key, { inflation_linked: e.target.checked }, ["inflation_linked"])}
                    />
                    {t("studio.financeDraftEditor.text.yes")}
                  </label>
                </LinkedField>
              </div>
              <div className="draft-cell draft-cell-end">{removeBtn("incomes", i.key, i.name)}</div>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id="expenses"
        title={t("studio.financeDraftEditor.attr.spending")}
        count={draft.expenses.length}
        emptyText={t("studio.financeDraftEditor.attr.noSpendingYetAddYour")}
        addLabel="Add spending"
        onAdd={() =>
          addItem("expenses", "e", {
            name: "Spending",
            category: "living",
            amount: null,
            frequency: "monthly",
            essential: true,
            inflation_pct: null,
            end_month: null,
          } as Omit<DraftExpense, "key">)
        }
      >
        <ul className="draft-items">
          {draft.expenses.map((x) => (
            <li key={x.key} className="draft-item">
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.name")}</span>
                {nameCell("expenses", x.key, x.name, t("studio.financeDraftEditor.str.spendingName"))}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.amount")}</span>
                {amountCell(`/expenses/${x.key}/amount`, `${x.name}: amount`, x.amount, (v) =>
                  setItem("expenses", x.key, { amount: v }, ["amount"]),
                )}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.howOften")}</span>
                <Select
                  label={t("studio.financeDraftEditor.tpl.howOften", { name: x.name })}
                  value={x.frequency}
                  options={FREQ}
                  onChange={(v) => v && setItem("expenses", x.key, { frequency: v }, ["frequency"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.needOrWant")}</span>
                <LinkedField path={`/expenses/${x.key}/essential`}>
                  <Select
                    label={t("studio.financeDraftEditor.tpl.needOrWant", { name: x.name })}
                    value={x.essential === null ? null : x.essential ? "need" : "want"}
                    options={[
                      { v: "need", label: "Need (essential)" },
                      { v: "want", label: "Want (could cut)" },
                    ]}
                    onChange={(v) => setItem("expenses", x.key, { essential: v === null ? null : v === "need" }, ["essential"])}
                  />
                </LinkedField>
              </div>
              <div className="draft-cell draft-cell-end">{removeBtn("expenses", x.key, x.name)}</div>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id="debts"
        title={t("studio.financeDraftEditor.attr.loans")}
        count={draft.debts.length}
        emptyText={t("studio.financeDraftEditor.attr.noLoansAddOneIf")}
        addLabel="Add loan"
        onAdd={() =>
          addItem("debts", "d", {
            name: "Loan",
            kind: "other",
            balance: null,
            interest_rate_pct: null,
            emi: null,
            remaining_months: null,
          } as Omit<DraftDebt, "key">)
        }
      >
        <ul className="draft-items">
          {draft.debts.map((d) => (
            <li key={d.key} className="draft-item">
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.name")}</span>
                {nameCell("debts", d.key, d.name, t("studio.financeDraftEditor.str.loanName"))}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.type")}</span>
                <Select
                  label={`${d.name}: type`}
                  value={d.kind}
                  options={DEBT_KINDS}
                  onChange={(v) => v && setItem("debts", d.key, { kind: v }, ["kind"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.stillOwed")}</span>
                {amountCell(`/debts/${d.key}/balance`, t("studio.financeDraftEditor.tpl.stillOwed", { name: d.name }), d.balance, (v) =>
                  setItem("debts", d.key, { balance: v }, ["balance"]),
                )}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.interestAYear")}</span>
                <LinkedField path={`/debts/${d.key}/interest_rate_pct`}>
                  <NumField
                    label={t("studio.financeDraftEditor.tpl.interestRate", { name: d.name })}
                    width={64}
                    value={d.interest_rate_pct}
                    onChange={(v) => setItem("debts", d.key, { interest_rate_pct: v }, ["interest_rate_pct"])}
                  />
                </LinkedField>
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.monthlyInstalment")}</span>
                {amountCell(`/debts/${d.key}/emi`, t("studio.financeDraftEditor.tpl.monthlyInstalment", { name: d.name }), d.emi, (v) =>
                  setItem("debts", d.key, { emi: v }, ["emi"]),
                )}
              </div>
              <div className="draft-cell draft-cell-end">{removeBtn("debts", d.key, d.name)}</div>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id="holdings"
        title={t("studio.financeDraftEditor.attr.savingsAndInvestments")}
        count={draft.holdings.length}
        emptyText={t("studio.financeDraftEditor.attr.noSavingsYetAddMoney")}
        addLabel="Add savings"
        onAdd={() =>
          addItem("holdings", "h", { name: "Savings", asset_class_id: "cash", amount: null, locked_until_month: null } as Omit<
            DraftHolding,
            "key"
          >)
        }
      >
        <ul className="draft-items">
          {draft.holdings.map((h) => (
            <li key={h.key} className="draft-item">
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.name")}</span>
                {nameCell("holdings", h.key, h.name, t("studio.financeDraftEditor.str.savingsName"))}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.heldIn")}</span>
                <LinkedField path={`/holdings/${h.key}/asset_class_id`}>
                  {classes.length ? (
                    <Select
                      label={t("studio.financeDraftEditor.tpl.heldIn", { name: h.name })}
                      value={h.asset_class_id}
                      options={
                        h.asset_class_id && !classes.some((c) => c.v === h.asset_class_id)
                          ? [...classes, { v: h.asset_class_id, label: h.asset_class_id }]
                          : classes
                      }
                      onChange={(v) => setItem("holdings", h.key, { asset_class_id: v }, ["asset_class_id"])}
                    />
                  ) : (
                    <TextInput
                      label={t("studio.financeDraftEditor.tpl.heldIn", { name: h.name })}
                      value={h.asset_class_id ?? ""}
                      onChange={(v) => setItem("holdings", h.key, { asset_class_id: v || null }, ["asset_class_id"])}
                    />
                  )}
                </LinkedField>
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.amountNow")}</span>
                {amountCell(`/holdings/${h.key}/amount`, `${h.name}: amount`, h.amount, (v) =>
                  setItem("holdings", h.key, { amount: v }, ["amount"]),
                )}
              </div>
              <div className="draft-cell draft-cell-end">{removeBtn("holdings", h.key, h.name)}</div>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id="goals"
        title={t("studio.financeDraftEditor.attr.goals")}
        count={draft.goals.length}
        emptyText={t("studio.financeDraftEditor.attr.noGoalsYetAddWhat")}
        addLabel="Add goal"
        onAdd={() =>
          addItem("goals", "g", {
            name: "Goal",
            kind: "other",
            target: null,
            target_month: null,
            priority: null,
            flexibility_months: 0,
            inflation_pct: null,
          } as Omit<DraftGoal, "key">)
        }
      >
        <ul className="draft-items">
          {draft.goals.map((g) => (
            <li key={g.key} className="draft-item">
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.name")}</span>
                {nameCell("goals", g.key, g.name, t("studio.financeDraftEditor.str.goalName"))}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.type")}</span>
                <Select
                  label={`${g.name}: type`}
                  value={g.kind}
                  options={GOAL_KINDS}
                  onChange={(v) => v && setItem("goals", g.key, { kind: v }, ["kind"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">
                  {t("studio.financeDraftEditor.text.costIn")}{" "}<Term k="todays_money">today's money</Term>
                </span>
                {amountCell(`/goals/${g.key}/target`, `${g.name}: cost`, g.target, (v) =>
                  setItem("goals", g.key, { target: v }, ["target"]),
                )}
                {g.kind === "retirement" && !g.target ? <span className="small muted">{t("studio.financeDraftEditor.text.emptyWeSuggestAnAmount")}</span> : null}
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.byMonth")}</span>
                <LinkedField path={`/goals/${g.key}/target_month`}>
                  <input
                    type="month"
                    className="input sm"
                    aria-label={t("studio.financeDraftEditor.tpl.byMonth", { name: g.name })}
                    value={g.target_month ?? ""}
                    onChange={(e) => setItem("goals", g.key, { target_month: e.target.value || null }, ["target_month"])}
                  />
                </LinkedField>
              </div>
              <div className="draft-cell">
                <span className="field-label">{t("studio.financeDraftEditor.text.howImportant")}</span>
                <LinkedField path={`/goals/${g.key}/priority`}>
                  <Select
                    label={t("studio.financeDraftEditor.tpl.howImportant", { name: g.name })}
                    value={g.priority}
                    options={PRIORITIES}
                    onChange={(v) => setItem("goals", g.key, { priority: v }, ["priority"])}
                  />
                </LinkedField>
              </div>
              <div className="draft-cell draft-cell-end">{removeBtn("goals", g.key, g.name)}</div>
            </li>
          ))}
        </ul>
      </Section>
      {pending ? (
        <ConfirmDialog
          title={t("studio.financeDraftEditor.tpl.remove2", { name: pending.name })}
          confirmLabel={t("studio.financeDraftEditor.btn.remove")}
          danger
          onCancel={() => setPending(null)}
          onConfirm={() => {
            pending.run();
            setPending(null);
          }}
        >
          {t("studio.financeDraftEditor.text.itIsRemovedFromThe")}
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

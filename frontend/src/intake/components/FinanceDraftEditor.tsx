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

const FREQ: { v: Frequency; label: string }[] = [
  { v: "monthly", label: "Each month" },
  { v: "quarterly", label: "Each quarter" },
  { v: "half_yearly", label: "Twice a year" },
  { v: "yearly", label: "Each year" },
  { v: "once", label: "Once" },
];
const INCOME_KINDS: { v: IncomeKind; label: string }[] = [
  { v: "salary", label: "Salary" },
  { v: "business", label: "Business" },
  { v: "rental", label: "Rent received" },
  { v: "pension", label: "Pension" },
  { v: "interest", label: "Interest" },
  { v: "other", label: "Other" },
];
const DEBT_KINDS: { v: DebtKind; label: string }[] = [
  { v: "home", label: "Home loan" },
  { v: "vehicle", label: "Vehicle loan" },
  { v: "education", label: "Education loan" },
  { v: "personal", label: "Personal loan" },
  { v: "credit_card", label: "Credit card" },
  { v: "other", label: "Other" },
];
const GOAL_KINDS: { v: GoalKind; label: string }[] = [
  { v: "retirement", label: "Retirement" },
  { v: "education", label: "Education" },
  { v: "home", label: "Home" },
  { v: "vehicle", label: "Vehicle" },
  { v: "travel", label: "Travel" },
  { v: "wedding", label: "Wedding" },
  { v: "business", label: "Business" },
  { v: "other", label: "Other" },
];
const PRIORITIES: { v: Priority; label: string }[] = [
  { v: "must", label: "Must have" },
  { v: "should", label: "Should have" },
  { v: "nice", label: "Nice to have" },
];
const RISK = [
  { v: 1, label: "1 - Very careful" },
  { v: 2, label: "2 - Careful" },
  { v: 3, label: "3 - Balanced" },
  { v: 4, label: "4 - Growth" },
  { v: 5, label: "5 - Comfortable with big swings" },
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
      {empty !== undefined || value === null ? <option value="">{empty ?? "Not set"}</option> : null}
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
              range {formatMoney(value.low, cur, loc)}-{formatMoney(value.high, cur, loc)}, using{" "}
              {formatMoney((value.low + value.high) / 2, cur, loc)}
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
    <button type="button" className="btn sm icon ghost" aria-label={`Remove ${name}`} onClick={() => removeItem(list, key, name)}>
      <Icon name="trash" />
    </button>
  );

  return (
    <div className="col" style={{ gap: 18 }}>
      <Section id="profile" title="About you">
        <div className="form-grid">
          <LinkedField path="/name" error={errOf("/name")}>
            <div className="field grow">
              <label htmlFor="fin-draft-name">Plan name</label>
              <TextInput
                id="fin-draft-name"
                className="input"
                label="Plan name"
                value={draft.name}
                required
                onChange={(v) => editDraft({ ...draft, name: v }, ["/name"])}
              />
            </div>
          </LinkedField>
          <LinkedField path="/profile/age">
            <div className="field">
              <span className="field-label">Your age</span>
              <NumField
                label="Your age"
                value={draft.profile.age}
                onChange={(v) => setProfile({ age: v === null ? null : Math.round(v) }, "age")}
              />
            </div>
          </LinkedField>
          <LinkedField path="/profile/retirement_age">
            <div className="field">
              <span className="field-label">Retire at age</span>
              <NumField
                label="Retire at age"
                value={draft.profile.retirement_age}
                onChange={(v) => setProfile({ retirement_age: v === null ? null : Math.round(v) }, "retirement_age")}
              />
            </div>
          </LinkedField>
          <LinkedField path="/profile/risk_tolerance">
            <div className="field">
              <span className="field-label">
                Risk level <Term k="risk_level" bare />
              </span>
              <Select
                label="Risk level"
                value={draft.profile.risk_tolerance}
                options={RISK}
                onChange={(v) => setProfile({ risk_tolerance: v }, "risk_tolerance")}
              />
            </div>
          </LinkedField>
          <LinkedField path="/emergency_fund_months">
            <div className="field">
              <span className="field-label">
                Emergency fund (months) <Term k="emergency_fund" bare />
              </span>
              <NumField
                label="Emergency fund in months of essential spending"
                value={draft.emergency_fund_months}
                onChange={(v) => editDraft({ ...draft, emergency_fund_months: v }, ["/emergency_fund_months"])}
              />
            </div>
          </LinkedField>
        </div>
      </Section>

      <Section
        id="incomes"
        title="Income"
        count={draft.incomes.length}
        emptyText="No income yet. Add what comes in after tax."
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
                <span className="field-label">Name</span>
                {nameCell("incomes", i.key, i.name, "Income name")}
              </div>
              <div className="draft-cell">
                <span className="field-label">Type</span>
                <Select
                  label={`${i.name}: type`}
                  value={i.kind}
                  options={INCOME_KINDS}
                  onChange={(v) => v && setItem("incomes", i.key, { kind: v }, ["kind"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">Amount after tax</span>
                {amountCell(`/incomes/${i.key}/amount`, `${i.name}: amount`, i.amount, (v) =>
                  setItem("incomes", i.key, { amount: v }, ["amount"]),
                )}
              </div>
              <div className="draft-cell">
                <span className="field-label">How often</span>
                <Select
                  label={`${i.name}: how often`}
                  value={i.frequency}
                  options={FREQ}
                  onChange={(v) => v && setItem("incomes", i.key, { frequency: v }, ["frequency"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">Rises with inflation</span>
                <LinkedField path={`/incomes/${i.key}/inflation_linked`}>
                  <label className="checkbox small">
                    <input
                      type="checkbox"
                      checked={i.inflation_linked}
                      onChange={(e) => setItem("incomes", i.key, { inflation_linked: e.target.checked }, ["inflation_linked"])}
                    />
                    Yes
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
        title="Spending"
        count={draft.expenses.length}
        emptyText="No spending yet. Add your regular costs, such as rent and groceries."
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
                <span className="field-label">Name</span>
                {nameCell("expenses", x.key, x.name, "Spending name")}
              </div>
              <div className="draft-cell">
                <span className="field-label">Amount</span>
                {amountCell(`/expenses/${x.key}/amount`, `${x.name}: amount`, x.amount, (v) =>
                  setItem("expenses", x.key, { amount: v }, ["amount"]),
                )}
              </div>
              <div className="draft-cell">
                <span className="field-label">How often</span>
                <Select
                  label={`${x.name}: how often`}
                  value={x.frequency}
                  options={FREQ}
                  onChange={(v) => v && setItem("expenses", x.key, { frequency: v }, ["frequency"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">Need or want</span>
                <LinkedField path={`/expenses/${x.key}/essential`}>
                  <Select
                    label={`${x.name}: need or want`}
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
        title="Loans"
        count={draft.debts.length}
        emptyText="No loans. Add one if you pay a monthly instalment."
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
                <span className="field-label">Name</span>
                {nameCell("debts", d.key, d.name, "Loan name")}
              </div>
              <div className="draft-cell">
                <span className="field-label">Type</span>
                <Select
                  label={`${d.name}: type`}
                  value={d.kind}
                  options={DEBT_KINDS}
                  onChange={(v) => v && setItem("debts", d.key, { kind: v }, ["kind"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">Still owed</span>
                {amountCell(`/debts/${d.key}/balance`, `${d.name}: still owed`, d.balance, (v) =>
                  setItem("debts", d.key, { balance: v }, ["balance"]),
                )}
              </div>
              <div className="draft-cell">
                <span className="field-label">Interest % a year</span>
                <LinkedField path={`/debts/${d.key}/interest_rate_pct`}>
                  <NumField
                    label={`${d.name}: interest rate`}
                    width={64}
                    value={d.interest_rate_pct}
                    onChange={(v) => setItem("debts", d.key, { interest_rate_pct: v }, ["interest_rate_pct"])}
                  />
                </LinkedField>
              </div>
              <div className="draft-cell">
                <span className="field-label">Monthly instalment</span>
                {amountCell(`/debts/${d.key}/emi`, `${d.name}: monthly instalment`, d.emi, (v) =>
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
        title="Savings and investments"
        count={draft.holdings.length}
        emptyText="No savings yet. Add money in the bank, funds or deposits."
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
                <span className="field-label">Name</span>
                {nameCell("holdings", h.key, h.name, "Savings name")}
              </div>
              <div className="draft-cell">
                <span className="field-label">Held in</span>
                <LinkedField path={`/holdings/${h.key}/asset_class_id`}>
                  {classes.length ? (
                    <Select
                      label={`${h.name}: held in`}
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
                      label={`${h.name}: held in`}
                      value={h.asset_class_id ?? ""}
                      onChange={(v) => setItem("holdings", h.key, { asset_class_id: v || null }, ["asset_class_id"])}
                    />
                  )}
                </LinkedField>
              </div>
              <div className="draft-cell">
                <span className="field-label">Amount now</span>
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
        title="Goals"
        count={draft.goals.length}
        emptyText="No goals yet. Add what you are saving for, such as a home or retirement."
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
                <span className="field-label">Name</span>
                {nameCell("goals", g.key, g.name, "Goal name")}
              </div>
              <div className="draft-cell">
                <span className="field-label">Type</span>
                <Select
                  label={`${g.name}: type`}
                  value={g.kind}
                  options={GOAL_KINDS}
                  onChange={(v) => v && setItem("goals", g.key, { kind: v }, ["kind"])}
                />
              </div>
              <div className="draft-cell">
                <span className="field-label">
                  Cost in <Term k="todays_money">today's money</Term>
                </span>
                {amountCell(`/goals/${g.key}/target`, `${g.name}: cost`, g.target, (v) =>
                  setItem("goals", g.key, { target: v }, ["target"]),
                )}
                {g.kind === "retirement" && !g.target ? <span className="small muted">Empty: we suggest an amount</span> : null}
              </div>
              <div className="draft-cell">
                <span className="field-label">By (month)</span>
                <LinkedField path={`/goals/${g.key}/target_month`}>
                  <input
                    type="month"
                    className="input sm"
                    aria-label={`${g.name}: by month`}
                    value={g.target_month ?? ""}
                    onChange={(e) => setItem("goals", g.key, { target_month: e.target.value || null }, ["target_month"])}
                  />
                </LinkedField>
              </div>
              <div className="draft-cell">
                <span className="field-label">How important</span>
                <LinkedField path={`/goals/${g.key}/priority`}>
                  <Select
                    label={`${g.name}: how important`}
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
          title={`Remove "${pending.name}"?`}
          confirmLabel="Remove"
          danger
          onCancel={() => setPending(null)}
          onConfirm={() => {
            pending.run();
            setPending(null);
          }}
        >
          It is removed from the draft.
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

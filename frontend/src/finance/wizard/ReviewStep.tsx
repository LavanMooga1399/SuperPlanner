import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import type { FinanceIssue, FinanceValidateResponse } from "../api/types";
import { formatMoney, roundDisplay } from "../lib/money";
import { fmtMonth } from "../lib/months";
import type { StepProps } from "./common";
import { HelpText } from "./HelpText";
import { STEPS, stepOfIssue } from "./steps";
import { DataTable } from "../../mfg/components/DataTable";
import { t, plural } from "../../lib/i18n";

export interface ReviewStepProps extends StepProps {
  planId: string;
  validation: FinanceValidateResponse | null;
  validating: boolean;
  validateError: string | null;
  runIssues: FinanceIssue[] | null;
}

export function ReviewStep({ plan, planId, validation, validating, validateError, runIssues }: ReviewStepProps) {
  const cur = plan.profile.currency;
  const loc = plan.profile.locale;
  const issues = runIssues ?? validation?.issues ?? [];
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");
  const cf = validation?.cashflow ?? null;
  const goals = plan.goals.filter((g) => g.enabled);
  const label = (k: string) => STEPS.find((s) => s.key === k)?.label ?? k;

  return (
    <div className="col gap-lg">
      <HelpText>
        Check the summary, fix anything marked as an error, then build your plan. Warnings do not stop the plan; they point out things worth
        a second look.
      </HelpText>
      <div className="kpis">
        <div className="card kpi"><div className="kpi-label">Income streams</div><div className="kpi-value">{plan.incomes.length}</div></div>
        <div className="card kpi"><div className="kpi-label">Expenses</div><div className="kpi-value">{plan.expenses.length}</div></div>
        <div className="card kpi"><div className="kpi-label">Loans</div><div className="kpi-value">{plan.debts.length}</div></div>
        <div className="card kpi"><div className="kpi-label">Savings</div><div className="kpi-value">{plan.holdings.length}</div></div>
        <div className="card kpi"><div className="kpi-label">Goals</div><div className="kpi-value">{goals.length}</div></div>
      </div>

      <section className="card" aria-labelledby="fin-issues-h" data-testid="fin-review-issues">
        <div className="card-header">
          <h2 id="fin-issues-h">{t("finance.reviewStep.head.checks")}</h2>
          <span className="small muted" role="status" aria-live="polite">
            {validating ? "Checking…" : errors.length ? `${plural(errors.length, "error")} to fix` : "No errors"}
          </span>
        </div>
        {validateError ? <div className="card-body"><span style={{ color: "var(--danger)" }}><Icon name="alert" /> {validateError}</span></div> : null}
        {!validation && validating ? <div className="card-body muted">Checking your plan…</div> : null}
        {validation && !issues.length ? (
          <div className="card-body row"><Icon name="check" style={{ color: "var(--ok)" }} /> Everything looks good.</div>
        ) : null}
        {[...errors, ...warnings].map((iss, i) => {
          const step = stepOfIssue(iss);
          return (
            <div className="issue" key={i} data-testid={`fin-issue-${iss.code}`} data-severity={iss.severity}>
              <span className="issue-icon" style={{ color: iss.severity === "error" ? "var(--danger)" : "var(--warn)" }}>
                <Icon name={iss.severity === "error" ? "x" : "alert"} />
              </span>
              <div className="grow">
                <strong>{iss.severity === "error" ? "Error" : "Warning"}:</strong> {iss.message}
              </div>
              {step !== "review" ? (
                <Link className="btn sm ghost" to={`/finance/${planId}/setup/${step}`}>
                  Fix in {label(step)} <Icon name="arrow-right" />
                </Link>
              ) : null}
            </div>
          );
        })}
      </section>

      {cf ? (
        <section className="card" aria-labelledby="fin-cfprev-h">
          <div className="card-header">
            <h2 id="fin-cfprev-h">{t("finance.reviewStep.head.cashflowPreview")}</h2>
            <span className="small muted">today's money</span>
          </div>
          <div className="card-body col">
            <ul className="explain-list" style={{ marginTop: 0 }}>
              <li>Average monthly surplus in the first year: {formatMoney(roundDisplay(cf.avg_monthly_surplus_first_year), cur, loc)}.</li>
              <li>
                Emergency fund target {formatMoney(roundDisplay(cf.ef_target), cur, loc)}, you already have {formatMoney(roundDisplay(cf.ef_initial), cur, loc)}
                {cf.ef_complete_month ? `; complete by ${fmtMonth(cf.ef_complete_month)}` : ""}.
              </li>
              {cf.negative_surplus_months.length ? (
                <li>Months where spending is higher than income: {cf.negative_surplus_months.map(fmtMonth).join(", ")}.</li>
              ) : null}
              {cf.debts_paid_off.map((d) => (
                <li key={d.debt_id}>
                  {plan.debts.find((x) => x.id === d.debt_id)?.name ?? d.debt_id}: {d.month ? `paid off by ${fmtMonth(d.month)}` : "not paid off within the plan"}.
                </li>
              ))}
            </ul>
            <DataTable
              rows={cf.years.slice(0, 5)}
              columns={[
                { key: "year", header: "Year from", width: "minmax(110px, 1fr)", sortValue: (y) => y.start_month, render: (y) => fmtMonth(y.start_month) },
                { key: "income", header: "Income", width: "120px", align: "right", sortValue: (y) => y.income, render: (y) => formatMoney(y.income, cur, loc) },
                { key: "essential", header: "Essentials", width: "120px", align: "right", sortValue: (y) => y.essential, render: (y) => formatMoney(y.essential, cur, loc) },
                { key: "discretionary", header: "Other spending", width: "130px", align: "right", sortValue: (y) => y.discretionary, render: (y) => formatMoney(y.discretionary, cur, loc) },
                { key: "loans", header: "Loans", width: "110px", align: "right", sortValue: (y) => y.debt_payments, render: (y) => formatMoney(y.debt_payments, cur, loc) },
                { key: "oneoff", header: "One-offs", width: "110px", align: "right", sortValue: (y) => y.one_off_net, render: (y) => formatMoney(y.one_off_net, cur, loc) },
                { key: "surplus", header: "Surplus", width: "120px", align: "right", sortValue: (y) => y.surplus, render: (y) => <span className={y.surplus < 0 ? "mfg-neg" : undefined}>{formatMoney(y.surplus, cur, loc)}</span> },
              ]}
              rowKey={(y) => y.year}
              label={t("finance.reviewStep.label.cashFlowPerPlanYear")}
              tableId="finance-review-cashflow"
              exportName="cash-flow-per-year"
              card={{ title: "year", fields: ["income", "surplus"] }}
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}

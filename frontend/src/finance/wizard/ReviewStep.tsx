import { Link } from "react-router-dom";
import { Icon } from "../../components/Icon";
import type { FinanceIssue, FinanceValidateResponse } from "../api/types";
import { formatMoney, roundDisplay } from "../lib/money";
import { fmtMonth } from "../lib/months";
import type { StepProps } from "./common";
import { HelpText } from "./HelpText";
import { STEPS, stepOfIssue } from "./steps";

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
          <h2 id="fin-issues-h">Checks</h2>
          <span className="small muted" role="status" aria-live="polite">
            {validating ? "Checking…" : errors.length ? `${errors.length} error${errors.length === 1 ? "" : "s"} to fix` : "No errors"}
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
            <h2 id="fin-cfprev-h">Cash-flow preview</h2>
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
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Cash flow per plan year</caption>
                <thead>
                  <tr>
                    <th scope="col">Year from</th>
                    <th scope="col" className="num">Income</th>
                    <th scope="col" className="num">Essentials</th>
                    <th scope="col" className="num">Other spending</th>
                    <th scope="col" className="num">Loans</th>
                    <th scope="col" className="num">One-offs</th>
                    <th scope="col" className="num">Surplus</th>
                  </tr>
                </thead>
                <tbody>
                  {cf.years.slice(0, 5).map((y) => (
                    <tr key={y.year}>
                      <td>{fmtMonth(y.start_month)}</td>
                      <td className="num">{formatMoney(y.income, cur, loc)}</td>
                      <td className="num">{formatMoney(y.essential, cur, loc)}</td>
                      <td className="num">{formatMoney(y.discretionary, cur, loc)}</td>
                      <td className="num">{formatMoney(y.debt_payments, cur, loc)}</td>
                      <td className="num">{formatMoney(y.one_off_net, cur, loc)}</td>
                      <td className="num" style={y.surplus < 0 ? { color: "var(--danger)" } : undefined}>{formatMoney(y.surplus, cur, loc)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}

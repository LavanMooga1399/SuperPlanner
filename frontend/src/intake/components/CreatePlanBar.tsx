import { useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { Term } from "../../components/Term";
import { formatMoney, roundDisplay } from "../../finance/lib/money";
import { KINDS } from "../../landing/kinds";
import type { FinanceBuildResult, FinanceDraft, ScheduleBuildResult, ScheduleDraft } from "../api/types";
import { draftProblems } from "../lib/draft";
import { pathLabel } from "../lib/paths";
import { formatWorkMinutes } from "../lib/pert";
import { useIntake } from "../state/IntakeContext";
import { t } from "../../lib/i18n";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

interface Line {
  severity: "error" | "warning" | "needed";
  text: string;
}

function ScheduleSummary({ build, draft }: { build: ScheduleBuildResult; draft: ScheduleDraft }) {
  const { state } = useIntake();
  const terms = KINDS[state.kind].terminology;
  const p = build.problem;
  if (!p) return null;
  const allPeople = p.resources.length > 0 && p.resources.every((r) => r.kind === "person");
  const resWord = allPeople
    ? plural(p.resources.length, "person", "people")
    : plural(p.resources.length, (terms?.resource ?? "resource").toLowerCase(), (terms?.resources ?? "resources").toLowerCase());
  const taskWords = [(terms?.task ?? "task").toLowerCase(), (terms?.tasks ?? "tasks").toLowerCase()] as const;
  const ds = build.duration_summary;
  return (
    <div className="col" style={{ gap: 4 }} data-testid="intake-build-summary">
      <div>
        <strong>
          {t("studio.createPlanBar.text.in", { length: plural(p.tasks.length, taskWords[0], taskWords[1]), length2: plural(draft.tasks.length, "step", "steps"), resWord: resWord })}
        </strong>
        {p.tasks.length > draft.tasks.length ? (
          <span className="small muted">{" "}{t("studio.createPlanBar.text.longStepsAreSplitInto")}</span>
        ) : null}
      </div>
      {ds && ds.tasks_with_range > 0 ? (
        <div className="small" data-testid="intake-pert-note">
          <Icon name="info" size={14} /> {plural(ds.tasks_with_range, "step has", "steps have")} a{" "}
          <Term k="duration_range">{t("studio.createPlanBar.text.durationRange")}</Term>. The plan uses the <Term k="expected_duration">{t("studio.createPlanBar.text.expectedValues")}</Term>{t("studio.createPlanBar.text.aboutOfWorkInTotal", { expectedworkminutes: formatWorkMinutes(ds.expected_work_minutes), optimisticworkminutes: formatWorkMinutes(ds.optimistic_work_minutes), v: " ", pessimisticworkminutes: formatWorkMinutes(ds.pessimistic_work_minutes) })}
        </div>
      ) : null}
    </div>
  );
}

function FinanceSummary({ build, draft }: { build: FinanceBuildResult; draft: FinanceDraft }) {
  const cf = build.cashflow;
  const cur = build.plan?.profile?.currency ?? draft.profile.currency ?? "INR";
  const loc = draft.profile.locale || "en-IN";
  const v = cf?.avg_monthly_surplus_first_year;
  return (
    <div className="col" style={{ gap: 4 }} data-testid="intake-build-summary">
      <strong>
        {[
          plural(draft.incomes.length, "income", "incomes"),
          plural(draft.expenses.length, "expense", "expenses"),
          plural(draft.debts.length, "loan", "loans"),
          plural(draft.holdings.length, "savings item", "savings items"),
          plural(draft.goals.length, "goal", "goals"),
        ].join(", ")}
      </strong>
      {v !== undefined && v !== null ? (
        <div data-testid="intake-cashflow">
          {v >= 0
            ? t("studio.createPlanBar.tpl.aboutLeftEachMonthIn", { formatMoney: formatMoney(roundDisplay(v), cur, loc) })
            : t("studio.createPlanBar.tpl.aboutShortEachMonthIn", { formatMoney: formatMoney(roundDisplay(-v), cur, loc) })}
          <span className="small muted">{" "}{t("studio.createPlanBar.text.afterExpensesAndLoanPayments")}</span>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Review and create (PHASE2.md 3.3): what the build found, the problems in plain words, "Check draft",
 * "Create plan" (only when nothing blocks) and "Start over". Nothing is saved before "Create plan".
 */
export function CreatePlanBar() {
  const { state, domain, busy, checking, buildFresh, checkDraft, create, startOver } = useIntake();
  const [confirmReset, setConfirmReset] = useState(false);
  const resp = state.response;
  if (!resp) return null;
  const draft = resp.draft;
  const lines: Line[] = [];
  for (const q of resp.questions.filter((x) => x.required)) lines.push({ severity: "needed", text: t("studio.createPlanBar.tpl.stillNeeded", { prompt: q.prompt }) });
  for (const p of draftProblems(draft)) lines.push({ severity: "error", text: `${pathLabel(draft, p.path)}: ${p.message}` });
  const build = buildFresh ? state.build : null;
  if (build) {
    if (domain === "schedule") {
      for (const i of (build as ScheduleBuildResult).report?.issues ?? []) lines.push({ severity: i.severity, text: i.message });
    } else {
      for (const i of (build as FinanceBuildResult).preflight?.issues ?? []) lines.push({ severity: i.severity, text: i.message });
    }
    for (const q of build.blocking) {
      if (!resp.questions.some((x) => x.id === q.id)) lines.push({ severity: "needed", text: t("studio.createPlanBar.tpl.stillNeeded", { prompt: q.prompt }) });
    }
  }
  const blocked = lines.some((l) => l.severity !== "warning");
  const canCreate = !!build && build.ready && !blocked && busy === null && !checking;
  const reason = checking
    ? t("studio.createPlanBar.str.checkingTheDraft")
    : blocked
      ? t("studio.createPlanBar.str.fixThePointsListedAbove")
      : !build
        ? t("studio.createPlanBar.str.pressCheckDraftToSee")
        : !build.ready
          ? t("studio.createPlanBar.str.theDraftIsNotReady")
          : t("studio.createPlanBar.str.nothingIsSavedUntilYou");

  return (
    <section className="card create-bar" aria-labelledby="intake-review-title">
      <div className="card-header">
        <h3 id="intake-review-title" style={{ margin: 0 }}>
          {t("studio.createPlanBar.text.review")}
        </h3>
        {checking ? (
          <span className="small muted row" role="status">
            <span className="spinner" aria-hidden />{" "}{t("studio.createPlanBar.text.checkingTheDraft")}
          </span>
        ) : null}
      </div>
      <div className="card-body col" style={{ gap: 10 }}>
        {build && build.ready !== undefined ? (
          domain === "schedule" ? (
            <ScheduleSummary build={build as ScheduleBuildResult} draft={draft as ScheduleDraft} />
          ) : (
            <FinanceSummary build={build as FinanceBuildResult} draft={draft as FinanceDraft} />
          )
        ) : null}
        {lines.length ? (
          <ul className="intake-issues" data-testid="intake-issues" aria-label={t("studio.createPlanBar.aria.pointsToCheck")}>
            {lines.map((l, i) => (
              <li key={i} className={`issue-line ${l.severity}`} data-severity={l.severity}>
                <Icon name={l.severity === "warning" ? "info" : "alert"} size={14} />
                <span>
                  <span className="sr-only">{l.severity === "warning" ? t("studio.createPlanBar.str.note") : l.severity === "error" ? t("studio.createPlanBar.str.problem") : ""}</span>
                  {l.text}
                </span>
              </li>
            ))}
          </ul>
        ) : build ? (
          <div className="small row" data-testid="intake-issues" data-empty={t("studio.createPlanBar.empty.true")}>
            <Icon name="check" size={14} /> {t("studio.createPlanBar.btn.noProblemsFound")}
          </div>
        ) : null}
        <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
          <button type="button" className="btn primary" data-testid="intake-create" disabled={!canCreate} aria-describedby="intake-create-why" onClick={() => void create()}>
            {busy === "create" ? <span className="spinner" aria-hidden /> : <Icon name="check" />}{" "}{t("studio.createPlanBar.text.createPlan")}
          </button>
          <button type="button" className="btn" data-testid="intake-build" disabled={busy !== null || checking} onClick={() => void checkDraft()}>
            <Icon name="refresh" /> {t("studio.createPlanBar.btn.checkDraft")}
          </button>
          <div className="grow" />
          <button type="button" className="btn ghost" data-testid="intake-start-over" disabled={busy !== null} onClick={() => setConfirmReset(true)}>
            {t("studio.createPlanBar.btn.startOver")}
          </button>
        </div>
        <span id="intake-create-why" className="small muted">
          {reason}
        </span>
      </div>
      {confirmReset ? (
        <ConfirmDialog
          title={t("studio.createPlanBar.title.startOver")}
          confirmLabel={t("studio.createPlanBar.btn.startOver")}
          danger
          onCancel={() => setConfirmReset(false)}
          onConfirm={() => {
            setConfirmReset(false);
            startOver();
          }}
        >
          {t("studio.createPlanBar.text.theDraftYourAnswersAnd", { v: state.flow === "import" ? "table" : "text" })}
        </ConfirmDialog>
      ) : null}
    </section>
  );
}

import { KindCard } from "./KindCard";
import { PLAN_KINDS } from "./kinds";
import { useStepByStep } from "./startPlan";
import { PageHeader } from "../components/PageHeader";
import { t } from "../lib/i18n";

/** Landing block "What do you want to plan?" (PHASE2.md 3.2): four kinds x four ways to start. */
export function PlanChooser() {
  const steps = useStepByStep();
  return (
    <section aria-labelledby="landing-title" className="plan-chooser" data-testid="plan-chooser">
      <PageHeader titleId="landing-title" title={t("studio.planChooser.title.whatDoYouWantTo")} description={t("studio.planChooser.desc.pickTheKindOfPlan")} />
      <div className="kind-grid">
        {PLAN_KINDS.map((k) => (
          <KindCard key={k} kind={k} steps={steps} headingLevel={2} />
        ))}
      </div>
    </section>
  );
}

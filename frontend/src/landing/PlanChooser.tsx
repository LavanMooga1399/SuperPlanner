import { KindCard } from "./KindCard";
import { PLAN_KINDS } from "./kinds";
import { useStepByStep } from "./startPlan";
import { PageHeader } from "../components/PageHeader";

/** Landing block "What do you want to plan?" (PHASE2.md 3.2): four kinds x four ways to start. */
export function PlanChooser() {
  const steps = useStepByStep();
  return (
    <section aria-labelledby="landing-title" className="plan-chooser" data-testid="plan-chooser">
      <PageHeader titleId="landing-title" title="What do you want to plan?" description="Pick the kind of plan, then how you want to start. You can change everything later." />
      <div className="kind-grid">
        {PLAN_KINDS.map((k) => (
          <KindCard key={k} kind={k} steps={steps} headingLevel={2} />
        ))}
      </div>
    </section>
  );
}

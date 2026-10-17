import { useEffect } from "react";
import { Link, useParams } from "react-router";
import { NotFound } from "../App";
import { Icon } from "../components/Icon";
import { KindCard } from "./KindCard";
import { KINDS, isPlanKind } from "./kinds";
import { useStepByStep } from "./startPlan";

/** `/new/:kind`: the four ways to start one kind of plan, as large buttons (PHASE2.md 3.1). */
export function StartPage() {
  const { kind } = useParams();
  const steps = useStepByStep();
  const valid = isPlanKind(kind);
  useEffect(() => {
    if (valid) document.title = `New ${KINDS[kind].label.toLowerCase()} - SuperPlanner`;
    return () => {
      document.title = "SuperPlanner Studio";
    };
  }, [kind, valid]);
  if (!valid) return <NotFound />;
  const info = KINDS[kind];
  return (
    <div className="col gap-lg start-page">
      <nav aria-label="Breadcrumb" className="small">
        <Link to="/">
          <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> All kinds of plan
        </Link>
      </nav>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div>
          <h1>New {info.label.toLowerCase()}</h1>
          <p>How do you want to start? Every way leads to a plan you can edit before anything is calculated.</p>
        </div>
      </div>
      <KindCard kind={kind} steps={steps} headingLevel={2} large />
    </div>
  );
}

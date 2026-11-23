import { useEffect } from "react";
import { Link, useParams } from "react-router";
import { NotFound } from "../App";
import { Icon } from "../components/Icon";
import { KindCard } from "./KindCard";
import { KINDS, isPlanKind } from "./kinds";
import { useStepByStep } from "./startPlan";
import { PageHeader } from "../components/PageHeader";
import { t } from "../lib/i18n";

/** `/new/:kind`: the four ways to start one kind of plan, as large buttons (PHASE2.md 3.1). */
export function StartPage() {
  const { kind } = useParams();
  const steps = useStepByStep();
  const valid = isPlanKind(kind);
  useEffect(() => {
    if (valid) document.title = t("studio.startPage.tpl.newSuperplanner", { label: KINDS[kind].label.toLowerCase() });
    return () => {
      document.title = t("studio.startPage.str.superplannerStudio");
    };
  }, [kind, valid]);
  if (!valid) return <NotFound />;
  const info = KINDS[kind];
  return (
    <div className="col gap-lg start-page">
      <nav aria-label={t("studio.startPage.aria.breadcrumb")} className="small">
        <Link to="/">
          <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> {t("studio.startPage.btn.allKindsOfPlan")}
        </Link>
      </nav>
      <PageHeader title={t("studio.startPage.tpl.new", { label: info.label.toLowerCase() })} description={t("studio.startPage.desc.howDoYouWantTo")} />
      <KindCard kind={kind} steps={steps} headingLevel={2} large />
    </div>
  );
}

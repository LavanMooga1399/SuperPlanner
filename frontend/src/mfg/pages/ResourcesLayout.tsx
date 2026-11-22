import { Outlet } from "react-router";
import { mfgPaths } from "../lib/paths";
import { SectionTabs } from "./MfgLayout";
import { PageHeader } from "../../components/PageHeader";
import { t } from "../../lib/i18n";

export function ResourcesLayout() {
  return (
    <div className="col gap-lg">
      <PageHeader
        title="People and tooling"
        description={t("mfg.resourcesLayout.desc.skillsTheOperatorsWhoHold")} />
      <SectionTabs
        label="People and tooling sections"
        tabs={[
          { to: mfgPaths.skills(), label: "Skills", testId: "resources-tab-skills" },
          { to: mfgPaths.operators(), label: "Operators", testId: "resources-tab-operators" },
          { to: mfgPaths.tooling(), label: "Tooling", testId: "resources-tab-tooling" },
        ]}
      />
      <Outlet />
    </div>
  );
}

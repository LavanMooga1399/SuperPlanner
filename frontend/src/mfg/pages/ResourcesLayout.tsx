import { Outlet } from "react-router";
import { mfgPaths } from "../lib/paths";
import { SectionTabs } from "./MfgLayout";
import { PageHeader } from "../../components/PageHeader";

export function ResourcesLayout() {
  return (
    <div className="col gap-lg">
      <PageHeader
        title="People &amp; tooling"
        description="Skills, the operators who hold them and the shifts they work, and shared tooling such as stencils and jigs." />
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

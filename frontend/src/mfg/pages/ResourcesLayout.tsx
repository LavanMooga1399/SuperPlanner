import { Outlet } from "react-router";
import { mfgPaths } from "../lib/paths";
import { SectionTabs } from "./MfgLayout";

export function ResourcesLayout() {
  return (
    <div className="col gap-lg">
      <div className="page-header mfg-header">
        <div>
          <h1>People &amp; tooling</h1>
          <p>Skills, the operators who hold them and the shifts they work, and shared tooling such as stencils and jigs.</p>
        </div>
      </div>
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

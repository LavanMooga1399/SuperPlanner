import { Outlet } from "react-router";
import { mfgPaths } from "../lib/paths";
import { SectionTabs } from "./MfgLayout";
import { PageHeader } from "../../components/PageHeader";

export function PlantLayout() {
  return (
    <div className="col gap-lg">
      <PageHeader title="Plant" description="Stages (work-center groups) and their lines, working shifts, holidays and plant settings." />
      <SectionTabs
        label="Plant sections"
        tabs={[
          { to: mfgPaths.groups(), label: "Stages & lines", testId: "plant-tab-groups" },
          { to: mfgPaths.shifts(), label: "Shifts", testId: "plant-tab-shifts" },
          { to: mfgPaths.calendar(), label: "Calendar", testId: "plant-tab-calendar" },
          { to: mfgPaths.setups(), label: "Changeovers", testId: "plant-tab-setups" },
          { to: mfgPaths.settings(), label: "Settings", testId: "plant-tab-settings" },
        ]}
      />
      <Outlet />
    </div>
  );
}

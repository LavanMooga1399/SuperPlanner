import { Outlet } from "react-router";
import { mfgPaths } from "../lib/paths";
import { SectionTabs } from "./MfgLayout";
import { PageHeader } from "../../components/PageHeader";
import { t } from "../../lib/i18n";

export function PlantLayout() {
  return (
    <div className="col gap-lg">
      <PageHeader title={t("mfg.plantLayout.title.plant")} description={t("mfg.plantLayout.desc.stagesWorkcenterGroupsAndTheir")} />
      <SectionTabs
        label={t("mfg.plantLayout.label.plantSections")}
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

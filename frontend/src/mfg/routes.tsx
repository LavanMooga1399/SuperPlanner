/**
 * Manufacturing routes (M 11.1), spread into the existing `App` children inside `RequireAuth` next to the
 * finance routes. The health "Fix" links of M 11.3 resolve to these patterns exactly.
 */
import { Navigate, type RouteObject } from "react-router";
import "./mfg.css";
import { MfgLayout, MfgNotFound } from "./pages/MfgLayout";
import { MfgHome } from "./pages/MfgHome";
import { ItemsPage } from "./pages/ItemsPage";
import { ItemShell } from "./pages/ItemShell";
import { ItemDetailsTab } from "./pages/ItemDetailsTab";
import { BomTab } from "./pages/BomTab";
import { BomEditPage } from "./pages/BomEditPage";
import { WhereUsedTab } from "./pages/WhereUsedTab";
import { RoutingTab } from "./pages/RoutingTab";
import { PlantLayout } from "./pages/PlantLayout";
import { GroupsPage } from "./pages/GroupsPage";
import { ShiftsPage } from "./pages/ShiftsPage";
import { CalendarPage } from "./pages/CalendarPage";
import { PlantSettingsPage } from "./pages/PlantSettingsPage";
import { ResourcesLayout } from "./pages/ResourcesLayout";
import { SkillsPage } from "./pages/SkillsPage";
import { OperatorsPage } from "./pages/OperatorsPage";
import { ToolingPage } from "./pages/ToolingPage";
import { HealthPage } from "./pages/HealthPage";
import { ImportWizard } from "./pages/ImportWizard";

export const mfgRoutes: RouteObject[] = [
  {
    path: "mfg",
    element: <MfgLayout />,
    children: [
      { index: true, element: <MfgHome /> },
      { path: "items", element: <ItemsPage /> },
      {
        path: "items/:itemId",
        element: <ItemShell />,
        children: [
          { index: true, element: <ItemDetailsTab /> },
          { path: "bom", element: <BomTab /> },
          { path: "bom/:bomId/edit", element: <BomEditPage /> },
          { path: "where-used", element: <WhereUsedTab /> },
          { path: "routing", element: <RoutingTab /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      {
        path: "plant",
        element: <PlantLayout />,
        children: [
          { index: true, element: <Navigate to="groups" replace /> },
          { path: "groups", element: <GroupsPage /> },
          { path: "shifts", element: <ShiftsPage /> },
          { path: "calendar", element: <CalendarPage /> },
          { path: "settings", element: <PlantSettingsPage /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      {
        path: "resources",
        element: <ResourcesLayout />,
        children: [
          { index: true, element: <Navigate to="skills" replace /> },
          { path: "skills", element: <SkillsPage /> },
          { path: "operators", element: <OperatorsPage /> },
          { path: "tooling", element: <ToolingPage /> },
          { path: "*", element: <MfgNotFound /> },
        ],
      },
      { path: "health", element: <HealthPage /> },
      { path: "import", element: <ImportWizard /> },
      { path: "import/:importId", element: <ImportWizard /> },
      { path: "*", element: <MfgNotFound /> },
    ],
  },
];

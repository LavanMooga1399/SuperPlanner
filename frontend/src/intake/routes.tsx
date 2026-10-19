/**
 * Intake routes (`/new/:kind/describe`, `/new/:kind/import`, PHASE2.md 3.1, 3.3).
 * `main.tsx` spreads this list into the `App` children (before the `*` route), so P3b adds its routes
 * here without editing `main.tsx`. Unknown kinds show NotFound inside each page.
 */
import type { RouteObject } from "react-router";
import "./intake.css";
import { DescribePage } from "./pages/DescribePage";
import { ImportPage } from "./pages/ImportPage";

export const intakeRoutes: RouteObject[] = [
  { path: "new/:kind/describe", element: <DescribePage /> },
  { path: "new/:kind/import", element: <ImportPage /> },
];

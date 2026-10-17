/**
 * Finance routes (FINANCE.md 20.1), spread into the existing `App` children before the `*` route.
 * Unknown deep paths such as /finance/foo/bar/baz match only `finance/*` and show NotFound.
 */
import type { RouteObject } from "react-router";
import { NotFound } from "../App";
import "./finance.css";
import { ComparePage } from "./pages/ComparePage";
import { FinanceHome } from "./pages/FinanceHome";
import { FinanceLayout } from "./pages/FinanceLayout";
import { FinancePlanIndex } from "./pages/FinancePlanIndex";
import { FinancePlanShell } from "./pages/FinancePlanShell";
import { ResultsPage } from "./pages/ResultsPage";
import { WhatIfPage } from "./pages/WhatIfPage";
import { WizardPage } from "./pages/WizardPage";

export const financeRoutes: RouteObject[] = [
  {
    path: "finance",
    element: <FinanceLayout />,
    children: [
      { index: true, element: <FinanceHome /> },
      {
        path: ":planId",
        element: <FinancePlanShell />,
        children: [
          { index: true, element: <FinancePlanIndex /> },
          { path: "setup/:step", element: <WizardPage /> },
          { path: "results", element: <ResultsPage /> },
          { path: "what-if", element: <WhatIfPage /> },
          { path: "compare", element: <ComparePage /> },
        ],
      },
      { path: "*", element: <NotFound /> },
    ],
  },
];

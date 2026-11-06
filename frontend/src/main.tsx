import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate } from "react-router";
import { RouterProvider } from "react-router/dom";
import "./styles/theme.css";
import { App, NotFound } from "./App";
import { HomePage } from "./pages/HomePage";
import { PlanWorkspace } from "./pages/PlanWorkspace";
import { TasksTab } from "./pages/tabs/TasksTab";
import { ResourcesTab } from "./pages/tabs/ResourcesTab";
import { DependenciesTab } from "./pages/tabs/DependenciesTab";
import { ValidateTab } from "./pages/tabs/ValidateTab";
import { OptimizeTab } from "./pages/tabs/OptimizeTab";
import { ScheduleTab } from "./pages/tabs/ScheduleTab";
import { CompareTab } from "./pages/tabs/CompareTab";
import { financeRoutes } from "./finance/routes";
import { intakeRoutes } from "./intake/routes";
import { mfgRoutes } from "./mfg/routes";
import { ExamplePage } from "./landing/ExamplePage";
import { StartPage } from "./landing/StartPage";
import { AuthRoot } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { SignInPage } from "./auth/SignInPage";
import { SecurityPage } from "./auth/SecurityPage";
import { TokensPage } from "./auth/TokensPage";
import { OrgListPage, OrgPage } from "./orgs/OrgPages";
import { SignUpPage } from "./auth/SignUpPage";
import { AccountPage } from "./auth/AccountPage";
import { registerServiceWorker } from "./pwa/pwa";
import { mobileRoutes } from "./mfg/mobile/routes";

// PHASE2B 4.10: the auth provider wraps everything (it needs the router); sign-in/sign-up sit outside the
// guard; every existing page is inside it. In single_user mode the guard renders the pages as before.
const router = createBrowserRouter([
  {
    element: <AuthRoot />,
    children: [
      // M6 2: the phone app (`/m`), its own shell without the desktop top bar
      ...mobileRoutes,
      {
        path: "/",
        element: <App />,
        children: [
          { path: "sign-in", element: <SignInPage /> },
          { path: "sign-up", element: <SignUpPage /> },
          // M5 3.2: also reached while a sign-in waits for its forced 2FA setup (`?pending=`), so outside the guard
          { path: "account/security", element: <SecurityPage /> },
          {
            element: <RequireAuth />,
            children: [
              { index: true, element: <HomePage /> },
              {
                path: "plans/:planId",
                element: <PlanWorkspace />,
                children: [
                  { index: true, element: <Navigate to="tasks" replace /> },
                  { path: "tasks", element: <TasksTab /> },
                  { path: "resources", element: <ResourcesTab /> },
                  { path: "dependencies", element: <DependenciesTab /> },
                  { path: "validate", element: <ValidateTab /> },
                  { path: "optimize", element: <OptimizeTab /> },
                  { path: "schedule", element: <ScheduleTab /> },
                  { path: "compare", element: <CompareTab /> },
                  { path: "*", element: <NotFound /> },
                ],
              },
              ...financeRoutes,
              ...mfgRoutes,
              { path: "new/:kind", element: <StartPage /> },
              { path: "new/:kind/example", element: <ExamplePage /> },
              ...intakeRoutes,
              { path: "account", element: <AccountPage /> },
              { path: "account/tokens", element: <TokensPage /> },
              { path: "orgs", element: <OrgListPage /> },
              { path: "orgs/:org", element: <OrgPage tab="overview" /> },
              { path: "orgs/:org/dashboard", element: <OrgPage tab="dashboard" /> },
              { path: "orgs/:org/plants", element: <OrgPage tab="plants" /> },
              { path: "orgs/:org/members", element: <OrgPage tab="members" /> },
              { path: "orgs/:org/publish", element: <OrgPage tab="publish" /> },
              { path: "orgs/:org/settings", element: <OrgPage tab="settings" /> },
              { path: "*", element: <NotFound /> },
            ],
          },
        ],
      },
    ],
  },
]);

// M6 2: the app shell is cached by the service worker in production builds; the dev server registers it only from
// the mobile pages (`/m`), so the desktop e2e specs keep plain network routing.
if (import.meta.env.PROD) window.addEventListener("load", () => void registerServiceWorker());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);

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
import { ExamplePage } from "./landing/ExamplePage";
import { StartPage } from "./landing/StartPage";
import { AuthRoot } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { SignInPage } from "./auth/SignInPage";
import { SignUpPage } from "./auth/SignUpPage";
import { AccountPage } from "./auth/AccountPage";

// PHASE2B 4.10: the auth provider wraps everything (it needs the router); sign-in/sign-up sit outside the
// guard; every existing page is inside it. In single_user mode the guard renders the pages as before.
const router = createBrowserRouter([
  {
    element: <AuthRoot />,
    children: [
      {
        path: "/",
        element: <App />,
        children: [
          { path: "sign-in", element: <SignInPage /> },
          { path: "sign-up", element: <SignUpPage /> },
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
              { path: "new/:kind", element: <StartPage /> },
              { path: "new/:kind/example", element: <ExamplePage /> },
              ...intakeRoutes,
              { path: "account", element: <AccountPage /> },
              { path: "*", element: <NotFound /> },
            ],
          },
        ],
      },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);

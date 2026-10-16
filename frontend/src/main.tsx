import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
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

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
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
      { path: "*", element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);

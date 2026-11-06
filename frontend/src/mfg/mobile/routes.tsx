/** M6 2: phone routes under `/m` (inside the auth guard, outside the desktop shell). */
import type { RouteObject } from "react-router";
import { RequireAuth } from "../../auth/RequireAuth";
import { MobileAlerts } from "./MobileAlerts";
import { MobileApprovals } from "./MobileApprovals";
import { MobileHome } from "./MobileHome";
import { MobileLayout } from "./MobileLayout";
import { MobileLine, MobileLines } from "./MobileLines";
import { MobileAssistant, MobileMore, MobileScan, MobileWo } from "./MobileMisc";
import { useParams } from "react-router";
import type { ReactElement } from "react";

function Keyed({ param, children }: { param: string; children: (key: string) => ReactElement }) {
  const params = useParams();
  return children(params[param] ?? "");
}

export const mobileRoutes: RouteObject[] = [
  {
    path: "m",
    element: <RequireAuth />,
    children: [
      {
        element: <MobileLayout />,
        children: [
          { index: true, element: <MobileHome /> },
          { path: "lines", element: <MobileLines /> },
          { path: "lines/:lineId", element: <Keyed param="lineId">{(k) => <MobileLine key={k} />}</Keyed> },
          { path: "alerts", element: <MobileAlerts /> },
          { path: "approvals", element: <MobileApprovals /> },
          { path: "wo/:woId", element: <Keyed param="woId">{(k) => <MobileWo key={k} />}</Keyed> },
          { path: "scan", element: <MobileScan /> },
          { path: "assistant", element: <MobileAssistant /> },
          { path: "more", element: <MobileMore /> },
          { path: "*", element: <MobileHome /> },
        ],
      },
    ],
  },
];

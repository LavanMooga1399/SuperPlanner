import { useEffect } from "react";
import { Outlet, useLocation } from "react-router";
import { DisclaimerBanner, DisclaimerDialog } from "../components/DisclaimerBanner";

/** Wraps every /finance/** route: disclaimer banner (F.21 rule 1) and first-visit dialog (rule 2). */
export function FinanceLayout() {
  const { pathname } = useLocation();
  const onResults = /\/results\/?$/.test(pathname);
  useEffect(() => {
    document.title = "Finance - SuperPlanner";
    return () => {
      document.title = "SuperPlanner Studio";
    };
  }, []);
  return (
    <div className="fin-page">
      <DisclaimerBanner compact={!onResults} />
      <Outlet />
      <DisclaimerDialog />
    </div>
  );
}

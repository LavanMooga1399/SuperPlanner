import { useEffect } from "react";
import { Outlet, useLocation } from "react-router";
import { DisclaimerBanner, DisclaimerDialog } from "../components/DisclaimerBanner";
import { t } from "../../lib/i18n";

/** Wraps every /finance/** route: disclaimer banner (F.21 rule 1) and first-visit dialog (rule 2). */
export function FinanceLayout() {
  const { pathname } = useLocation();
  const onResults = /\/results\/?$/.test(pathname);
  useEffect(() => {
    document.title = t("finance.financeLayout.str.financeSuperplanner");
    return () => {
      document.title = t("finance.financeLayout.str.superplannerStudio");
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

/** `/mfg/purchasing/**` shell (M2 14.2): purchase orders, purchase requests, delivery schedule, suppliers. */
import { Navigate, Outlet, useLocation } from "react-router";
import { mfgPaths } from "../../lib/paths";
import { SectionTabs } from "../MfgLayout";
import { PageHeader } from "../../../components/PageHeader";
import { t } from "../../../lib/i18n";

export function PurchasingLayout() {
  const { pathname } = useLocation();
  if (/^\/mfg\/purchasing\/?$/.test(pathname)) return <Navigate to={mfgPaths.purchaseDocs("po")} replace />;
  return (
    <div className="col gap-lg">
      <PageHeader
        title={t("mfg.purchasingLayout.title.purchasing")}
        description={t("mfg.purchasingLayout.desc.purchaseRequestsPurchaseOrdersWith")} />
      <SectionTabs
        label={t("mfg.purchasingLayout.label.purchasingSections")}
        tabs={[
          { to: mfgPaths.purchaseDocs("po"), label: "Purchase orders", testId: "pur-tab-orders" },
          { to: mfgPaths.purchaseDocs("pr"), label: "Purchase requests", testId: "pur-tab-requests" },
          { to: mfgPaths.deliveryBoard(), label: "Delivery schedule", testId: "pur-tab-schedule" },
          { to: mfgPaths.suppliers(), label: "Suppliers", testId: "pur-tab-suppliers" },
        ]}
      />
      <Outlet />
    </div>
  );
}

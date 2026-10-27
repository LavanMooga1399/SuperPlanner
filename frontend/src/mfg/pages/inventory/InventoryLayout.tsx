/** `/mfg/inventory/**` shell (M2 14.2): title, "Post" menu and the tabs Stock / Ledger / Lots / Locations. */
import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import type { PostingType } from "../../api/typesM2";
import { ImportShortcut } from "../../components/ImportShortcut";
import { PermissionGate } from "../../components/PermissionGate";
import { POSTING_LABEL } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { SectionTabs } from "../MfgLayout";

export const FORM_TYPES: PostingType[] = ["receipt_misc", "issue_misc", "transfer", "adjust", "count"];

/** Menu of the manual posting types; keeps `item`/`location` filters of the current page as defaults. */
export function PostMenu() {
  const [open, setOpen] = useState(false);
  const [params] = useSearchParams();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const item = params.get("item") ?? undefined;
  const location = params.get("location") ?? undefined;
  return (
    <PermissionGate perm="inventory">
      <div className="mfg-menu" ref={ref}>
        <button type="button" className="btn primary" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} data-testid="post-menu">
          <Icon name="plus" /> Post stock movement <Icon name="chevron-down" />
        </button>
        {open ? (
          <div className="mfg-menu-list" role="menu">
            {FORM_TYPES.map((t) => (
              <Link key={t} role="menuitem" className="mfg-menu-item" to={mfgPaths.post({ type: t, item, location })} onClick={() => setOpen(false)} data-testid={`post-menu-${t}`}>
                {POSTING_LABEL[t]}
              </Link>
            ))}
            <p className="faint small" style={{ margin: "4px 8px" }}>
              Goods receipts against purchase orders: open the order and use Receive.
            </p>
          </div>
        ) : null}
      </div>
    </PermissionGate>
  );
}

export function InventoryLayout() {
  return (
    <div className="col gap-lg">
      <div className="page-header mfg-header">
        <div>
          <h1>Inventory</h1>
          <p>Stock by location and lot. Every change is a posting in the ledger; corrections are reversals.</p>
        </div>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <ImportShortcut what="stock" testId="inventory-import" />
          <PostMenu />
        </div>
      </div>
      <SectionTabs
        label="Inventory sections"
        tabs={[
          { to: mfgPaths.inventory(), label: "Stock", testId: "inv-tab-balances", end: true },
          { to: mfgPaths.transactions(), label: "Ledger", testId: "inv-tab-transactions" },
          { to: mfgPaths.lots(), label: "Lots", testId: "inv-tab-lots" },
          { to: mfgPaths.locations(), label: "Locations", testId: "inv-tab-locations" },
        ]}
      />
      <Outlet />
    </div>
  );
}

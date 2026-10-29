/** `/mfg/items/:itemId` shell (M 11.1): header + tabs (Details, BOM, Where used, Routing). */
import { NavLink, Outlet, useOutletContext, useParams, Link } from "react-router";
import { Icon } from "../../components/Icon";
import { getItem } from "../api/client";
import type { ItemRecord } from "../api/types";
import { MfgError, NotFoundPanel, Spinner } from "../components/Feedback";
import { ActiveBadge, MakeBuyBadge } from "../components/StatusChip";
import { mfgPaths } from "../lib/paths";
import { isNotFound, useLoad } from "../lib/useMfg";

export interface ItemContext {
  item: ItemRecord;
  setItem(item: ItemRecord): void;
  reloadItem(): void;
}

export function useItem(): ItemContext {
  return useOutletContext<ItemContext>();
}

export function ItemShell() {
  const { itemId = "" } = useParams();
  const item = useLoad((signal) => getItem(itemId, signal), [itemId]);
  const it = item.data && item.data.id === itemId ? item.data : null;

  if (item.error && isNotFound(item.error))
    return (
      <NotFoundPanel
        what="Item"
        back={
          <Link className="btn" to={mfgPaths.items()}>
            Back to items
          </Link>
        }
      />
    );
  if (item.error && !it) return <MfgError error={item.error} onRetry={item.reload} />;
  if (!it) return <Spinner label="Loading item…" />;

  const tabs = [
    { to: mfgPaths.item(it.id), label: "Details", end: true as boolean, testId: "item-tab-details" },
    { to: mfgPaths.itemBom(it.id), label: "BOM", testId: "item-tab-bom" },
    { to: mfgPaths.whereUsed(it.id), label: "Where used", testId: "item-tab-where-used" },
    { to: mfgPaths.routing(it.id), label: "Routing", testId: "item-tab-routing" },
    { to: mfgPaths.itemStock(it.id), label: "Stock", testId: "item-tab-stock" },
    ...(it.make_buy === "buy" ? [{ to: mfgPaths.itemSuppliers(it.id), label: "Suppliers", testId: "item-tab-suppliers" }] : []),
  ];
  const ctx: ItemContext = { item: it, setItem: (x) => item.setData(x), reloadItem: item.reload };

  return (
    <div className="col" style={{ gap: 12 }}>
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.items()}>Items</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{it.part_number}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 className="mono" data-testid="item-title">
            {it.part_number}
          </h1>
          <span className="chip" title="Revision">
            Rev. {it.revision}
          </span>
          <MakeBuyBadge value={it.make_buy} />
          <ActiveBadge active={it.active} />
          <span className="muted mfg-ellipsis" style={{ minWidth: 0 }}>
            {it.description}
          </span>
        </div>
      </div>
      <nav className="tabs" aria-label="Item sections">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => `tab${isActive ? " active" : ""}`} data-testid={t.testId}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="tab-panel" style={{ paddingTop: 4 }}>
        <Outlet context={ctx} />
      </div>
    </div>
  );
}

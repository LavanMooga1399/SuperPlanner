/** `/mfg/items/:itemId` shell (M 11.1): header + tabs (Details, BOM, Where used, Routing). */
import { NavLink, Outlet, useOutletContext, useParams, Link } from "react-router";
import { Icon } from "../../components/Icon";
import { getItem } from "../api/client";
import type { ItemRecord } from "../api/types";
import { MfgError, NotFoundPanel, Spinner } from "../components/Feedback";
import { ActiveBadge, MakeBuyBadge } from "../components/StatusChip";
import { mfgPaths } from "../lib/paths";
import { isNotFound, useLoad } from "../lib/useMfg";
import { t, t as tr } from "../../lib/i18n";

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
        what={tr("mfg.itemShell.attr.item")}
        back={
          <Link className="btn" to={mfgPaths.items()}>
            {t("mfg.itemShell.btn.backToItems")}
          </Link>
        }
      />
    );
  if (item.error && !it) return <MfgError error={item.error} onRetry={item.reload} />;
  if (!it) return <Spinner label={t("mfg.itemShell.label.loadingItem")} />;

  const tabs = [
    { to: mfgPaths.item(it.id), label: tr("mfg.itemShell.str.details"), end: true as boolean, testId: "item-tab-details" },
    { to: mfgPaths.itemBom(it.id), label: "BOM", testId: "item-tab-bom" },
    { to: mfgPaths.whereUsed(it.id), label: tr("mfg.itemShell.str.whereUsed"), testId: "item-tab-where-used" },
    { to: mfgPaths.routing(it.id), label: tr("mfg.itemShell.str.routing"), testId: "item-tab-routing" },
    { to: mfgPaths.itemStock(it.id), label: tr("mfg.itemShell.str.stock"), testId: "item-tab-stock" },
    ...(it.make_buy === "buy" ? [{ to: mfgPaths.itemSuppliers(it.id), label: tr("mfg.itemShell.str.suppliers"), testId: "item-tab-suppliers" }] : []),
  ];
  const ctx: ItemContext = { item: it, setItem: (x) => item.setData(x), reloadItem: item.reload };

  return (
    <div className="col" style={{ gap: 12 }}>
      <nav aria-label={t("mfg.itemShell.aria.breadcrumb")} className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.items()}>{tr("mfg.itemShell.text.items")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{it.part_number}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 className="mono" data-testid="item-title">
            {it.part_number}
          </h1>
          <span className="chip" title={tr("mfg.itemShell.attr.revision")}>
            {tr("mfg.itemShell.text.rev", { revision: it.revision })}
          </span>
          <MakeBuyBadge value={it.make_buy} />
          <ActiveBadge active={it.active} />
          <span className="muted mfg-ellipsis" style={{ minWidth: 0 }}>
            {it.description}
          </span>
        </div>
      </div>
      <nav className="tabs" aria-label={t("mfg.itemShell.aria.itemSections")}>
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

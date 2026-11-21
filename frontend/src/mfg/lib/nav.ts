/**
 * Manufacturing navigation model (UX-STANDARD 3): one definition for the sidebar, the breadcrumbs and the
 * command palette. Groups follow the people who use them (planners, buyers and stores, supervisors, managers,
 * master-data owners). `key` drives the `mfg-subnav-<key>` test ids; `testId` the `nav-group-*` ids.
 */
import type { IconName } from "../../components/Icon";
import { mfgPaths } from "./paths";

export interface NavSection {
  key: string;
  label: string;
  to: string;
  icon: IconName;
  end?: boolean;
  /** Extra path prefixes that belong to this section (for breadcrumbs / active state). */
  match?: string[];
  /** Words the command palette also matches. */
  keywords?: string;
  ownerOnly?: boolean;
}

export interface NavGroupDef {
  key: string;
  label: string;
  testId: string;
  sections: NavSection[];
}

export const MFG_NAV: NavGroupDef[] = [
  {
    key: "overview",
    label: "Overview",
    testId: "nav-group-overview",
    sections: [
      { key: "overview", label: "Overview", to: mfgPaths.home(), icon: "home", end: true, keywords: "home start" },
      { key: "dashboard", label: "Dashboard", to: mfgPaths.dashboard(), icon: "dashboard", keywords: "management tiles" },
      { key: "kpis", label: "KPIs", to: mfgPaths.kpis(), icon: "chart", keywords: "oee adherence performance" },
    ],
  },
  {
    key: "planning",
    label: "Planning",
    testId: "nav-group-planning",
    sections: [
      { key: "demand", label: "Demand", to: mfgPaths.demand(), icon: "flag", keywords: "demand orders sales orders customer" },
      { key: "mrp", label: "MRP", to: mfgPaths.mrp(), icon: "layers", keywords: "material requirements planning runs planned orders" },
      { key: "schedule", label: "Schedule", to: mfgPaths.schedule(), icon: "calendar", keywords: "aps gantt schedule runs capacity" },
      { key: "shortages", label: "Shortages", to: mfgPaths.shortages(), icon: "alert", keywords: "missing material" },
      { key: "replan", label: "Replanning", to: mfgPaths.replan(), icon: "refresh", keywords: "triggers notifications" },
    ],
  },
  {
    key: "supply",
    label: "Supply and stores",
    testId: "nav-group-supply",
    sections: [
      { key: "purchasing", label: "Purchasing", to: mfgPaths.purchasing(), icon: "briefcase", keywords: "purchase orders requests suppliers deliveries" },
      { key: "inventory", label: "Inventory", to: mfgPaths.inventory(), icon: "box", keywords: "stock balances lots locations postings" },
      { key: "transfers", label: "Transfers", to: mfgPaths.transfers(), icon: "truck", keywords: "inter-plant" },
    ],
  },
  {
    key: "production",
    label: "Production",
    testId: "nav-group-execution",
    sections: [
      { key: "work-orders", label: "Work orders", to: mfgPaths.workOrders(), icon: "wrench", keywords: "wo kitting" },
      { key: "floor", label: "Shop floor", to: mfgPaths.floorOverview(), icon: "factory", keywords: "lines operations downtime" },
      { key: "serials", label: "Serials", to: mfgPaths.serials(), icon: "barcode", keywords: "serial numbers units" },
      { key: "trace", label: "Trace and recall", to: mfgPaths.trace(), icon: "link", match: ["/mfg/recalls"], keywords: "genealogy where used recall" },
    ],
  },
  {
    key: "master",
    label: "Master data",
    testId: "nav-group-setup",
    sections: [
      { key: "items", label: "Items", to: mfgPaths.items(), icon: "list", keywords: "parts bom routing" },
      { key: "plant", label: "Plant", to: mfgPaths.plant(), icon: "settings", keywords: "lines groups shifts calendar setups" },
      { key: "resources", label: "People and tooling", to: mfgPaths.resources(), icon: "users", keywords: "operators skills tools" },
      { key: "health", label: "Data health", to: mfgPaths.health(), icon: "check", keywords: "issues validation" },
      { key: "import", label: "Import and export", to: mfgPaths.importStart(), icon: "upload", keywords: "excel csv" },
      { key: "members", label: "Members", to: mfgPaths.members(), icon: "lock", ownerOnly: true, match: ["/mfg/settings"], keywords: "roles access" },
    ],
  },
  {
    key: "control",
    label: "Control",
    testId: "nav-group-control",
    sections: [
      { key: "eco", label: "Engineering changes", to: mfgPaths.ecos(), icon: "file", keywords: "eco change requests" },
      { key: "integration", label: "ERP integration", to: mfgPaths.integration(), icon: "database", keywords: "erp sync endpoints" },
      { key: "audit", label: "Audit trail", to: mfgPaths.audit(), icon: "shield", keywords: "history log" },
    ],
  },
];

/** The section (and its group) a pathname belongs to; the longest matching prefix wins. */
export function sectionFor(pathname: string): { group: NavGroupDef; section: NavSection } | null {
  let best: { group: NavGroupDef; section: NavSection; len: number } | null = null;
  for (const group of MFG_NAV)
    for (const section of group.sections) {
      const prefixes = [section.to.split("?")[0], ...(section.match ?? [])];
      for (const p of prefixes) {
        const hit = section.end ? pathname === p || pathname === `${p}/` : pathname === p || pathname.startsWith(`${p}/`);
        if (hit && (!best || p.length > best.len)) best = { group, section, len: p.length };
      }
    }
  // the shop-floor overview lives under /mfg/floor/overview; the floor events page under /mfg/floor/events
  if (!best && pathname.startsWith("/mfg/floor/")) {
    const g = MFG_NAV.find((x) => x.key === "production")!;
    return { group: g, section: g.sections.find((s) => s.key === "floor")! };
  }
  return best ? { group: best.group, section: best.section } : null;
}

/**
 * Manufacturing navigation model (UX-STANDARD 3): one definition for the sidebar, the breadcrumbs and the
 * command palette. Groups follow the people who use them (planners, buyers and stores, supervisors, managers,
 * master-data owners). `key` drives the `mfg-subnav-<key>` test ids; `testId` the `nav-group-*` ids.
 */
import type { IconName } from "../../components/Icon";
import { mfgPaths } from "./paths";
import { t } from "../../lib/i18n";

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
    get label() {
      return t("nav.mfg.group.overview");
    },
    testId: "nav-group-overview",
    sections: [
      { key: "overview", get label() { return t("nav.mfg.section.overview"); }, to: mfgPaths.home(), icon: "home", end: true, keywords: t("mfg.nav.str.homeStart") },
      { key: "dashboard", get label() { return t("nav.mfg.section.dashboard"); }, to: mfgPaths.dashboard(), icon: "dashboard", keywords: t("mfg.nav.str.managementTiles") },
      { key: "kpis", get label() { return t("nav.mfg.section.kpis"); }, to: mfgPaths.kpis(), icon: "chart", keywords: t("mfg.nav.str.oeeAdherencePerformance") },
    ],
  },
  {
    key: "planning",
    get label() {
      return t("nav.mfg.group.planning");
    },
    testId: "nav-group-planning",
    sections: [
      { key: "demand", get label() { return t("nav.mfg.section.demand"); }, to: mfgPaths.demand(), icon: "flag", keywords: t("mfg.nav.str.demandOrdersSalesOrdersCustomer") },
      { key: "mrp", get label() { return t("nav.mfg.section.mrp"); }, to: mfgPaths.mrp(), icon: "layers", keywords: t("mfg.nav.str.materialRequirementsPlanningRunsPlanned") },
      { key: "schedule", get label() { return t("nav.mfg.section.schedule"); }, to: mfgPaths.schedule(), icon: "calendar", keywords: t("mfg.nav.str.apsGanttScheduleRunsCapacity") },
      { key: "shortages", get label() { return t("nav.mfg.section.shortages"); }, to: mfgPaths.shortages(), icon: "alert", keywords: t("mfg.nav.str.missingMaterial") },
      { key: "replan", get label() { return t("nav.mfg.section.replan"); }, to: mfgPaths.replan(), icon: "refresh", keywords: t("mfg.nav.str.triggersNotifications") },
    ],
  },
  {
    key: "supply",
    get label() {
      return t("nav.mfg.group.supply");
    },
    testId: "nav-group-supply",
    sections: [
      { key: "purchasing", get label() { return t("nav.mfg.section.purchasing"); }, to: mfgPaths.purchasing(), icon: "briefcase", keywords: t("mfg.nav.str.purchaseOrdersRequestsSuppliersDeliveries") },
      { key: "inventory", get label() { return t("nav.mfg.section.inventory"); }, to: mfgPaths.inventory(), icon: "box", keywords: t("mfg.nav.str.stockBalancesLotsLocationsPostings") },
      { key: "transfers", get label() { return t("nav.mfg.section.transfers"); }, to: mfgPaths.transfers(), icon: "truck", keywords: "inter-plant" },
    ],
  },
  {
    key: "production",
    get label() {
      return t("nav.mfg.group.production");
    },
    testId: "nav-group-execution",
    sections: [
      { key: "work-orders", get label() { return t("nav.mfg.section.work-orders"); }, to: mfgPaths.workOrders(), icon: "wrench", keywords: t("mfg.nav.str.woKitting") },
      { key: "floor", get label() { return t("nav.mfg.section.floor"); }, to: mfgPaths.floorOverview(), icon: "factory", keywords: t("mfg.nav.str.linesOperationsDowntime") },
      { key: "serials", get label() { return t("nav.mfg.section.serials"); }, to: mfgPaths.serials(), icon: "barcode", keywords: t("mfg.nav.str.serialNumbersUnits") },
      { key: "trace", get label() { return t("nav.mfg.section.trace"); }, to: mfgPaths.trace(), icon: "link", match: ["/mfg/recalls"], keywords: t("mfg.nav.str.genealogyWhereUsedRecall") },
    ],
  },
  {
    key: "master",
    get label() {
      return t("nav.mfg.group.master");
    },
    testId: "nav-group-setup",
    sections: [
      { key: "items", get label() { return t("nav.mfg.section.items"); }, to: mfgPaths.items(), icon: "list", keywords: t("mfg.nav.str.partsBomRouting") },
      { key: "plant", get label() { return t("nav.mfg.section.plant"); }, to: mfgPaths.plant(), icon: "settings", keywords: t("mfg.nav.str.linesGroupsShiftsCalendarSetups") },
      { key: "resources", get label() { return t("nav.mfg.section.resources"); }, to: mfgPaths.resources(), icon: "users", keywords: t("mfg.nav.str.operatorsSkillsTools") },
      { key: "health", get label() { return t("nav.mfg.section.health"); }, to: mfgPaths.health(), icon: "check", keywords: t("mfg.nav.str.issuesValidation") },
      { key: "import", get label() { return t("nav.mfg.section.import"); }, to: mfgPaths.importStart(), icon: "upload", keywords: t("mfg.nav.str.excelCsv") },
      { key: "members", get label() { return t("nav.mfg.section.members"); }, to: mfgPaths.members(), icon: "lock", ownerOnly: true, match: ["/mfg/settings"], keywords: t("mfg.nav.str.rolesAccess") },
    ],
  },
  {
    key: "control",
    get label() {
      return t("nav.mfg.group.control");
    },
    testId: "nav-group-control",
    sections: [
      { key: "eco", get label() { return t("nav.mfg.section.eco"); }, to: mfgPaths.ecos(), icon: "file", keywords: t("mfg.nav.str.ecoChangeRequests") },
      { key: "integration", get label() { return t("nav.mfg.section.integration"); }, to: mfgPaths.integration(), icon: "database", keywords: t("mfg.nav.str.erpSyncEndpoints") },
      { key: "audit", get label() { return t("nav.mfg.section.audit"); }, to: mfgPaths.audit(), icon: "shield", keywords: t("mfg.nav.str.historyLog") },
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

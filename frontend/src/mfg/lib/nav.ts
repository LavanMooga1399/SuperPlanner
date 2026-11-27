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
  /** M9: `network` = only in the network workspace, `both` = everywhere; default plant only. */
  scope?: "plant" | "network" | "both";
}

export interface NavGroupDef {
  key: string;
  label: string;
  testId: string;
  sections: NavSection[];
  /** M9: `network` = only in the network workspace, `both` = everywhere; default plant only. */
  scope?: "plant" | "network" | "both";
}

export const MFG_NAV: NavGroupDef[] = [
  // M9 10: the network workspace shows its own group; plant-only menus are hidden there
  {
    key: "network",
    get label() {
      return t("net.nav.group");
    },
    testId: "nav-group-network",
    scope: "network",
    sections: [
      { key: "network", get label() { return t("net.nav.network"); }, to: mfgPaths.network(), icon: "link", end: true, match: ["/mfg/network/runs"], keywords: t("net.nav.kwNetwork") },
      { key: "network-sourcing", get label() { return t("net.nav.sourcing"); }, to: mfgPaths.networkSourcing(), icon: "truck", keywords: t("net.nav.kwSourcing") },
      { key: "sop", get label() { return t("net.nav.sop"); }, to: mfgPaths.sop(), icon: "calendar", keywords: t("net.nav.kwSop") },
      { key: "trade", get label() { return t("net.nav.trade"); }, to: mfgPaths.trade(), icon: "flag", keywords: t("net.nav.kwTrade") },
      { key: "sourcing-risk", get label() { return t("net.nav.risk"); }, to: mfgPaths.sourcingRisk(), icon: "shield", scope: "both", keywords: t("net.nav.kwRisk") },
    ],
  },
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
      { key: "forecast", get label() { return t("nav.mfg.section.forecast"); }, to: mfgPaths.forecast(), icon: "chart", keywords: t("nav.mfg.kw.forecast") },
      { key: "invopt", get label() { return t("nav.mfg.section.invopt"); }, to: mfgPaths.invopt(), icon: "shield", keywords: t("nav.mfg.kw.invopt") },
      { key: "rate", get label() { return t("nav.mfg.section.rate"); }, to: mfgPaths.ratePlans(), icon: "columns", keywords: t("nav.mfg.kw.rate") },
      { key: "sterilisation", get label() { return t("nav.mfg.section.sterilisation"); }, to: mfgPaths.sterilisation(), icon: "clock", keywords: t("nav.mfg.kw.sterilisation") },
      { key: "kanban", get label() { return t("nav.mfg.section.kanban"); }, to: mfgPaths.kanban(), icon: "barcode", keywords: t("nav.mfg.kw.kanban") },
      { key: "shortages", get label() { return t("nav.mfg.section.shortages"); }, to: mfgPaths.shortages(), icon: "alert", keywords: t("mfg.nav.str.missingMaterial") },
      { key: "mps", get label() { return t("net.nav.mps"); }, to: mfgPaths.mps(), icon: "compare", keywords: t("net.nav.kwMps") },
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
      { key: "plant-sourcing-risk", get label() { return t("net.nav.risk"); }, to: mfgPaths.sourcingRisk(), icon: "shield", keywords: t("net.nav.kwRisk") },
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
    key: "quality",
    get label() {
      return t("nav.mfg.group.quality");
    },
    testId: "nav-group-quality",
    sections: [
      { key: "qa-lots", get label() { return t("nav.mfg.section.qa-lots"); }, to: mfgPaths.qaLots(), icon: "eye", keywords: t("nav.mfg.kw.qa-lots") },
      { key: "qa-holds", get label() { return t("nav.mfg.section.qa-holds"); }, to: mfgPaths.qaHolds(), icon: "lock", keywords: t("nav.mfg.kw.qa-holds") },
      { key: "qa-ncrs", get label() { return t("nav.mfg.section.qa-ncrs"); }, to: mfgPaths.qaNcrs(), icon: "alert", keywords: t("nav.mfg.kw.qa-ncrs") },
      { key: "qa-capas", get label() { return t("nav.mfg.section.qa-capas"); }, to: mfgPaths.qaCapas(), icon: "refresh", keywords: t("nav.mfg.kw.qa-capas") },
      { key: "qa-complaints", get label() { return t("nav.mfg.section.qa-complaints"); }, to: mfgPaths.qaComplaints(), icon: "chat", keywords: t("nav.mfg.kw.qa-complaints") },
      { key: "qa-field-actions", get label() { return t("nav.mfg.section.qa-field-actions"); }, to: mfgPaths.qaFieldActions(), icon: "truck", keywords: t("nav.mfg.kw.qa-field-actions") },
      { key: "qa-equipment", get label() { return t("nav.mfg.section.qa-equipment"); }, to: mfgPaths.qaEquipmentList(), icon: "wrench", keywords: t("nav.mfg.kw.qa-equipment") },
      { key: "qa-plans", get label() { return t("nav.mfg.section.qa-plans"); }, to: mfgPaths.qaPlans(), icon: "file", keywords: t("nav.mfg.kw.qa-plans") },
      { key: "qa-schemes", get label() { return t("nav.mfg.section.qa-schemes"); }, to: mfgPaths.qaSchemes(), icon: "columns", keywords: t("nav.mfg.kw.qa-schemes") },
      { key: "qa-settings", get label() { return t("nav.mfg.section.qa-settings"); }, to: mfgPaths.qaSettings(), icon: "settings", keywords: t("nav.mfg.kw.qa-settings") },
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
    scope: "both",
    sections: [
      { key: "eco", get label() { return t("nav.mfg.section.eco"); }, to: mfgPaths.ecos(), icon: "file", keywords: t("mfg.nav.str.ecoChangeRequests") },
      { key: "integration", get label() { return t("nav.mfg.section.integration"); }, to: mfgPaths.integration(), icon: "database", keywords: t("mfg.nav.str.erpSyncEndpoints") },
      { key: "audit", get label() { return t("nav.mfg.section.audit"); }, to: mfgPaths.audit(), icon: "shield", keywords: t("mfg.nav.str.historyLog") },
      { key: "esig-policies", get label() { return t("nav.mfg.section.esig-policies"); }, to: mfgPaths.esigPolicies(), icon: "lock", keywords: t("nav.mfg.kw.esig-policies") },
      { key: "part11", get label() { return t("nav.mfg.section.part11"); }, to: mfgPaths.part11(), icon: "check", end: true, keywords: t("nav.mfg.kw.part11") },
      { key: "validation", get label() { return t("nav.mfg.section.validation"); }, to: mfgPaths.validation(), icon: "check", keywords: t("nav.mfg.kw.validation") },
      { key: "part11-export", get label() { return t("nav.mfg.section.part11-export"); }, to: mfgPaths.part11Exports(), icon: "download", keywords: t("nav.mfg.kw.part11-export") },
    ],
  },
];

/** Groups and sections visible in the current workspace kind (M9 10). */
export function navFor(isNetwork: boolean): NavGroupDef[] {
  const show = (scope: NavGroupDef["scope"]) => (scope === "both" ? true : scope === "network" ? isNetwork : !isNetwork);
  return MFG_NAV.filter((g) => show(g.scope)).map((g) => (g.scope === "both" ? { ...g, sections: g.sections.filter((s) => s.scope !== "network" || isNetwork) } : g));
}

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

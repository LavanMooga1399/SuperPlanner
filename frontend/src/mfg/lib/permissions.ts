/**
 * Role-based UI gating (M2 10.2, 14.1). `GET /me` is loaded once per Manufacturing area mount and shared via
 * context; components ask `can("inventory")`. The server stays the authority: a 403 `MFG_FORBIDDEN` is shown
 * as the forbidden banner (`Feedback.MfgError`). Only when no workspace is stored and `/me` answers 404 (an
 * M1-only server) is the caller treated as the owner of their own workspace (the M1 behaviour); any other `/me`
 * failure offers no permissions and shows an error with a retry.
 */
import { createContext, createElement, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "../../api/client";
import { getMe, listWorkspaces } from "../api/clientM2";
import type { MeResponse, Permission, Role, WorkspaceInfo } from "../api/typesM2";
import { clearWorkspace, currentWorkspace } from "./workspace";
import { intlLocale, t } from "../../lib/i18n";

export const ALL_PERMISSIONS: readonly Permission[] = [
  "view",
  "master_edit",
  "supplier_edit",
  "inventory",
  "pr_edit",
  "pr_approve",
  "po_edit",
  "demand_edit",
  "wo_edit",
  "mrp_run",
  "import",
  "schedule_run",
  "schedule_publish",
  "floor_view",
  "floor_report",
  "floor_supervise",
  "downtime_report",
  "replan_manage",
  "trace_view",
  "eco_edit",
  "eco_approve",
  "transfer_edit",
  "integration_admin",
  "assistant_use",
  "qa_inspect",
  "qa_decide",
  "qa_plan_edit",
  "ncr_edit",
  "ncr_approve",
  "capa_edit",
  "complaint_edit",
  "field_action_edit",
  "capa_approve",
  "equipment_edit",
  "audit_view",
  "esig_policy_edit",
  "forecast_edit",
  "forecast_approve",
  "inventory_policy_edit",
  "inventory_policy_approve",
  "rate_plan",
  "ster_plan",
  "ster_release",
  "kanban_edit",
  "kanban_scan",
  "validation_view",
  "network_plan",
  "network_edit",
  "network_publish",
  "sop_edit",
  "sop_publish",
  "trade_admin",
  "dhr_review",
  "deviation_edit",
  "coa_edit",
  "udi_edit",
  "udi_export",
  "label_admin",
  "label_print",
  "validation_admin",
  "owner",
];

export const ROLE_LABEL: Record<Role | "owner", string> = {
  owner: t("mfg.permissions.str.owner"),
  viewer: t("mfg.permissions.str.viewer"),
  planner: t("mfg.permissions.str.planner"),
  purchaser: t("mfg.permissions.str.purchaser"),
  store_keeper: t("mfg.permissions.str.storeKeeper"),
  approver: t("mfg.permissions.str.approver"),
  operator: t("mfg.permissions.str.operator"),
  supervisor: t("mfg.permissions.str.supervisor"),
  plant_admin: t("mfg.permissions.str.plantAdmin"),
  qa_inspector: t("qa.roles.str.qaInspector"),
  qa_engineer: t("qa.roles.str.qaEngineer"),
  qa_approver: t("qa.roles.str.qaApprover"),
  metrology: t("qa.roles.str.metrology"),
  plant_manager: t("plan.roles.plantManager"),
  auditor: t("plan.roles.auditor"),
  executive: t("net.roles.executive"),
  regulatory: t("gxp.roles.regulatory"),
  labeling: t("gxp.roles.labeling"),
};

export const ROLE_HELP: Record<Role, string> = {
  viewer: t("mfg.permissions.str.seesEverythingChangesNothing"),
  planner: t("mfg.permissions.str.masterDataDemandWorkOrders"),
  purchaser: t("mfg.permissions.str.suppliersPurchaseRequestsAndPurchase"),
  store_keeper: t("mfg.permissions.str.stockPostingsReceiptsIssuesTransfers"),
  approver: t("mfg.permissions.str.approvesOrRejectsPurchaseRequests"),
  operator: t("mfg.permissions.str.shopFloorStartsReportsAnd"),
  supervisor: t("mfg.permissions.str.shopFloorLeadEverythingAn"),
  plant_admin: t("mfg.permissions.str.everythingInThisPlantLike"),
  qa_inspector: t("qa.roles.str.qaInspectorHelp"),
  qa_engineer: t("qa.roles.str.qaEngineerHelp"),
  qa_approver: t("qa.roles.str.qaApproverHelp"),
  metrology: t("qa.roles.str.metrologyHelp"),
  plant_manager: t("plan.roles.plantManagerHelp"),
  auditor: t("plan.roles.auditorHelp"),
  executive: t("net.roles.executiveHelp"),
  regulatory: t("gxp.roles.regulatoryHelp"),
  labeling: t("gxp.roles.labelingHelp"),
};

/** 10.2 matrix: which member roles hold a permission (the owner holds all). */
export const PERMISSION_ROLES: Record<Permission, Role[]> = {
  view: ["viewer", "planner", "purchaser", "store_keeper", "approver", "operator", "supervisor", "qa_inspector", "qa_engineer", "qa_approver", "metrology", "executive", "regulatory", "labeling"],
  master_edit: ["planner"],
  supplier_edit: ["planner", "purchaser"],
  inventory: ["store_keeper"],
  pr_edit: ["planner", "purchaser"],
  pr_approve: ["approver"],
  po_edit: ["purchaser"],
  demand_edit: ["planner"],
  wo_edit: ["planner"],
  mrp_run: ["planner"],
  import: ["planner"],
  schedule_run: ["planner"],
  schedule_publish: ["planner"],
  floor_view: ["viewer", "planner", "purchaser", "store_keeper", "approver", "operator", "supervisor"],
  floor_report: ["operator", "supervisor", "planner"],
  floor_supervise: ["supervisor"],
  downtime_report: ["operator", "supervisor", "planner"],
  replan_manage: ["planner"],
  trace_view: ["viewer", "planner", "purchaser", "store_keeper", "approver", "operator", "supervisor", "plant_admin"],
  eco_edit: ["planner", "plant_admin"],
  eco_approve: ["approver", "plant_admin"],
  transfer_edit: ["planner", "store_keeper", "plant_admin"],
  integration_admin: ["plant_admin"],
  assistant_use: ["plant_admin", "planner", "purchaser", "store_keeper", "approver", "supervisor", "viewer", "qa_inspector", "qa_engineer", "qa_approver", "metrology"],
  qa_inspect: ["qa_inspector", "qa_engineer", "qa_approver", "operator", "supervisor"],
  qa_decide: ["qa_inspector", "qa_engineer", "qa_approver"],
  qa_plan_edit: ["qa_engineer", "qa_approver"],
  ncr_edit: ["qa_inspector", "qa_engineer", "qa_approver", "supervisor"],
  ncr_approve: ["qa_engineer", "qa_approver"],
  capa_edit: ["qa_engineer", "qa_approver"],
  complaint_edit: ["qa_engineer", "qa_approver"],
  field_action_edit: ["qa_engineer", "qa_approver"],
  capa_approve: ["qa_approver"],
  equipment_edit: ["metrology", "qa_engineer"],
  audit_view: ["qa_engineer", "qa_approver"],
  esig_policy_edit: ["qa_approver"],
  // M8 11 (S0: plant_manager = planner + approvals; auditor = read + validation)
  forecast_edit: ["planner", "plant_manager"],
  forecast_approve: ["plant_manager"],
  inventory_policy_edit: ["planner", "plant_manager"],
  inventory_policy_approve: ["plant_manager"],
  rate_plan: ["planner", "plant_manager"],
  ster_plan: ["planner", "plant_manager"],
  ster_release: ["qa_approver"],
  kanban_edit: ["planner", "plant_manager"],
  kanban_scan: ["operator"],
  validation_view: ["qa_approver", "auditor", "plant_admin"],
  // M9 9 (network workspace): planner plans, plant_manager edits and publishes, executive signs the S&OP approval
  network_plan: ["planner", "plant_manager"],
  network_edit: ["plant_manager"],
  network_publish: ["plant_manager"],
  sop_edit: ["planner", "plant_manager"],
  sop_publish: ["plant_manager"],
  trade_admin: ["plant_manager"],
  // M10 10: eDHR review, deviations, CoA, UDI (new role regulatory), labels (new role labeling), validation
  dhr_review: ["qa_engineer", "qa_approver"],
  deviation_edit: ["qa_engineer", "qa_approver", "supervisor"],
  coa_edit: ["qa_engineer", "qa_approver"],
  udi_edit: ["regulatory", "qa_approver"],
  udi_export: ["regulatory", "qa_approver"],
  label_admin: ["labeling", "qa_engineer"],
  label_print: ["labeling", "supervisor", "operator"],
  validation_admin: ["qa_approver", "plant_admin"],
  owner: [],
};

export function rolesText(roles: Role[]): string {
  return roles.length ? new Intl.ListFormat(intlLocale(), { type: "disjunction" }).format(roles.map((r) => ROLE_LABEL[r])) : t("mfg.permissions.str.owner");
}

/** Tooltip for a hidden/disabled action. */
export function needsText(p: Permission): string {
  return t("mfg.permissions.tpl.yourRoleInThisWorkspace", { rolesText: rolesText(PERMISSION_ROLES[p]) });
}

export interface Access {
  me: MeResponse | null;
  workspaces: WorkspaceInfo[];
  loading: boolean;
  /** True when `/me` is not available and the UI assumes the own workspace (owner). */
  assumed: boolean;
  /** `/me` failed (network, 5xx, ...): no permissions are offered until `retry()` succeeds. */
  error: unknown;
  retry(): void;
  can(p: Permission): boolean;
  isOwner: boolean;
  /** M9 4: the current workspace is the organisation's network workspace (plant-only menus hidden). */
  isNetwork: boolean;
}

const OWNER_FALLBACK: MeResponse = {
  user_id: "",
  workspace_owner_id: "",
  workspace_name: "",
  is_owner: true,
  roles: [],
  permissions: [...ALL_PERMISSIONS],
};

const AccessContext = createContext<Access | null>(null);

export function AccessProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [assumed, setAssumed] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctl = new AbortController();
    setLoading(true);
    setError(null);
    getMe(ctl.signal)
      .then((m) => {
        setMe(m);
        setAssumed(false);
      })
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        const notFound = e instanceof ApiError && e.status === 404;
        if (notFound && currentWorkspace()) {
          // the stored workspace is gone (membership removed): back to the own one
          clearWorkspace();
          window.location.assign("/mfg");
          return;
        }
        if (notFound) {
          // `/me` does not exist on this server (M1-only deployment): the own workspace, as in M1
          setMe(OWNER_FALLBACK);
          setAssumed(true);
          return;
        }
        // any other failure: no edit permissions, an error with a retry (never assume the owner)
        setMe(null);
        setAssumed(false);
        setError(e);
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    listWorkspaces(ctl.signal)
      .then((w) => setWorkspaces(w.items))
      .catch(() => undefined);
    return () => ctl.abort();
  }, [attempt]);

  const value = useMemo<Access>(() => {
    const perms = new Set<Permission>(me?.permissions ?? []);
    return {
      me,
      workspaces,
      loading,
      assumed,
      error,
      retry: () => setAttempt((n) => n + 1),
      // while loading or after an error, nothing is offered (avoids flashing buttons a viewer cannot use)
      can: (p) => perms.has(p),
      isOwner: Boolean(me?.is_owner),
      isNetwork: me?.workspace_kind === "network" || workspaces.some((w) => isNetworkWs(w) && w.owner_id === (currentWorkspace() ?? me?.workspace_owner_id)),
    };
  }, [me, workspaces, loading, assumed, error]);

  return createElement(AccessContext.Provider, { value }, children);
}

/** Outside an `AccessProvider` (tests, M1 pages rendered alone) everything is allowed. */
export function useAccess(): Access {
  const ctx = useContext(AccessContext);
  if (ctx) return ctx;
  return {
    me: OWNER_FALLBACK,
    workspaces: [],
    loading: false,
    assumed: true,
    error: null,
    retry: () => undefined,
    can: () => true,
    isOwner: true,
    isNetwork: false,
  };
}

/** M9 4: the network workspace (`/workspaces[].plant_kind`). */
export function isNetworkWs(w: WorkspaceInfo): boolean {
  return w.plant_kind === "network";
}

export function useCan(p: Permission): boolean {
  return useAccess().can(p);
}

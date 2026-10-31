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
  "owner",
];

export const ROLE_LABEL: Record<Role | "owner", string> = {
  owner: "Owner",
  viewer: "Viewer",
  planner: "Planner",
  purchaser: "Purchaser",
  store_keeper: "Store keeper",
  approver: "Approver",
  operator: "Operator",
  supervisor: "Supervisor",
};

export const ROLE_HELP: Record<Role, string> = {
  viewer: "Sees everything, changes nothing.",
  planner: "Master data, demand, work orders, MRP and schedule runs, publishing the schedule, purchase requests, imports.",
  purchaser: "Suppliers, purchase requests and purchase orders (incl. converting approved requests).",
  store_keeper: "Stock postings: receipts, issues, transfers, counts, reversals, lots.",
  approver: "Approves or rejects purchase requests.",
  operator: "Shop floor: starts, reports and completes operations, reports downtime. Sees the floor pages and reads the rest. Use it for shared station accounts too.",
  supervisor: "Shop floor lead: everything an operator does plus corrections, reopen and skip of operations.",
};

/** 10.2 matrix: which member roles hold a permission (the owner holds all). */
export const PERMISSION_ROLES: Record<Permission, Role[]> = {
  view: ["viewer", "planner", "purchaser", "store_keeper", "approver", "operator", "supervisor"],
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
  owner: [],
};

export function rolesText(roles: Role[]): string {
  return roles.length ? roles.map((r) => ROLE_LABEL[r]).join(" or ") : "Owner";
}

/** Tooltip for a hidden/disabled action. */
export function needsText(p: Permission): string {
  return `Your role in this workspace does not allow this (needs: ${rolesText(PERMISSION_ROLES[p])}).`;
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
  };
}

export function useCan(p: Permission): boolean {
  return useAccess().can(p);
}

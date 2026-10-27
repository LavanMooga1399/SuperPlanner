/**
 * Role-based UI gating (M2 10.2, 14.1). `GET /me` is loaded once per Manufacturing area mount and shared via
 * context; components ask `can("inventory")`. The server stays the authority: a 403 `MFG_FORBIDDEN` is shown
 * as the forbidden banner (`Feedback.MfgError`). Until `/me` exists on the server (or in M1-only deployments)
 * the caller is treated as the owner of their own workspace, which is exactly the M1 behaviour.
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
  "owner",
];

export const ROLE_LABEL: Record<Role | "owner", string> = {
  owner: "Owner",
  viewer: "Viewer",
  planner: "Planner",
  purchaser: "Purchaser",
  store_keeper: "Store keeper",
  approver: "Approver",
};

export const ROLE_HELP: Record<Role, string> = {
  viewer: "Sees everything, changes nothing.",
  planner: "Master data, demand, work orders, MRP runs, purchase requests, imports.",
  purchaser: "Suppliers, purchase requests and purchase orders (incl. converting approved requests).",
  store_keeper: "Stock postings: receipts, issues, transfers, counts, reversals, lots.",
  approver: "Approves or rejects purchase requests.",
};

/** 10.2 matrix: which member roles hold a permission (the owner holds all). */
export const PERMISSION_ROLES: Record<Permission, Role[]> = {
  view: ["viewer", "planner", "purchaser", "store_keeper", "approver"],
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
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctl = new AbortController();
    getMe(ctl.signal)
      .then((m) => {
        setMe(m);
        setAssumed(false);
      })
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        if (e instanceof ApiError && e.status === 404 && currentWorkspace()) {
          // the stored workspace is gone (membership removed): back to the own one
          clearWorkspace();
          window.location.assign("/mfg");
          return;
        }
        setMe(OWNER_FALLBACK);
        setAssumed(true);
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    listWorkspaces(ctl.signal)
      .then((w) => setWorkspaces(w.items))
      .catch(() => undefined);
    return () => ctl.abort();
  }, []);

  const value = useMemo<Access>(() => {
    const perms = new Set<Permission>(me?.permissions ?? []);
    return {
      me,
      workspaces,
      loading,
      assumed,
      // while loading, nothing is offered (avoids flashing buttons a viewer cannot use)
      can: (p) => perms.has(p),
      isOwner: Boolean(me?.is_owner),
    };
  }, [me, workspaces, loading, assumed]);

  return createElement(AccessContext.Provider, { value }, children);
}

/** Outside an `AccessProvider` (tests, M1 pages rendered alone) everything is allowed. */
export function useAccess(): Access {
  const ctx = useContext(AccessContext);
  if (ctx) return ctx;
  return { me: OWNER_FALLBACK, workspaces: [], loading: false, assumed: true, can: () => true, isOwner: true };
}

export function useCan(p: Permission): boolean {
  return useAccess().can(p);
}

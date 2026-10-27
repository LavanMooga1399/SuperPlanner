/**
 * `PermissionGate` (M2 14.1): renders its children only when the user's role in the current workspace holds
 * `perm`. `mode="disable"` keeps the control visible but disabled with an explanation (used where hiding would
 * confuse, e.g. a primary action on a document). The server still enforces every permission.
 */
import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";
import type { Permission } from "../api/typesM2";
import { needsText, useAccess } from "../lib/permissions";

export function PermissionGate({
  perm,
  children,
  mode = "hide",
  fallback = null,
}: {
  perm: Permission;
  children: ReactNode;
  mode?: "hide" | "disable";
  fallback?: ReactNode;
}) {
  const { can } = useAccess();
  if (can(perm)) return <>{children}</>;
  if (mode === "disable" && isValidElement(children)) {
    const el = children as ReactElement<{ disabled?: boolean; title?: string; "aria-disabled"?: boolean }>;
    return cloneElement(el, { disabled: true, "aria-disabled": true, title: needsText(perm) });
  }
  return <>{fallback}</>;
}

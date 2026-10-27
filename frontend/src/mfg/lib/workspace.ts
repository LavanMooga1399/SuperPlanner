/**
 * Workspace selection (M2 14.1, 10.1): the chosen plant workspace (owner user id) lives in `sessionStorage`
 * and is sent as `X-SP-Workspace` by every `/mfg` call (`mfgRaw`, uploads, downloads). Absent = own workspace.
 * Switching reloads the Manufacturing area so no data of the previous workspace stays on screen.
 */
const KEY = "sp.mfg.workspace";
export const WORKSPACE_HEADER = "X-SP-Workspace";

export function currentWorkspace(): string | null {
  try {
    return sessionStorage.getItem(KEY) || null;
  } catch {
    return null;
  }
}

export function workspaceHeaders(): Record<string, string> {
  const ws = currentWorkspace();
  return ws ? { [WORKSPACE_HEADER]: ws } : {};
}

/** `ownerId` null (or the caller's own id) = own workspace. Reloads the Manufacturing overview. */
export function switchWorkspace(ownerId: string | null, ownId?: string | null): void {
  try {
    if (!ownerId || ownerId === ownId) sessionStorage.removeItem(KEY);
    else sessionStorage.setItem(KEY, ownerId);
  } catch {
    /* storage disabled: stays in the own workspace */
  }
  window.location.assign("/mfg");
}

/** A stored workspace that the server no longer knows (membership removed): fall back to the own one. */
export function clearWorkspace(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

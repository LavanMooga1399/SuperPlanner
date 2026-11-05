/**
 * Workspace switcher + role badge (M2 14.1). The switcher is shown only when the user belongs to more than one
 * workspace; the choice is kept in `sessionStorage` and sent as `X-SP-Workspace` on every mfg call.
 */
import { Icon } from "../../components/Icon";
import type { WorkspaceInfo } from "../api/typesM2";
import { ROLE_LABEL, useAccess } from "../lib/permissions";
import { currentWorkspace, switchWorkspace } from "../lib/workspace";

export function WorkspaceSwitcher() {
  const { me, workspaces } = useAccess();
  if (workspaces.length <= 1) return null;
  const own = workspaces.find((w) => w.is_owner);
  const selected = currentWorkspace() ?? own?.owner_id ?? "";
  return (
    <label className="row small mfg-workspace">
      <Icon name="factory" size={14} />
      <span className="muted">Plant</span>
      <select
        className="select sm"
        value={selected}
        onChange={(e) => switchWorkspace(e.target.value, own?.owner_id ?? me?.user_id)}
        aria-label="Plant workspace"
        data-testid="workspace-switcher"
      >
        {groupByOrg(workspaces).map(([org, list]) =>
          org ? (
            <optgroup key={org} label={org}>
              {list.map((w) => (
                <option key={w.owner_id} value={w.owner_id}>
                  {wsLabel(w)}
                </option>
              ))}
            </optgroup>
          ) : (
            list.map((w) => (
              <option key={w.owner_id} value={w.owner_id}>
                {wsLabel(w)}
              </option>
            ))
          ),
        )}
      </select>
    </label>
  );
}

/** M5: plants of an organisation are grouped under its name; personal plants first. */
function groupByOrg(ws: WorkspaceInfo[]): [string | null, WorkspaceInfo[]][] {
  const m = new Map<string | null, WorkspaceInfo[]>();
  for (const w of ws) {
    const k = w.org?.name ?? null;
    m.set(k, [...(m.get(k) ?? []), w]);
  }
  return [...m.entries()].sort((a, b) => (a[0] === null ? -1 : b[0] === null ? 1 : a[0].localeCompare(b[0])));
}

function wsLabel(w: WorkspaceInfo): string {
  const name = `${w.plant_code ? `${w.plant_code} · ` : ""}${w.plant_name || "Plant"}`;
  return `${name}${w.is_owner ? " (mine)" : ` (${w.roles.map((r) => ROLE_LABEL[r]).join(", ")})`}`;
}

export function RoleBadge() {
  const { me, assumed } = useAccess();
  if (!me || assumed) return null;
  const roles = me.is_owner ? ["Owner"] : me.roles.map((r) => ROLE_LABEL[r]);
  return (
    <span
      className={`badge ${me.is_owner ? "accent" : "info"}`}
      data-testid="role-badge"
      data-roles={me.is_owner ? "owner" : me.roles.join(",")}
      title={me.is_owner ? "You own this plant workspace" : `Your roles in ${me.workspace_name || "this plant"}`}
    >
      <Icon name={me.is_owner ? "star" : "lock"} />
      {roles.join(", ")}
    </span>
  );
}

/**
 * `/mfg/settings/members` (M2 14.2, 10): the plant owner adds other accounts with roles (planner, purchaser,
 * store keeper, approver, viewer), changes roles, deactivates or removes them. Owner only; in single-user mode
 * the server answers 422 `MBR_UNAVAILABLE` and the page explains it.
 */
import { useState } from "react";
import { ApiError } from "../../api/client";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { createMember, deleteMember, listMembers, updateMember } from "../api/clientM2";
import type { MemberRecord, Role } from "../api/typesM2";
import { EntityFormDialog } from "../components/EntityFormDialog";
import { MfgError, Spinner } from "../components/Feedback";
import { TextField } from "../components/Field";
import { ROLE_OPTIONS } from "../lib/formatM2";
import { ROLE_HELP, ROLE_LABEL, useAccess } from "../lib/permissions";
import { fmtTimestamp } from "../lib/format";
import { useLoad } from "../lib/useMfg";

function RolePicker({ value, onChange }: { value: Role[]; onChange(r: Role[]): void }) {
  return (
    <fieldset className="mfg-fieldset">
      <legend>Roles (one or more)</legend>
      {ROLE_OPTIONS.map((o) => (
        <label key={o.value} className="checkbox" style={{ alignItems: "flex-start" }}>
          <input
            type="checkbox"
            checked={value.includes(o.value)}
            onChange={(e) => onChange(e.target.checked ? [...value, o.value] : value.filter((r) => r !== o.value))}
            data-testid={`member-role-${o.value}`}
          />
          <span>
            <strong>{o.label}</strong>
            <span className="muted small"> · {ROLE_HELP[o.value]}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

function MemberDialog({ member, onClose, onSaved }: { member: MemberRecord | null; onClose(): void; onSaved(): void }) {
  const [email, setEmail] = useState("");
  const [roles, setRoles] = useState<Role[]>(member?.roles ?? ["viewer"]);
  const [active, setActive] = useState(member?.active ?? true);
  return (
    <EntityFormDialog
      title={member ? `Roles of ${member.user.display_name || member.user.email}` : "Add a member"}
      submitLabel={member ? "Save" : "Add member"}
      testId="member-form"
      disabled={!roles.length || (!member && !email.trim())}
      onClose={onClose}
      onSubmit={async () => {
        if (member) await updateMember(member.id, { roles, active }, member.row_version);
        else await createMember({ email: email.trim(), roles, active: true });
        onSaved();
      }}
    >
      {member ? null : (
        <TextField label="Email of an existing account" value={email} onChange={setEmail} maxLength={254} placeholder="name@company.com" hint="The person must already have a SuperPlanner account." testId="member-email" />
      )}
      <RolePicker value={roles} onChange={setRoles} />
      {member ? (
        <label className="checkbox">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active (an inactive member cannot open this plant)
        </label>
      ) : null}
    </EntityFormDialog>
  );
}

export function MembersPage() {
  const { isOwner, assumed, loading } = useAccess();
  const list = useLoad((signal) => (isOwner ? listMembers(signal) : null), [isOwner]);
  const [editing, setEditing] = useState<MemberRecord | "new" | null>(null);
  const [removing, setRemoving] = useState<MemberRecord | null>(null);
  const [error, setError] = useState<unknown>(null);
  if (loading) return <Spinner />;
  if (!isOwner || assumed)
    return (
      <Banner tone="warn" icon="lock" title="Only the owner of this plant manages members" testId="forbidden-banner">
        Members and their roles are set by the account that owns the plant.
      </Banner>
    );
  const unavailable = list.error instanceof ApiError && list.error.code === "MBR_UNAVAILABLE";
  return (
    <div className="col gap-lg" data-testid="members-page">
      <div className="page-header mfg-header">
        <div>
          <h1>Members</h1>
          <p>Let colleagues work in your plant: store keepers post stock, purchasers handle orders, approvers approve requests, planners plan.</p>
        </div>
        {!unavailable ? (
          <button type="button" className="btn primary" onClick={() => setEditing("new")} data-testid="member-add">
            <Icon name="plus" /> Add member
          </button>
        ) : null}
      </div>
      {unavailable ? (
        <Banner tone="info" title="Members need accounts mode">
          This server runs in single-user mode, so there are no other accounts to add.
        </Banner>
      ) : (
        <MfgError error={list.error ?? error} onRetry={list.reload} />
      )}
      {list.loading && !list.data ? <Spinner /> : null}
      {list.data ? (
        <div className="table-wrap card">
          <table className="table" data-testid="members-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Roles</th>
                <th>Status</th>
                <th>Added</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    Only you work in this plant so far.
                  </td>
                </tr>
              ) : null}
              {list.data.items.map((m) => (
                <tr key={m.id} data-testid="member-row" data-email={m.user.email} data-roles={m.roles.join(",")}>
                  <td>{m.user.display_name}</td>
                  <td>{m.user.email}</td>
                  <td>
                    <span className="row wrap" style={{ gap: 4 }}>
                      {m.roles.map((r) => (
                        <span key={r} className="badge info">
                          {ROLE_LABEL[r]}
                        </span>
                      ))}
                    </span>
                  </td>
                  <td>
                    {m.active ? (
                      <span className="badge ok">
                        <Icon name="check" /> Active
                      </span>
                    ) : (
                      <span className="badge info">
                        <Icon name="ban" /> Inactive
                      </span>
                    )}
                  </td>
                  <td className="small">{fmtTimestamp(m.created_at)}</td>
                  <td className="right">
                    <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                      <button type="button" className="btn sm" onClick={() => setEditing(m)} data-testid="member-edit">
                        Edit
                      </button>
                      <button type="button" className="btn sm ghost icon" aria-label={`Remove ${m.user.email}`} onClick={() => setRemoving(m)} data-testid="member-remove">
                        <Icon name="trash" />
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {editing ? (
        <MemberDialog
          member={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            list.reload();
          }}
        />
      ) : null}
      {removing ? (
        <ConfirmDialog
          title={`Remove ${removing.user.email}?`}
          confirmLabel="Remove member"
          danger
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            const m = removing;
            setRemoving(null);
            setError(null);
            deleteMember(m.id, m.row_version).then(list.reload, setError);
          }}
        >
          <p style={{ margin: 0 }}>They can no longer open this plant. Their past postings and approvals stay in the history.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

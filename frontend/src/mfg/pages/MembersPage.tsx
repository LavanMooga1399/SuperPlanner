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
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/VirtualTable";
import { TextField } from "../components/Field";
import { ROLE_OPTIONS } from "../lib/formatM2";
import { ROLE_HELP, ROLE_LABEL, useAccess } from "../lib/permissions";
import { fmtTimestamp } from "../lib/format";
import { useLoad } from "../lib/useMfg";
import { PageHeader } from "../../components/PageHeader";
import { t } from "../../lib/i18n";

function RolePicker({ value, onChange }: { value: Role[]; onChange(r: Role[]): void }) {
  return (
    <fieldset className="mfg-fieldset">
      <legend>{t("mfg.membersPage.head.rolesOneOrMore")}</legend>
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
      title={member ? t("mfg.membersPage.tpl.rolesOf", { v: member.user.display_name || member.user.email }) : t("mfg.membersPage.str.addAMember")}
      submitLabel={member ? t("mfg.membersPage.str.save") : t("mfg.membersPage.str.addMember")}
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
        <TextField label={t("mfg.membersPage.label.emailOfAnExistingAccount")} value={email} onChange={setEmail} maxLength={254} placeholder={t("mfg.membersPage.ph.namecompanycom")} hint={t("mfg.membersPage.hint.thePersonMustAlreadyHave")} testId="member-email" />
      )}
      <RolePicker value={roles} onChange={setRoles} />
      {member ? (
        <label className="checkbox">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />{" "}{t("mfg.membersPage.text.activeAnInactiveMemberCannot")}
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
  const columns: Column<MemberRecord>[] = [
    { key: "name", header: t("mfg.membersPage.str.name"), width: "minmax(160px, 1fr)", sortValue: (m) => m.user.display_name, render: (m) => m.user.display_name },
    { key: "email", header: t("mfg.membersPage.str.email"), width: "minmax(200px, 1.4fr)", sortValue: (m) => m.user.email, render: (m) => m.user.email },
    {
      key: "roles",
      header: t("mfg.membersPage.str.roles"),
      width: "minmax(200px, 1.6fr)",
      exportValue: (m) => m.roles.map((r) => ROLE_LABEL[r]).join("; "),
      render: (m) => (
        <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
          {m.roles.map((r) => (
            <span key={r} className="badge info">
              {ROLE_LABEL[r]}
            </span>
          ))}
        </span>
      ),
    },
    {
      key: "status",
      header: t("mfg.membersPage.str.status"),
      width: "110px",
      sortValue: (m) => (m.active ? 0 : 1),
      exportValue: (m) => (m.active ? t("mfg.membersPage.str.active") : t("mfg.membersPage.str.inactive")),
      render: (m) =>
        m.active ? (
          <span className="badge ok">
            <Icon name="check" /> {t("mfg.membersPage.btn.active")}
          </span>
        ) : (
          <span className="badge info">
            <Icon name="ban" /> {t("mfg.membersPage.btn.inactive")}
          </span>
        ),
    },
    { key: "added", header: t("mfg.membersPage.str.added"), width: "150px", sortValue: (m) => m.created_at, render: (m) => fmtTimestamp(m.created_at) },
    {
      key: "actions",
      header: <span className="sr-only">{t("mfg.membersPage.text.actions")}</span>,
      label: t("mfg.membersPage.str.actions"),
      width: "96px",
      align: "right",
      hideable: false,
      exportValue: () => "",
      render: (m) => (
        <span className="row" style={{ gap: 4, justifyContent: "flex-end", flexWrap: "nowrap" }}>
          <button type="button" className="btn sm" onClick={() => setEditing(m)} data-testid="member-edit">
            {t("mfg.membersPage.btn.edit")}
          </button>
          <button type="button" className="btn sm ghost icon" aria-label={t("mfg.membersPage.tpl.remove", { email: m.user.email })} onClick={() => setRemoving(m)} data-testid="member-remove">
            <Icon name="trash" />
          </button>
        </span>
      ),
    },
  ];
  if (loading) return <Spinner />;
  if (!isOwner || assumed)
  return (
      <Banner tone="warn" icon="lock" title={t("mfg.membersPage.title.onlyTheOwnerOfThis")} testId="forbidden-banner">
        {t("mfg.membersPage.text.membersAndTheirRolesAre")}
      </Banner>
    );
  const unavailable = list.error instanceof ApiError && list.error.code === "MBR_UNAVAILABLE";
  return (
    <div className="col gap-lg" data-testid="members-page">
      <PageHeader
        title={t("mfg.membersPage.title.members")}
        description={t("mfg.membersPage.desc.letColleaguesWorkInYour")}
        actions={
          <>
            {!unavailable ? (
          <button type="button" className="btn primary" onClick={() => setEditing("new")} data-testid="member-add">
            <Icon name="plus" /> {t("mfg.membersPage.btn.addMember")}
          </button>
        ) : null}
          </>
        }
      />
      {unavailable ? (
        <Banner tone="info" title={t("mfg.membersPage.title.membersNeedAccountsMode")}>
          {t("mfg.membersPage.text.thisServerRunsInSingle")}
        </Banner>
      ) : (
        <MfgError error={list.error ?? error} onRetry={list.reload} />
      )}
      {!unavailable ? (
        <DataTable
          rows={list.data?.items ?? []}
          columns={columns}
          rowKey={(m) => m.id}
          label={t("mfg.membersPage.label.plantMembers")}
          testId="members-table"
          loading={list.loading && !list.data}
          exportName="plant-members"
          rowExtras={(m) => ({ testId: "member-row", data: { email: m.user.email, roles: m.roles.join(",") } })}
          empty={t("mfg.membersPage.empty.onlyYouWorkInThis")}
          card={{ title: "name", status: "status", actions: "actions", fields: ["email", "roles"] }}
        />
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
          title={t("mfg.membersPage.tpl.remove2", { email: removing.user.email })}
          confirmLabel={t("mfg.membersPage.btn.removeMember")}
          danger
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            const m = removing;
            setRemoving(null);
            setError(null);
            deleteMember(m.id, m.row_version).then(list.reload, setError);
          }}
        >
          <p style={{ margin: 0 }}>{t("mfg.membersPage.text.theyCanNoLongerOpen")}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

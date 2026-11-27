/**
 * Organisations and plants (M5 3.4). `/orgs` lists the organisations you belong to (and creates one);
 * `/orgs/:org` has Overview (per-plant KPIs, late demand, open replan triggers, integration health), Plants (create,
 * rename, give people roles in a plant, open it), Members (add by email, admin/member, disable), Master data
 * (publish items or all master data from one plant to others) and Settings (name, require two-step verification).
 * Org admins manage; members see the overview of the plants they can view.
 */
import { useEffect, useState } from "react";
import { OrgDashboardTab } from "../mfg/pages/m6/OrgDashboard";
import { Link, NavLink, useNavigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { Banner } from "../components/Banner";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import {
  addOrgMember,
  acceptOrgInvite,
  createOrg,
  createOrgPlant,
  getOrg,
  getOrgOverview,
  grantPlantRoles,
  listOrgMembers,
  listOrgPlants,
  listOrgs,
  publishMaster,
  removeOrgMember,
  updateOrg,
  updateOrgMember,
  updateOrgPlant,
} from "../mfg/api/clientM5";
import type { Role } from "../mfg/api/typesM2";
import type { Org, OrgMember, OrgPlant, OrgRole, PublishJob } from "../mfg/api/typesM5";
import { MfgError, Spinner } from "../mfg/components/Feedback";
import { ROLE_HELP, ROLE_LABEL } from "../mfg/lib/permissions";
import { useLoad } from "../mfg/lib/useMfg";
import { switchWorkspace } from "../mfg/lib/workspace";
import "./orgs.css";
import { formatDateTime } from "../lib/locale";
import { PageHeader } from "../components/PageHeader";
import { t, t as tr } from "../lib/i18n";
import { DataTable } from "../mfg/components/DataTable";
import { toast } from "../components/Toast";
import { reinstateEsig, revokeEsig } from "../mfg/api/clientM7";
import type { EsigStatus } from "../mfg/api/typesM7";
import { createNetwork } from "../mfg/api/clientM9";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
const PLANT_ROLES: (Role | "plant_admin")[] = ["plant_admin", "planner", "purchaser", "store_keeper", "approver", "supervisor", "operator", "viewer", "qa_inspector", "qa_engineer", "qa_approver", "metrology", "plant_manager", "auditor", "executive", "regulatory", "labeling"];

function openPlant(ownerId: string) {
  switchWorkspace(ownerId, null);
}

export function OrgListPage() {
  const navigate = useNavigate();
  const orgs = useLoad((signal) => listOrgs(signal), []);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    document.title = tr("account.orgPages.str.organisationsSuperplanner");
  }, []);
  const autoSlug = (n: string) =>
    n
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 40);
  return (
    <div className="org-page col gap-lg" data-testid="org-list">
      <PageHeader
        title={t("account.orgPages.title.organisations")}
        actions={
          <>
            <button type="button" className="btn primary" onClick={() => setCreating(true)} data-testid="org-new">
            <Icon name="plus" /> {t("account.orgPages.btn.newOrganisation")}
            </button>
          </>
        }
      />
      <p className="muted" style={{ margin: 0 }}>
        {tr("account.orgPages.text.anOrganisationGroupsThePlants")}
      </p>
      <MfgError error={orgs.error} onRetry={orgs.reload} />
      {orgs.loading && !orgs.data ? <Spinner /> : null}
      {orgs.data && !orgs.data.items.length ? <div className="card card-body muted">{tr("account.orgPages.text.youAreNotInAn")}</div> : null}
      {(orgs.data?.items ?? []).filter((o) => o.invited).map((o) => (
        <div key={`inv-${o.id}`} className="card card-body row wrap" style={{ justifyContent: "space-between" }} data-testid="org-invite">
          <span>
            <strong>{o.name}</strong>{" "}{tr("account.orgPages.text.invitedYouUntilYouAccept")}
          </span>
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await acceptOrgInvite(o.id);
                orgs.reload();
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
            data-testid="org-accept"
          >
            {tr("account.orgPages.text.acceptInvitation")}
          </button>
        </div>
      ))}
      {!creating ? <MfgError error={error} /> : null}
      <div className="org-grid">
        {(orgs.data?.items ?? []).filter((o) => !o.invited).map((o) => (
          <Link key={o.id} to={`/orgs/${encodeURIComponent(o.id)}`} className="card card-body org-tile" data-testid="org-row" data-slug={o.slug}>
            <strong>{o.name}</strong>
            <span className="muted small">
              {o.plants ?? "–"} plants · {o.members ?? "–"} people
            </span>
            <span className="row" style={{ gap: 6 }}>
              {o.my_role === "org_admin" ? (
                <span className="badge accent">
                  <Icon name="star" /> {t("account.orgPages.btn.admin")}
                </span>
              ) : (
                <span className="badge info">{tr("account.orgPages.text.member")}</span>
              )}
              {o.require_2fa ? (
                <span className="badge ok">
                  <Icon name="lock" />{" "}{tr("account.orgPages.text.2faRequired")}
                </span>
              ) : null}
            </span>
          </Link>
        ))}
      </div>
      {creating ? (
        <Dialog
          title={t("account.orgPages.title.newOrganisation")}
          onClose={() => setCreating(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setCreating(false)}>
                {t("account.orgPages.btn.cancel")}
              </button>
              <button
                type="button"
                className="btn primary"
                disabled={busy || !name.trim() || !slug.trim()}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    const o = await createOrg({ name: name.trim(), slug: slug.trim() });
                    navigate(`/orgs/${encodeURIComponent(o.id)}/plants`);
                  } catch (e) {
                    setError(e);
                    setBusy(false);
                  }
                }}
                data-testid="org-create"
              >
                {tr("account.orgPages.text.create")}
              </button>
            </>
          }
        >
          <div className="col">
            <div className="field">
              <label htmlFor="org-name">{t("account.orgPages.label.name")}</label>
              <input
                id="org-name"
                className="input"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!slug || slug === autoSlug(name)) setSlug(autoSlug(e.target.value));
                }}
                data-testid="org-name"
              />
            </div>
            <div className="field">
              <label htmlFor="org-slug">{t("account.orgPages.label.shortNameInLinks")}</label>
              <input id="org-slug" className="input mono" value={slug} onChange={(e) => setSlug(autoSlug(e.target.value))} />
            </div>
            {error instanceof ApiError && error.code === "ORG_CREATE_DISABLED" ? (
              <p className="muted" data-testid="org-create-disabled">
                {tr("account.orgPages.text.onThisInstallationOrganisationsAre")}<code>manage.py create-org</code>{tr("account.orgPages.text.askThemToCreateIt")}
              </p>
            ) : (
              <MfgError error={error} />
            )}
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}

type Tab = "overview" | "dashboard" | "plants" | "members" | "publish" | "settings";

export function OrgPage({ tab }: { tab: Tab }) {
  const { org: orgId = "" } = useParams();
  const org = useLoad((signal) => getOrg(orgId, signal), [orgId]);
  const o = org.data;
  useEffect(() => {
    if (o) document.title = `${o.name} - SuperPlanner`;
  }, [o]);
  if (org.loading && !o) return <Spinner />;
  if (!o) return <MfgError error={org.error} onRetry={org.reload} />;
  const admin = o.my_role === "org_admin";
  const tabs: { key: Tab; label: string; admin?: boolean }[] = [
    { key: "overview", label: tr("account.orgPages.str.overview") },
    { key: "dashboard", label: tr("account.orgPages.str.dashboard") },
    { key: "plants", label: tr("account.orgPages.str.plants") },
    { key: "members", label: tr("account.orgPages.str.people"), admin: true },
    { key: "publish", label: tr("account.orgPages.str.masterData"), admin: true },
    { key: "settings", label: tr("account.orgPages.str.settings"), admin: true },
  ];
  return (
    <div className="org-page col gap-lg" data-testid="org-page" data-slug={o.slug}>
      <nav className="breadcrumb" aria-label={t("account.orgPages.aria.breadcrumb")}>
        <Link to="/orgs">{tr("account.orgPages.text.organisations")}</Link> <Icon name="chevron-right" size={12} /> <span>{o.name}</span>
      </nav>
      <PageHeader title={o.name} />
      <nav className="tabs" aria-label={t("account.orgPages.aria.organisationSections")}>
        {tabs
          .filter((t) => admin || !t.admin)
          .map((t) => (
            <NavLink key={t.key} to={`/orgs/${encodeURIComponent(o.id)}${t.key === "overview" ? "" : `/${t.key}`}`} end className={({ isActive }) => `tab${isActive ? " active" : ""}`} data-testid={`org-tab-${t.key}`}>
              {t.label}
            </NavLink>
          ))}
      </nav>
      {tab === "overview" ? <OrgOverviewTab org={o} /> : null}
      {tab === "dashboard" ? <OrgDashboardTab orgId={o.id} /> : null}
      {tab === "plants" ? <PlantsTab org={o} admin={admin} /> : null}
      {tab === "members" && admin ? <MembersTab org={o} /> : null}
      {tab === "publish" && admin ? <PublishTab org={o} /> : null}
      {tab === "settings" && admin ? <SettingsTab org={o} onSaved={org.setData} /> : null}
    </div>
  );
}

function OrgOverviewTab({ org }: { org: Org }) {
  const ov = useLoad((signal) => getOrgOverview(org.id, signal), [org.id]);
  return (
    <section className="card card-table" data-testid="org-overview">
      <MfgError error={ov.error} onRetry={ov.reload} />
      <DataTable
        rows={ov.data?.plants ?? []}
        columns={[
          {
            key: "plant",
            header: t("account.orgPages.head.plant"),
            width: "minmax(180px, 1.4fr)",
            sortValue: (p) => p.plant.code,
            exportValue: (p) => `${p.plant.code} ${p.plant.name ?? ""}`.trim(),
            render: (p) => (
              <span className="mfg-ellipsis">
                <strong>{p.plant.code}</strong> <span className="muted">{p.plant.name ?? ""}</span>
                {!p.visible ? <span className="vt-sub">{t("account.orgPages.text.noRoleInPlant")}</span> : null}
              </span>
            ),
          },
          { key: "otd", header: t("account.orgPages.head.ontimeDelivery"), width: "120px", align: "right", sortValue: (p) => (p.visible ? (p.kpis?.otd ?? null) : null), render: (p) => (p.visible ? pct(p.kpis?.otd) : "") },
          { key: "oee", header: t("account.orgPages.head.oee"), width: "80px", align: "right", sortValue: (p) => (p.visible ? (p.kpis?.oee ?? null) : null), render: (p) => (p.visible ? pct(p.kpis?.oee) : "") },
          { key: "adh", header: t("account.orgPages.head.scheduleAdherence"), width: "140px", align: "right", sortValue: (p) => (p.visible ? (p.kpis?.adherence ?? null) : null), render: (p) => (p.visible ? pct(p.kpis?.adherence) : "") },
          {
            key: "late",
            header: t("account.orgPages.head.lateDemandLines"),
            width: "130px",
            align: "right",
            sortValue: (p) => (p.visible ? (p.late_demand ?? null) : null),
            exportValue: (p) => p.late_demand ?? "",
            render: (p) =>
              !p.visible ? "" : p.late_demand === null || p.late_demand === undefined ? (
                "–"
              ) : p.late_demand ? (
                <span className="badge warn">
                  <Icon name="alert" /> {p.late_demand}
                </span>
              ) : (
                "0"
              ),
          },
          { key: "trig", header: t("account.orgPages.head.changesToReplan"), width: "140px", align: "right", sortValue: (p) => (p.visible ? (p.open_triggers ?? null) : null), render: (p) => (p.visible ? (p.open_triggers ?? "–") : "") },
          {
            key: "erp",
            header: t("account.orgPages.head.erpConnection"),
            width: "minmax(190px, 1.2fr)",
            exportValue: (p) => (!p.integration?.enabled ? "not connected" : p.integration.dead_deliveries ? `${p.integration.dead_deliveries} failed deliveries` : "healthy"),
            render: (p) =>
              !p.visible ? null : (
                <span>
                  {!p.integration?.enabled ? (
                    <span className="faint">{t("account.orgPages.text.notConnected")}</span>
                  ) : p.integration.dead_deliveries ? (
                    <span className="badge danger">
                      <Icon name="alert" /> {t("account.orgPages.text.failedDeliveries", { n: p.integration.dead_deliveries })}
                    </span>
                  ) : (
                    <span className="badge ok">
                      <Icon name="check" /> {t("account.orgPages.btn.healthy")}
                    </span>
                  )}
                  {p.integration?.last_batch_at ? <span className="vt-sub">{t("account.orgPages.text.lastDataIn", { when: formatDateTime(p.integration.last_batch_at) })}</span> : null}
                </span>
              ),
          },
          {
            key: "actions",
            header: <span className="sr-only">{t("account.orgPages.aria.actions")}</span>,
            label: t("account.orgPages.aria.actions"),
            width: "88px",
            align: "right",
            exportValue: () => "",
            render: (p) =>
              p.visible ? (
                <button type="button" className="btn sm" onClick={() => openPlant(p.plant.owner_id)}>
                  {t("account.orgPages.btn.open")}
                </button>
              ) : null,
          },
        ]}
        rowKey={(p) => p.plant.owner_id}
        label={t("account.orgPages.aria.plantsAtAGlance")}
        tableId="org-overview"
        loading={ov.loading && !ov.data}
        exportName="organisation-overview"
        rowExtras={(p) => ({ testId: "org-overview-plant", data: { code: p.plant.code } })}
        empty={t("account.orgPages.empty.noPlants")}
        card={{ title: "plant", status: "erp", actions: "actions", fields: ["otd", "late", "trig"] }}
      />
    </section>
  );
}

function PlantsTab({ org, admin }: { org: Org; admin: boolean }) {
  const plants = useLoad((signal) => listOrgPlants(org.id, signal), [org.id]);
  const members = useLoad((signal) => (admin ? listOrgMembers(org.id, signal) : null), [org.id, admin]);
  const [edit, setEdit] = useState<OrgPlant | "new" | null>(null);
  const [roles, setRoles] = useState<OrgPlant | null>(null);
  const [netErr, setNetErr] = useState<unknown>(null);
  const hasNetwork = (plants.data?.items ?? []).some((p) => p.kind === "network");
  return (
    <section className="card card-table" data-testid="org-plants">
      <div className="card-header row" style={{ justifyContent: "space-between" }}>
        <h2>{t("account.orgPages.head.plants")}</h2>
        {admin ? (
          <span className="row" style={{ gap: 6 }}>
            {!hasNetwork && plants.data ? (
              <button
                type="button"
                className="btn sm"
                title={t("net.org.networkHint")}
                onClick={() => {
                  setNetErr(null);
                  createNetwork(org.id)
                    .then(() => {
                      toast(t("net.org.networkCreated"));
                      plants.reload();
                    })
                    .catch((e: unknown) => setNetErr(e));
                }}
                data-testid="network-new"
              >
                <Icon name="link" /> {t("net.org.networkBtn")}
              </button>
            ) : null}
            <button type="button" className="btn sm primary" onClick={() => setEdit("new")} data-testid="plant-new">
              <Icon name="plus" /> {t("account.orgPages.btn.newPlant")}
            </button>
          </span>
        ) : null}
      </div>
      <MfgError error={netErr} />
      <MfgError error={plants.error} onRetry={plants.reload} />
      <DataTable
        rows={plants.data?.items ?? []}
        columns={[
          { key: "code", header: t("account.orgPages.head.code"), width: "110px", sortValue: (p) => p.code, render: (p) => <strong className="mono">{p.code}</strong> },
          { key: "name", header: t("account.orgPages.label.name"), width: "minmax(180px, 1.4fr)", sortValue: (p) => p.name, render: (p) => p.name },
          {
            key: "roles",
            header: t("account.orgPages.head.yourRoles"),
            width: "minmax(180px, 1.4fr)",
            render: (p) => (p.my_roles?.length ? p.my_roles.map((r) => ROLE_LABEL[r as Role] ?? r).join(", ") : <span className="faint">{t("account.orgPages.text.none")}</span>),
          },
          {
            key: "actions",
            header: <span className="sr-only">{t("account.orgPages.aria.actions")}</span>,
            label: t("account.orgPages.aria.actions"),
            width: admin ? "300px" : "88px",
            align: "right",
            exportValue: () => "",
            render: (p) => (
              <span className="row" style={{ justifyContent: "flex-end", gap: 4, flexWrap: "nowrap" }}>
                <button type="button" className="btn sm" onClick={() => openPlant(p.plant_owner_id)} data-testid="plant-open">
                  {t("account.orgPages.btn.open")}
                </button>
                {admin ? (
                  <>
                    <button type="button" className="btn sm ghost" onClick={() => setRoles(p)} data-testid="plant-roles">
                      {t("account.orgPages.btn.peopleAndRoles")}
                    </button>
                    <button type="button" className="btn sm ghost" onClick={() => setEdit(p)}>
                      {t("account.orgPages.btn.rename")}
                    </button>
                  </>
                ) : null}
              </span>
            ),
          },
        ]}
        rowKey={(p) => p.id}
        label={t("account.orgPages.head.plants")}
        tableId="org-plants"
        loading={plants.loading && !plants.data}
        exportName="organisation-plants"
        rowExtras={(p) => ({ testId: "plant-row", data: { code: p.code } })}
        empty={t("account.orgPages.empty.noPlants")}
        card={{ title: "code", actions: "actions", fields: ["name", "roles"] }}
      />
      {edit ? <PlantDialog org={org} plant={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); plants.reload(); }} /> : null}
      {roles ? <RolesDialog org={org} plant={roles} members={members.data?.items ?? []} onClose={() => { setRoles(null); members.reload(); }} /> : null}
    </section>
  );
}

function PlantDialog({ org, plant, onClose, onSaved }: { org: Org; plant: OrgPlant | null; onClose(): void; onSaved(): void }) {
  const [code, setCode] = useState(plant?.code ?? "");
  const [name, setName] = useState(plant?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Dialog
      title={plant ? tr("account.orgPages.tpl.plant", { code: plant.code }) : tr("account.orgPages.str.newPlant")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t("account.orgPages.btn.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !code.trim() || !name.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                if (plant) await updateOrgPlant(org.id, plant.id, { name: name.trim() });
                else await createOrgPlant(org.id, { code: code.trim(), name: name.trim() });
                onSaved();
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
            data-testid="plant-save"
          >
            {plant ? tr("account.orgPages.str.save") : tr("account.orgPages.str.createPlant")}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="pl-code">{t("account.orgPages.label.code")}</label>
          <input id="pl-code" className="input mono" value={code} disabled={Boolean(plant)} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={16} placeholder={t("account.orgPages.ph.egBlr")} data-testid="plant-code" />
        </div>
        <div className="field">
          <label htmlFor="pl-name">{t("account.orgPages.label.name")}</label>
          <input id="pl-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} data-testid="plant-name" />
        </div>
        {!plant ? <span className="faint small">{tr("account.orgPages.text.theNewPlantStartsEmpty")}</span> : null}
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

function RolesDialog({ org, plant, members, onClose }: { org: Org; plant: OrgPlant; members: OrgMember[]; onClose(): void }) {
  const [userId, setUserId] = useState("");
  const current = members.find((m) => m.user.id === userId)?.plants?.find((p) => p.plant_owner_id === plant.plant_owner_id)?.roles ?? [];
  const [sel, setSel] = useState<Set<Role | "plant_admin">>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  useEffect(() => setSel(new Set(current)), [userId]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Dialog
      title={tr("account.orgPages.tpl.peopleIn", { code: plant.code })}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t("account.orgPages.btn.close")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !userId}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await grantPlantRoles(org.id, plant.id, { user_id: userId, roles: [...sel] });
                setDone(sel.size ? "Roles saved." : "Removed from the plant.");
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
            data-testid="roles-save"
          >
            {tr("account.orgPages.text.saveRoles")}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="rl-user">{t("account.orgPages.label.person")}</label>
          <select id="rl-user" className="select" value={userId} onChange={(e) => { setUserId(e.target.value); setDone(null); }} data-testid="roles-user">
            <option value="">{tr("account.orgPages.text.chooseAMemberOfThe")}</option>
            {members.map((m) => (
              <option key={m.id} value={m.user.id}>
                {m.user.display_name || m.user.email}
                {m.user.display_name && m.user.email ? ` (${m.user.email})` : ""}
              </option>
            ))}
          </select>
        </div>
        {userId ? (
          <div className="col" style={{ gap: 4 }} role="group" aria-label={t("account.orgPages.aria.roles")}>
            {PLANT_ROLES.map((r) => (
              <label key={r} className="checkbox">
                <input
                  type="checkbox"
                  checked={sel.has(r)}
                  onChange={() =>
                    setSel((s) => {
                      const n = new Set(s);
                      if (n.has(r)) n.delete(r);
                      else n.add(r);
                      return n;
                    })
                  }
                  data-testid={`role-${r}`}
                />
                <span>
                  <strong>{ROLE_LABEL[r as Role] ?? r}</strong> <span className="muted small">{ROLE_HELP[r as Role] ?? ""}</span>
                </span>
              </label>
            ))}
            <span className="faint small">{tr("account.orgPages.text.noRoleNoAccessTo")}</span>
          </div>
        ) : null}
        {done ? (
          <span className="badge ok">
            <Icon name="check" /> {done}
          </span>
        ) : null}
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

function MembersTab({ org }: { org: Org }) {
  const members = useLoad((signal) => listOrgMembers(org.id, signal), [org.id]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>("org_member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [removing, setRemoving] = useState<OrgMember | null>(null);
  const [signing, setSigning] = useState<OrgMember | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      members.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card" data-testid="org-members">
      <div className="card-header">
        <h2>{t("account.orgPages.head.people")}</h2>
      </div>
      <div className="card-body col">
        <form
          className="row wrap"
          style={{ alignItems: "flex-end" }}
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              await addOrgMember(org.id, { email: email.trim(), org_role: role });
              setEmail("");
            });
          }}
        >
          <div className="field" style={{ flex: "1 1 260px" }}>
            <label htmlFor="mb-email">{t("account.orgPages.label.addAPersonByEmail")}</label>
            <input id="mb-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t("account.orgPages.ph.namecompanycom")} data-testid="member-email" />
          </div>
          <div className="field">
            <label htmlFor="mb-role">{t("account.orgPages.label.as")}</label>
            <select id="mb-role" className="select" value={role} onChange={(e) => setRole(e.target.value as OrgRole)}>
              <option value="org_member">{tr("account.orgPages.text.member")}</option>
              <option value="org_admin">{tr("account.orgPages.text.adminManagesPlantsAndPeople")}</option>
            </select>
          </div>
          <button type="submit" className="btn primary" disabled={busy || !email.includes("@")} data-testid="member-add">
            <Icon name="plus" /> {t("account.orgPages.btn.add")}
          </button>
        </form>
        <span className="faint small">{tr("account.orgPages.text.peopleWithACompanyAccount")}</span>
        <MfgError error={error ?? members.error} onRetry={members.reload} />
      </div>
      <DataTable
        rows={members.data?.items ?? []}
        columns={[
          {
            key: "person",
            header: t("account.orgPages.head.person"),
            width: "minmax(200px, 1.4fr)",
            sortValue: (m) => m.user.display_name || m.user.email || "",
            exportValue: (m) => `${m.user.display_name ?? ""} <${m.user.email ?? ""}>`,
            render: (m) => (
              <span>
                <strong>{m.user.display_name || m.user.email}</strong>
                <span className="vt-sub">{m.user.email}</span>
              </span>
            ),
          },
          {
            key: "plants",
            header: t("account.orgPages.head.plantAccess"),
            width: "minmax(220px, 2fr)",
            wrap: true,
            exportValue: (m) => (m.plants ?? []).map((p) => `${p.code}: ${p.roles.join("/")}`).join("; "),
            render: (m) => (
              <span className="small">
                {m.user.disabled ? (
                  <span className="badge warn">
                    <Icon name="ban" /> {t("account.orgPages.btn.disabled")}
                  </span>
                ) : null}{" "}
                {m.plants?.length ? m.plants.map((p) => `${p.code}: ${p.roles.map((r) => ROLE_LABEL[r as Role] ?? r).join(", ")}`).join(" · ") : <span className="faint">{t("account.orgPages.text.none")}</span>}
              </span>
            ),
          },
          {
            key: "role",
            header: t("account.orgPages.head.orgRole"),
            width: "160px",
            sortValue: (m) => m.org_role,
            exportValue: (m) => m.org_role,
            render: (m) => (
              <select className="select sm" aria-label={t("account.orgPages.aria.roleOf", { email: m.user.email ?? "" })} value={m.org_role} disabled={busy} onChange={(e) => void act(() => updateOrgMember(org.id, m.id, { org_role: e.target.value as OrgRole }))}>
                <option value="org_member">{t("account.orgPages.text.member")}</option>
                <option value="org_admin">{t("account.orgPages.text.admin")}</option>
              </select>
            ),
          },
          {
            key: "actions",
            header: <span className="sr-only">{t("account.orgPages.aria.actions")}</span>,
            label: t("account.orgPages.aria.actions"),
            width: "200px",
            align: "right",
            exportValue: () => "",
            render: (m) => (
              <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                {m.user.id ? (
                  <button type="button" className="btn sm ghost" disabled={busy} onClick={() => setSigning(m)} data-testid="member-signing">
                    {t("account.orgPages.btn.signing")}
                  </button>
                ) : null}
                <button type="button" className="btn sm ghost" disabled={busy} onClick={() => setRemoving(m)}>
                  {t("account.orgPages.btn.remove")}
                </button>
              </span>
            ),
          },
        ]}
        rowKey={(m) => m.id}
        label={t("account.orgPages.aria.people")}
        tableId="org-members"
        loading={members.loading && !members.data}
        exportName="organisation-people"
        rowExtras={(m) => ({ testId: "member-row", data: { email: m.user.email ?? "" }, className: m.user.disabled ? "faint" : undefined })}
        empty={t("account.orgPages.empty.noPeople")}
        card={{ title: "person", status: "role", actions: "actions", fields: ["plants"] }}
      />
      {signing ? <SigningDialog org={org} member={signing} onClose={() => setSigning(null)} /> : null}
      {removing ? (
        <ConfirmDialog
          title={tr("account.orgPages.tpl.remove", { v: removing.user.email ?? "this person" })}
          confirmLabel={t("account.orgPages.btn.remove")}
          danger
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            const m = removing;
            setRemoving(null);
            void act(() => removeOrgMember(org.id, m.id));
          }}
        >
          <p style={{ margin: 0 }}>{tr("account.orgPages.text.theyLoseAccessToEvery", { name: org.name })}</p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}

/** Electronic signing of one member (M7 4.1 P4, review M2): revoke, or reinstate after a revocation. */
function SigningDialog({ org, member, onClose }: { org: Org; member: OrgMember; onClose(): void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [status, setStatus] = useState<EsigStatus | null>(null);
  const who = member.user.display_name || member.user.email || "";
  const run = async (fn: () => Promise<EsigStatus>, done: string) => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await fn());
      toast(done);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("account.orgPages.tpl.signingTitle", { who })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.close")}
          </button>
          <button type="button" className="btn danger" disabled={busy || Boolean(status?.revoked_at)} onClick={() => void run(() => revokeEsig(org.id, member.id), t("account.orgPages.tpl.signingRevoked", { who }))} data-testid="esig-revoke">
            <Icon name="ban" /> {t("account.orgPages.btn.revokeSigning")}
          </button>
          <button type="button" className="btn primary" disabled={busy || (status !== null && !status.revoked_at)} onClick={() => void run(() => reinstateEsig(org.id, member.id), t("account.orgPages.tpl.signingReinstated", { who }))} data-testid="esig-reinstate">
            <Icon name="check" /> {t("account.orgPages.btn.reinstateSigning")}
          </button>
        </>
      }
    >
      <div className="col">
        <p style={{ margin: 0 }}>{t("account.orgPages.text.signingHelp")}</p>
        {status ? (
          <p style={{ margin: 0 }} role="status" data-testid="esig-member-status">
            <span className={`badge ${status.revoked_at ? "warn" : status.enrolled ? "ok" : ""}`}>
              <Icon name={status.revoked_at ? "ban" : status.enrolled ? "check" : "info"} />{" "}
              {status.revoked_at
                ? t("account.orgPages.tpl.signingStateRevoked", { when: formatDateTime(status.revoked_at) })
                : status.enrolled
                  ? t("account.orgPages.text.signingStateEnrolled")
                  : t("account.orgPages.text.signingStateNotEnrolled")}
            </span>
          </p>
        ) : null}
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

function PublishTab({ org }: { org: Org }) {
  const plants = useLoad((signal) => listOrgPlants(org.id, signal), [org.id]);
  const [source, setSource] = useState("");
  const [targets, setTargets] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState<"items" | "master">("items");
  const [prefix, setPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [job, setJob] = useState<PublishJob | null>(null);
  const list = plants.data?.items ?? [];
  const code = (owner: string) => list.find((p) => p.plant_owner_id === owner)?.code ?? owner;
  return (
    <section className="card" data-testid="org-publish">
      <div className="card-header">
        <h2>{t("account.orgPages.head.publishMasterData")}</h2>
      </div>
      <div className="card-body col">
        <p className="muted" style={{ margin: 0 }}>
          {tr("account.orgPages.text.copiesItemsOrAllMaster")}
        </p>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="pb-src">{t("account.orgPages.label.fromPlant")}</label>
            <select id="pb-src" className="select" value={source} onChange={(e) => setSource(e.target.value)} data-testid="publish-source">
              <option value="">{tr("account.orgPages.text.choose")}</option>
              {list.map((p) => (
                <option key={p.id} value={p.plant_owner_id}>
                  {p.code} · {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="pb-scope">{t("account.orgPages.label.what")}</label>
            <select id="pb-scope" className="select" value={scope} onChange={(e) => setScope(e.target.value as "items" | "master")}>
              <option value="items">{tr("account.orgPages.text.itemsOnly")}</option>
              <option value="master">{tr("account.orgPages.text.allMasterData")}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="pb-prefix">{t("account.orgPages.label.onlyPartNumbersStartingWith")}</label>
            <input id="pb-prefix" className="input mono" value={prefix} onChange={(e) => setPrefix(e.target.value)} />
          </div>
        </div>
        <fieldset className="mfg-fieldset">
          <legend>{t("account.orgPages.head.toPlants")}</legend>
          {list
            .filter((p) => p.plant_owner_id !== source)
            .map((p) => (
              <label key={p.id} className="checkbox">
                <input
                  type="checkbox"
                  checked={targets.has(p.plant_owner_id)}
                  onChange={() =>
                    setTargets((t) => {
                      const n = new Set(t);
                      if (n.has(p.plant_owner_id)) n.delete(p.plant_owner_id);
                      else n.add(p.plant_owner_id);
                      return n;
                    })
                  }
                  data-testid="publish-target"
                />
                {p.code} · {p.name}
              </label>
            ))}
        </fieldset>
        <MfgError error={error} />
        <div>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !source || ![...targets].some((t) => t !== source)}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                setJob(await publishMaster(org.id, { source_plant: source, target_plants: [...targets].filter((t) => t !== source), scope, part_number_prefix: prefix.trim() || null }));
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
            data-testid="publish-run"
          >
            <Icon name="upload" /> {t("account.orgPages.btn.publish")}
          </button>
        </div>
        {job ? (
          <div data-testid="publish-result" data-status={job.status}>
            {job.status === "queued" || job.status === "running" ? <Banner tone="info" title={t("account.orgPages.title.publishingInTheBackground")}>{tr("account.orgPages.text.eachTargetPlantIsUpdated")}</Banner> : null}
            {job.results && Object.keys(job.results).length ? (
              <DataTable
                rows={Object.entries(job.results).map(([owner, r]) => ({ owner, ...r }))}
                columns={[
                  { key: "plant", header: t("account.orgPages.head.plant"), width: "120px", sortValue: (r) => code(r.owner), render: (r) => <span className="mono">{code(r.owner)}</span> },
                  { key: "status", header: t("account.orgPages.head.result"), width: "120px", sortValue: (r) => r.status, render: (r) => r.status },
                  { key: "counts", header: t("account.orgPages.head.records"), width: "minmax(180px, 1.4fr)", render: (r) => (r.counts ? Object.entries(r.counts).map(([k, v]) => `${v} ${k}`).join(" · ") : "") },
                  { key: "errors", header: t("account.orgPages.head.problems"), width: "minmax(200px, 2fr)", wrap: true, render: (r) => r.errors?.map((e) => e.message).join("; ") ?? "" },
                ]}
                rowKey={(r) => r.owner}
                label={t("account.orgPages.aria.publishResults")}
                tableId="org-publish-results"
                exportName="publish-results"
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function SettingsTab({ org, onSaved }: { org: Org; onSaved(o: Org): void }) {
  const [name, setName] = useState(org.name);
  const [req2fa, setReq2fa] = useState(org.require_2fa);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  return (
    <section className="card" data-testid="org-settings">
      <div className="card-body col">
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="os-name">{t("account.orgPages.label.name")}</label>
          <input id="os-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={req2fa} onChange={(e) => setReq2fa(e.target.checked)} data-testid="org-require-2fa" />
          <span>
            <strong>{tr("account.orgPages.text.requireTwoStepVerification")}</strong> <span className="muted small">{tr("account.orgPages.text.forPeopleWhoSignIn")}</span>
          </span>
        </label>
        <MfgError error={error} />
        <div className="row">
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                onSaved(await updateOrg(org.id, { name: name.trim(), require_2fa: req2fa }, org.row_version));
                setSaved(true);
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
            data-testid="org-settings-save"
          >
            <Icon name="save" /> {t("account.orgPages.btn.save")}
          </button>
          {saved ? (
            <span className="badge ok">
              <Icon name="check" /> {t("account.orgPages.btn.saved")}
            </span>
          ) : null}
        </div>
      </div>
    </section>
  );
}

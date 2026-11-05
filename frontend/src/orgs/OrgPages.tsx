/**
 * Organisations and plants (M5 3.4). `/orgs` lists the organisations you belong to (and creates one);
 * `/orgs/:org` has Overview (per-plant KPIs, late demand, open replan triggers, integration health), Plants (create,
 * rename, give people roles in a plant, open it), Members (add by email, admin/member, disable), Master data
 * (publish items or all master data from one plant to others) and Settings (name, require two-step verification).
 * Org admins manage; members see the overview of the plants they can view.
 */
import { useEffect, useState } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router";
import { Banner } from "../components/Banner";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import {
  addOrgMember,
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

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
const PLANT_ROLES: (Role | "plant_admin")[] = ["plant_admin", "planner", "purchaser", "store_keeper", "approver", "supervisor", "operator", "viewer"];

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
    document.title = "Organisations - SuperPlanner";
  }, []);
  const autoSlug = (n: string) =>
    n
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 40);
  return (
    <div className="org-page col gap-lg" data-testid="org-list">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Organisations</h1>
        <button type="button" className="btn primary" onClick={() => setCreating(true)} data-testid="org-new">
          <Icon name="plus" /> New organisation
        </button>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        An organisation groups the plants of one company: people work in several plants, master data is published between them, and stock moves by transfer orders.
      </p>
      <MfgError error={orgs.error} onRetry={orgs.reload} />
      {orgs.loading && !orgs.data ? <Spinner /> : null}
      {orgs.data && !orgs.data.items.length ? <div className="card card-body muted">You are not in an organisation yet. Your own plant works on its own as before.</div> : null}
      <div className="org-grid">
        {(orgs.data?.items ?? []).map((o) => (
          <Link key={o.id} to={`/orgs/${encodeURIComponent(o.id)}`} className="card card-body org-tile" data-testid="org-row" data-slug={o.slug}>
            <strong>{o.name}</strong>
            <span className="muted small">
              {o.plants ?? "–"} plants · {o.members ?? "–"} people
            </span>
            <span className="row" style={{ gap: 6 }}>
              {o.my_role === "org_admin" ? (
                <span className="badge accent">
                  <Icon name="star" /> Admin
                </span>
              ) : (
                <span className="badge info">Member</span>
              )}
              {o.require_2fa ? (
                <span className="badge ok">
                  <Icon name="lock" /> 2FA required
                </span>
              ) : null}
            </span>
          </Link>
        ))}
      </div>
      {creating ? (
        <Dialog
          title="New organisation"
          onClose={() => setCreating(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setCreating(false)}>
                Cancel
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
                Create
              </button>
            </>
          }
        >
          <div className="col">
            <div className="field">
              <label htmlFor="org-name">Name</label>
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
              <label htmlFor="org-slug">Short name (in links)</label>
              <input id="org-slug" className="input mono" value={slug} onChange={(e) => setSlug(autoSlug(e.target.value))} />
            </div>
            <MfgError error={error} />
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}

type Tab = "overview" | "plants" | "members" | "publish" | "settings";

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
    { key: "overview", label: "Overview" },
    { key: "plants", label: "Plants" },
    { key: "members", label: "People", admin: true },
    { key: "publish", label: "Master data", admin: true },
    { key: "settings", label: "Settings", admin: true },
  ];
  return (
    <div className="org-page col gap-lg" data-testid="org-page" data-slug={o.slug}>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/orgs">Organisations</Link> <Icon name="chevron-right" size={12} /> <span>{o.name}</span>
      </nav>
      <h1 style={{ margin: 0 }}>{o.name}</h1>
      <nav className="tabs" aria-label="Organisation sections">
        {tabs
          .filter((t) => admin || !t.admin)
          .map((t) => (
            <NavLink key={t.key} to={`/orgs/${encodeURIComponent(o.id)}${t.key === "overview" ? "" : `/${t.key}`}`} end className={({ isActive }) => `tab${isActive ? " active" : ""}`} data-testid={`org-tab-${t.key}`}>
              {t.label}
            </NavLink>
          ))}
      </nav>
      {tab === "overview" ? <OrgOverviewTab org={o} /> : null}
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
    <section className="card" data-testid="org-overview">
      <MfgError error={ov.error} onRetry={ov.reload} />
      {ov.loading && !ov.data ? <Spinner /> : null}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Plant</th>
              <th className="right">On-time delivery</th>
              <th className="right">OEE</th>
              <th className="right">Schedule adherence</th>
              <th className="right">Late demand lines</th>
              <th className="right">Changes to replan</th>
              <th>ERP connection</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(ov.data?.plants ?? []).map((p) => (
              <tr key={p.plant.owner_id} data-testid="org-overview-plant" data-code={p.plant.code}>
                <td>
                  <strong>{p.plant.code}</strong> <span className="muted">{p.plant.name ?? ""}</span>
                </td>
                {p.visible ? (
                  <>
                    <td className="right">{pct(p.kpis?.otd)}</td>
                    <td className="right">{pct(p.kpis?.oee)}</td>
                    <td className="right">{pct(p.kpis?.adherence)}</td>
                    <td className="right">
                      {p.late_demand === null || p.late_demand === undefined ? (
                        "–"
                      ) : p.late_demand ? (
                        <span className="badge warn">
                          <Icon name="alert" /> {p.late_demand}
                        </span>
                      ) : (
                        "0"
                      )}
                    </td>
                    <td className="right">{p.open_triggers ?? "–"}</td>
                    <td className="small">
                      {!p.integration?.enabled ? (
                        <span className="faint">not connected</span>
                      ) : p.integration.dead_deliveries ? (
                        <span className="badge danger">
                          <Icon name="alert" /> {p.integration.dead_deliveries} failed deliveries
                        </span>
                      ) : (
                        <span className="badge ok">
                          <Icon name="check" /> healthy
                        </span>
                      )}
                      {p.integration?.last_batch_at ? <div className="faint">last data in {new Date(p.integration.last_batch_at).toLocaleString()}</div> : null}
                    </td>
                    <td>
                      <button type="button" className="btn sm" onClick={() => openPlant(p.plant.owner_id)}>
                        Open
                      </button>
                    </td>
                  </>
                ) : (
                  <td colSpan={7} className="faint">
                    You have no role in this plant.
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PlantsTab({ org, admin }: { org: Org; admin: boolean }) {
  const plants = useLoad((signal) => listOrgPlants(org.id, signal), [org.id]);
  const members = useLoad((signal) => (admin ? listOrgMembers(org.id, signal) : null), [org.id, admin]);
  const [edit, setEdit] = useState<OrgPlant | "new" | null>(null);
  const [roles, setRoles] = useState<OrgPlant | null>(null);
  return (
    <section className="card" data-testid="org-plants">
      <div className="card-header row" style={{ justifyContent: "space-between" }}>
        <h2>Plants</h2>
        {admin ? (
          <button type="button" className="btn sm primary" onClick={() => setEdit("new")} data-testid="plant-new">
            <Icon name="plus" /> New plant
          </button>
        ) : null}
      </div>
      <MfgError error={plants.error} onRetry={plants.reload} />
      <table className="table">
        <tbody>
          {(plants.data?.items ?? []).map((p) => (
            <tr key={p.id} data-testid="plant-row" data-code={p.code}>
              <td>
                <strong className="mono">{p.code}</strong> {p.name}
                {p.my_roles?.length ? <div className="faint small">your roles: {p.my_roles.map((r) => ROLE_LABEL[r as Role] ?? r).join(", ")}</div> : null}
              </td>
              <td className="right">
                <span className="row" style={{ justifyContent: "flex-end" }}>
                  <button type="button" className="btn sm" onClick={() => openPlant(p.plant_owner_id)} data-testid="plant-open">
                    Open
                  </button>
                  {admin ? (
                    <>
                      <button type="button" className="btn sm ghost" onClick={() => setRoles(p)} data-testid="plant-roles">
                        People and roles
                      </button>
                      <button type="button" className="btn sm ghost" onClick={() => setEdit(p)}>
                        Rename
                      </button>
                    </>
                  ) : null}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
      title={plant ? `Plant ${plant.code}` : "New plant"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
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
            {plant ? "Save" : "Create plant"}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="pl-code">Code</label>
          <input id="pl-code" className="input mono" value={code} disabled={Boolean(plant)} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={16} placeholder="e.g. BLR" data-testid="plant-code" />
        </div>
        <div className="field">
          <label htmlFor="pl-name">Name</label>
          <input id="pl-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} data-testid="plant-name" />
        </div>
        {!plant ? <span className="faint small">The new plant starts empty: publish master data to it, or load a sample, then add people.</span> : null}
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
      title={`People in ${plant.code}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Close
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
            Save roles
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="rl-user">Person</label>
          <select id="rl-user" className="select" value={userId} onChange={(e) => { setUserId(e.target.value); setDone(null); }} data-testid="roles-user">
            <option value="">Choose a member of the organisation…</option>
            {members.map((m) => (
              <option key={m.id} value={m.user.id}>
                {m.user.display_name || m.user.email}
                {m.user.display_name && m.user.email ? ` (${m.user.email})` : ""}
              </option>
            ))}
          </select>
        </div>
        {userId ? (
          <div className="col" style={{ gap: 4 }} role="group" aria-label="Roles">
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
            <span className="faint small">No role = no access to this plant.</span>
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
        <h2>People</h2>
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
            <label htmlFor="mb-email">Add a person by email</label>
            <input id="mb-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" data-testid="member-email" />
          </div>
          <div className="field">
            <label htmlFor="mb-role">As</label>
            <select id="mb-role" className="select" value={role} onChange={(e) => setRole(e.target.value as OrgRole)}>
              <option value="org_member">Member</option>
              <option value="org_admin">Admin (manages plants and people)</option>
            </select>
          </div>
          <button type="submit" className="btn primary" disabled={busy || !email.includes("@")} data-testid="member-add">
            <Icon name="plus" /> Add
          </button>
        </form>
        <span className="faint small">People with a company account (single sign-on) can also join on their first sign-in. Plant access is given under Plants.</span>
        <MfgError error={error ?? members.error} onRetry={members.reload} />
      </div>
      <table className="table">
        <tbody>
          {(members.data?.items ?? []).map((m) => {
            const disabled = m.user.disabled ?? false;
            return (
              <tr key={m.id} data-testid="member-row" data-email={m.user.email ?? ""} className={disabled ? "faint" : undefined}>
                <td>
                  <strong>{m.user.display_name || m.user.email}</strong>
                  <div className="small muted">{m.user.email}</div>
                </td>
                <td className="small">
                  {disabled ? (
                    <span className="badge warn">
                      <Icon name="ban" /> disabled
                    </span>
                  ) : null}
                  {m.plants?.length ? <div className="faint">{m.plants.map((p) => `${p.code}: ${p.roles.map((r) => ROLE_LABEL[r as Role] ?? r).join(", ")}`).join(" · ")}</div> : null}
                </td>
                <td>
                  <select className="select sm" aria-label={`Role of ${m.user.email}`} value={m.org_role} disabled={busy} onChange={(e) => void act(() => updateOrgMember(org.id, m.id, { org_role: e.target.value as OrgRole }))}>
                    <option value="org_member">Member</option>
                    <option value="org_admin">Admin</option>
                  </select>
                </td>
                <td className="right">
                  <button type="button" className="btn sm ghost" disabled={busy} onClick={() => setRemoving(m)}>
                    Remove
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {removing ? (
        <ConfirmDialog
          title={`Remove ${removing.user.email ?? "this person"}?`}
          confirmLabel="Remove"
          danger
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            const m = removing;
            setRemoving(null);
            void act(() => removeOrgMember(org.id, m.id));
          }}
        >
          <p style={{ margin: 0 }}>They lose access to every plant of {org.name}. Their past work stays recorded under their name.</p>
        </ConfirmDialog>
      ) : null}
    </section>
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
        <h2>Publish master data</h2>
      </div>
      <div className="card-body col">
        <p className="muted" style={{ margin: 0 }}>
          Copies items (or all master data: items, BOMs, routings, suppliers) from one plant into others through the normal import checks. Running it again changes only what differs. Fields owned by an ERP in a target plant are left alone.
        </p>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="pb-src">From plant</label>
            <select id="pb-src" className="select" value={source} onChange={(e) => setSource(e.target.value)} data-testid="publish-source">
              <option value="">Choose…</option>
              {list.map((p) => (
                <option key={p.id} value={p.plant_owner_id}>
                  {p.code} · {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="pb-scope">What</label>
            <select id="pb-scope" className="select" value={scope} onChange={(e) => setScope(e.target.value as "items" | "master")}>
              <option value="items">Items only</option>
              <option value="master">All master data</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="pb-prefix">Only part numbers starting with (optional)</label>
            <input id="pb-prefix" className="input mono" value={prefix} onChange={(e) => setPrefix(e.target.value)} />
          </div>
        </div>
        <fieldset className="mfg-fieldset">
          <legend>To plants</legend>
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
            <Icon name="upload" /> Publish
          </button>
        </div>
        {job ? (
          <div data-testid="publish-result" data-status={job.status}>
            {job.status === "queued" || job.status === "running" ? <Banner tone="info" title="Publishing in the background">Each target plant is updated in its own step; the results also appear in each plant's Integration, Batches.</Banner> : null}
            {job.results && Object.keys(job.results).length ? (
              <table className="table">
                <tbody>
                  {Object.entries(job.results).map(([owner, r]) => (
                    <tr key={owner}>
                      <td className="mono">{code(owner)}</td>
                      <td>{r.status}</td>
                      <td className="small">{r.counts ? Object.entries(r.counts).map(([k, v]) => `${v} ${k}`).join(" · ") : ""}</td>
                      <td className="small">{r.errors?.map((e) => e.message).join("; ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
          <label htmlFor="os-name">Name</label>
          <input id="os-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={req2fa} onChange={(e) => setReq2fa(e.target.checked)} data-testid="org-require-2fa" />
          <span>
            <strong>Require two-step verification</strong> <span className="muted small">for people who sign in with a password. They set it up at their next sign-in. Company accounts (single sign-on) are not affected.</span>
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
            <Icon name="save" /> Save
          </button>
          {saved ? (
            <span className="badge ok">
              <Icon name="check" /> Saved
            </span>
          ) : null}
        </div>
      </div>
    </section>
  );
}

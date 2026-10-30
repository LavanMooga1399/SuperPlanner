import { useEffect } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { Icon, type IconName } from "../../components/Icon";
import { MfgError } from "../components/Feedback";
import { RoleBadge, WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { mfgPaths } from "../lib/paths";
import { AccessProvider, useAccess } from "../lib/permissions";

interface Section {
  key: string;
  label: string;
  to: string;
  icon: IconName;
  end?: boolean;
}

const SETUP: Section[] = [
  { key: "overview", label: "Overview", to: mfgPaths.home(), icon: "factory", end: true },
  { key: "items", label: "Items", to: mfgPaths.items(), icon: "list" },
  { key: "plant", label: "Plant", to: mfgPaths.plant(), icon: "settings" },
  { key: "resources", label: "People & tooling", to: mfgPaths.resources(), icon: "briefcase" },
  { key: "health", label: "Data health", to: mfgPaths.health(), icon: "check" },
  { key: "import", label: "Import / export", to: mfgPaths.importStart(), icon: "upload" },
];

const PLANNING: Section[] = [
  { key: "demand", label: "Demand", to: mfgPaths.demand(), icon: "flag" },
  { key: "mrp", label: "MRP", to: mfgPaths.mrp(), icon: "graph" },
  { key: "schedule", label: "Schedule", to: mfgPaths.schedule(), icon: "calendar" },
  { key: "shortages", label: "Shortages", to: mfgPaths.shortages(), icon: "alert" },
  { key: "work-orders", label: "Work orders", to: mfgPaths.workOrders(), icon: "play" },
  { key: "purchasing", label: "Purchasing", to: mfgPaths.purchasing(), icon: "briefcase" },
  { key: "inventory", label: "Inventory", to: mfgPaths.inventory(), icon: "layers" },
];

function NavGroup({ label, sections, testId }: { label: string; sections: Section[]; testId: string }) {
  return (
    <div className="mfg-nav-group" role="group" aria-label={label} data-testid={testId}>
      <span className="mfg-nav-group-label" aria-hidden>
        {label}
      </span>
      <div className="tabs mfg-subnav">
        {sections.map((s) => (
          <NavLink
            key={s.key}
            to={s.to}
            end={s.end}
            className={({ isActive }) => `tab${isActive ? " active" : ""}`}
            data-testid={`mfg-subnav-${s.key}`}
          >
            <Icon name={s.icon} size={14} />
            {s.label}
          </NavLink>
        ))}
      </div>
    </div>
  );
}

/** `/me` failed: say so and offer a retry (no edit permissions meanwhile). */
function AccessError() {
  const { error, retry } = useAccess();
  if (!error) return null;
  return (
    <div data-testid="mfg-access-error">
      <MfgError error={error} onRetry={retry} title="Your workspace permissions could not be loaded" />
    </div>
  );
}

function MfgNav() {
  const { isOwner, assumed } = useAccess();
  const setup = isOwner && !assumed ? [...SETUP, { key: "members", label: "Members", to: mfgPaths.members(), icon: "lock" as IconName }] : SETUP;
  return (
    <div className="mfg-nav">
      <nav className="mfg-nav-groups" aria-label="Manufacturing sections">
        <NavGroup label="Setup" sections={setup} testId="nav-group-setup" />
        <NavGroup label="Planning & stores" sections={PLANNING} testId="nav-group-planning" />
      </nav>
      <div className="row mfg-nav-side">
        <WorkspaceSwitcher />
        <RoleBadge />
      </div>
    </div>
  );
}

/** Wraps every /mfg/** route: area title, workspace/role context and the two-group sub-navigation (M2 14.1). */
export function MfgLayout() {
  useEffect(() => {
    document.title = "Manufacturing - SuperPlanner";
    return () => {
      document.title = "SuperPlanner Studio";
    };
  }, []);
  return (
    <AccessProvider>
      <div className="mfg-page">
        <MfgNav />
        <AccessError />
        <Outlet />
      </div>
    </AccessProvider>
  );
}

export function MfgNotFound() {
  return (
    <div className="empty" data-testid="mfg-not-found">
      <Icon name="help" size={32} />
      <h2>Page not found</h2>
      <p>This manufacturing page does not exist.</p>
      <Link className="btn" to={mfgPaths.home()}>
        Back to Manufacturing
      </Link>
    </div>
  );
}

/** Secondary tab strip used by the Plant and People & tooling sections. */
export function SectionTabs({ label, tabs }: { label: string; tabs: { to: string; label: string; testId: string; end?: boolean }[] }) {
  return (
    <nav className="tabs mfg-section-tabs" aria-label={label}>
      {tabs.map((t) => (
        <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => `tab${isActive ? " active" : ""}`} data-testid={t.testId}>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

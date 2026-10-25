import { useEffect } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { Icon, type IconName } from "../../components/Icon";
import { mfgPaths } from "../lib/paths";

const SECTIONS: { key: string; label: string; to: string; icon: IconName; end?: boolean }[] = [
  { key: "overview", label: "Overview", to: mfgPaths.home(), icon: "factory", end: true },
  { key: "items", label: "Items", to: mfgPaths.items(), icon: "list" },
  { key: "plant", label: "Plant", to: mfgPaths.plant(), icon: "settings" },
  { key: "resources", label: "People & tooling", to: mfgPaths.resources(), icon: "briefcase" },
  { key: "health", label: "Data health", to: mfgPaths.health(), icon: "check" },
  { key: "import", label: "Import / export", to: mfgPaths.importStart(), icon: "upload" },
];

/** Wraps every /mfg/** route: area title and the section sub-navigation (M 11.2). */
export function MfgLayout() {
  useEffect(() => {
    document.title = "Manufacturing - SuperPlanner";
    return () => {
      document.title = "SuperPlanner Studio";
    };
  }, []);
  return (
    <div className="mfg-page">
      <nav className="tabs mfg-subnav" aria-label="Manufacturing sections">
        {SECTIONS.map((s) => (
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
      </nav>
      <Outlet />
    </div>
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
export function SectionTabs({ label, tabs }: { label: string; tabs: { to: string; label: string; testId: string }[] }) {
  return (
    <nav className="tabs mfg-section-tabs" aria-label={label}>
      {tabs.map((t) => (
        <NavLink key={t.to} to={t.to} className={({ isActive }) => `tab${isActive ? " active" : ""}`} data-testid={t.testId}>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

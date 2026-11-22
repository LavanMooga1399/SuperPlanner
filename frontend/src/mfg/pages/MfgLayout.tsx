import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { Icon } from "../../components/Icon";
import { HeaderTools } from "../../components/shell/HeaderSlot";
import { MfgError } from "../components/Feedback";
import { NotificationBell } from "../components/NotificationBell";
import { AssistantButton } from "../assistant/AssistantPanel";
import { RoleBadge, WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { mfgPaths } from "../lib/paths";
import { MFG_NAV, sectionFor, type NavGroupDef } from "../lib/nav";
import { AccessProvider, useAccess } from "../lib/permissions";
import { useStoredState } from "../../lib/useAsync";
import { t } from "../../lib/i18n";

function NavGroup({ group, ownerVisible, collapsed }: { group: NavGroupDef; ownerVisible: boolean; collapsed: boolean }) {
  const sections = group.sections.filter((s) => !s.ownerOnly || ownerVisible);
  return (
    <div className="side-group" role="group" aria-labelledby={`side-${group.key}`} data-testid={group.testId}>
      <span className="side-group-label" id={`side-${group.key}`}>
        {group.label}
      </span>
      <ul className="side-list">
        {sections.map((s) => (
          <li key={s.key}>
            <NavLink
              to={s.to}
              end={s.end}
              className={({ isActive }) => `side-link${isActive ? " active" : ""}`}
              data-testid={`mfg-subnav-${s.key}`}
              title={collapsed ? s.label : undefined}
            >
              <Icon name={s.icon} size={16} />
              <span className="side-text">{s.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
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

/** Left navigation (UX-STANDARD 3): role-oriented groups, collapsible to an icon rail, drawer on phones. */
function MfgSidebar({ collapsed, onToggle, open, onClose }: { collapsed: boolean; onToggle(): void; open: boolean; onClose(): void }) {
  const { isOwner, assumed } = useAccess();
  const { pathname } = useLocation();
  useEffect(() => onClose(), [pathname]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      {open ? <div className="side-scrim" onClick={onClose} aria-hidden /> : null}
      <aside className={`side${collapsed ? " collapsed" : ""}${open ? " open" : ""}`} aria-label="Manufacturing">
        <nav className="side-scroll" aria-label="Manufacturing sections">
          {MFG_NAV.map((g) => (
            <NavGroup key={g.key} group={g} ownerVisible={isOwner && !assumed} collapsed={collapsed} />
          ))}
        </nav>
        <button type="button" className="side-toggle" onClick={onToggle} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} aria-expanded={!collapsed} data-testid="side-toggle">
          <Icon name="sidebar" size={16} />
          <span className="side-text">Collapse</span>
        </button>
      </aside>
    </>
  );
}

/** Route-derived breadcrumb for every Manufacturing page; hidden by CSS when the page has its own record trail. */
function MfgBreadcrumbs({ onMenu }: { onMenu(): void }) {
  const { pathname } = useLocation();
  const hit = sectionFor(pathname);
  const atSection = hit && pathname.replace(/\/$/, "") === hit.section.to.split("?")[0];
  return (
    <div className="crumb-bar">
      <button type="button" className="btn ghost sm icon side-menu-btn" onClick={onMenu} aria-label="Open navigation" data-testid="side-open">
        <Icon name="menu" />
      </button>
      <nav aria-label="Breadcrumb" className="crumbs auto-crumbs">
        <ol>
          <li>
            <Link to={mfgPaths.home()}>Manufacturing</Link>
          </li>
          {hit && hit.section.key !== "overview" ? (
            <>
              <li>
                <span className="crumb-group">{hit.group.label}</span>
              </li>
              <li>{atSection ? <span aria-current="page">{hit.section.label}</span> : <Link to={hit.section.to}>{hit.section.label}</Link>}</li>
            </>
          ) : null}
        </ol>
      </nav>
    </div>
  );
}

function MfgTools() {
  return (
    <HeaderTools>
      <WorkspaceSwitcher />
      <RoleBadge />
      <AssistantButton />
      <NotificationBell />
    </HeaderTools>
  );
}

/** Wraps every /mfg/** route: sidebar navigation, header tools, breadcrumb, then the page (UX-STANDARD 3). */
export function MfgLayout() {
  const [collapsed, setCollapsed] = useStoredState<boolean>("sp.side.collapsed", false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    document.title = "Manufacturing - SuperPlanner";
    return () => {
      document.title = "SuperPlanner Studio";
    };
  }, []);
  return (
    <AccessProvider>
      <MfgTools />
      <div className={`mfg-shell${collapsed ? " side-collapsed" : ""}`}>
        <MfgSidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} open={open} onClose={() => setOpen(false)} />
        <div className="mfg-content">
          <MfgBreadcrumbs onMenu={() => setOpen(true)} />
          <div className="mfg-page">
            <AccessError />
            <Outlet />
          </div>
        </div>
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
        {t("mfg.mfgLayout.btn.backToManufacturing")}
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

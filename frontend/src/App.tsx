import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { getHealth } from "./api/client";
import type { Health } from "./api/types";
import { Icon } from "./components/Icon";
import { useStoredState } from "./lib/useAsync";

type ThemePref = "light" | "dark";

function systemTheme(): ThemePref {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

function ThemeToggle() {
  const [pref, setPref] = useStoredState<ThemePref | null>("sp.theme", null);
  const theme = pref ?? systemTheme();
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="btn ghost icon"
      onClick={() => setPref(next)}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      data-testid="theme-toggle"
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}

function ServerStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    let alive = true;
    const check = () =>
      getHealth()
        .then((h) => alive && (setHealth(h), setDown(false)))
        .catch(() => alive && setDown(true));
    void check();
    const t = setInterval(check, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  if (down)
    return (
      <span className="server-dot" role="status" style={{ color: "var(--danger)" }}>
        <Icon name="alert" size={14} /> Server offline
      </span>
    );
  if (!health) return null;
  return (
    <span className="server-dot hide-sm" title={`OR-Tools ${health.ortools_version}, database ${health.database}`}>
      <Icon name={health.status === "ok" ? "check" : "alert"} size={14} />
      Engine {health.version}
    </span>
  );
}

/** Top-level sections. Finance is active iff the path starts with /finance; Scheduling otherwise (FINANCE.md 20.1). */
function MainNav() {
  const { pathname } = useLocation();
  const finance = pathname === "/finance" || pathname.startsWith("/finance/");
  return (
    <nav aria-label="Main" className="main-nav">
      <Link to="/" className={`main-nav-link${finance ? "" : " active"}`} aria-current={finance ? undefined : "page"} data-testid="nav-scheduling">
        Scheduling
      </Link>
      <Link to="/finance" className={`main-nav-link${finance ? " active" : ""}`} aria-current={finance ? "page" : undefined} data-testid="nav-finance">
        Finance
      </Link>
    </nav>
  );
}

export function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand" aria-label="SuperPlanner home">
          <svg className="brand-mark" viewBox="0 0 22 22" aria-hidden>
            <rect x="1" y="1" width="20" height="20" rx="5" fill="var(--accent)" />
            <rect x="5" y="6" width="7" height="3" rx="1.2" fill="var(--accent-contrast)" />
            <rect x="9" y="11" width="8" height="3" rx="1.2" fill="var(--accent-contrast)" opacity="0.85" />
            <rect x="6" y="16" width="5" height="2" rx="1" fill="var(--accent-contrast)" opacity="0.6" />
          </svg>
          SuperPlanner <span className="muted hide-sm" style={{ fontWeight: 500 }}>Studio</span>
        </Link>
        <MainNav />
        <div className="topbar-spacer" />
        <ServerStatus />
        <ThemeToggle />
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="empty">
      <Icon name="help" size={32} />
      <h2>Page not found</h2>
      <p>The page you are looking for does not exist.</p>
      <Link className="btn" to="/">
        Back to plans
      </Link>
    </div>
  );
}

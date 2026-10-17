import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { NETWORK_MESSAGE, getHealth } from "./api/client";
import type { Health } from "./api/types";
import { Banner } from "./components/Banner";
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

/** Polls /health; shared by the top bar dot and the offline banner. */
function useServerHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  const [checking, setChecking] = useState(false);
  const alive = useRef(true);
  const check = useCallback(() => {
    setChecking(true);
    return getHealth()
      .then((h) => alive.current && (setHealth(h), setDown(false)))
      .catch(() => alive.current && setDown(true))
      .finally(() => alive.current && setChecking(false));
  }, []);
  useEffect(() => {
    alive.current = true;
    void check();
    const t = setInterval(check, 30000);
    return () => {
      alive.current = false;
      clearInterval(t);
    };
  }, [check]);
  return { health, down, checking, check };
}

function ServerStatus({ health, down }: { health: Health | null; down: boolean }) {
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

/** True for the finance area: /finance* (FINANCE.md 20.1) and the money start pages /new/money* (PHASE2.md 3.1). */
export function isFinancePath(pathname: string): boolean {
  return /^\/finance(\/|$)/.test(pathname) || /^\/new\/money(\/|$)/.test(pathname);
}

/** Top-level sections. Finance is active for finance paths; Scheduling otherwise. */
function MainNav() {
  const { pathname } = useLocation();
  const finance = isFinancePath(pathname);
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
  const server = useServerHealth();
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
        <ServerStatus health={server.health} down={server.down} />
        <ThemeToggle />
      </header>
      <main className="main">
        {server.down ? (
          <div className="mb">
            <Banner
              tone="danger"
              role="alert"
              testId="server-offline"
              title="Server not reachable"
              actions={
                <button className="btn sm" onClick={() => void server.check()} disabled={server.checking}>
                  {server.checking ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} Retry
                </button>
              }
            >
              {NETWORK_MESSAGE}
            </Banner>
          </div>
        ) : null}
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

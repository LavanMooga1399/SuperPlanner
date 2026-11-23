import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { HeaderSlotContext } from "./components/shell/HeaderSlot";
import { DisplayMenu, ThemeToggle } from "./components/shell/DisplayMenu";
import { CommandPalette } from "./components/shell/CommandPalette";
import { GlobalShortcuts, ShortcutsDialog } from "./components/shell/Shortcuts";
import { MOD, openPalette, openShortcuts } from "./components/shell/commands";
import { Toaster } from "./components/Toast";
import { syncDisplayPrefs } from "./lib/prefs";
import { NETWORK_MESSAGE, getHealth } from "./api/client";
import type { Health } from "./api/types";
import { Banner } from "./components/Banner";
import { Icon } from "./components/Icon";
import { AccountMenu } from "./auth/AccountMenu";
import { useAuth } from "./auth/AuthContext";
import { SessionExpiredBanner } from "./auth/SessionExpiredBanner";
import { isMfgPath } from "./mfg/lib/paths";
import { t, t as tr } from "./lib/i18n";

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
        <Icon name="alert" size={14} />{" "}{tr("shell.app.text.serverOffline")}
      </span>
    );
  if (!health) return null;
  return (
    <span
      className="server-dot hide-md"
      title={tr("shell.app.tpl.engineOrToolsDatabase", { version: health.version, ortoolsversion: health.ortools_version, database: health.database })}
      aria-label={health.status === "ok" ? tr("shell.app.tpl.serverConnectedEngine", { version: health.version }) : tr("shell.app.str.serverDegraded")}
      role="img"
    >
      <span className={`status-dot ${health.status === "ok" ? "ok" : "warn"}`} aria-hidden />
      <span aria-hidden>{health.status === "ok" ? tr("shell.app.str.connected") : tr("shell.app.str.degraded")}</span>
    </span>
  );
}

/** True for the finance area: /finance* (FINANCE.md 20.1) and the money start pages /new/money* (PHASE2.md 3.1). */
export function isFinancePath(pathname: string): boolean {
  return /^\/finance(\/|$)/.test(pathname) || /^\/new\/money(\/|$)/.test(pathname);
}

/** Top-level sections. Finance / Manufacturing are active for their paths; Scheduling otherwise (M1 11.1). */
function MainNav() {
  const { pathname } = useLocation();
  const finance = isFinancePath(pathname);
  const mfg = isMfgPath(pathname);
  const scheduling = !finance && !mfg;
  return (
    <nav aria-label={tr("shell.app.attr.main")} className="main-nav">
      <Link to="/" className={`main-nav-link${scheduling ? " active" : ""}`} aria-current={scheduling ? "page" : undefined} data-testid="nav-scheduling">
        {tr("shell.app.text.scheduling")}
      </Link>
      <Link to="/finance" className={`main-nav-link${finance ? " active" : ""}`} aria-current={finance ? "page" : undefined} data-testid="nav-finance">
        {tr("shell.app.text.finance")}
      </Link>
      <Link to="/mfg" className={`main-nav-link${mfg ? " active" : ""}`} aria-current={mfg ? "page" : undefined} data-testid="nav-mfg">
        {tr("shell.app.text.manufacturing")}
      </Link>
    </nav>
  );
}

function SearchButton() {
  return (
    <button type="button" className="global-search" onClick={openPalette} aria-label={tr("shell.app.tpl.searchAndCommandsK", { MOD: MOD })} data-testid="global-search">
      <Icon name="search" size={14} />
      <span className="global-search-text">{t("shell.search")}</span>
      <kbd className="hide-sm">{MOD} K</kbd>
    </button>
  );
}

export function App() {
  const server = useServerHealth();
  const auth = useAuth();
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  // display settings follow the person (server preferences), once signed in
  useEffect(() => {
    if (auth.status === "authenticated") syncDisplayPrefs();
  }, [auth.status]);
  // Accounts mode, nobody signed in (sign-in / sign-up pages): no section links to pages that need a session.
  const showNav = !(auth.mode === "accounts" && auth.status !== "authenticated");
  return (
    <HeaderSlotContext.Provider value={slot}>
      <div className="app-shell">
        <a href="#main" className="skip-link">
          {t("shell.skip")}
        </a>
        <header className="topbar">
          <Link to="/" className="brand" aria-label={tr("shell.app.attr.superplannerHome")}>
            <svg className="brand-mark" viewBox="0 0 22 22" aria-hidden>
              <rect x="1" y="1" width="20" height="20" rx="5" fill="var(--accent)" />
              <rect x="5" y="6" width="7" height="3" rx="1.2" fill="var(--accent-contrast)" />
              <rect x="9" y="11" width="8" height="3" rx="1.2" fill="var(--accent-contrast)" opacity="0.85" />
              <rect x="6" y="16" width="5" height="2" rx="1" fill="var(--accent-contrast)" opacity="0.6" />
            </svg>
            <span className="hide-sm">SuperPlanner</span>
          </Link>
          {showNav ? <MainNav /> : null}
          <div className="topbar-spacer" />
          {showNav ? <SearchButton /> : null}
          <div className="topbar-tools">
            <div className="topbar-slot" ref={setSlot} />
            <ServerStatus health={server.health} down={server.down} />
            <span className="topbar-sep hide-sm" aria-hidden />
            <button type="button" className="btn ghost icon" onClick={openShortcuts} aria-label={t("shell.help")} title={`${t("shell.help")} (?)`} data-testid="help-button">
              <Icon name="help" />
            </button>
            <DisplayMenu />
            <ThemeToggle />
            <AccountMenu />
          </div>
        </header>
        <main className="main" id="main" tabIndex={-1}>
          {server.down ? (
            <div className="mb">
              <Banner
                tone="danger"
                role="alert"
                testId="server-offline"
                title={tr("shell.app.attr.serverNotReachable")}
                actions={
                  <button className="btn sm" onClick={() => void server.check()} disabled={server.checking}>
                    {server.checking ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />}{" "}{tr("shell.app.text.retry")}
                  </button>
                }
              >
                {NETWORK_MESSAGE}
              </Banner>
            </div>
          ) : null}
          <SessionExpiredBanner />
          <Outlet />
        </main>
        {showNav ? (
          <>
            <GlobalShortcuts />
            <CommandPalette />
            <ShortcutsDialog />
          </>
        ) : null}
        <Toaster />
      </div>
    </HeaderSlotContext.Provider>
  );
}

export function NotFound() {
  return (
    <div className="empty">
      <Icon name="help" size={32} />
      <h2>{tr("shell.app.text.pageNotFound")}</h2>
      <p>{tr("shell.app.text.thePageYouAreLooking")}</p>
      <Link className="btn" to="/">
        {tr("shell.app.text.backToPlans")}
      </Link>
    </div>
  );
}

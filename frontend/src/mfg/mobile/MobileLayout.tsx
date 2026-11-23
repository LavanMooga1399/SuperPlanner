/**
 * Phone shell of `/m/**` (M6 2): 360-430 px first, large targets, bottom navigation (Home, Lines, Alerts, Approvals,
 * More), the plant switcher, the offline state and the M4 offline queue (acknowledgements and downtime close wait
 * here while offline and are replayed in order; approvals need the network). No desktop top bar.
 */
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { Icon, type IconName } from "../../components/Icon";
import { SessionExpiredBanner } from "../../auth/SessionExpiredBanner";
import { registerServiceWorker } from "../../pwa/pwa";
import { listApprovals } from "../api/clientM6";
import { MfgError } from "../components/Feedback";
import { discardFailed, retryFailed, syncNow, useAutoSync, useFloorQueue } from "../floor/offlineQueue";
import { AccessProvider, useAccess } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { useLoad } from "../lib/useMfg";
import { currentWorkspace, switchWorkspace } from "../lib/workspace";
import "./mobile.css";
import { t, t as tr } from "../../lib/i18n";

function useStoredTheme() {
  useEffect(() => {
    let pref: string | null = null;
    try {
      pref = JSON.parse(localStorage.getItem("sp.theme") ?? "null") as string | null;
    } catch {
      pref = null;
    }
    const sys = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", pref === "dark" || pref === "light" ? pref : sys);
  }, []);
}

function PlantSwitch() {
  const access = useAccess();
  const ws = access.workspaces;
  const current = currentWorkspace() ?? access.me?.workspace_owner_id ?? "";
  if (ws.length <= 1) return <span className="m-plant" data-testid="m-plant">{access.me?.workspace_name || ws[0]?.plant_name || tr("mobile.mobileLayout.str.myPlant")}</span>;
  return (
    <>
      <label htmlFor="m-plant" className="sr-only">
        {tr("mobile.mobileLayout.text.plant")}
      </label>
      <select
        id="m-plant"
        className="select m-plant-select"
        value={current}
        onChange={(e) => switchWorkspace(e.target.value, access.me?.user_id, "/m")}
        data-testid="m-plant"
      >
        {ws.map((w) => (
          <option key={w.owner_id} value={w.owner_id}>
            {w.plant_code ? `${w.plant_code} ` : ""}
            {w.plant_name}
          </option>
        ))}
      </select>
    </>
  );
}

function QueueStatus({ online }: { online: boolean }) {
  const q = useFloorQueue();
  const [open, setOpen] = useState(false);
  if (!q.pending.length && !q.failed.length) return null;
  return (
    <div className={`m-queue ${q.failed.length ? "danger" : ""}`} role="status" data-testid="m-queue">
      <button type="button" className="m-queue-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <Icon name={q.failed.length ? "alert" : "clock"} size={16} />
        {q.pending.length ? tr("mobile.mobileLayout.tpl.waitingToSync", { length: q.pending.length }) : ""}
        {q.pending.length && q.failed.length ? " · " : ""}
        {q.failed.length ? tr("mobile.mobileLayout.tpl.notAccepted", { length: q.failed.length }) : ""}
        <Icon name={open ? "chevron-down" : "chevron-right"} size={14} />
      </button>
      {open ? (
        <ul className="m-queue-list">
          {q.pending.map((a) => (
            <li key={a.id}>
              <Icon name="clock" size={14} /> {a.label}
            </li>
          ))}
          {q.failed.map((a) => (
            <li key={a.id} className="col" style={{ gap: 4 }}>
              <span>
                <Icon name="alert" size={14} /> {a.label}: {a.error?.message}
              </span>
              <span className="row" style={{ gap: 6 }}>
                <button type="button" className="btn sm" onClick={() => retryFailed(a.id)}>
                  {t("mobile.mobileLayout.btn.retry")}
                </button>
                <button type="button" className="btn ghost sm" onClick={() => discardFailed(a.id)}>
                  {t("mobile.mobileLayout.btn.discard")}
                </button>
              </span>
            </li>
          ))}
          {online && q.pending.length ? (
            <li>
              <button type="button" className="btn sm" onClick={() => void syncNow()} disabled={q.syncing}>
                {q.syncing ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />}{" "}{tr("mobile.mobileLayout.text.syncNow")}
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

const TABS: { to: string; label: string; icon: IconName; end?: boolean; key: string }[] = [
  { to: "/m", label: "Home", icon: "factory", end: true, key: "home" },
  { to: "/m/lines", label: tr("mobile.mobileLayout.str.lines"), icon: "layers", key: "lines" },
  { to: "/m/alerts", label: tr("mobile.mobileLayout.str.alerts"), icon: "alert", key: "alerts" },
  { to: "/m/approvals", label: tr("mobile.mobileLayout.str.approvals"), icon: "check", key: "approvals" },
  { to: "/m/more", label: tr("mobile.mobileLayout.str.more"), icon: "list", key: "more" },
];

function BottomNav() {
  const { online } = useAutoSync();
  const appr = useLoad((signal) => (online ? listApprovals(signal) : null), [online]);
  usePolling(appr.reload, online, 60000);
  useEffect(() => {
    const on = () => appr.reload();
    window.addEventListener("sp-push", on);
    return () => window.removeEventListener("sp-push", on);
  }, [appr.reload]);
  const n = appr.data?.items.length ?? 0;
  return (
    <nav className="m-tabs" aria-label={t("mobile.mobileLayout.aria.mobileSections")}>
      {TABS.map((t) => (
        <NavLink key={t.key} to={t.to} end={t.end} className={({ isActive }) => `m-tab${isActive ? " active" : ""}`} data-testid={`m-tab-${t.key}`}>
          <Icon name={t.icon} size={20} />
          <span>{t.label}</span>
          {t.key === "approvals" && n > 0 ? (
            <span className="m-tab-count" aria-label={`${n} waiting`}>
              {n}
            </span>
          ) : null}
        </NavLink>
      ))}
    </nav>
  );
}

function Shell() {
  const navigate = useNavigate();
  const access = useAccess();
  const { online } = useAutoSync();
  useStoredTheme();
  useEffect(() => {
    void registerServiceWorker();
    // the service worker asks an open window to go to a notification's page when it cannot navigate it itself
    const onMsg = (e: MessageEvent) => {
      const d = e.data as { type?: string; link?: string } | null;
      if (d?.type === "open" && typeof d.link === "string" && d.link.startsWith("/") && !d.link.startsWith("//")) navigate(d.link);
      // a push arrived while the app is open: pages refresh their counts (see BottomNav)
      if (d?.type === "push") window.dispatchEvent(new CustomEvent("sp-push", { detail: d }));
    };
    navigator.serviceWorker?.addEventListener("message", onMsg);
    document.title = tr("mobile.mobileLayout.str.superplannerMobile");
    return () => navigator.serviceWorker?.removeEventListener("message", onMsg);
  }, [navigate]);
  return (
    <div className="m-shell" data-testid="m-shell">
      <header className="m-head">
        <Link to="/m" className="m-brand" aria-label={t("mobile.mobileLayout.aria.superplannerMobileHome")}>
          <svg viewBox="0 0 22 22" width="26" height="26" aria-hidden>
            <rect x="1" y="1" width="20" height="20" rx="5" fill="var(--accent)" />
            <rect x="5" y="6" width="7" height="3" rx="1.2" fill="var(--accent-contrast)" />
            <rect x="9" y="11" width="8" height="3" rx="1.2" fill="var(--accent-contrast)" opacity="0.85" />
            <rect x="6" y="16" width="5" height="2" rx="1" fill="var(--accent-contrast)" opacity="0.6" />
          </svg>
        </Link>
        <PlantSwitch />
        <span className={`m-online ${online ? "ok" : "off"}`} role="status" data-testid="m-online" data-online={online}>
          <Icon name={online ? "check" : "alert"} size={14} /> {online ? tr("mobile.mobileLayout.str.online") : tr("mobile.mobileLayout.str.offline")}
        </span>
      </header>
      <main className="m-main">
        <SessionExpiredBanner />
        {!online ? (
          <div className="m-banner warn" role="status" data-testid="m-offline">
            <Icon name="alert" size={16} /> {t("mobile.mobileLayout.btn.youAreOfflineAcknowledgementsAre")}
          </div>
        ) : null}
        <QueueStatus online={online} />
        {access.error ? <MfgError error={access.error} onRetry={access.retry} title={tr("mobile.mobileLayout.attr.yourPlantPermissionsCouldNot")} /> : null}
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}

export function MobileLayout() {
  return (
    <AccessProvider>
      <Shell />
    </AccessProvider>
  );
}

/** "Online" for pages that must not act offline (approvals). */
export function useOnline(): boolean {
  return useAutoSync().online;
}

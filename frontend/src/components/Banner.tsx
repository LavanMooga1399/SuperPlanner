import type { ReactNode } from "react";
import { NETWORK_MESSAGE } from "../api/client";
import { Icon, type IconName } from "./Icon";

export interface BannerProps {
  tone?: "ok" | "warn" | "danger" | "accent" | "info";
  icon?: IconName;
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  testId?: string;
  role?: "status" | "alert";
}

const DEFAULT_ICON: Record<string, IconName> = {
  ok: "check",
  warn: "alert",
  danger: "alert",
  accent: "info",
  info: "info",
};

export function Banner({ tone = "info", icon, title, children, actions, testId, role }: BannerProps) {
  return (
    <div className={`banner ${tone === "info" ? "" : tone}`} data-testid={testId} role={role}>
      <Icon name={icon ?? DEFAULT_ICON[tone]} />
      <div className="banner-body">
        {title ? <strong>{title}</strong> : null}
        {children ? <div>{children}</div> : null}
      </div>
      {actions ? <div className="banner-actions">{actions}</div> : null}
    </div>
  );
}

/** Error with an optional Retry. A network failure gets its own title (PHASE2.md 3.6). */
export function ErrorBanner({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null;
  const network = error === NETWORK_MESSAGE;
  return (
    <Banner
      tone="danger"
      role="alert"
      title={network ? "Server not reachable" : "Something went wrong"}
      testId={network ? "network-error" : undefined}
      actions={onRetry ? <button className="btn sm" onClick={onRetry}><Icon name="refresh" /> Retry</button> : null}
    >
      {error}
    </Banner>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="empty" role="status">
      <span className="spinner" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

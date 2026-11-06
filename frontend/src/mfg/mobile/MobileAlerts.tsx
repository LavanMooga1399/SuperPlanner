/**
 * `/m/alerts` (M6 2): M4 notifications, newest first, unacknowledged on top, with severity as icon + text and an
 * Acknowledge button that goes through the offline queue (sent once when back online).
 */
import { useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { listNotifications } from "../api/clientM4";
import type { MfgNotification, Severity } from "../api/typesM4";
import { safeInternalLink } from "../assistant/AnswerText";
import { MfgError, Spinner } from "../components/Feedback";
import { pendingIds, submitNotificationAck, useFloorQueue } from "../floor/offlineQueue";
import { floorErrorText } from "../floor/floorText";
import { usePolling } from "../lib/usePolling";
import { useLoad } from "../lib/useMfg";
import { useOnline } from "./MobileLayout";

const SEVERITY: Record<Severity, { label: string; tone: string; icon: "alert" | "info" }> = {
  critical: { label: "Critical", tone: "danger", icon: "alert" },
  warning: { label: "Warning", tone: "warn", icon: "alert" },
  info: { label: "Info", tone: "info", icon: "info" },
};

function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity] ?? SEVERITY.info;
  return (
    <span className={`badge ${s.tone}`} data-severity={severity}>
      <Icon name={s.icon} /> {s.label}
    </span>
  );
}

/** Desktop floor links open the phone's line page. */
export function mobileLink(link: string | null): string | null {
  const to = safeInternalLink(link);
  if (!to) return null;
  const m = to.match(/^\/mfg\/floor\/lines\/([^/?#]+)/);
  if (m) return `/m/lines/${m[1]}`;
  const w = to.match(/^\/mfg\/(?:floor\/wo|work-orders)\/([^/?#]+)$/);
  if (w) return `/m/wo/${w[1]}`;
  return to;
}

function AlertRow({ n }: { n: MfgNotification }) {
  useFloorQueue();
  const waiting = pendingIds("notification_ack").has(n.id);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const acked = Boolean(n.acknowledged_at) || done;
  const to = mobileLink(n.link);
  const ack = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await submitNotificationAck(n.id, `Alert acknowledged: ${n.title}`);
      if (r.status === "sent") setDone(true);
    } catch (e) {
      setErr(floorErrorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="m-card" data-testid="m-alert" data-acked={acked || waiting}>
      <div className="row" style={{ justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
        <strong>{n.title}</strong>
        <SeverityBadge severity={n.severity} />
      </div>
      {n.body ? <p style={{ margin: 0 }}>{n.body}</p> : null}
      <span className="muted small">{new Date(n.created_at).toLocaleString()}</span>
      <div className="m-actions">
        {acked ? (
          <span className="m-state small">
            <Icon name="check" size={14} /> Acknowledged{n.acknowledged_by ? ` by ${n.acknowledged_by.name ?? n.acknowledged_by.code}` : ""}
          </span>
        ) : waiting ? (
          <span className="m-state small" data-testid="m-alert-waiting">
            <Icon name="clock" size={14} /> Acknowledged, waiting to sync
          </span>
        ) : (
          <button type="button" className="btn primary" onClick={() => void ack()} disabled={busy} data-testid="m-alert-ack">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Acknowledge
          </button>
        )}
        {to ? (
          <Link to={to} className="btn">
            Open <Icon name="arrow-right" />
          </Link>
        ) : null}
      </div>
      {err ? (
        <p className="field-error" role="alert" style={{ margin: 0 }}>
          {err}
        </p>
      ) : null}
    </li>
  );
}

export function MobileAlerts() {
  const online = useOnline();
  const list = useLoad((signal) => listNotifications({ limit: 50 }, signal), [online]);
  usePolling(list.reload, online, 30000);
  const items = [...(list.data?.items ?? [])].sort((a, b) => Number(Boolean(a.acknowledged_at)) - Number(Boolean(b.acknowledged_at)) || b.created_at.localeCompare(a.created_at));
  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-alerts">
      <h1>Alerts</h1>
      {list.error && !list.data ? <MfgError error={list.error} onRetry={list.reload} /> : null}
      {list.loading && !list.data ? <Spinner /> : null}
      {list.data && !items.length ? <p className="muted">No alerts.</p> : null}
      <ul className="m-list">
        {items.map((n) => (
          <AlertRow key={n.id} n={n} />
        ))}
      </ul>
    </div>
  );
}

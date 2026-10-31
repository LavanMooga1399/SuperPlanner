/** Header bell (M4 12, #220/#221): unacknowledged notifications, refreshed every minute; the count is text too. */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { listNotifications } from "../api/clientM4";
import { usePlantClock } from "../lib/plantTime";
import { mfgPaths } from "../lib/paths";
import { useLoad } from "../lib/useMfg";
import { usePolling } from "../lib/usePolling";
import { NotificationList } from "../pages/m4/ReplanPage";

export function NotificationBell() {
  const clock = usePlantClock();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const n = useLoad((signal) => listNotifications({ unacked: true, limit: 20 }, signal).catch(() => null), []);
  usePolling(n.reload, true, 60000);
  const count = n.data ? (n.data.unacked ?? n.data.total ?? n.data.items.length) : 0;
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  if (!n.data && !n.loading) return null; // server without M4 notifications
  return (
    <div className="mfg-bell" ref={ref}>
      <button
        type="button"
        className="btn ghost"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={count ? `${count} new notification${count === 1 ? "" : "s"}` : "Notifications, none new"}
        onClick={() => setOpen((v) => !v)}
        data-testid="notif-bell"
        data-count={count}
      >
        <Icon name="flag" />
        {count ? <span className="mfg-bell-count">{count > 99 ? "99+" : count}</span> : null}
      </button>
      {open ? (
        <div className="mfg-bell-pop card" role="dialog" aria-label="Notifications">
          <div className="card-header row" style={{ justifyContent: "space-between" }}>
            <strong>New notifications</strong>
            <Link to={mfgPaths.replan()} onClick={() => setOpen(false)}>
              All and replanning
            </Link>
          </div>
          <NotificationList items={n.data?.items ?? []} onAck={n.reload} clock={clock} compact />
        </div>
      ) : null}
    </div>
  );
}

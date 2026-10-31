/**
 * `/mfg/replan` (M4 7, 12): what changed on the floor and in supply since the plan was published (replan triggers),
 * the notifications, and the replan proposals. The planner makes a proposal run from selected triggers (#219, a copy
 * of the published run at "now"), compares it with the published plan and publishes it - nothing republishes
 * silently unless the plant chose `auto_publish` (principle F3).
 */
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { Icon } from "../../../components/Icon";
import { getPlant } from "../../api/client";
import { getPublishedRun, listApsRuns } from "../../api/clientM3";
import { ackNotification, handleTrigger, ignoreTrigger, listNotifications, listTriggers, runReplan } from "../../api/clientM4";
import type { PlantM4Fields, ReplanTrigger, TriggerKind } from "../../api/typesM4";
import { ApsStatusChip, PolicyBadge } from "../../components/ApsBits";
import { MfgError } from "../../components/Feedback";
import { TRIGGER } from "../../floor/floorText";
import { usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { useLoad } from "../../lib/useMfg";
import { usePolling } from "../../lib/usePolling";
import { ReasonDialog } from "./FloorEvents";

const POLICY_TEXT: Record<string, string> = {
  notify: "Changes wait for you; make a proposal when you want one.",
  auto_whatif: "The first warning starts a proposal after a short wait so later changes join it. You compare and publish.",
  auto_publish: "Proposals are published when they break no rules, keep the frozen work and are not later than the current plan.",
};

const SEV_TONE: Record<string, string> = { critical: "danger", warning: "warn", info: "info" };

/** where a trigger's subject lives in the UI */
export function triggerLink(t: ReplanTrigger): string | null {
  const id = t.ref_id;
  const lineId = typeof t.details?.line_id === "string" ? t.details.line_id : null;
  switch (t.ref_type) {
    case "downtime":
    case "line":
      return lineId ? mfgPaths.floorLine(lineId) : mfgPaths.floorOverview();
    case "work_order":
    case "wo":
      return mfgPaths.workOrder(id);
    case "wo_operation":
    case "operation":
      return mfgPaths.floorOp(id);
    case "demand_order":
      return mfgPaths.demandOrder(id);
    case "po_schedule":
    case "purchase_schedule":
      return mfgPaths.deliveryBoard({});
    default:
      return null;
  }
}

export function ReplanPage() {
  const clock = usePlantClock();
  const navigate = useNavigate();
  const canManage = useCan("replan_manage");
  const canRun = useCan("schedule_run");
  const [status, setStatus] = useState<"active" | "all">("active");
  const [kind, setKind] = useState<TriggerKind | "">("");
  const plant = useLoad((signal) => getPlant(signal), []);
  const triggers = useLoad((signal) => listTriggers({ status: status === "active" ? ["open", "attached"] : undefined, kind: kind || undefined, limit: 200 }, signal), [status, kind]);
  const notes = useLoad((signal) => listNotifications({ limit: 30 }, signal), []);
  const published = useLoad((signal) => getPublishedRun(signal).catch(() => null), []);
  const runs = useLoad((signal) => listApsRuns({ limit: 30, offset: 0 }, signal), []);
  usePolling(() => {
    triggers.reload();
    notes.reload();
    runs.reload();
  }, true, 30000);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [closing, setClosing] = useState<{ t: ReplanTrigger; action: "ignore" | "handle" } | null>(null);
  const policy = (plant.data as (PlantM4Fields & object) | null)?.replan_policy ?? "notify";
  const rows = triggers.data?.items ?? [];
  const proposals = (runs.data?.items ?? []).filter((r) => /^Replan/i.test(r.label) && r.id !== published.data?.id);

  const propose = async () => {
    setBusy(true);
    setError(null);
    try {
      const run = await runReplan([...sel]);
      setSel(new Set());
      navigate(published.data ? mfgPaths.apsCompare(run.id, published.data.id) : mfgPaths.apsRun(run.id));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid="replan-page">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Replanning</h1>
        <span className="row wrap">
          {published.data ? (
            <Link className="btn" to={mfgPaths.apsRun(published.data.id)}>
              Published: schedule #{published.data.run_no}
            </Link>
          ) : (
            <span className="muted">No published schedule yet</span>
          )}
        </span>
      </div>
      <div className="banner" data-testid="replan-policy" data-policy={policy}>
        <Icon name="info" />
        <div>
          <strong>{policy === "notify" ? "Notify only" : policy === "auto_whatif" ? "Automatic proposals" : "Automatic publish"}</strong> {POLICY_TEXT[policy]}{" "}
          <Link to={mfgPaths.settings()}>Change in plant settings</Link>
        </div>
      </div>
      <MfgError error={error ?? triggers.error} onRetry={triggers.reload} />

      <section className="card">
        <div className="card-header row wrap" style={{ justifyContent: "space-between" }}>
          <h2>What changed ({rows.length})</h2>
          <div className="row wrap">
            <select className="select sm" style={{ width: "auto" }} aria-label="Show" value={status} onChange={(e) => setStatus(e.target.value as "active" | "all")}>
              <option value="active">Open</option>
              <option value="all">All, incl. handled</option>
            </select>
            <select className="select sm" style={{ width: "auto" }} aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value as TriggerKind | "")}>
              <option value="">All kinds</option>
              {(Object.keys(TRIGGER) as TriggerKind[]).map((k) => (
                <option key={k} value={k}>
                  {TRIGGER[k].label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn primary"
              disabled={!canRun || busy || (!sel.size && !rows.some((r) => r.status === "open"))}
              title={canRun ? undefined : needsText("schedule_run")}
              onClick={() => void propose()}
              data-testid="replan-run"
            >
              <Icon name="play" /> {sel.size ? `Make a proposal from ${sel.size} selected` : "Make a proposal from all open"}
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table" data-testid="trigger-table">
            <thead>
              <tr>
                <th aria-label="Select" />
                <th>What</th>
                <th>Details</th>
                <th>When</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    {triggers.loading ? "Loading…" : "Nothing changed since the plan was published."}
                  </td>
                </tr>
              ) : null}
              {rows.map((t) => (
                <tr key={t.id} data-testid="trigger-row" data-kind={t.kind} data-status={t.status} data-severity={t.severity}>
                  <td>
                    {t.status === "open" ? (
                      <input
                        type="checkbox"
                        aria-label={`Select ${TRIGGER[t.kind]?.label ?? t.kind}`}
                        checked={sel.has(t.id)}
                        onChange={() =>
                          setSel((s) => {
                            const n = new Set(s);
                            if (n.has(t.id)) n.delete(t.id);
                            else n.add(t.id);
                            return n;
                          })
                        }
                      />
                    ) : null}
                  </td>
                  <td>
                    <span className={`badge ${SEV_TONE[t.severity] ?? "info"}`}>
                      <Icon name={TRIGGER[t.kind]?.icon ?? "alert"} /> {TRIGGER[t.kind]?.label ?? t.kind}
                    </span>
                    <div className="faint small">{t.severity}</div>
                  </td>
                  <td>
                    <span>{t.message}</span>
                    {triggerLink(t) ? (
                      <div className="small">
                        <Link to={triggerLink(t)!}>Open</Link>
                      </div>
                    ) : null}
                  </td>
                  <td className="small">{clock.dateTime(t.detected_at)}</td>
                  <td className="small">
                    {t.status === "attached" && t.aps_run_id ? (
                      <Link to={mfgPaths.apsRun(t.aps_run_id)}>in a proposal</Link>
                    ) : t.status === "open" ? (
                      "open"
                    ) : (
                      `${t.status}${t.handled_at ? ` ${clock.dateTime(t.handled_at)}` : ""}`
                    )}
                  </td>
                  <td>
                    {canManage && (t.status === "open" || t.status === "attached") ? (
                      <span className="row">
                        <button type="button" className="btn sm" onClick={() => setClosing({ t, action: "handle" })} data-testid="trigger-handle">
                          Handled
                        </button>
                        <button type="button" className="btn sm ghost" onClick={() => setClosing({ t, action: "ignore" })} data-testid="trigger-ignore">
                          Ignore
                        </button>
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>Proposals</h2>
        </div>
        <div className="table-wrap">
          <table className="table" data-testid="replan-proposals">
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Started</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {proposals.length === 0 ? (
                <tr>
                  <td colSpan={4} className="muted">
                    No proposals.
                  </td>
                </tr>
              ) : null}
              {proposals.map((r) => (
                <tr key={r.id} data-testid="replan-proposal">
                  <td>
                    <Link to={mfgPaths.apsRun(r.id)}>
                      Schedule #{r.run_no} · {r.label}
                    </Link>{" "}
                    <PolicyBadge policy={r.policy} />
                  </td>
                  <td>
                    <ApsStatusChip run={r} />
                  </td>
                  <td className="small">{clock.dateTime(r.started_at ?? r.finished_at)}</td>
                  <td>
                    {published.data && r.status === "completed" ? (
                      <Link className="btn sm" to={mfgPaths.apsCompare(r.id, published.data.id)}>
                        <Icon name="compare" /> Compare with published
                      </Link>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>Notifications</h2>
        </div>
        <NotificationList items={notes.data?.items ?? []} onAck={notes.reload} clock={clock} />
      </section>

      {closing ? (
        <ReasonDialog
          title={closing.action === "handle" ? "Mark as handled" : "Ignore this change"}
          text={`${TRIGGER[closing.t.kind]?.label ?? closing.t.kind}: ${closing.t.message}`}
          confirm={closing.action === "handle" ? "Mark handled" : "Ignore"}
          onClose={() => setClosing(null)}
          onConfirm={async (note) => {
            if (closing.action === "handle") await handleTrigger(closing.t.id, note);
            else await ignoreTrigger(closing.t.id, note);
            setClosing(null);
            triggers.reload();
          }}
        />
      ) : null}
    </div>
  );
}

export function NotificationList({ items, onAck, clock, compact }: { items: import("../../api/typesM4").MfgNotification[]; onAck(): void; clock: ReturnType<typeof usePlantClock>; compact?: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!items.length) return <div className="card-body muted">No notifications.</div>;
  return (
    <ul className="mfg-ex-list" data-testid="notif-list">
      {items.map((n) => (
        <li key={n.id} className="mfg-ex-item" data-testid="notif-item" data-acked={Boolean(n.acknowledged_at)}>
          <span className={`badge ${SEV_TONE[n.severity] ?? "info"}`}>
            <Icon name={n.severity === "info" ? "info" : "alert"} /> {n.severity}
          </span>
          <div className="col" style={{ gap: 2, minWidth: 0, flex: 1 }}>
            <strong>{n.link ? <Link to={n.link}>{n.title}</Link> : n.title}</strong>
            {!compact && n.body ? <span className="small">{n.body}</span> : null}
            <span className="faint small">{clock.dateTime(n.created_at)}</span>
          </div>
          {n.acknowledged_at ? (
            <span className="faint small">
              <Icon name="check" size={12} /> seen
            </span>
          ) : (
            <button
              type="button"
              className="btn sm"
              disabled={busy === n.id}
              onClick={async () => {
                setBusy(n.id);
                try {
                  await ackNotification(n.id);
                  onAck();
                } finally {
                  setBusy(null);
                }
              }}
              data-testid="notif-ack"
            >
              Mark seen
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

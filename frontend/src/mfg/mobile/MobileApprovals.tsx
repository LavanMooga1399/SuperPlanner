/**
 * `/m/approvals` (M6 2, M5 `/mfg/approvals`): what waits for this user's decision.
 * - Purchase request: approve / reject with a reason (M2, If-Match).
 * - Engineering change: approve / reject with a note (M5, If-Match).
 * - Schedule proposal: compare with the published schedule (key figures), then publish (M3/M4, If-Match; a
 *   stale-basis answer asks again).
 * - Suggested overtime: accept = a new schedule from that run with these shifts opened (`copy_of` + `open_shifts`).
 * Approvals need the network (fresh data, If-Match); offline the buttons are disabled with the reason.
 */
import { useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import { Icon, type IconName } from "../../components/Icon";
import { purchaseAction } from "../api/clientM2";
import { compareApsRuns, publishApsRun, rerunWithOpenShifts } from "../api/clientM3";
import { ecoAction } from "../api/clientM5";
import { listApprovals } from "../api/clientM6";
import type { Permission } from "../api/typesM2";
import type { ApprovalItem, ApprovalKind } from "../api/typesM6";
import { MfgError, Spinner } from "../components/Feedback";
import { needsText, useAccess } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { errorText, isConflict, useLoad } from "../lib/useMfg";
import { mobileLink } from "./MobileAlerts";
import { useOnline } from "./MobileLayout";

const KIND: Record<ApprovalKind, { label: string; icon: IconName; perm: Permission }> = {
  pr: { label: "Purchase request", icon: "briefcase", perm: "pr_approve" },
  eco: { label: "Engineering change", icon: "refresh", perm: "eco_approve" },
  proposal: { label: "Schedule proposal", icon: "calendar", perm: "schedule_publish" },
  overtime: { label: "Suggested overtime", icon: "clock", perm: "schedule_run" },
};

const FILTERS: { key: ApprovalKind | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pr", label: "Purchasing" },
  { key: "eco", label: "Changes" },
  { key: "proposal", label: "Schedules" },
  { key: "overtime", label: "Overtime" },
];

type Outcome = { tone: "ok" | "danger"; text: string } | null;

function fmtMinutes(m: number | null | undefined): string | null {
  if (m === null || m === undefined) return null;
  if (Math.abs(m) >= 1440) return `${(m / 1440).toFixed(1)} days`;
  if (Math.abs(m) >= 60) return `${(m / 60).toFixed(1)} h`;
  return `${Math.round(m)} min`;
}

function ProposalCompare({ item }: { item: ApprovalItem }) {
  const cmp = useLoad((signal) => (item.base_run_id ? compareApsRuns(item.base_run_id, item.id, signal) : null), [item.id, item.base_run_id]);
  if (!item.base_run_id) return <p className="muted small" style={{ margin: 0 }}>No published schedule to compare with.</p>;
  if (cmp.loading && !cmp.data) return <p className="muted small" role="status" style={{ margin: 0 }}><span className="spinner" aria-hidden /> Comparing…</p>;
  if (cmp.error) return <MfgError error={cmp.error} onRetry={cmp.reload} title="Could not compare" />;
  const t = cmp.data?.tradeoff;
  const kpis = (cmp.data?.kpis ?? []).slice(0, 4);
  return (
    <div className="col" style={{ gap: 6 }} data-testid="m-proposal-compare">
      {t ? (
        <dl className="m-dl">
          <dt>Late demand lines</dt>
          <dd>{t.late_demand_saved >= 0 ? `${t.late_demand_saved} fewer` : `${-t.late_demand_saved} more`}</dd>
          <dt>Lateness</dt>
          <dd>{t.late_minutes_saved >= 0 ? `${fmtMinutes(t.late_minutes_saved)} less` : `${fmtMinutes(-t.late_minutes_saved)} more`}</dd>
          <dt>Overtime</dt>
          <dd>{t.overtime_hours_added ? `${t.overtime_hours_added.toFixed(1)} h more (${Math.round(t.overtime_cost_added).toLocaleString()})` : "no change"}</dd>
        </dl>
      ) : null}
      {kpis.length ? (
        <table className="table small">
          <thead>
            <tr>
              <th scope="col">Figure</th>
              <th scope="col">Published</th>
              <th scope="col">Proposal</th>
            </tr>
          </thead>
          <tbody>
            {kpis.map((k) => (
              <tr key={k.key}>
                <th scope="row">{k.key.replace(/_/g, " ")}</th>
                <td>{k.a ?? "–"}</td>
                <td>{k.b ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

function ApprovalCard({ item, online, onDone }: { item: ApprovalItem; online: boolean; onDone(): void }) {
  const access = useAccess();
  const k = KIND[item.kind] ?? { label: item.kind, icon: "flag" as IconName, perm: "view" as Permission };
  const allowed = access.can(k.perm);
  const [busy, setBusy] = useState<string | null>(null);
  const [out, setOut] = useState<Outcome>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [showCompare, setShowCompare] = useState(false);
  const [confirmStale, setConfirmStale] = useState(false);
  const blocked = !online ? "Needs a connection: approvals always use the latest data." : !allowed ? needsText(k.perm) : null;
  const to = mobileLink(item.link);

  const run = async (what: string, fn: () => Promise<unknown>, okText: string) => {
    setBusy(what);
    setOut(null);
    try {
      await fn();
      setOut({ tone: "ok", text: okText });
      setRejecting(false);
      setConfirmStale(false);
      window.setTimeout(onDone, 1200);
    } catch (e) {
      if (e instanceof ApiError && e.code === "APS_RUN_STALE_BASIS") {
        setConfirmStale(true);
        setOut({ tone: "danger", text: "Another schedule was published after this proposal was made. Publishing it changes work already planned for the floor." });
      } else setOut({ tone: "danger", text: isConflict(e) ? "This changed since the list was loaded. Reload the list and check it again." : errorText(e) });
    } finally {
      setBusy(null);
    }
  };

  const approve = () => {
    if (item.kind === "pr") return run("approve", () => purchaseAction("pr", item.id, "approve", item.row_version), "Approved.");
    if (item.kind === "eco") return run("approve", () => ecoAction(item.id, "approve", item.row_version), "Approved.");
    if (item.kind === "proposal") return run("approve", () => publishApsRun(item.id, item.row_version, confirmStale), "Published. It is now the plant schedule.");
    return run("approve", () => rerunWithOpenShifts(item.id, item.shifts ?? [], `Overtime accepted: ${item.label}`.slice(0, 120)), "Accepted. A new schedule with this overtime is being made; it appears here as a proposal to publish.");
  };
  const reject = () => {
    if (item.kind === "pr") return run("reject", () => purchaseAction("pr", item.id, "reject", item.row_version, { reason: reason.trim() }), "Rejected.");
    return run("reject", () => ecoAction(item.id, "reject", item.row_version, { note: reason.trim() }), "Rejected.");
  };
  const approveLabel = item.kind === "proposal" ? (confirmStale ? "Publish anyway" : "Publish") : item.kind === "overtime" ? "Accept overtime" : "Approve";
  const canReject = item.kind === "pr" || item.kind === "eco";

  return (
    <li className="m-card" data-testid="m-approval" data-kind={item.kind} data-id={item.id}>
      <span className="muted small m-state">
        <Icon name={k.icon} size={14} /> {k.label}
      </span>
      <div className="row" style={{ justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
        <strong>{item.label}</strong>
        {item.created_at ? <span className="muted small">{new Date(item.created_at).toLocaleDateString()}</span> : null}
      </div>
      <p style={{ margin: 0 }}>{item.summary}</p>
      {item.requested_by ? <span className="muted small">From {item.requested_by.name}</span> : null}
      {item.facts?.length ? (
        <dl className="m-dl">
          {item.facts.map((f) => (
            <div key={f.label} style={{ display: "contents" }}>
              <dt>{f.label}</dt>
              <dd>{f.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {item.kind === "overtime" ? (
        <dl className="m-dl">
          {(item.shifts ?? []).map((s, i) => (
            <div key={i} style={{ display: "contents" }}>
              <dt>Shift {i + 1}</dt>
              <dd>
                {new Date(s.start).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} –{" "}
                {new Date(s.end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </dd>
            </div>
          ))}
          {item.tardiness_saved_minutes ? (
            <>
              <dt>Saves</dt>
              <dd>{fmtMinutes(item.tardiness_saved_minutes)} of lateness</dd>
            </>
          ) : null}
          {item.cost ? (
            <>
              <dt>Cost</dt>
              <dd>{Math.round(item.cost).toLocaleString()}</dd>
            </>
          ) : null}
        </dl>
      ) : null}
      {item.kind === "proposal" ? (
        <>
          <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={showCompare} onClick={() => setShowCompare((v) => !v)} disabled={!online} data-testid="m-proposal-compare-btn">
            <Icon name={showCompare ? "chevron-down" : "compare"} /> Compare with the published schedule
          </button>
          {showCompare ? <ProposalCompare item={item} /> : null}
        </>
      ) : null}
      {rejecting ? (
        <div className="col" style={{ gap: 6 }}>
          <label htmlFor={`rej-${item.id}`} className="small" style={{ fontWeight: 600 }}>
            Reason
          </label>
          <textarea id={`rej-${item.id}`} className="textarea" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="m-approval-reason" />
        </div>
      ) : null}
      {out?.tone !== "ok" ? (
        <div className="m-actions">
          {rejecting ? (
            <>
              <button type="button" className="btn danger" disabled={Boolean(blocked) || busy !== null || !reason.trim()} onClick={() => void reject()} data-testid="m-approval-reject-confirm">
                {busy === "reject" ? <span className="spinner" aria-hidden /> : <Icon name="x" />} Reject
              </button>
              <button type="button" className="btn ghost" onClick={() => setRejecting(false)}>
                Cancel
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn primary" disabled={Boolean(blocked) || busy !== null} onClick={() => void approve()} data-testid="m-approval-approve">
                {busy === "approve" ? <span className="spinner" aria-hidden /> : <Icon name="check" />} {approveLabel}
              </button>
              {canReject ? (
                <button type="button" className="btn" disabled={Boolean(blocked) || busy !== null} onClick={() => setRejecting(true)} data-testid="m-approval-reject">
                  <Icon name="x" /> Reject
                </button>
              ) : null}
            </>
          )}
          {to ? (
            <Link to={to} className="btn ghost">
              Details
            </Link>
          ) : null}
        </div>
      ) : null}
      {blocked && out?.tone !== "ok" ? (
        <span className="muted small m-state" data-testid="m-approval-blocked">
          <Icon name={!online ? "alert" : "lock"} size={12} /> {blocked}
        </span>
      ) : null}
      {out ? (
        <p className={out.tone === "danger" ? "field-error" : "m-state"} role={out.tone === "danger" ? "alert" : "status"} style={{ margin: 0 }} data-testid="m-approval-result">
          {out.tone === "ok" ? <Icon name="check" size={14} /> : null} {out.text}
        </p>
      ) : null}
    </li>
  );
}

export function MobileApprovals() {
  const online = useOnline();
  const list = useLoad((signal) => (online ? listApprovals(signal) : null), [online]);
  usePolling(list.reload, online, 60000);
  const [filter, setFilter] = useState<ApprovalKind | "all">("all");
  const items = (list.data?.items ?? []).filter((x) => filter === "all" || x.kind === filter);
  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-approvals">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Approvals</h1>
        <button type="button" className="btn ghost sm" onClick={list.reload} disabled={!online} aria-label="Reload approvals">
          <Icon name="refresh" />
        </button>
      </div>
      {!online ? (
        <div className="m-banner warn" role="status">
          <Icon name="alert" size={16} /> Approvals need a connection. They are shown again when you are back online.
        </div>
      ) : null}
      <div className="row wrap" role="group" aria-label="Show" style={{ gap: 6 }}>
        {FILTERS.map((f) => (
          <button key={f.key} type="button" className={`btn sm${filter === f.key ? " primary" : ""}`} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
            {f.label}
            {f.key !== "all" && list.data ? ` (${list.data.items.filter((x) => x.kind === f.key).length})` : ""}
          </button>
        ))}
      </div>
      {list.error && !list.data ? <MfgError error={list.error} onRetry={list.reload} /> : null}
      {list.loading && !list.data ? <Spinner /> : null}
      {list.data && !items.length ? (
        <p className="muted" data-testid="m-approvals-empty">
          <Icon name="check" size={14} /> Nothing waits for you.
        </p>
      ) : null}
      <ul className="m-list">
        {items.map((it) => (
          <ApprovalCard key={`${it.kind}-${it.id}-${it.label}`} item={it} online={online} onDone={list.reload} />
        ))}
      </ul>
    </div>
  );
}

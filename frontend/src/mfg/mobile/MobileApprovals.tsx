/**
 * `/m/approvals` (M6 2, M5 `/mfg/approvals`): what waits for this user's decision - purchase requests (M2),
 * engineering changes (M5), schedule proposals (M3/M4) and suggested overtime (M3). Each item carries the exact
 * requests of its actions (`actions: [{label, method, path, body}]`); the app sends them as the user (session,
 * CSRF, workspace header) with If-Match = the item's `row_version`. An action whose body has an empty `reason` /
 * `note` asks for it first. A schedule proposal can be compared with the published schedule before publishing; a
 * stale-basis answer (409 `APS_RUN_STALE_BASIS`) asks once more and then sends `confirm_stale_basis`.
 * Approvals need the network (fresh data, If-Match); offline the buttons are disabled with the reason.
 */
import { useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import { Icon, type IconName } from "../../components/Icon";
import { compareApsRuns, getPublishedRun } from "../api/clientM3";
import { listApprovals, requestPath, runApprovalAction } from "../api/clientM6";
import type { Permission } from "../api/typesM2";
import type { ApprovalAction, ApprovalItem, ApprovalKind } from "../api/typesM6";
import { MfgError, Spinner } from "../components/Feedback";
import { needsText, PERMISSION_ROLES, useAccess } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { errorText, isConflict, useLoad } from "../lib/useMfg";
import { mobileLink } from "./MobileAlerts";
import { useOnline } from "./MobileLayout";

const KIND: Record<ApprovalKind, { label: string; icon: IconName }> = {
  pr: { label: "Purchase request", icon: "briefcase" },
  eco: { label: "Engineering change", icon: "refresh" },
  replan_proposal: { label: "Schedule proposal", icon: "calendar" },
  overtime: { label: "Suggested overtime", icon: "clock" },
};

const FILTERS: { key: ApprovalKind | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pr", label: "Purchasing" },
  { key: "eco", label: "Changes" },
  { key: "replan_proposal", label: "Schedules" },
  { key: "overtime", label: "Overtime" },
];

/** The text field an action needs (`reason` for PR reject, `note` for ECO reject), if its body has it empty. */
function textField(a: ApprovalAction): "reason" | "note" | null {
  for (const k of ["reason", "note"] as const) if (k in (a.body ?? {}) && !String(a.body[k] ?? "").trim()) return k;
  return null;
}

const isNegative = (a: ApprovalAction) => /reject|decline/i.test(a.label) || /\/reject$/.test(a.path);

type Outcome = { tone: "ok" | "danger"; text: string } | null;

function ProposalCompare({ runId }: { runId: string }) {
  const cmp = useLoad(async (signal) => {
    const pub = await getPublishedRun(signal).catch(() => null);
    if (!pub) return null;
    return compareApsRuns(pub.id, runId, signal);
  }, [runId]);
  if (cmp.loading && !cmp.data)
    return (
      <p className="muted small" role="status" style={{ margin: 0 }}>
        <span className="spinner" aria-hidden /> Comparing…
      </p>
    );
  if (cmp.error) return <MfgError error={cmp.error} onRetry={cmp.reload} title="Could not compare" />;
  if (!cmp.data) return <p className="muted small" style={{ margin: 0 }}>There is no published schedule to compare with.</p>;
  const t = cmp.data.tradeoff;
  const kpis = cmp.data.kpis.slice(0, 5);
  const mins = (m: number) => (Math.abs(m) >= 1440 ? `${(m / 1440).toFixed(1)} days` : Math.abs(m) >= 60 ? `${(m / 60).toFixed(1)} h` : `${Math.round(m)} min`);
  return (
    <div className="col" style={{ gap: 6 }} data-testid="m-proposal-compare">
      {t ? (
        <dl className="m-dl">
          <dt>Late demand lines</dt>
          <dd>{t.late_demand_saved > 0 ? `${t.late_demand_saved} fewer` : t.late_demand_saved < 0 ? `${-t.late_demand_saved} more` : "same"}</dd>
          <dt>Lateness</dt>
          <dd>{t.late_minutes_saved > 0 ? `${mins(t.late_minutes_saved)} less` : t.late_minutes_saved < 0 ? `${mins(-t.late_minutes_saved)} more` : "same"}</dd>
          <dt>Overtime</dt>
          <dd>{t.overtime_hours_added ? `${t.overtime_hours_added.toFixed(1)} h more (cost ${Math.round(t.overtime_cost_added).toLocaleString()})` : "no change"}</dd>
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
                <th scope="row" style={{ fontWeight: 500 }}>
                  {k.key.replace(/_/g, " ")}
                </th>
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
  const k = KIND[item.kind] ?? { label: item.kind, icon: "flag" as IconName };
  const perm = item.permission as Permission;
  const allowed = perm in PERMISSION_ROLES && access.can(perm);
  const [busy, setBusy] = useState<string | null>(null);
  const [out, setOut] = useState<Outcome>(null);
  const [asking, setAsking] = useState<ApprovalAction | null>(null);
  const [text, setText] = useState("");
  const [showCompare, setShowCompare] = useState(false);
  const [stale, setStale] = useState<ApprovalAction | null>(null);
  const blocked = !online ? "Needs a connection: approvals always use the latest data." : !allowed ? needsText(perm) : null;
  const to = mobileLink(item.link);
  const actions = item.actions.filter((a) => requestPath(a) !== null);

  const send = async (a: ApprovalAction, extra: Record<string, unknown> = {}) => {
    setBusy(a.label);
    setOut(null);
    const field = textField(a);
    const body = { ...(a.body ?? {}), ...(field ? { [field]: text.trim() } : {}), ...extra };
    try {
      await runApprovalAction(a, item.row_version, body, `appr-${item.kind}-${item.id}-${a.label}-${Date.now()}`.slice(0, 120));
      setOut({ tone: "ok", text: item.kind === "overtime" ? "Accepted. A new schedule with this overtime is being made; publish it when it is ready." : `${a.label}: done.` });
      setAsking(null);
      setStale(null);
      window.setTimeout(onDone, 1500);
    } catch (e) {
      if (e instanceof ApiError && e.code === "APS_RUN_STALE_BASIS") {
        setStale(a);
        setOut({ tone: "danger", text: "Another schedule was published after this proposal was made. Publishing it anyway changes work already planned for the floor." });
      } else setOut({ tone: "danger", text: isConflict(e) ? "This changed since the list was loaded. Reload the list and check it again." : errorText(e) });
    } finally {
      setBusy(null);
    }
  };

  const click = (a: ApprovalAction) => {
    if (textField(a)) {
      setAsking(a);
      setText("");
    } else void send(a);
  };

  const done = out?.tone === "ok";
  return (
    <li className="m-card" data-testid="m-approval" data-kind={item.kind} data-id={item.id}>
      <span className="muted small m-state">
        <Icon name={k.icon} size={14} /> {k.label}
        {item.number && item.kind !== "overtime" ? ` · ${item.number}` : ""}
      </span>
      <div className="row" style={{ justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
        <strong>{item.title}</strong>
        {item.waiting_since ? <span className="muted small nowrap">since {new Date(item.waiting_since).toLocaleDateString()}</span> : null}
      </div>
      {item.summary ? <p style={{ margin: 0 }}>{item.summary}</p> : null}
      {item.kind === "replan_proposal" ? (
        <>
          <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={showCompare} onClick={() => setShowCompare((v) => !v)} disabled={!online} data-testid="m-proposal-compare-btn">
            <Icon name={showCompare ? "chevron-down" : "compare"} /> Compare with the published schedule
          </button>
          {showCompare ? <ProposalCompare runId={item.id} /> : null}
        </>
      ) : null}
      {asking ? (
        <div className="col" style={{ gap: 6 }}>
          <label htmlFor={`appr-text-${item.kind}-${item.id}`} className="small" style={{ fontWeight: 600 }}>
            {textField(asking) === "reason" ? "Reason" : "Note"} (required)
          </label>
          <textarea id={`appr-text-${item.kind}-${item.id}`} className="textarea" rows={2} value={text} onChange={(e) => setText(e.target.value)} data-testid="m-approval-reason" />
        </div>
      ) : null}
      {!done ? (
        <div className="m-actions">
          {asking ? (
            <>
              <button type="button" className={`btn ${isNegative(asking) ? "danger" : "primary"}`} disabled={Boolean(blocked) || busy !== null || !text.trim()} onClick={() => void send(asking)} data-testid="m-approval-text-confirm">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name={isNegative(asking) ? "x" : "check"} />} {asking.label}
              </button>
              <button type="button" className="btn ghost" onClick={() => setAsking(null)}>
                Cancel
              </button>
            </>
          ) : stale ? (
            <>
              <button type="button" className="btn primary" disabled={Boolean(blocked) || busy !== null} onClick={() => void send(stale, { confirm_stale_basis: true })} data-testid="m-approval-stale-confirm">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="flag" />} Publish anyway
              </button>
              <button type="button" className="btn ghost" onClick={() => { setStale(null); setOut(null); }}>
                Cancel
              </button>
            </>
          ) : (
            actions.map((a, i) => (
              <button
                key={a.label}
                type="button"
                className={`btn${i === 0 && !isNegative(a) ? " primary" : ""}`}
                disabled={Boolean(blocked) || busy !== null}
                onClick={() => click(a)}
                data-testid={`m-approval-action-${i}`}
                data-label={a.label}
              >
                {busy === a.label ? <span className="spinner" aria-hidden /> : <Icon name={isNegative(a) ? "x" : "check"} />} {a.label}
              </button>
            ))
          )}
          {to ? (
            <Link to={to} className="btn ghost">
              Details
            </Link>
          ) : null}
        </div>
      ) : null}
      {blocked && !done ? (
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
          <ApprovalCard key={`${it.kind}-${it.id}`} item={it} online={online} onDone={list.reload} />
        ))}
      </ul>
    </div>
  );
}

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
import { PageHeader } from "../../../components/PageHeader";
import { t as tr } from "../../../lib/i18n";
import { DataTable } from "../../components/DataTable";
import type { Column } from "../../components/VirtualTable";

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
      <PageHeader
        title={tr("mfg.replanPage.title.replanning")}
        actions={
          <>
            {published.data ? (
            <Link className="btn" to={mfgPaths.apsRun(published.data.id)}>
            Published: schedule #{published.data.run_no}
            </Link>
            ) : (
            <span className="muted">No published schedule yet</span>
            )}
          </>
        }
      />
      <div className="banner" data-testid="replan-policy" data-policy={policy}>
        <Icon name="info" />
        <div>
          <strong>{policy === "notify" ? "Notify only" : policy === "auto_whatif" ? "Automatic proposals" : "Automatic publish"}</strong> {POLICY_TEXT[policy]}{" "}
          <Link to={mfgPaths.settings()}>Change in plant settings</Link>
        </div>
      </div>
      <MfgError error={error ?? triggers.error} onRetry={triggers.reload} />

      <section className="card card-table">
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
        <DataTable
          rows={rows}
          columns={[
            {
              key: "sel",
              header: <span className="sr-only">Select</span>,
              label: "Select",
              width: "40px",
              align: "center",
              hideable: false,
              exportValue: () => "",
              render: (x) =>
                x.status === "open" ? (
                  <input
                    type="checkbox"
                    className="vt-check"
                    aria-label={`Select ${TRIGGER[x.kind]?.label ?? x.kind}`}
                    checked={sel.has(x.id)}
                    onChange={() =>
                      setSel((cur) => {
                        const n = new Set(cur);
                        if (n.has(x.id)) n.delete(x.id);
                        else n.add(x.id);
                        return n;
                      })
                    }
                  />
                ) : null,
            },
            {
              key: "what",
              header: "What",
              width: "minmax(170px, 1fr)",
              sortValue: (x) => TRIGGER[x.kind]?.label ?? x.kind,
              exportValue: (x) => `${TRIGGER[x.kind]?.label ?? x.kind} (${x.severity})`,
              render: (x) => (
                <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                  <span className={`badge ${SEV_TONE[x.severity] ?? "info"}`}>
                    <Icon name={TRIGGER[x.kind]?.icon ?? "alert"} /> {TRIGGER[x.kind]?.label ?? x.kind}
                  </span>
                  <span className="faint small">{x.severity}</span>
                </span>
              ),
            },
            {
              key: "details",
              header: "Details",
              width: "minmax(240px, 2.5fr)",
              wrap: true,
              exportValue: (x) => x.message,
              render: (x) => (
                <span>
                  {x.message}
                  {triggerLink(x) ? (
                    <>
                      {" "}
                      <Link to={triggerLink(x)!} className="small">
                        Open
                      </Link>
                    </>
                  ) : null}
                </span>
              ),
            },
            { key: "when", header: "When", width: "150px", sortValue: (x) => x.detected_at, render: (x) => clock.dateTime(x.detected_at) },
            {
              key: "status",
              header: "Status",
              width: "minmax(130px, 1fr)",
              sortValue: (x) => x.status,
              exportValue: (x) => x.status,
              render: (x) =>
                x.status === "attached" && x.aps_run_id ? (
                  <Link to={mfgPaths.apsRun(x.aps_run_id)}>in a proposal</Link>
                ) : x.status === "open" ? (
                  "open"
                ) : (
                  `${x.status}${x.handled_at ? ` ${clock.dateTime(x.handled_at)}` : ""}`
                ),
            },
            ...(canManage
              ? [
                  {
                    key: "actions",
                    header: <span className="sr-only">Actions</span>,
                    label: "Actions",
                    width: "160px",
                    exportValue: () => "",
                    render: (x: ReplanTrigger) =>
                      x.status === "open" || x.status === "attached" ? (
                        <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                          <button type="button" className="btn sm" onClick={() => setClosing({ t: x, action: "handle" })} data-testid="trigger-handle">
                            {tr("mfg.replanPage.btn.handled")}
                          </button>
                          <button type="button" className="btn sm ghost" onClick={() => setClosing({ t: x, action: "ignore" })} data-testid="trigger-ignore">
                            {tr("mfg.replanPage.btn.ignore")}
                          </button>
                        </span>
                      ) : null,
                  } as Column<ReplanTrigger>,
                ]
              : []),
          ]}
          rowKey={(x) => x.id}
          label="What changed"
          testId="trigger-table"
          loading={triggers.loading && !rows.length}
          exportName="replanning-changes"
          rowExtras={(x) => ({ testId: "trigger-row", data: { kind: x.kind, status: x.status, severity: x.severity } })}
          empty="Nothing changed since the plan was published."
          card={{ title: "what", status: "status", actions: "sel", fields: ["details", "when"] }}
        />
      </section>

      <section className="card card-table">
        <div className="card-header">
          <h2>Proposals</h2>
        </div>
        <DataTable
          rows={proposals}
          columns={[
            {
              key: "run",
              header: "Run",
              width: "minmax(240px, 2fr)",
              sortValue: (r) => r.run_no,
              exportValue: (r) => `Schedule #${r.run_no} · ${r.label}`,
              render: (r) => (
                <span className="row" style={{ gap: 6, flexWrap: "nowrap", minWidth: 0 }}>
                  <Link to={mfgPaths.apsRun(r.id)} className="mfg-ellipsis">
                    Schedule #{r.run_no} · {r.label}
                  </Link>
                  <PolicyBadge policy={r.policy} />
                </span>
              ),
            },
            { key: "status", header: "Status", width: "150px", sortValue: (r) => r.status, exportValue: (r) => r.status, render: (r) => <ApsStatusChip run={r} /> },
            { key: "started", header: "Started", width: "150px", sortValue: (r) => r.started_at ?? r.finished_at, render: (r) => clock.dateTime(r.started_at ?? r.finished_at) },
            {
              key: "actions",
              header: <span className="sr-only">Actions</span>,
              label: "Actions",
              width: "220px",
              exportValue: () => "",
              render: (r) =>
                published.data && r.status === "completed" ? (
                  <Link className="btn sm" to={mfgPaths.apsCompare(r.id, published.data.id)}>
                    <Icon name="compare" /> {tr("mfg.replanPage.btn.compareWithPublished")}
                  </Link>
                ) : null,
            },
          ]}
          rowKey={(r) => r.id}
          label="Proposals"
          testId="replan-proposals"
          exportName="replanning-proposals"
          rowExtras={() => ({ testId: "replan-proposal" })}
          empty="No proposals. Make one from the open changes above."
        />
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
              <Icon name="check" size={12} /> {tr("mfg.replanPage.btn.seen")}
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

/**
 * Capacity load (M3 12, 9.2): per stage (or the lines of one stage) and day/week, scheduled minutes against
 * regular (base) and optional/opened capacity, with the MRP-required minutes as a marker (rough-cut overload
 * before scheduling). A bar opens the Gantt of that stage and period. Numbers are in the bar's label and title,
 * not only in the colour.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { getApsLoad } from "../../api/clientM3";
import type { LoadRow } from "../../api/typesM3";
import { MfgError, Spinner } from "../../components/Feedback";
import { addDays, fmtDate } from "../../lib/format";
import { mfgPaths } from "../../lib/paths";
import { useLoad } from "../../lib/useMfg";
import { useApsRun } from "./ApsRunShell";

const H = 90;

export function utilPct(r: LoadRow): number {
  const cap = r.base_minutes + r.opened_minutes;
  return cap > 0 ? (100 * r.scheduled_minutes) / cap : r.scheduled_minutes > 0 ? 999 : 0;
}

export function ApsLoadTab() {
  const { run } = useApsRun();
  const navigate = useNavigate();
  const [bucket, setBucket] = useState<"day" | "week">("day");
  const [group, setGroup] = useState("");
  const load = useLoad((signal) => getApsLoad(run.id, { bucket, group_id: group || undefined }, signal), [run.id, bucket, group]);
  const rows = load.data?.items ?? [];

  const series = useMemo(() => {
    const m = new Map<string, { key: string; label: string; groupId: string; lineId: string | null; rows: LoadRow[] }>();
    for (const r of rows) {
      const lineLevel = Boolean(group);
      if (lineLevel ? !r.line : r.line) continue;
      const key = lineLevel ? r.line!.id : r.group.id;
      if (!m.has(key)) m.set(key, { key, label: lineLevel ? r.line!.code : `${r.group.code} · ${r.group.name}`, groupId: r.group.id, lineId: lineLevel ? r.line!.id : null, rows: [] });
      m.get(key)!.rows.push(r);
    }
    for (const s of m.values()) s.rows.sort((a, b) => (a.day < b.day ? -1 : 1));
    return [...m.values()];
  }, [rows, group]);
  const groups = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of rows) m.set(r.group.id, `${r.group.code} · ${r.group.name}`);
    return [...m.entries()];
  }, [rows]);

  return (
    <div className="col gap-lg" data-testid="aps-load">
      <div className="toolbar mfg-filters">
        <div className="row" role="group" aria-label="Period">
          {(["day", "week"] as const).map((b) => (
            <button key={b} type="button" className={`btn sm${bucket === b ? " primary" : ""}`} aria-pressed={bucket === b} onClick={() => setBucket(b)}>
              {b === "day" ? "Days" : "Weeks"}
            </button>
          ))}
        </div>
        <div className="field">
          <label htmlFor="ld-group">Show</label>
          <select id="ld-group" className="select sm" value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">All stages</option>
            {groups.map(([id, label]) => (
              <option key={id} value={id}>
                Lines of {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="pg-legend">
        <span>
          <span className="pg-swatch" style={{ background: "var(--bar)" }} /> scheduled
        </span>
        <span>
          <span className="pg-swatch" style={{ border: "1px solid var(--text-muted)" }} /> regular capacity
        </span>
        <span>
          <span className="pg-swatch" style={{ border: "1px dashed var(--warn)" }} /> optional (overtime) capacity
        </span>
        <span>
          <span className="pg-swatch" style={{ borderTop: "3px solid var(--danger)" }} /> required by MRP dates
        </span>
        <span>"!" over regular capacity</span>
      </div>
      <MfgError error={load.error} onRetry={load.reload} />
      {load.loading && !load.data ? <Spinner /> : null}
      {series.length === 0 && load.data ? <p className="muted">No load in this run.</p> : null}
      {series.map((s) => {
        const max = Math.max(1, ...s.rows.map((r) => Math.max(r.base_minutes + r.optional_minutes, r.scheduled_minutes, r.required_minutes)));
        return (
          <section key={s.key} className="card" data-testid="load-series" data-group={s.label}>
            <div className="card-header">
              <h3>{s.label}</h3>
            </div>
            <div className="card-body" style={{ overflowX: "auto" }}>
              <div className="row" style={{ gap: 3, alignItems: "flex-end", flexWrap: "nowrap", height: H + 22 }}>
                {s.rows.map((r) => {
                  const u = utilPct(r);
                  const capH = ((r.base_minutes) / max) * H;
                  const optH = ((r.base_minutes + r.optional_minutes) / max) * H;
                  const schH = (r.scheduled_minutes / max) * H;
                  const reqH = (r.required_minutes / max) * H;
                  const over = r.scheduled_minutes > r.base_minutes + 1e-6;
                  const to = bucket === "day" ? addDays(r.day, 1) : addDays(r.day, 7);
                  const label = `${fmtDate(r.day)}: ${Math.round(r.scheduled_minutes / 60)} h scheduled of ${Math.round(r.base_minutes / 60)} h regular${r.optional_minutes ? ` (+${Math.round(r.optional_minutes / 60)} h optional${r.opened_minutes ? `, ${Math.round(r.opened_minutes / 60)} h opened` : ""})` : ""}; MRP needs ${Math.round(r.required_minutes / 60)} h; ${Math.round(u)}% busy`;
                  return (
                    <button
                      key={r.day}
                      type="button"
                      className="mfg-load-col"
                      title={label}
                      aria-label={label}
                      onClick={() => navigate(mfgPaths.apsGantt(run.id, { view: "line", group: s.groupId, line: s.lineId ?? undefined, from: r.day, to }))}
                      data-testid="load-bar"
                      data-group={s.label.split(" · ")[0]}
                      data-util={Math.round(u)}
                      data-day={r.day}
                    >
                      <span className="mfg-load-area" style={{ height: H }}>
                        <span className="mfg-load-opt" style={{ height: optH }} />
                        <span className="mfg-load-cap" style={{ height: capH }} />
                        <span className={`mfg-load-sch${over ? " over" : ""}`} style={{ height: schH }} />
                        {r.required_minutes ? <span className="mfg-load-req" style={{ bottom: reqH }} /> : null}
                      </span>
                      <span className="mfg-load-lbl">
                        {over ? "!" : ""}
                        {Math.round(u)}%
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}

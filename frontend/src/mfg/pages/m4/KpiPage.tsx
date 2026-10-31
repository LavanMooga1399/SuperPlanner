/**
 * `/mfg/kpis` (M4 9, 12, #222/#223): dashboard tiles (OTD, utilisation, OEE-lite, WIP, setup time, schedule
 * adherence, first-pass yield) with an 8-week trend sparkline, drill-down to stage/line, top scrap and downtime
 * reasons, worst adherence lines and the per-operation adherence list. Definitions are shown under each tile so the
 * numbers are not jargon.
 */
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listGroups, listLines } from "../../api/client";
import { getAdherence, getKpis } from "../../api/clientM4";
import type { AdherenceRow, KpiResponse, RatioKey } from "../../api/typesM4";
import { MfgError, Spinner } from "../../components/Feedback";
import { DOWNTIME } from "../../floor/floorText";
import { addDays } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";

interface TileDef {
  key: RatioKey | "wip" | "setup";
  testId: string;
  label: string;
  help: string;
  fmt: "pct" | "count" | "minutes";
}

const TILES: TileDef[] = [
  { key: "otd", testId: "otd", label: "On-time delivery", help: "Demand lines shipped in full on or before the due date, of those due.", fmt: "pct" },
  { key: "utilisation", testId: "util", label: "Utilisation", help: "Setup and run time recorded on the floor, of the regular shift time (planned stops excluded).", fmt: "pct" },
  { key: "oee", testId: "oee", label: "OEE (simplified)", help: "Availability x speed against standard x first-pass yield.", fmt: "pct" },
  { key: "wip", testId: "wip", label: "Work in progress", help: "Released or running work orders: count, value and average age.", fmt: "count" },
  { key: "setup", testId: "setup", label: "Setup time", help: "Actual changeover time and count, against the published plan.", fmt: "minutes" },
  { key: "adherence", testId: "adherence", label: "Schedule adherence", help: "Operations started near their planned start and finished by the planned end, of those planned.", fmt: "pct" },
  { key: "fpy", testId: "fpy", label: "First-pass yield", help: "Units passing the inspection steps without rework, of those entering.", fmt: "pct" },
];

const PERIODS = [
  { key: "7", label: "Last 7 days", days: 7 },
  { key: "30", label: "Last 30 days", days: 30 },
  { key: "90", label: "Last 90 days", days: 90 },
];

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(v >= 0.995 || v === 0 ? 0 : 1)}%`);
/** "SOLDER_BRIDGE" -> "Solder bridge" */
const scrapLabel = (code: string) => (code ? code.charAt(0).toUpperCase() + code.slice(1).toLowerCase().replace(/_/g, " ") : "Unspecified");
const hours = (m: number) => `${(m / 60).toFixed(m < 600 ? 1 : 0)} h`;

function Sparkline({ values, label }: { values: (number | null)[]; label: string }) {
  const pts = values.map((v, i) => ({ v, i })).filter((p): p is { v: number; i: number } => p.v !== null && Number.isFinite(p.v));
  if (pts.length < 2) return <span className="faint small">no trend yet</span>;
  const W = 120;
  const H = 30;
  const min = Math.min(...pts.map((p) => p.v));
  const max = Math.max(...pts.map((p) => p.v));
  const span = max - min || 1;
  const x = (i: number) => (i / Math.max(1, values.length - 1)) * (W - 4) + 2;
  const y = (v: number) => H - 3 - ((v - min) / span) * (H - 6);
  const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label} trend over the last ${values.length} weeks`} className="kpi-spark">
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={1.6} />
      <circle cx={x(last.i)} cy={y(last.v)} r={2.5} fill="var(--accent)" />
    </svg>
  );
}

export function KpiPage() {
  const clock = usePlantClock();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "30";
  const dim = (params.get("dim") ?? "plant") as "plant" | "group" | "line";
  const dimId = params.get("id") ?? "";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  const today = clock.day(new Date().toISOString());
  const days = PERIODS.find((p) => p.key === period)?.days ?? 30;
  const from = addDays(today, -(days - 1));
  const groups = useLoad((signal) => listGroups({}, signal), []);
  const lines = useLoad((signal) => listLines({}, signal), []);
  const k = useLoad((signal) => getKpis({ from, to: today, dim, dim_id: dimId || undefined, bucket: "day" }, signal), [from, today, dim, dimId]);
  // trend: 8 weeks by week, same dimension
  const trend = useLoad((signal) => getKpis({ from: addDays(today, -55), to: today, dim, dim_id: dimId || undefined, bucket: "week" }, signal), [today, dim, dimId]);
  const names = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of groups.data?.items ?? []) m.set(g.id, g.code);
    for (const l of lines.data?.items ?? []) m.set(l.id, l.code);
    return m;
  }, [groups.data, lines.data]);
  const d = k.data;

  return (
    <div className="col gap-lg" data-testid="kpi-page">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>KPIs</h1>
        <div className="toolbar">
          <div className="row" role="group" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p.key} type="button" className={`btn sm${period === p.key ? " primary" : ""}`} aria-pressed={period === p.key} onClick={() => set("period", p.key)}>
                {p.label}
              </button>
            ))}
          </div>
          <select
            className="select sm"
            aria-label="Scope"
            value={dim === "plant" ? "" : `${dim}:${dimId}`}
            onChange={(e) => {
              const [a, b] = e.target.value.split(":");
              setParams((prev) => {
                const n = new URLSearchParams(prev);
                if (!a) {
                  n.delete("dim");
                  n.delete("id");
                } else {
                  n.set("dim", a);
                  n.set("id", b);
                }
                return n;
              });
            }}
            data-testid="kpi-scope"
          >
            <option value="">Whole plant</option>
            <optgroup label="Stages">
              {(groups.data?.items ?? []).map((g) => (
                <option key={g.id} value={`group:${g.id}`}>
                  {g.code} · {g.name}
                </option>
              ))}
            </optgroup>
            <optgroup label="Lines">
              {(lines.data?.items ?? []).map((l) => (
                <option key={l.id} value={`line:${l.id}`}>
                  {l.code}
                </option>
              ))}
            </optgroup>
          </select>
        </div>
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        {d?.period.from ?? from} to {d?.period.to ?? today} ({d?.period.time_zone ?? clock.zoneLabel}); today is live, earlier days are cached.
      </p>
      <MfgError error={k.error} onRetry={k.reload} />
      {k.loading && !d ? <Spinner label="Calculating…" /> : null}
      {d ? (
        <>
          <div className="kpi-tiles">
            {TILES.map((t) => (
              <Tile key={t.key} t={t} d={d} trend={trend.data} />
            ))}
          </div>
          {d.by_dim.length ? (
            <DrillDown
              d={d}
              names={names}
              onPick={(dd, id) =>
                setParams((p) => {
                  const n = new URLSearchParams(p);
                  n.set("dim", dd);
                  n.set("id", id);
                  return n;
                })
              }
            />
          ) : null}
          <div className="grid-2" style={{ alignItems: "start" }}>
            <section className="card">
              <div className="card-header">
                <h2>Top scrap reasons</h2>
              </div>
              <table className="table" data-testid="kpi-top-scrap">
                <tbody>
                  {d.top_scrap.length === 0 ? (
                    <tr>
                      <td className="muted">No scrap recorded.</td>
                    </tr>
                  ) : null}
                  {d.top_scrap.map((s, i) => (
                    <tr key={i}>
                      <td>
                        {scrapLabel(s.reason_code)}
                        {s.operation || s.item_family ? <div className="faint small">{[s.operation, s.item_family].filter(Boolean).join(" · ")}</div> : null}
                      </td>
                      <td className="right">{fmtNum(s.qty)} units</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="card">
              <div className="card-header">
                <h2>Top downtime reasons</h2>
              </div>
              <table className="table" data-testid="kpi-top-downtime">
                <tbody>
                  {d.top_downtime.length === 0 ? (
                    <tr>
                      <td className="muted">No downtime recorded.</td>
                    </tr>
                  ) : null}
                  {d.top_downtime.map((x, i) => (
                    <tr key={i}>
                      <td>
                        {DOWNTIME[x.kind as keyof typeof DOWNTIME]?.label ?? x.kind}
                        {x.reason ? <span className="faint small"> · {x.reason}</span> : null}
                        {x.line ? <div className="faint small">{x.line.code}</div> : null}
                      </td>
                      <td className="right">{fmtDuration(x.minutes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
          {d.worst_adherence_lines.length ? (
            <section className="card">
              <div className="card-header">
                <h2>Lines furthest from the plan</h2>
              </div>
              <table className="table">
                <tbody>
                  {d.worst_adherence_lines.map((w) => (
                    <tr key={w.line.id}>
                      <td>
                        <button
                          type="button"
                          className="btn link"
                          onClick={() =>
                            setParams((p) => {
                              const n = new URLSearchParams(p);
                              n.set("dim", "line");
                              n.set("id", w.line.id);
                              return n;
                            })
                          }
                        >
                          {w.line.code}
                        </button>
                      </td>
                      <td className="right">{pct(w.value)} adherent</td>
                      <td className="right faint">
                        {w.num} of {w.den} operations
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
          {dim === "line" && dimId ? <AdherenceList lineId={dimId} from={from} to={today} /> : null}
        </>
      ) : null}
    </div>
  );
}

function Tile({ t, d, trend }: { t: TileDef; d: KpiResponse; trend: KpiResponse | null }) {
  const m = d.metrics;
  let v: number | null = null;
  let main = "–";
  let sub = "";
  if (t.key === "wip") {
    const w = m.wip;
    v = w ? w.count : null;
    main = w ? fmtNum(w.count) : "–";
    sub = w ? [`value ${fmtNum(Math.round(w.value))}`, w.avg_age_days !== null ? `avg ${w.avg_age_days.toFixed(1)} days old` : ""].filter(Boolean).join(" · ") : "";
  } else if (t.key === "setup") {
    const x = m.setup;
    v = x ? x.actual_minutes : null;
    main = x ? hours(x.actual_minutes) : "–";
    sub = x ? [`${fmtNum(x.changeovers)} changeovers`, x.planned_minutes !== null ? `plan ${hours(x.planned_minutes)}` : ""].filter(Boolean).join(" · ") : "";
  } else {
    const r = m[t.key];
    v = r?.value ?? null;
    main = pct(v);
    if (r?.den && t.key !== "oee") sub = `${fmtNum(r.num)} of ${fmtNum(r.den)}`;
    if (t.key === "oee") sub = `availability ${pct(m.availability?.value)} · speed ${pct(m.performance?.value)} · FPY ${pct(m.fpy?.value)}`;
  }
  const values = (trend?.series?.[t.key] ?? []).map((p) => p.value);
  return (
    <div className="card kpi kpi-tile" data-testid={`kpi-tile-${t.testId}`} data-value={v ?? ""}>
      <div className="kpi-label">{t.label}</div>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div className="kpi-value">{main}</div>
        <Sparkline values={values} label={t.label} />
      </div>
      {sub ? <div className="kpi-sub">{sub}</div> : null}
      <div className="faint small">{t.help}</div>
    </div>
  );
}

function DrillDown({ d, names, onPick }: { d: KpiResponse; names: Map<string, string>; onPick(dim: "group" | "line", id: string): void }) {
  const all: RatioKey[] = ["otd", "utilisation", "availability", "performance", "oee", "adherence", "fpy", "scrap_rate"];
  const keys = all.filter((k) => d.by_dim.some((r) => r[k] !== undefined));
  return (
    <section className="card">
      <div className="card-header">
        <h2>{d.by_dim[0]?.dim === "group" ? "By stage" : "By line"}</h2>
      </div>
      <div className="table-wrap">
        <table className="table" data-testid="kpi-drill">
          <thead>
            <tr>
              <th />
              {keys.map((k) => (
                <th key={k} className="right">
                  {k === "otd" ? "OTD" : k === "oee" ? "OEE" : k === "fpy" ? "FPY" : k === "scrap_rate" ? "Scrap" : k[0].toUpperCase() + k.slice(1)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.by_dim.map((r) => (
              <tr key={r.ref.id}>
                <td>
                  <button type="button" className="btn link" onClick={() => onPick(r.dim, r.ref.id)}>
                    {r.ref.code || names.get(r.ref.id) || r.ref.id}
                  </button>
                </td>
                {keys.map((k) => (
                  <td key={k} className="right">
                    {pct(r[k])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AdherenceList({ lineId, from, to }: { lineId: string; from: string; to: string }) {
  const clock = usePlantClock();
  const data = usePaged<AdherenceRow>((offset, limit, signal) => getAdherence({ from, to, line_id: lineId, limit, offset }, signal), [lineId, from, to]);
  return (
    <section className="card">
      <div className="card-header">
        <h2>Planned against actual</h2>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap">
        <table className="table" data-testid="kpi-adherence">
          <thead>
            <tr>
              <th>Work order / step</th>
              <th>Planned</th>
              <th>Actual</th>
              <th>Start</th>
              <th>End</th>
              <th>On plan?</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.wo_operation_id}>
                <td>
                  <Link to={mfgPaths.workOrder(r.wo.id)} className="mono">
                    {r.wo.number}
                  </Link>{" "}
                  / {r.seq}
                  {r.line ? <span className="faint small"> · {r.line.code}</span> : null}
                </td>
                <td className="small">
                  {clock.dateTime(r.planned_start)} – {clock.time(r.planned_end)}
                </td>
                <td className="small">{r.actual_start ? `${clock.dateTime(r.actual_start)} – ${r.actual_end ? clock.time(r.actual_end) : "running"}` : "not started"}</td>
                <td className="small">{r.start_delta_minutes === null ? "" : `${r.start_delta_minutes > 0 ? "+" : "−"}${fmtDuration(r.start_delta_minutes)}`}</td>
                <td className="small">{r.end_delta_minutes === null ? "" : `${r.end_delta_minutes > 0 ? "+" : "−"}${fmtDuration(r.end_delta_minutes)}`}</td>
                <td>
                  {r.adherent ? (
                    <span className="badge ok">
                      <Icon name="check" /> yes
                    </span>
                  ) : (
                    <span className="badge warn">
                      <Icon name="alert" /> no
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.rows.length < data.total ? (
        <div className="card-footer">
          <button type="button" className="btn sm" onClick={data.onEndReached} disabled={data.loading}>
            Show more ({data.rows.length} of {data.total})
          </button>
        </div>
      ) : null}
    </section>
  );
}

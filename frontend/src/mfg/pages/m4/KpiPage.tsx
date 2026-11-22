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
import { PageHeader } from "../../../components/PageHeader";
import { FilterBar } from "../../../components/FilterBar";
import { DataTable, ShowMore } from "../../components/DataTable";
import type { Column } from "../../components/VirtualTable";

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

type ScrapRow = KpiResponse["top_scrap"][number];
type DowntimeRow = KpiResponse["top_downtime"][number];
const SCRAP_COLS: Column<ScrapRow>[] = [
  {
    key: "reason",
    header: "Reason",
    width: "minmax(160px, 1fr)",
    wrap: true,
    render: (s) => (
      <span>
        {scrapLabel(s.reason_code)}
        {s.operation || s.item_family ? <span className="faint small"> · {[s.operation, s.item_family].filter(Boolean).join(" · ")}</span> : null}
      </span>
    ),
  },
  { key: "qty", header: "Scrapped", width: "112px", align: "right", render: (s) => `${fmtNum(s.qty)} ${s.qty === 1 ? "unit" : "units"}` },
];
const DOWNTIME_COLS: Column<DowntimeRow>[] = [
  {
    key: "reason",
    header: "Reason",
    width: "minmax(160px, 1fr)",
    wrap: true,
    render: (x) => (
      <span>
        {DOWNTIME[x.kind as keyof typeof DOWNTIME]?.label ?? x.kind}
        {x.reason ? <span className="faint small"> · {x.reason}</span> : null}
        {x.line ? <span className="faint small"> · {x.line.code}</span> : null}
      </span>
    ),
  },
  { key: "minutes", header: "Lost time", width: "112px", align: "right", render: (x) => fmtDuration(x.minutes) },
];

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
      <PageHeader title="KPIs" />
      <FilterBar>
        <div className="field">
          <span className="field-label" id="kpi-period-label">
            Period
          </span>
          <div className="btn-group" role="group" aria-labelledby="kpi-period-label">
            {PERIODS.map((p) => (
              <button key={p.key} type="button" className="btn" aria-pressed={period === p.key} onClick={() => set("period", p.key)}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <label htmlFor="kpi-scope">Scope</label>
          <select
            id="kpi-scope"
            className="select"
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
      </FilterBar>
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
            <section className="card card-table">
              <div className="card-header">
                <h2>Top scrap reasons</h2>
              </div>
              <DataTable
                rows={d.top_scrap}
                columns={SCRAP_COLS}
                rowKey={(_, i) => i}
                label="Top scrap reasons"
                testId="kpi-top-scrap"
                columnSettings={false}
                empty="No scrap recorded."
              />
            </section>
            <section className="card card-table">
              <div className="card-header">
                <h2>Top downtime reasons</h2>
              </div>
              <DataTable
                rows={d.top_downtime}
                columns={DOWNTIME_COLS}
                rowKey={(_, i) => i}
                label="Top downtime reasons"
                testId="kpi-top-downtime"
                columnSettings={false}
                empty="No downtime recorded."
              />
            </section>
          </div>
          {d.worst_adherence_lines.length ? (
            <section className="card card-table">
              <div className="card-header">
                <h2>Lines furthest from the plan</h2>
              </div>
              <DataTable
                rows={d.worst_adherence_lines}
                columns={[
                  {
                    key: "line",
                    header: "Line",
                    width: "minmax(140px, 1fr)",
                    sortValue: (w) => w.line.code,
                    render: (w) => (
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
                    ),
                  },
                  { key: "value", header: "Adherence", width: "120px", align: "right", sortValue: (w) => w.value, render: (w) => pct(w.value) },
                  { key: "ops", header: "Operations on plan", width: "180px", align: "right", sortValue: (w) => w.den, render: (w) => `${fmtNum(w.num)} of ${fmtNum(w.den)}` },
                ]}
                rowKey={(w) => w.line.id}
                label="Lines furthest from the plan"
                tableId="kpi-worst-lines"
                columnSettings={false}
              />
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
  const isGroup = d.by_dim[0]?.dim === "group";
  type Row = KpiResponse["by_dim"][number];
  const name = (r: Row) => r.ref.code || names.get(r.ref.id) || r.ref.id;
  const columns: Column<Row>[] = [
    {
      key: "ref",
      header: isGroup ? "Stage" : "Line",
      width: "minmax(140px, 1fr)",
      sortValue: name,
      render: (r) => (
        <button type="button" className="btn link" onClick={() => onPick(r.dim, r.ref.id)}>
          {name(r)}
        </button>
      ),
    },
    ...keys.map(
      (k): Column<Row> => ({
        key: k,
        header: k === "otd" ? "OTD" : k === "oee" ? "OEE" : k === "fpy" ? "FPY" : k === "scrap_rate" ? "Scrap" : k[0].toUpperCase() + k.slice(1),
        width: "112px",
        align: "right",
        sortValue: (r) => r[k] ?? null,
        render: (r) => pct(r[k]),
      }),
    ),
  ];
  return (
    <section className="card card-table">
      <div className="card-header">
        <h2>{isGroup ? "By stage" : "By line"}</h2>
      </div>
      <DataTable rows={d.by_dim} columns={columns} rowKey={(r) => r.ref.id} label={isGroup ? "KPIs by stage" : "KPIs by line"} testId="kpi-drill" exportName="kpis-by-line" card={{ title: "ref", fields: keys.slice(0, 4) }} />
    </section>
  );
}

function AdherenceList({ lineId, from, to }: { lineId: string; from: string; to: string }) {
  const clock = usePlantClock();
  const data = usePaged<AdherenceRow>((offset, limit, signal) => getAdherence({ from, to, line_id: lineId, limit, offset }, signal), [lineId, from, to]);
  const delta = (m: number | null) => (m === null ? "" : `${m > 0 ? "+" : "−"}${fmtDuration(m)}`);
  const columns: Column<AdherenceRow>[] = [
    {
      key: "wo",
      header: "Work order / step",
      width: "minmax(180px, 1.2fr)",
      sortValue: (r) => `${r.wo.number}/${String(r.seq).padStart(4, "0")}`,
      render: (r) => (
        <span>
          <Link to={mfgPaths.workOrder(r.wo.id)} className="mono">
            {r.wo.number}
          </Link>{" "}
          / {r.seq}
          {r.line ? <span className="faint small"> · {r.line.code}</span> : null}
        </span>
      ),
    },
    { key: "planned", header: "Planned", width: "minmax(170px, 1fr)", sortValue: (r) => r.planned_start, render: (r) => `${clock.dateTime(r.planned_start)} – ${clock.time(r.planned_end)}` },
    {
      key: "actual",
      header: "Actual",
      width: "minmax(170px, 1fr)",
      sortValue: (r) => r.actual_start,
      render: (r) => (r.actual_start ? `${clock.dateTime(r.actual_start)} – ${r.actual_end ? clock.time(r.actual_end) : "running"}` : "not started"),
    },
    { key: "start", header: "Start", width: "96px", align: "right", sortValue: (r) => r.start_delta_minutes, render: (r) => delta(r.start_delta_minutes) },
    { key: "end", header: "End", width: "96px", align: "right", sortValue: (r) => r.end_delta_minutes, render: (r) => delta(r.end_delta_minutes) },
    {
      key: "ok",
      header: "On plan?",
      width: "96px",
      sortValue: (r) => (r.adherent ? 1 : 0),
      exportValue: (r) => (r.adherent ? "yes" : "no"),
      render: (r) =>
        r.adherent ? (
          <span className="badge ok">
            <Icon name="check" /> yes
          </span>
        ) : (
          <span className="badge warn">
            <Icon name="alert" /> no
          </span>
        ),
    },
  ];
  return (
    <section className="card card-table">
      <div className="card-header">
        <h2>Planned against actual</h2>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <DataTable
        rows={data.rows}
        columns={columns}
        rowKey={(r) => r.wo_operation_id}
        label="Planned against actual"
        testId="kpi-adherence"
        totalCount={data.total}
        loading={data.loading}
        exportName="schedule-adherence"
        empty="No planned operations on this line in the period."
        footer={<ShowMore shown={data.rows.length} total={data.total} noun="operations" loading={data.loading} onMore={data.onEndReached} />}
        card={{ title: "wo", status: "ok", fields: ["planned", "start", "end"] }}
      />
    </section>
  );
}

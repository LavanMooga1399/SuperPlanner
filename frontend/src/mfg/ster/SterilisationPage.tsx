/**
 * Sterilisation `/mfg/sterilisation` (M8 8, 12): EtO load planning. Chamber timeline (each load = sterilisation
 * cycle, then aeration, then the release wait until the planned release date), pallets in aeration over time,
 * loads awaiting QA release, and the load panel with its members and the floor steps (load -> cycle -> aeration
 * -> awaiting release). Release is a signed QA action (M7 policy `ster_load.release`, SignatureDialog); a failed load
 * keeps the sterility holds and opens one NCR for all lots.
 */
import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { Legend } from "../../finance/charts/Legend";
import { niceTicks, useWidth } from "../../finance/charts/scales";
import { plural, t } from "../../lib/i18n";
import { formatDay, formatNumber } from "../../lib/locale";
import { advanceSterLoad, failSterLoad, listSterLoads, loadSterLoad, planSterLoads, releaseSterLoad } from "../api/clientM8";
import type { SterAdvanceTo, SterLoad, SterMember, SterStatus } from "../api/typesM8";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { usePlantClock } from "../lib/plantTime";
import { setSearchParam } from "../lib/usePaged";
import { errorCode, useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { ReasonConfirm } from "../forecast/ForecastPage";
import { codeText, Facts, ItemById, num, Segmented, SterChip } from "../forecast/shared";

const HOUR = 3600000;
const DAY = 24 * HOUR;
const ACTIVE: SterStatus[] = ["planned", "loaded", "cycling", "aerating", "awaiting_release"];
type View = "active" | "awaiting_release" | "all";

/** The next floor step of a load (8): planned -> loaded (batch load) -> cycling -> aerating -> awaiting release. */
const NEXT: Partial<Record<SterStatus, { to: SterAdvanceTo | "load"; label: "plan.ster.btn.load" | "plan.ster.btn.cycle" | "plan.ster.btn.aerate" | "plan.ster.btn.aerated" }>> = {
  planned: { to: "load", label: "plan.ster.btn.load" },
  loaded: { to: "cycling", label: "plan.ster.btn.cycle" },
  cycling: { to: "aerating", label: "plan.ster.btn.aerate" },
  aerating: { to: "awaiting_release", label: "plan.ster.btn.aerated" },
};

export function SterilisationPage() {
  const [params, setParams] = useSearchParams();
  const view = (["awaiting_release", "all"].includes(params.get("view") ?? "") ? params.get("view") : "active") as View;
  const canPlan = useCan("ster_plan");
  const clock = usePlantClock();
  useEffect(() => {
    document.title = t("plan.ster.title");
  }, []);
  // every load from a week back (the list is short by nature; pages of 200 up to 1,000 loads)
  const loads = useLoad(async (s) => {
    const from = new Date(Date.now() - 7 * DAY).toISOString().slice(0, 10);
    const first = await listSterLoads({ from, limit: 200 }, s);
    const items = [...first.items];
    while (items.length < Math.min(first.total, 1000)) {
      const next = await listSterLoads({ from, limit: 200, offset: items.length }, s);
      if (!next.items.length) break;
      items.push(...next.items);
    }
    return { ...first, items };
  }, []);
  const all = loads.data?.items ?? [];
  const shown = all.filter((l) => (view === "all" ? true : view === "active" ? ACTIVE.includes(l.status) : l.status === "awaiting_release"));
  const awaiting = all.filter((l) => l.status === "awaiting_release");
  const selId = params.get("load") ?? "";
  const sel = all.find((l) => l.id === selId) ?? null;
  const [planning, setPlanning] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const plan = async () => {
    setPlanning(true);
    setErr(null);
    try {
      const r = await planSterLoads({ days: 30 });
      toast(t("plan.ster.toast.planned", { n: plural(r.loads, t("plan.noun.load"), t("plan.noun.loads")), p: formatNumber(r.pallets), w: r.warnings.length }));
      loads.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setPlanning(false);
    }
  };
  const columns = useMemo<Column<SterLoad>[]>(
    () => [
      { key: "number", header: t("plan.ster.head.load"), width: "110px", sortValue: (l) => l.number, render: (l) => <span className="mono">{l.number}</span> },
      { key: "status", header: t("plan.ster.head.status"), width: "170px", exportValue: (l) => l.status, render: (l) => <SterChip s={l.status} /> },
      { key: "chamber", header: t("plan.ster.head.chamber"), width: "100px", sortValue: (l) => l.chamber_code, render: (l) => <span className="mono">{l.chamber_code ?? ""}</span> },
      { key: "cycle", header: t("plan.ster.head.cycle"), width: "100px", drop: 2, render: (l) => <span className="mono">{l.cycle_code}</span> },
      { key: "pallets", header: t("plan.ster.head.pallets"), width: "80px", align: "right", sortValue: (l) => l.pallets, render: (l) => <span className="pl-num">{l.pallets}</span> },
      { key: "start", header: t("plan.ster.head.start"), width: "150px", sortValue: (l) => l.planned_start, render: (l) => clock.dateTime(l.actual_start ?? l.planned_start) },
      { key: "aer", header: t("plan.ster.head.aerEnd"), width: "150px", drop: 1, sortValue: (l) => l.aeration_end, render: (l) => clock.dateTime(l.actual_aeration_end ?? l.aeration_end) },
      { key: "release", header: t("plan.ster.head.release"), width: "120px", sortValue: (l) => l.release_due, render: (l) => formatDay(l.release_due) },
      { key: "flags", header: t("plan.fc.head.flags"), width: "minmax(120px, 1fr)", drop: 3, exportValue: (l) => l.flags.join(" "), render: (l) => (l.flags.length ? <span className="mfg-ellipsis small">{l.flags.map(codeText).join(", ")}</span> : null) },
    ],
    [clock],
  );
  return (
    <div className="col gap-lg" data-testid="ster-page">
      <PageHeader
        title={t("plan.ster.title")}
        description={t("plan.ster.desc")}
        facts={loads.data ? [[t("plan.ster.fact.active"), formatNumber(all.filter((l) => ACTIVE.includes(l.status)).length)], [t("plan.ster.fact.awaiting"), formatNumber(awaiting.length)]] : []}
        actions={
          <button type="button" className="btn primary" disabled={!canPlan || planning} title={canPlan ? t("plan.ster.hint.plan") : needsText("ster_plan")} onClick={() => void plan()} data-testid="ster-plan">
            {planning ? <span className="spinner" aria-hidden /> : <Icon name="calendar" />} {t("plan.ster.btn.plan")}
          </button>
        }
      />
      <MfgError error={err} />
      <MfgError error={loads.error} onRetry={loads.reload} />
      {loads.loading && !loads.data ? <Spinner /> : null}
      {loads.data ? (
        <>
          <section className="card" aria-labelledby="ster-tl-h">
            <div className="card-header pl-card-header">
              <h2 className="pl-h2" id="ster-tl-h">{t("plan.ster.tl.title")}</h2>
              <Segmented<View>
                label={t("plan.ster.label.view")}
                value={view}
                testId="ster-view"
                onChange={(v) => setSearchParam(setParams, "view", v === "active" ? "" : v)}
                options={[
                  { value: "active", label: t("plan.ster.view.active") },
                  { value: "awaiting_release", label: t("plan.ster.view.awaiting") },
                  { value: "all", label: t("plan.label.all") },
                ]}
              />
            </div>
            <div className="card-body">
              {shown.length ? <ChamberTimeline loads={shown} selected={selId} onSelect={(id) => setSearchParam(setParams, "load", id)} /> : <p className="muted" style={{ margin: 0 }}>{t("plan.ster.empty")}</p>}
            </div>
          </section>
          <div className="pl-two">
            <section className="card card-table" aria-label={t("plan.ster.aw.title")}>
              <div className="card-header pl-card-header">
                <h2 className="pl-h2">{t("plan.ster.aw.title")}</h2>
                <span className="muted small">{t("plan.ster.aw.hint")}</span>
              </div>
              <AwaitingList loads={awaiting} onChanged={loads.reload} onSelect={(id) => setSearchParam(setParams, "load", id)} />
            </section>
            <section className="card">
              <div className="card-header pl-card-header">
                <h2 className="pl-h2">{t("plan.ster.aer.title")}</h2>
              </div>
              <div className="card-body">
                <AerationChart loads={all.filter((l) => l.status !== "cancelled" && l.status !== "failed")} />
              </div>
            </section>
          </div>
          {sel ? <LoadPanel key={sel.id + sel.row_version} load={sel} onChanged={loads.reload} onClose={() => setSearchParam(setParams, "load", "")} /> : null}
          <section className="card card-table" aria-label={t("plan.ster.list")}>
            <DataTable<SterLoad>
              rows={shown}
              columns={columns}
              rowKey={(l) => l.id}
              label={t("plan.ster.list")}
              testId="ster-loads"
              exportName="sterilisation-loads"
              onRowClick={(l) => setSearchParam(setParams, "load", l.id)}
              onActivate={(l) => setSearchParam(setParams, "load", l.id)}
              rowExtras={(l) => ({ testId: "ster-load-row", className: l.id === selId ? "mfg-selected" : undefined, data: { status: l.status, load: l.number } })}
              empty={t("plan.ster.empty")}
            />
          </section>
        </>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- chamber timeline
const ROW_H = 34;
const LEFT = 90;

function ChamberTimeline({ loads, selected, onSelect }: { loads: SterLoad[]; selected: string; onSelect(id: string): void }) {
  const clock = usePlantClock();
  const [ref, width] = useWidth<HTMLDivElement>(900);
  const [hover, setHover] = useState<SterLoad | null>(null);
  const chambers = [...new Set(loads.map((l) => l.chamber_code ?? l.chamber_line_id))].sort();
  const t0 = Math.floor(Math.min(...loads.map((l) => Date.parse(l.actual_start ?? l.planned_start))) / DAY) * DAY;
  const t1 = Math.ceil(Math.max(...loads.map((l) => Math.max(Date.parse(l.aeration_end), Date.parse(`${l.release_due}T23:59:00Z`)))) / DAY) * DAY;
  const span = Math.max(DAY, t1 - t0);
  const innerW = Math.max(200, width - LEFT - 10);
  const x = (ms: number) => LEFT + ((ms - t0) / span) * innerW;
  const H = chambers.length * ROW_H + 26;
  const days = Math.round(span / DAY);
  const every = Math.max(1, Math.ceil(days / Math.max(2, Math.floor(innerW / 70))));
  const ticks: number[] = [];
  for (let d = 0; d <= days; d += every) ticks.push(t0 + d * DAY);
  const now = Date.now();
  const keyNav = (e: KeyboardEvent<SVGGElement>, l: SterLoad) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(l.id);
    }
  };
  return (
    <figure className="pl-chart" data-testid="ster-timeline">
      <div ref={ref} className="pl-chart-area" style={{ overflowX: "auto" }}>
        <svg width={width} height={H} role="group" aria-label={t("plan.ster.tl.aria", { n: loads.length, c: chambers.length })}>
          <defs>
            <pattern id="pl-aer" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="var(--info-soft)" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--info)" strokeWidth="1.5" />
            </pattern>
          </defs>
          {ticks.map((ms) => (
            <g key={ms}>
              <line x1={x(ms)} x2={x(ms)} y1={0} y2={H - 20} stroke="var(--grid)" />
              <text x={x(ms) + 3} y={H - 6} className="pl-axis">{formatDay(new Date(ms).toISOString().slice(0, 10)).replace(/ \d{4}$/, "")}</text>
            </g>
          ))}
          {now > t0 && now < t1 ? <line x1={x(now)} x2={x(now)} y1={0} y2={H - 20} stroke="var(--accent)" strokeDasharray="3 3" /> : null}
          {chambers.map((c, i) => (
            <g key={c}>
              <text x={6} y={i * ROW_H + 20} className="pl-axis mono pl-tl-label">{c}</text>
              <line x1={LEFT} x2={LEFT + innerW} y1={(i + 1) * ROW_H} y2={(i + 1) * ROW_H} stroke="var(--grid)" />
            </g>
          ))}
          {loads.map((l) => {
            const row = chambers.indexOf(l.chamber_code ?? l.chamber_line_id);
            const y = row * ROW_H + 6;
            const s = Date.parse(l.actual_start ?? l.planned_start);
            const e = Date.parse(l.actual_end ?? l.planned_end);
            const a = Date.parse(l.actual_aeration_end ?? l.aeration_end);
            const r = Date.parse(`${l.release_due}T12:00:00Z`);
            const on = l.id === selected;
            const label = t("plan.ster.tl.barAria", { n: l.number, status: t(`plan.ster.status.${l.status === "awaiting_release" ? "awaitingRelease" : l.status}` as "plan.ster.status.planned"), p: l.pallets, s: clock.dateTime(l.planned_start), a: clock.dateTime(l.aeration_end), r: formatDay(l.release_due) });
            const failed = l.status === "failed";
            return (
              <g key={l.id} tabIndex={0} role="button" aria-label={label} aria-pressed={on} className="pl-tl-load" onClick={() => onSelect(l.id)} onKeyDown={(ev) => keyNav(ev, l)} onMouseEnter={() => setHover(l)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(l)} onBlur={() => setHover(null)} data-testid="ster-tl-load" data-status={l.status}>
                {r > a && l.status !== "released" ? <line x1={x(a)} x2={x(r)} y1={y + 11} y2={y + 11} stroke="var(--warn)" strokeWidth={2} strokeDasharray="2 3" /> : null}
                {r > a && l.status !== "released" ? <path d={`M${x(r)},${y + 5}l5,6l-5,6l-5,-6z`} fill="var(--warn)" /> : null}
                <rect x={x(e)} y={y} width={Math.max(2, x(a) - x(e))} height={22} fill="url(#pl-aer)" stroke="var(--info)" rx={3} />
                <rect x={x(s)} y={y} width={Math.max(3, x(e) - x(s))} height={22} rx={3} fill={failed ? "var(--danger)" : l.status === "released" ? "var(--ok)" : "var(--bar)"} stroke={on ? "var(--text)" : "none"} strokeWidth={2} />
                {x(a) - x(s) > 70 ? (
                  <text x={x(s) + 4} y={y + 15} className="pl-tl-text">{`${l.number} · ${l.pallets}`}</text>
                ) : null}
                {failed ? <text x={x(s) + 2} y={y - 1} className="pl-axis">✕</text> : null}
              </g>
            );
          })}
        </svg>
        {hover ? (
          <div className="pl-tip" role="status" style={{ left: Math.min(x(Date.parse(hover.planned_start)) + 10, width - 240), top: chambers.indexOf(hover.chamber_code ?? hover.chamber_line_id) * ROW_H + 32 }}>
            <div className="pl-tip-title">{`${hover.number} · ${hover.cycle_code}`}</div>
            <div className="pl-tip-row"><span>{t("plan.ster.head.status")}</span><span><SterChip s={hover.status} /></span></div>
            <div className="pl-tip-row"><span>{t("plan.ster.head.pallets")}</span><span>{hover.pallets}</span></div>
            <div className="pl-tip-row"><span>{t("plan.ster.lg.cycle")}</span><span>{`${clock.time(hover.planned_start)}–${clock.time(hover.planned_end)}`}</span></div>
            <div className="pl-tip-row"><span>{t("plan.ster.head.aerEnd")}</span><span>{clock.dateTime(hover.aeration_end)}</span></div>
            <div className="pl-tip-row"><span>{t("plan.ster.head.release")}</span><span>{formatDay(hover.release_due)}</span></div>
            {hover.flags.length ? <div className="small">{hover.flags.map(codeText).join(", ")}</div> : null}
          </div>
        ) : null}
      </div>
      <figcaption className="pl-gantt-legend">
        <span><span className="pl-lg-bar" aria-hidden /> {t("plan.ster.lg.cycle")}</span>
        <span><span className="pl-lg-aer" aria-hidden /> {t("plan.ster.lg.aeration")}</span>
        <span><span className="pl-lg-wait" aria-hidden /> {t("plan.ster.lg.wait")}</span>
        <span><span className="pl-lg-bar ok" aria-hidden /> {t("plan.ster.lg.released")}</span>
        <span><span className="pl-lg-bar danger" aria-hidden /> {t("plan.ster.lg.failed")}</span>
      </figcaption>
    </figure>
  );
}

// ---------------------------------------------------------------- aeration
const AH = 170;
const AM = { l: 44, r: 10, t: 10, b: 22 };

/** Pallets in aeration over time (step area), from each load's cycle end to its aeration end; the peak is marked. */
function AerationChart({ loads }: { loads: SterLoad[] }) {
  const [ref, width] = useWidth<HTMLDivElement>(420);
  const pts = useMemo(() => {
    const ev: [number, number][] = [];
    for (const l of loads) {
      ev.push([Date.parse(l.actual_end ?? l.planned_end), l.pallets]);
      ev.push([Date.parse(l.actual_aeration_end ?? l.aeration_end), -l.pallets]);
    }
    ev.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const out: { at: number; v: number }[] = [];
    let v = 0;
    for (const [at, d] of ev) {
      v += d;
      if (out.length && out[out.length - 1].at === at) out[out.length - 1].v = v;
      else out.push({ at, v });
    }
    return out;
  }, [loads]);
  if (pts.length < 2) return <p className="muted" style={{ margin: 0 }}>{t("plan.ster.aer.empty")}</p>;
  const t0 = pts[0].at;
  const t1 = pts[pts.length - 1].at;
  const peak = pts.reduce((m, p) => (p.v > m.v ? p : m), pts[0]);
  const innerW = width - AM.l - AM.r;
  const innerH = AH - AM.t - AM.b;
  const ticks = niceTicks(0, Math.max(1, peak.v), 3);
  const top = ticks[ticks.length - 1] || 1;
  const x = (ms: number) => AM.l + ((ms - t0) / Math.max(1, t1 - t0)) * innerW;
  const y = (v: number) => AM.t + innerH - (v / top) * innerH;
  let d = `M${x(t0)},${y(0)}`;
  let prev = 0;
  for (const p of pts) {
    d += `L${x(p.at).toFixed(1)},${y(prev).toFixed(1)}L${x(p.at).toFixed(1)},${y(p.v).toFixed(1)}`;
    prev = p.v;
  }
  d += `L${x(t1)},${y(0)}Z`;
  const days = Math.max(1, Math.round((t1 - t0) / DAY));
  const every = Math.max(1, Math.ceil(days / Math.max(2, Math.floor(innerW / 70))));
  const aria = t("plan.ster.aer.aria", { peak: peak.v, at: formatDay(new Date(peak.at).toISOString().slice(0, 10)) });
  return (
    <figure className="pl-chart" data-testid="ster-aeration">
      <div ref={ref} className="pl-chart-area">
        <svg width={width} height={AH} role="img" aria-label={aria}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={AM.l} x2={AM.l + innerW} y1={y(v)} y2={y(v)} stroke="var(--grid)" />
              <text x={AM.l - 6} y={y(v) + 3} textAnchor="end" className="pl-axis">{formatNumber(v)}</text>
            </g>
          ))}
          {Array.from({ length: Math.floor(days / every) + 1 }, (_, i) => Math.floor(t0 / DAY) * DAY + i * every * DAY)
            .filter((ms) => ms >= t0)
            .map((ms) => (
              <text key={ms} x={x(ms)} y={AH - 6} textAnchor="middle" className="pl-axis">{formatDay(new Date(ms).toISOString().slice(0, 10)).replace(/ \d{4}$/, "")}</text>
            ))}
          <path d={d} fill="url(#pl-aer2)" stroke="var(--info)" strokeWidth={1.5} />
          <defs>
            <pattern id="pl-aer2" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="var(--info-soft)" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--info)" strokeWidth="1" />
            </pattern>
          </defs>
          <circle cx={x(peak.at)} cy={y(peak.v)} r={3.5} fill="var(--info)" />
          <text x={Math.min(x(peak.at) + 6, AM.l + innerW - 90)} y={y(peak.v) - 4} className="pl-axis">{t("plan.ster.aer.peak", { n: peak.v })}</text>
        </svg>
      </div>
      <figcaption>
        <Legend label={t("plan.chart.legend")} items={[{ label: t("plan.ster.aer.series"), color: "var(--info-soft)", kind: "box" }]} />
      </figcaption>
      <p className="sr-only">{aria}</p>
    </figure>
  );
}

// ---------------------------------------------------------------- awaiting release, load panel, actions
/** Readable texts of the sterilisation 409s (R6); other errors use the shared error banner. */
function SterError({ error }: { error: unknown }) {
  const code = errorCode(error);
  if (code === "STER_AERATION_INCOMPLETE") return <Banner tone="warn" role="alert" title={t("plan.ster.err.aeration")}>{t("plan.ster.err.aerationBody")}</Banner>;
  if (code === "STER_RELEASE_TOO_EARLY") return <Banner tone="warn" role="alert" title={t("plan.ster.err.early")}>{t("plan.ster.err.earlyBody")}</Banner>;
  return <MfgError error={error} />;
}

const todayIso = () => new Date().toISOString().slice(0, 10);

function useLoadActions(onChanged: () => void) {
  const [releasing, setReleasing] = useState<SterLoad | null>(null);
  const [early, setEarly] = useState("");
  const [failing, setFailing] = useState<SterLoad | null>(null);
  const dialogs = (
    <>
      {releasing ? (
        <SignatureDialog<SterLoad>
          title={t("plan.ster.dlg.releaseTitle", { n: releasing.number })}
          recordType="ster_load"
          recordId={releasing.id}
          recordLabel={releasing.number}
          action="release"
          meaning="approved"
          submitLabel={t("plan.ster.btn.signRelease")}
          plainLabel={t("plan.ster.btn.release")}
          commentLabel={t("plan.ster.label.releaseNote")}
          effect={t("plan.ster.dlg.releaseEffect", { n: plural(releasing.members.length, t("plan.noun.lot"), t("plan.noun.lots")) })}
          children={
            releasing.release_due > todayIso() ? (
              <div className="col pl-gap" data-testid="ster-early">
                <Banner tone="warn" title={t("plan.ster.early.title", { d: formatDay(releasing.release_due) })}>{t("plan.ster.early.body")}</Banner>
                <div className="field">
                  <label htmlFor="ster-early-reason">
                    {t("plan.ster.early.label")} <span className="req" aria-hidden>*</span>
                  </label>
                  <textarea id="ster-early-reason" className="textarea" rows={2} maxLength={500} required aria-required value={early} onChange={(e) => setEarly(e.target.value)} data-testid="ster-early-reason" />
                </div>
              </div>
            ) : undefined
          }
          canSubmit={releasing.release_due <= todayIso() || early.trim().length > 0}
          perform={(sig, comment) => releaseSterLoad(releasing, sig, comment, releasing.release_due > todayIso() ? early : null)}
          onDone={(res) => {
            toast(signedToast(res, t("plan.ster.toast.released", { n: releasing.number })));
            setReleasing(null);
            setEarly("");
            onChanged();
          }}
          onClose={() => {
            setReleasing(null);
            setEarly("");
          }}
        />
      ) : null}
      {failing ? (
        <ReasonConfirm
          title={t("plan.ster.dlg.failTitle", { n: failing.number })}
          body={t("plan.ster.dlg.failBody")}
          confirm={t("plan.ster.btn.fail")}
          danger
          onClose={() => setFailing(null)}
          run={async (r) => {
            const l = await failSterLoad(failing, r);
            toast(t("plan.ster.toast.failed", { n: failing.number, ncr: l.ncr_id ? t("plan.ster.toast.ncr") : "" }));
            setFailing(null);
            onChanged();
          }}
        />
      ) : null}
    </>
  );
  return {
    release: (l: SterLoad) => {
      setEarly("");
      setReleasing(l);
    },
    fail: setFailing,
    dialogs,
  };
}

function AwaitingList({ loads, onChanged, onSelect }: { loads: SterLoad[]; onChanged(): void; onSelect(id: string): void }) {
  const canRelease = useCan("ster_release");
  const canFail = useCan("qa_decide");
  const act = useLoadActions(onChanged);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <>
      <DataTable<SterLoad>
        rows={[...loads].sort((a, b) => a.release_due.localeCompare(b.release_due))}
        rowKey={(l) => l.id}
        label={t("plan.ster.aw.title")}
        testId="ster-awaiting"
        columnSettings={false}
        empty={t("plan.ster.aw.empty")}
        onRowClick={(l) => onSelect(l.id)}
        rowExtras={(l) => ({ testId: "ster-awaiting-row", data: { load: l.number } })}
        columns={[
          { key: "number", header: t("plan.ster.head.load"), width: "100px", render: (l) => <span className="mono">{l.number}</span> },
          { key: "lots", header: t("plan.ster.head.lots"), width: "minmax(90px, 1fr)", render: (l) => plural(l.members.length, t("plan.noun.lot"), t("plan.noun.lots")) },
          {
            key: "due",
            header: t("plan.ster.head.release"),
            width: "130px",
            render: (l) =>
              l.release_due < today ? (
                <span className="badge warn"><Icon name="clock" /> {formatDay(l.release_due)}</span>
              ) : (
                formatDay(l.release_due)
              ),
          },
          {
            key: "actions",
            header: "",
            label: t("plan.label.actions"),
            width: "200px",
            render: (l) => (
              <span className="row" style={{ gap: 4 }}>
                <button type="button" className="btn sm primary" disabled={!canRelease} title={canRelease ? undefined : needsText("ster_release")} onClick={(e) => {
                  e.stopPropagation();
                  act.release(l);
                }} data-testid="ster-release">
                  <Icon name="check" /> {t("plan.ster.btn.release")}
                </button>
                <button type="button" className="btn sm" disabled={!canFail} title={canFail ? undefined : needsText("qa_decide")} onClick={(e) => {
                  e.stopPropagation();
                  act.fail(l);
                }} data-testid="ster-fail">
                  {t("plan.ster.btn.fail")}
                </button>
              </span>
            ),
          },
        ]}
      />
      {act.dialogs}
    </>
  );
}

function LoadPanel({ load, onChanged, onClose }: { load: SterLoad; onChanged(): void; onClose(): void }) {
  const clock = usePlantClock();
  const canPlan = useCan("ster_plan");
  const canRelease = useCan("ster_release");
  const canFail = useCan("qa_decide");
  const act = useLoadActions(onChanged);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [cancel, setCancel] = useState(false);
  const [at, setAt] = useState("");
  const reason = useChangeReason();
  const next = NEXT[load.status];
  const atIso = at ? clock.fromLocal(at) : null;
  const atFuture = atIso !== null && Date.parse(atIso) > Date.now() + 60000;
  const nowLocal = clock.toLocal(new Date().toISOString());
  const step = async (to: SterAdvanceTo | "load") => {
    const why = await reason.ask(t("plan.ster.what", { n: load.number }));
    if (why === null) return;
    setBusy(true);
    setErr(null);
    try {
      if (to === "load") await loadSterLoad(load, why);
      else await advanceSterLoad(load, to, to === "cancelled" ? null : atIso, why);
      toast(t("plan.ster.toast.step", { n: load.number }));
      setCancel(false);
      onChanged();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card" data-testid="ster-panel" aria-label={load.number}>
      <div className="card-header pl-card-header">
        <h2 className="pl-h2">
          <span className="mono">{load.number}</span> <SterChip s={load.status} />
        </h2>
        <span className="row" style={{ gap: 6 }}>
          {next && next.to !== "load" ? (
            <span className="pl-at">
              <label htmlFor="ster-at" className="small muted">{t("plan.ster.label.at")}</label>
              <input id="ster-at" className="input" type="datetime-local" max={nowLocal} value={at} aria-invalid={atFuture} onChange={(e) => setAt(e.target.value)} data-testid="ster-at" />
            </span>
          ) : null}
          {next ? (
            <button type="button" className="btn sm primary" disabled={!canPlan || busy || atFuture} title={canPlan ? undefined : needsText("ster_plan")} onClick={() => void step(next.to)} data-testid="ster-next">
              <Icon name="arrow-right" /> {t(next.label)}
            </button>
          ) : null}
          {load.status === "awaiting_release" ? (
            <>
              <button type="button" className="btn sm primary" disabled={!canRelease} onClick={() => act.release(load)}>
                <Icon name="check" /> {t("plan.ster.btn.release")}
              </button>
              <button type="button" className="btn sm" disabled={!canFail} onClick={() => act.fail(load)}>
                {t("plan.ster.btn.fail")}
              </button>
            </>
          ) : null}
          {load.status === "planned" || load.status === "loaded" ? (
            <button type="button" className="btn sm ghost" disabled={!canPlan || busy} onClick={() => setCancel(true)}>
              {t("plan.ster.btn.cancel")}
            </button>
          ) : null}
          <button type="button" className="btn sm ghost icon" aria-label={t("common.close")} onClick={onClose}>
            <Icon name="x" />
          </button>
        </span>
      </div>
      <div className="card-body col pl-gap">
        {atFuture ? <p className="pl-field-err" role="alert"><Icon name="alert" size={12} /> {t("plan.ster.err.future")}</p> : null}
        <SterError error={err} />
        {load.status === "failed" ? (
          <p className="pl-note" style={{ margin: 0 }} data-testid="ster-failed-replan">
            <Icon name="refresh" size={14} /> {t("plan.ster.text.replan")}
            {canPlan ? (
              <button type="button" className="btn sm" disabled={busy} onClick={() => {
                setBusy(true);
                setErr(null);
                planSterLoads({ days: 30 })
                  .then((r) => {
                    toast(t("plan.ster.toast.planned", { n: plural(r.loads, t("plan.noun.load"), t("plan.noun.loads")), p: formatNumber(r.pallets), w: r.warnings.length }));
                    onChanged();
                  })
                  .catch((e: unknown) => setErr(e))
                  .finally(() => setBusy(false));
              }} data-testid="ster-replan">
                {t("plan.ster.btn.plan")}
              </button>
            ) : null}
          </p>
        ) : null}
        {load.ncr_id ? (
          <Banner tone="danger" title={t("plan.ster.text.ncr")}>
            <Link to={mfgPaths.qaNcr(load.ncr_id)}>{t("plan.ster.text.openNcr")}</Link>
          </Banner>
        ) : null}
        <Facts
          rows={[
            [t("plan.ster.head.chamber"), load.chamber_code ?? "–"],
            [t("plan.ster.head.cycle"), load.cycle_code],
            [t("plan.ster.head.pallets"), String(load.pallets)],
            [t("plan.ster.head.start"), clock.dateTime(load.actual_start ?? load.planned_start)],
            [t("plan.ster.fact.cycleEnd"), clock.dateTime(load.actual_end ?? load.planned_end)],
            [t("plan.ster.head.aerEnd"), clock.dateTime(load.actual_aeration_end ?? load.aeration_end)],
            [t("plan.ster.head.release"), formatDay(load.release_due)],
          ]}
        />
        {load.flags.length ? (
          <div className="row wrap" style={{ gap: 6 }}>
            {load.flags.map((f) => (
              <span key={f} className="badge warn"><Icon name="alert" /> {codeText(f)}</span>
            ))}
          </div>
        ) : null}
        <DataTable<SterMember>
          rows={load.members}
          rowKey={(m) => m.id}
          label={t("plan.ster.members")}
          testId="ster-members"
          columnSettings={false}
          columns={[
            { key: "item", header: t("plan.fc.head.item"), width: "minmax(180px, 2fr)", render: (m) => <ItemById id={m.item_id} part={m.part_number} /> },
            { key: "wo", header: t("plan.ster.head.wo"), width: "120px", render: (m) => (m.wo_id ? <Link to={mfgPaths.workOrder(m.wo_id)} className="mono">{m.wo_number ?? m.wo_id}</Link> : <span className="muted">{t("plan.ster.text.ratePlan")}</span>) },
            { key: "lot", header: t("plan.ster.head.lot"), width: "130px", render: (m) => <span className="mono">{m.lot_code ?? "–"}</span> },
            { key: "qty", header: t("plan.ster.head.qty"), width: "110px", align: "right", render: (m) => <span className="pl-num">{num(m.qty)}</span> },
            { key: "pal", header: t("plan.ster.head.pallets"), width: "80px", align: "right", render: (m) => <span className="pl-num">{num(m.pallets, 1)}</span> },
          ]}
        />
      </div>
      {cancel ? (
        <ConfirmDialog title={t("plan.ster.dlg.cancelTitle", { n: load.number })} confirmLabel={t("plan.ster.btn.cancel")} danger busy={busy} onConfirm={() => void step("cancelled")} onCancel={() => setCancel(false)}>
          <p>{t("plan.ster.dlg.cancelBody")}</p>
        </ConfirmDialog>
      ) : null}
      {act.dialogs}
      {reason.dialog}
    </section>
  );
}

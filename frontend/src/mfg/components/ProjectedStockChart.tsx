/**
 * Projected stock of one item (M2 14.2 `ProjectedStockChart`, 8.13): two step lines over exact dates, "existing
 * supply only" (solid; where it drops below zero is the shortage, hatched) and "with planned orders" (dashed),
 * plus per-bucket bars of requirements and supplies. One point per event date (at most ~5,000), drawn as
 * `polyline`s; the shortage area is a single path. Line styles differ by dash pattern, not only by colour.
 */
import { useMemo } from "react";
import type { Bucket, TimelineEvent } from "../api/typesM2";
import { fmtDate } from "../lib/format";
import { fmtNum } from "../lib/formatM2";

const W = 960;
const H = 260;
const PAD_L = 56;
const PAD_R = 12;
const PAD_T = 12;
const LINE_H = 170;
const BAR_TOP = PAD_T + LINE_H + 16;
const BAR_H = 48;
const DAY = 86400000;

const dayOf = (d: string) => Math.round(Date.parse(`${d}T00:00:00Z`) / DAY);

interface Pt {
  day: number;
  existing: number;
  planned: number;
}

function niceTicks(lo: number, hi: number, n = 4): number[] {
  const span = hi - lo || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return out;
}

export function ProjectedStockChart({ timeline, buckets, asOf, uom }: { timeline: TimelineEvent[]; buckets: Bucket[]; asOf: string; uom: string }) {
  const model = useMemo(() => {
    // one point per date: the balances after the last event of that date
    const pts: Pt[] = [];
    for (const e of timeline) {
      const d = dayOf(e.date);
      const last = pts[pts.length - 1];
      if (last && last.day === d) {
        last.existing = e.balance_existing;
        last.planned = e.balance_planned;
      } else pts.push({ day: d, existing: e.balance_existing, planned: e.balance_planned });
    }
    const d0 = Math.min(dayOf(asOf), pts[0]?.day ?? dayOf(asOf), buckets[0] ? dayOf(buckets[0].start) : Infinity);
    const lastDay = Math.max(pts[pts.length - 1]?.day ?? d0, buckets.length ? dayOf(buckets[buckets.length - 1].end) : d0);
    const d1 = Math.max(lastDay + 1, d0 + 7);
    let lo = 0;
    let hi = 0;
    for (const p of pts) {
      lo = Math.min(lo, p.existing, p.planned);
      hi = Math.max(hi, p.existing, p.planned);
    }
    if (hi === lo) hi = lo + 1;
    const padY = (hi - lo) * 0.08;
    lo -= lo < 0 ? padY : 0;
    hi += padY;
    const x = (d: number) => PAD_L + ((d - d0) / (d1 - d0)) * (W - PAD_L - PAD_R);
    const y = (v: number) => PAD_T + (1 - (v - lo) / (hi - lo)) * LINE_H;
    const step = (key: "existing" | "planned") => {
      const out: string[] = [];
      let prev: number | null = null;
      for (const p of pts) {
        const px = x(p.day).toFixed(1);
        if (prev !== null) out.push(`${px},${y(prev).toFixed(1)}`);
        out.push(`${px},${y(p[key]).toFixed(1)}`);
        prev = p[key];
      }
      if (prev !== null) out.push(`${x(d1).toFixed(1)},${y(prev).toFixed(1)}`);
      return out.join(" ");
    };
    // shortage area: every interval where the existing-only balance is below zero
    const zero = y(0);
    let shade = "";
    pts.forEach((p, i) => {
      if (p.existing >= 0) return;
      const xa = x(p.day);
      const xb = x(i + 1 < pts.length ? pts[i + 1].day : d1);
      shade += `M${xa.toFixed(1)} ${zero.toFixed(1)}H${xb.toFixed(1)}V${y(p.existing).toFixed(1)}H${xa.toFixed(1)}Z`;
    });
    let barMax = 1;
    for (const b of buckets) barMax = Math.max(barMax, b.gross, b.existing_supply + b.planned);
    const months: { x: number; label: string }[] = [];
    const dStart = new Date(d0 * DAY);
    const m = new Date(Date.UTC(dStart.getUTCFullYear(), dStart.getUTCMonth() + 1, 1));
    while (m.getTime() / DAY < d1) {
      months.push({ x: x(m.getTime() / DAY), label: fmtDate(m.toISOString().slice(0, 10)).replace(/^1 /, "") });
      m.setUTCMonth(m.getUTCMonth() + 1);
    }
    const firstShort = pts.find((p) => p.existing < 0);
    return { pts, x, y, d1, existing: step("existing"), planned: step("planned"), shade, zero, ticks: niceTicks(lo, hi), barMax, months, firstShort, minExisting: Math.min(0, ...pts.map((p) => p.existing)) };
  }, [timeline, buckets, asOf]);

  const summary = model.firstShort
    ? `Projected stock: short from ${fmtDate(new Date(model.firstShort.day * DAY).toISOString().slice(0, 10))}, lowest ${fmtNum(model.minExisting)} ${uom} without planned orders.`
    : `Projected stock never drops below zero with existing supply.`;

  return (
    <figure className="mfg-chart" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={summary} data-testid="item-plan-chart" data-points={model.pts.length} data-short={model.firstShort ? "true" : "false"}>
        <defs>
          <pattern id="mfg-short-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--danger-soft)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--danger)" strokeWidth="2" />
          </pattern>
        </defs>
        {model.ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W - PAD_R} y1={model.y(t)} y2={model.y(t)} stroke="var(--grid)" />
            <text x={PAD_L - 6} y={model.y(t) + 3} textAnchor="end" className="mfg-week-axis">
              {fmtNum(t)}
            </text>
          </g>
        ))}
        {model.months.map((mo) => (
          <g key={mo.x}>
            <line x1={mo.x} x2={mo.x} y1={PAD_T} y2={BAR_TOP + BAR_H} stroke="var(--grid)" />
            <text x={mo.x + 3} y={H - 4} className="mfg-week-axis">
              {mo.label}
            </text>
          </g>
        ))}
        <line x1={PAD_L} x2={W - PAD_R} y1={model.zero} y2={model.zero} stroke="var(--grid-strong)" strokeWidth={1.5} />
        {model.shade ? <path d={model.shade} fill="url(#mfg-short-hatch)" opacity={0.9} data-testid="item-plan-shortage" /> : null}
        <polyline points={model.planned} fill="none" stroke="var(--ok)" strokeWidth={2} strokeDasharray="6 4" />
        <polyline points={model.existing} fill="none" stroke="var(--accent)" strokeWidth={2} />
        <line x1={model.x(dayOf(asOf))} x2={model.x(dayOf(asOf))} y1={PAD_T} y2={PAD_T + LINE_H} stroke="var(--text-faint)" strokeDasharray="2 3" />
        {buckets.map((b) => {
          const xa = model.x(dayOf(b.start));
          const xb = model.x(dayOf(b.end) + 1);
          const w = Math.max(2, (xb - xa) / 2 - 2);
          const hg = (b.gross / model.barMax) * BAR_H;
          const hs = ((b.existing_supply + b.planned) / model.barMax) * BAR_H;
          return (
            <g key={b.start}>
              <title>{`${fmtDate(b.start)}: needed ${fmtNum(b.gross)}, existing supply ${fmtNum(b.existing_supply)}, planned ${fmtNum(b.planned)}${b.short ? " (short)" : ""}`}</title>
              <rect x={xa + 1} y={BAR_TOP + BAR_H - hg} width={w} height={hg} fill="var(--warn)" />
              <rect x={xa + 1 + w + 1} y={BAR_TOP + BAR_H - hs} width={w} height={hs} fill="none" stroke="var(--ok)" strokeWidth={1.5} />
            </g>
          );
        })}
        <line x1={PAD_L} x2={W - PAD_R} y1={BAR_TOP + BAR_H} y2={BAR_TOP + BAR_H} stroke="var(--grid-strong)" />
      </svg>
      <figcaption className="row wrap small muted" style={{ gap: 14 }}>
        <span className="row" style={{ gap: 4 }}>
          <svg width="26" height="8" aria-hidden>
            <line x1="0" y1="4" x2="26" y2="4" stroke="var(--accent)" strokeWidth="2" />
          </svg>
          With existing supply only (solid)
        </span>
        <span className="row" style={{ gap: 4 }}>
          <svg width="26" height="8" aria-hidden>
            <line x1="0" y1="4" x2="26" y2="4" stroke="var(--ok)" strokeWidth="2" strokeDasharray="6 4" />
          </svg>
          With planned orders (dashed)
        </span>
        <span className="row" style={{ gap: 4 }}>
          <svg width="14" height="10" aria-hidden>
            <rect width="14" height="10" fill="url(#mfg-short-hatch)" />
          </svg>
          Shortage (hatched)
        </span>
        <span className="row" style={{ gap: 4 }}>
          <svg width="10" height="10" aria-hidden>
            <rect width="10" height="10" fill="var(--warn)" />
          </svg>
          Needed per period (filled bar)
        </span>
        <span className="row" style={{ gap: 4 }}>
          <svg width="10" height="10" aria-hidden>
            <rect x="1" y="1" width="8" height="8" fill="none" stroke="var(--ok)" strokeWidth="1.5" />
          </svg>
          Supply per period (outlined bar)
        </span>
        <span>{summary}</span>
      </figcaption>
    </figure>
  );
}

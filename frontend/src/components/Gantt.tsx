/**
 * SVG Gantt timeline (ARCHITECTURE 17.4).
 * - mode "tasks": one row per task, grouped by `group` (collapsible)
 * - mode "resources": one lane per resource; capacity > 1 lanes stack overlapping bars
 * - zoom in px/hour (4, 8, 16, 32, 64), day grid in the plan offset
 * - dependency arrows, deadline markers (red dashed = hard), milestones as diamonds
 * - critical chain outlined, late tasks hatched + "Late" text
 * - non-working time shaded, rows virtualized above 300
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { Dependency, PlacementOut, Problem, Schedule } from "../api/types";
import { closedIntervals, expandWindows, firstMidnight } from "../lib/calendar";
import type { Terms } from "../lib/terms";
import { fmtDuration, isoToMinute, isoToMs, offsetMinutesOf, wallParts } from "../lib/time";
import { Icon } from "./Icon";

export const ZOOM_LEVELS = [4, 8, 16, 32, 64];
export type GanttMode = "tasks" | "resources";

const ROW_H = 30;
const BAR_H = 20;
const HEAD_H = 44;
const LABEL_W = 230;
const VIRTUALIZE_ABOVE = 300;
const OVERSCAN = 12;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

interface BarInfo {
  p: PlacementOut;
  name: string;
  milestone: boolean;
  late: boolean;
  lateHard: boolean;
  critical: boolean;
  violated: boolean;
  locked: boolean;
}

type Row =
  | { kind: "group"; key: string; label: string; count: number; collapsed: boolean; span: [number, number] | null }
  | { kind: "task"; key: string; label: string; bar: BarInfo | null; taskId: string; deadline: { m: number; hard: boolean } | null; resourceId?: string }
  | { kind: "lane"; key: string; label: string; resourceId: string; bars: BarInfo[]; sub: number; subCount: number; capacity: number };

export interface GanttProps {
  schedule: Schedule;
  draft: Problem;
  terms: Terms;
  mode: GanttMode;
  pxPerHour: number;
  showArrows: boolean;
  showShading: boolean;
  selected: string | null;
  onSelect(taskId: string): void;
}

function tierTicks(pxPerHour: number): number {
  if (pxPerHour >= 64) return 60;
  if (pxPerHour >= 32) return 120;
  if (pxPerHour >= 16) return 180;
  if (pxPerHour >= 8) return 360;
  return 0;
}

export function Gantt({ schedule, draft, terms, mode, pxPerHour, showArrows, showShading, selected, onSelect }: GanttProps) {
  const hs = schedule.horizon_start;
  const off = offsetMinutesOf(hs);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [scroll, setScroll] = useState({ top: 0, left: 0, height: 600, width: 1200 });

  const taskById = useMemo(() => new Map(draft.tasks.map((t) => [t.id, t])), [draft.tasks]);
  const resById = useMemo(() => new Map(draft.resources.map((r) => [r.id, r])), [draft.resources]);
  const chain = useMemo(() => new Set(schedule.explanation?.critical_chain ?? []), [schedule.explanation]);
  const hardViolated = useMemo(
    () => new Set(schedule.violations.filter((v) => v.severity === "hard").flatMap((v) => v.task_ids)),
    [schedule.violations],
  );

  const bars = useMemo(() => {
    const m = new Map<string, BarInfo>();
    for (const p of schedule.placements) {
      const t = taskById.get(p.task_id);
      const ex = schedule.explanation?.tasks[p.task_id];
      const status = ex?.deadline_status;
      m.set(p.task_id, {
        p,
        name: t?.name ?? p.task_id,
        milestone: t ? t.type === "milestone" : p.end === p.start,
        late: status === "late_soft" || status === "late_hard",
        lateHard: status === "late_hard",
        critical: chain.has(p.task_id),
        violated: hardViolated.has(p.task_id),
        locked: !!t?.locked,
      });
    }
    return m;
  }, [schedule, taskById, chain, hardViolated]);

  // ---- time range
  const { rangeStart, rangeEnd } = useMemo(() => {
    let lo = 0;
    let hi = 0;
    for (const p of schedule.placements) {
      lo = Math.min(lo, p.start);
      hi = Math.max(hi, p.end);
    }
    for (const t of draft.tasks) {
      if (t.deadline && bars.has(t.id)) {
        const d = isoToMinute(t.deadline, hs);
        if (d > hi && d - hi < 14 * 1440) hi = d;
      }
    }
    const m0 = firstMidnight(hs);
    const start = m0 + Math.floor((lo - m0) / 1440) * 1440;
    const end = m0 + Math.ceil((hi + 60 - m0) / 1440) * 1440;
    return { rangeStart: start, rangeEnd: Math.max(end, start + 1440) };
  }, [schedule.placements, draft.tasks, bars, hs]);

  const pxPerMin = pxPerHour / 60;
  const x = (m: number) => (m - rangeStart) * pxPerMin;
  const chartW = Math.ceil((rangeEnd - rangeStart) * pxPerMin);

  // ---- rows
  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    if (mode === "tasks") {
      const ordered = [...draft.tasks]
        .filter((t) => bars.has(t.id))
        .sort((a, b) => bars.get(a.id)!.p.start - bars.get(b.id)!.p.start || a.id.localeCompare(b.id));
      // tasks in schedule but no longer in the plan
      const extra = schedule.placements.filter((p) => !taskById.has(p.task_id));
      const missing = draft.tasks.filter((t) => !bars.has(t.id));
      const hasGroups = draft.tasks.some((t) => t.group);
      const pushTask = (id: string, label: string) => {
        const t = taskById.get(id);
        out.push({
          kind: "task",
          key: `t-${id}`,
          label,
          bar: bars.get(id) ?? null,
          taskId: id,
          deadline: t?.deadline ? { m: isoToMinute(t.deadline, hs), hard: t.deadline_hard } : null,
        });
      };
      if (hasGroups) {
        const groups = new Map<string, string[]>();
        for (const t of ordered) {
          const g = t.group ?? "";
          if (!groups.has(g)) groups.set(g, []);
          groups.get(g)!.push(t.id);
        }
        for (const [g, ids] of groups) {
          const key = g || "__none";
          const isCol = collapsed.has(key);
          let span: [number, number] | null = null;
          for (const id of ids) {
            const b = bars.get(id)!;
            span = span ? [Math.min(span[0], b.p.start), Math.max(span[1], b.p.end)] : [b.p.start, b.p.end];
          }
          out.push({ kind: "group", key, label: g ? `${terms.group} ${g}` : `No ${terms.groupL}`, count: ids.length, collapsed: isCol, span });
          if (!isCol) for (const id of ids) pushTask(id, taskById.get(id)!.name);
        }
      } else {
        for (const t of ordered) pushTask(t.id, t.name);
      }
      for (const p of extra) pushTask(p.task_id, `${p.task_id} (removed)`);
      for (const t of missing) pushTask(t.id, `${t.name} (not scheduled)`);
    } else {
      const byRes = new Map<string, BarInfo[]>();
      for (const b of bars.values()) for (const r of b.p.resource_ids) {
        if (!byRes.has(r)) byRes.set(r, []);
        byRes.get(r)!.push(b);
      }
      const resIds = [...draft.resources.map((r) => r.id), ...[...byRes.keys()].filter((r) => !resById.has(r))];
      for (const rid of resIds) {
        const list = (byRes.get(rid) ?? []).sort((a, b) => a.p.start - b.p.start);
        // Greedy interval colouring into sub-rows.
        const subEnds: number[] = [];
        const assign = new Map<BarInfo, number>();
        for (const b of list) {
          let k = subEnds.findIndex((e) => e <= b.p.start);
          if (k === -1) {
            k = subEnds.length;
            subEnds.push(b.p.end);
          } else subEnds[k] = b.p.end;
          assign.set(b, k);
        }
        const subCount = Math.max(1, subEnds.length);
        const r = resById.get(rid);
        for (let s = 0; s < subCount; s++) {
          out.push({
            kind: "lane",
            key: `r-${rid}-${s}`,
            label: s === 0 ? (r?.name ?? rid) : "",
            resourceId: rid,
            bars: list.filter((b) => assign.get(b) === s),
            sub: s,
            subCount,
            capacity: r?.capacity ?? 1,
          });
        }
      }
      // Tasks without resources (milestones, free tasks)
      const free = [...bars.values()].filter((b) => b.p.resource_ids.length === 0).sort((a, b) => a.p.start - b.p.start);
      if (free.length) {
        out.push({ kind: "group", key: "__free", label: `Without ${terms.resourceL}`, count: free.length, collapsed: collapsed.has("__free"), span: null });
        if (!collapsed.has("__free"))
          for (const b of free) {
            const t = taskById.get(b.p.task_id);
            out.push({ kind: "task", key: `f-${b.p.task_id}`, label: b.name, bar: b, taskId: b.p.task_id, deadline: t?.deadline ? { m: isoToMinute(t.deadline, hs), hard: t.deadline_hard } : null });
          }
      }
    }
    return out;
  }, [mode, draft.tasks, draft.resources, bars, collapsed, taskById, resById, schedule.placements, terms, hs]);

  // ---- virtualization
  const totalH = rows.length * ROW_H;
  const virtual = rows.length > VIRTUALIZE_ABOVE;
  const first = virtual ? Math.max(0, Math.floor(scroll.top / ROW_H) - OVERSCAN) : 0;
  const last = virtual ? Math.min(rows.length, Math.ceil((scroll.top + scroll.height) / ROW_H) + OVERSCAN) : rows.length;
  const visibleRows = rows.slice(first, last).map((r, i) => ({ r, idx: first + i }));

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const update = () => setScroll({ top: el.scrollTop, left: el.scrollLeft, height: el.clientHeight, width: el.clientWidth });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Keep the left edge roughly in place in time when zooming.
  const prevZoom = useRef(pxPerHour);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || prevZoom.current === pxPerHour) return;
    const ratio = pxPerHour / prevZoom.current;
    el.scrollLeft = el.scrollLeft * ratio;
    prevZoom.current = pxPerHour;
  }, [pxPerHour]);

  // Scroll the selected bar into view.
  useEffect(() => {
    if (!selected) return;
    const el = scrollRef.current?.querySelector<SVGGElement>(`[data-testid="gantt-bar-${CSS.escape(selected)}"]`);
    el?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selected]);

  // Row index of each task (first occurrence) for arrows.
  const rowOfTask = useMemo(() => {
    const m = new Map<string, number>();
    rows.forEach((r, i) => {
      if (r.kind === "task" && r.bar && !m.has(r.taskId)) m.set(r.taskId, i);
      if (r.kind === "lane") for (const b of r.bars) if (!m.has(b.p.task_id)) m.set(b.p.task_id, i);
    });
    return m;
  }, [rows]);

  // ---- header ticks
  const days: number[] = [];
  for (let m = rangeStart; m < rangeEnd; m += 1440) days.push(m);
  const tickStep = tierTicks(pxPerHour);
  const h0 = isoToMs(hs);
  const dayLabel = (m: number) => {
    const p = wallParts(h0 + (m + 1) * 60000, off);
    return pxPerHour >= 8 ? `${DAYS[p.weekday]} ${p.day} ${MONTHS[p.month]}` : `${DAYS[p.weekday].slice(0, 2)} ${p.day}`;
  };

  // ---- shading per lane / per task row (closed time of the assigned resources)
  const closedByRes = useMemo(() => {
    const m = new Map<string, Array<[number, number]>>();
    if (!showShading) return m;
    for (const r of draft.resources) {
      if (!r.calendar) continue;
      m.set(r.id, closedIntervals(expandWindows(r.calendar, hs, rangeStart, rangeEnd), rangeStart, rangeEnd));
    }
    return m;
  }, [draft.resources, hs, rangeStart, rangeEnd, showShading]);

  const onBarKey = (e: KeyboardEvent, id: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(id);
    }
  };

  const seenTestIds = new Set<string>();
  const renderBar = (b: BarInfo, y: number) => {
    const id = b.p.task_id;
    const testId = seenTestIds.has(id) ? undefined : `gantt-bar-${id}`;
    seenTestIds.add(id);
    const x1 = x(b.p.start);
    const w = Math.max(2, x(b.p.end) - x1);
    const top = y + (ROW_H - BAR_H) / 2;
    const isSel = selected === id;
    const label = `${b.name}: ${fmtDuration(b.p.end - b.p.start)}${b.late ? ", Late" : ""}${b.critical ? ", on critical chain" : ""}${b.violated ? ", has a rule violation" : ""}${b.locked ? ", fixed" : ""}`;
    const textInside = w > 60;
    const fill = b.violated ? "var(--danger)" : b.late ? "var(--warn)" : b.critical ? "var(--bar-crit)" : "var(--bar)";
    if (b.milestone) {
      const cx = x1;
      const cy = y + ROW_H / 2;
      return (
        <g key={`${id}-${y}`} className={`gantt-bar${isSel ? " selected" : ""}`} tabIndex={0} role="button" aria-label={label} data-testid={testId} data-task-id={id} onClick={() => onSelect(id)} onKeyDown={(e) => onBarKey(e, id)}>
          <title>{label}</title>
          <path className="bar-rect" d={`M${cx},${cy - 9} L${cx + 9},${cy} L${cx},${cy + 9} L${cx - 9},${cy} Z`} fill={b.late ? "var(--warn)" : "var(--text)"} />
          <text x={cx + 13} y={cy + 4} fontSize={11.5} fill="var(--text)">
            {b.name}
            {b.late ? " · Late" : ""}
          </text>
        </g>
      );
    }
    return (
      <g key={`${id}-${y}`} className={`gantt-bar${isSel ? " selected" : ""}`} tabIndex={0} role="button" aria-label={label} data-testid={testId} data-task-id={id} data-late={b.late || undefined} onClick={() => onSelect(id)} onKeyDown={(e) => onBarKey(e, id)}>
        <title>{label}</title>
        <rect className="bar-rect" x={x1} y={top} width={w} height={BAR_H} rx={4} fill={fill} stroke={b.critical ? "var(--text)" : "none"} strokeWidth={b.critical ? 1.5 : 0} />
        {b.late ? <rect x={x1} y={top} width={w} height={BAR_H} rx={4} fill="url(#gantt-hatch)" pointerEvents="none" /> : null}
        {b.violated ? <rect x={x1 - 2} y={top - 2} width={w + 4} height={BAR_H + 4} rx={5} fill="none" stroke="var(--danger)" strokeDasharray="4 3" strokeWidth={1.5} /> : null}
        {textInside ? (
          <>
            <clipPath id={`clip-${id}-${y}`}>
              <rect x={x1 + 4} y={top} width={w - 8} height={BAR_H} />
            </clipPath>
            <text x={x1 + 6} y={top + 14} fontSize={11.5} fill="var(--bar-text)" clipPath={`url(#clip-${id}-${y})`} fontWeight={500}>
              {b.late ? "Late · " : ""}
              {b.name}
            </text>
          </>
        ) : (
          <text x={x1 + w + 12} y={top + 14} fontSize={11} fill="var(--text-muted)">
            {b.late ? "Late · " : ""}
            {b.name}
          </text>
        )}
      </g>
    );
  };

  const arrows = useMemo(() => {
    if (!showArrows) return [] as Array<{ d: Dependency; path: string; critical: boolean }>;
    const out: Array<{ d: Dependency; path: string; critical: boolean }> = [];
    for (const d of draft.dependencies) {
      const a = bars.get(d.predecessor);
      const b = bars.get(d.successor);
      const ra = rowOfTask.get(d.predecessor);
      const rb = rowOfTask.get(d.successor);
      if (!a || !b || ra === undefined || rb === undefined) continue;
      if (virtual && ((ra < first && rb < first) || (ra >= last && rb >= last))) continue;
      const fromEnd = d.type === "FS" || d.type === "FF";
      const toStart = d.type === "FS" || d.type === "SS";
      const x1 = x(fromEnd ? a.p.end : a.p.start);
      const x2 = x(toStart ? b.p.start : b.p.end);
      const y1 = ra * ROW_H + ROW_H / 2;
      const y2 = rb * ROW_H + ROW_H / 2;
      let path: string;
      if (x2 - x1 >= 14) {
        const mx = x1 + 7;
        path = `M${x1},${y1} H${mx} V${y2} H${x2 - 2}`;
      } else {
        const ymid = y1 + (y2 >= y1 ? ROW_H / 2 : -ROW_H / 2);
        path = `M${x1},${y1} H${x1 + 7} V${ymid} H${x2 - 9} V${y2} H${x2 - 2}`;
      }
      out.push({ d, path, critical: chain.has(d.predecessor) && chain.has(d.successor) });
    }
    return out;
  }, [showArrows, draft.dependencies, bars, rowOfTask, virtual, first, last, chain]); // eslint-disable-line react-hooks/exhaustive-deps

  const nowMin = Math.floor((Date.now() - h0) / 60000);
  const horizonEnd = draft.horizon_days * 1440;

  return (
    <div className="gantt-wrap" data-testid="gantt" data-mode={mode}>
      <div
        className="gantt-scroll"
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          if (virtual) setScroll({ top: el.scrollTop, left: el.scrollLeft, height: el.clientHeight, width: el.clientWidth });
        }}
      >
        <div className="gantt-grid" style={{ width: LABEL_W + chartW, ["--label-w" as string]: `${LABEL_W}px` }}>
          <div className="gantt-corner" style={{ height: HEAD_H }}>
            {mode === "tasks" ? terms.tasks : terms.resources}
          </div>
          <div className="gantt-head" style={{ height: HEAD_H }}>
            <svg className="gantt-svg" width={chartW} height={HEAD_H} aria-hidden>
              {days.map((m) => (
                <g key={m}>
                  <line x1={x(m)} x2={x(m)} y1={0} y2={HEAD_H} stroke="var(--grid-strong)" />
                  <text x={x(m) + 4} y={16} fontSize={11.5} fontWeight={600} fill="var(--text)">
                    {1440 * pxPerMin > 40 ? dayLabel(m) : ""}
                  </text>
                  {tickStep
                    ? Array.from({ length: Math.floor(1440 / tickStep) - 1 }, (_, k) => (k + 1) * tickStep).map((t) => (
                        <g key={t}>
                          <line x1={x(m + t)} x2={x(m + t)} y1={HEAD_H - 10} y2={HEAD_H} stroke="var(--grid)" />
                          <text x={x(m + t) + 3} y={HEAD_H - 6} fontSize={10} fill="var(--text-faint)">
                            {String(Math.floor(t / 60)).padStart(2, "0")}:{String(t % 60).padStart(2, "0")}
                          </text>
                        </g>
                      ))
                    : null}
                </g>
              ))}
            </svg>
          </div>

          <div className="gantt-labels" style={{ height: totalH, position: "sticky", left: 0 }}>
            <div style={{ position: "relative", height: totalH }}>
              {visibleRows.map(({ r, idx }) => {
                const style = { position: "absolute" as const, top: idx * ROW_H, left: 0, right: 0, height: ROW_H };
                if (r.kind === "group")
                  return (
                    <div key={r.key} className="gantt-label group" style={style}>
                      <button
                        type="button"
                        aria-expanded={!r.collapsed}
                        onClick={() =>
                          setCollapsed((s) => {
                            const n = new Set(s);
                            if (n.has(r.key)) n.delete(r.key);
                            else n.add(r.key);
                            return n;
                          })
                        }
                      >
                        <span aria-hidden>{r.collapsed ? "▸" : "▾"}</span>
                        <span className="lbl">{r.label}</span>
                        <span className="faint small">({r.count})</span>
                      </button>
                    </div>
                  );
                if (r.kind === "lane")
                  return (
                    <div key={r.key} className="gantt-label" style={{ ...style, borderBottom: r.sub < r.subCount - 1 ? "none" : undefined }} title={r.label}>
                      <span className="lbl">{r.label}</span>
                      {r.sub === 0 && r.capacity > 1 ? <span className="chip">×{r.capacity}</span> : null}
                    </div>
                  );
                const b = r.bar;
                return (
                  <div key={r.key} className="gantt-label" style={style} title={r.label}>
                    {b?.critical ? <Icon name="flag" size={12} title="On the critical chain" style={{ color: "var(--accent)", flex: "0 0 auto" }} /> : null}
                    <span className="lbl" style={b ? undefined : { color: "var(--text-faint)" }}>{r.label}</span>
                    {b?.late ? <span className="badge danger" style={{ padding: "0 5px", fontSize: 10.5 }}>Late</span> : null}
                  </div>
                );
              })}
            </div>
          </div>

          <div style={{ position: "relative", height: totalH }}>
            <svg className="gantt-svg" width={chartW} height={Math.max(totalH, 1)} role="group" aria-label={`${terms.schedule} timeline`}>
              <defs>
                <pattern id="gantt-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <line x1="0" y1="0" x2="0" y2="6" stroke="rgba(255,255,255,0.55)" strokeWidth="2.2" />
                </pattern>
                <marker id="gantt-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                  <path d="M0,0 L10,5 L0,10 z" fill="var(--text-faint)" />
                </marker>
                <marker id="gantt-arrow-crit" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                  <path d="M0,0 L10,5 L0,10 z" fill="var(--accent)" />
                </marker>
              </defs>
              {/* day grid */}
              {days.map((m) => (
                <line key={m} x1={x(m)} x2={x(m)} y1={0} y2={totalH} stroke="var(--grid-strong)" />
              ))}
              {tickStep && pxPerHour >= 16
                ? days.flatMap((m) =>
                    Array.from({ length: Math.floor(1440 / tickStep) - 1 }, (_, k) => m + (k + 1) * tickStep).map((t) => (
                      <line key={`${m}-${t}`} x1={x(t)} x2={x(t)} y1={0} y2={totalH} stroke="var(--grid)" />
                    )),
                  )
                : null}
              {/* horizon end */}
              {horizonEnd < rangeEnd ? <rect x={x(horizonEnd)} y={0} width={Math.max(0, x(rangeEnd) - x(horizonEnd))} height={totalH} fill="var(--shade)" /> : null}
              {/* rows */}
              {visibleRows.map(({ r, idx }) => {
                const y = idx * ROW_H;
                const shadeRes = r.kind === "lane" ? r.resourceId : r.kind === "task" ? r.bar?.p.resource_ids[0] : undefined;
                const closed = shadeRes ? closedByRes.get(shadeRes) : undefined;
                return (
                  <g key={r.key}>
                    {r.kind === "group" ? <rect x={0} y={y} width={chartW} height={ROW_H} fill="var(--surface-2)" /> : null}
                    {closed
                      ? closed.map(([s, e]) => (
                          <rect key={s} x={x(s)} y={y} width={Math.max(0, x(e) - x(s))} height={ROW_H} fill="var(--shade)" />
                        ))
                      : null}
                    {r.kind === "lane" && r.sub < r.subCount - 1 ? null : (
                      <line x1={0} x2={chartW} y1={y + ROW_H - 0.5} y2={y + ROW_H - 0.5} stroke="var(--grid)" />
                    )}
                    {r.kind === "group" && r.collapsed && r.span ? (
                      <rect x={x(r.span[0])} y={y + 10} width={Math.max(2, x(r.span[1]) - x(r.span[0]))} height={10} rx={3} fill="var(--bar-alt)" />
                    ) : null}
                  </g>
                );
              })}
              {/* arrows */}
              {arrows.map(({ d, path, critical }) => (
                <path
                  key={`${d.predecessor}->${d.successor}`}
                  d={path}
                  fill="none"
                  stroke={critical ? "var(--accent)" : "var(--text-faint)"}
                  strokeWidth={critical ? 1.6 : 1}
                  markerEnd={`url(#${critical ? "gantt-arrow-crit" : "gantt-arrow"})`}
                  opacity={0.85}
                  pointerEvents="none"
                />
              ))}
              {/* bars + deadlines */}
              {visibleRows.map(({ r, idx }) => {
                const y = idx * ROW_H;
                if (r.kind === "lane") return <g key={r.key}>{r.bars.map((b) => renderBar(b, y))}</g>;
                if (r.kind !== "task") return null;
                return (
                  <g key={r.key}>
                    {r.deadline && r.deadline.m >= rangeStart && r.deadline.m <= rangeEnd ? (
                      <g aria-hidden>
                        <line
                          x1={x(r.deadline.m)}
                          x2={x(r.deadline.m)}
                          y1={y + 2}
                          y2={y + ROW_H - 2}
                          stroke={r.deadline.hard ? "var(--danger)" : "var(--warn)"}
                          strokeWidth={1.6}
                          strokeDasharray={r.deadline.hard ? "3 2" : undefined}
                        />
                        <path
                          d={`M${x(r.deadline.m)},${y + 1} l4,4 l-4,4 l-4,-4 z`}
                          fill={r.deadline.hard ? "var(--danger)" : "var(--warn)"}
                        />
                      </g>
                    ) : null}
                    {r.bar ? renderBar(r.bar, y) : null}
                  </g>
                );
              })}
              {/* now line */}
              {nowMin > rangeStart && nowMin < rangeEnd ? (
                <g aria-hidden>
                  <line x1={x(nowMin)} x2={x(nowMin)} y1={0} y2={totalH} stroke="var(--accent)" strokeWidth={1} strokeDasharray="2 3" />
                </g>
              ) : null}
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}

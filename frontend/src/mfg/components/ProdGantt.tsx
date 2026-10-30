/**
 * Production Gantt (M3 12 `ProdGantt`, 9.1): bars and calendar bands drawn on a <canvas> (only what is in view),
 * row labels as a windowed DOM list (<= ~80 DOM rows), horizontal and vertical scrolling, zoom from hours to
 * months (buttons, +/- keys, Ctrl+wheel), a tooltip with the start reason, and drag to edit: dragging a bar to
 * another line row and/or time shows a preview; within the same line the drop can also mean "put in this order"
 * (resequence). The owner applies the edit (child run, 6.7).
 *
 * Status is never colour alone: late bars get a thick outline and a "!" mark, frozen bars a dashed outline and
 * "F", locked bars "L", split parts "1/2"; the legend repeats this.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent as RMouseEvent, type WheelEvent } from "react";
import { Icon } from "../../components/Icon";
import { lineIdOfRow, type BandKind, type GanttBar, type GanttResponse, type GanttRow } from "../api/typesM3";
import type { PlantClock } from "../lib/plantTime";
import { fmtDuration } from "../lib/plantTime";

export const ZOOMS = [1.5, 3, 6, 12, 24, 48, 96, 160]; // px per hour: ~month .. ~hour
const ROW_H = 28;
const HEAD_H = 40;
const LABEL_W = 200;
const SNAP_MIN = 5;
const OVERSCAN = 8;
const HOUR = 3600000;

export interface DropProposal {
  bar: GanttBar;
  /** target row (line view: a line row) */
  row: GanttRow;
  start: string;
  sameRow: boolean;
  /** op_nos of that line in the new order (when dropped on its own row) */
  order: number[];
}

interface Props {
  data: GanttResponse;
  clock: PlantClock;
  from: number;
  to: number;
  zoom: number;
  onZoom(z: number): void;
  editable: boolean;
  /** line view: bars may change rows; other views: time only */
  rowsAreLines: boolean;
  selected: number | null;
  onSelect(opNo: number | null): void;
  onDrop(p: DropProposal): void;
  preview: DropProposal | null;
  /** tooltip text for a bar (start reason), loaded lazily by the owner */
  reasonOf(opNo: number): string | null;
  onHover(opNo: number | null): void;
}

function css(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function ProdGantt({ data, clock, from, to, zoom, onZoom, editable, rowsAreLines, selected, onSelect, onDrop, preview, reasonOf, onHover }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [view, setView] = useState({ left: 0, top: 0, w: 800, h: 500 });
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<{ bar: GanttBar; x: number; y: number } | null>(null);
  const drag = useRef<{ bar: GanttBar; x0: number; y0: number; moved: boolean; dx: number; dy: number } | null>(null);
  const [dragTick, setDragTick] = useState(0);
  const raf = useRef<number | null>(null);
  const pxPerMs = ZOOMS[zoom] / HOUR;

  // ---------------------------------------------------------------- rows (collapsible), bars and bands by row
  const visibleRows = useMemo(() => {
    const out: GanttRow[] = [];
    const hidden = new Set<string>();
    for (const r of data.rows) {
      if (r.parent_key && (hidden.has(r.parent_key) || collapsed.has(r.parent_key))) {
        hidden.add(r.key);
        continue;
      }
      out.push(r);
    }
    return out;
  }, [data.rows, collapsed]);
  const rowIndex = useMemo(() => new Map(visibleRows.map((r, i) => [r.key, i])), [visibleRows]);
  const hasKids = useMemo(() => new Set(data.rows.filter((r) => r.parent_key).map((r) => r.parent_key!)), [data.rows]);
  const barsByRow = useMemo(() => {
    const m = new Map<string, { bar: GanttBar; s: number; e: number }[]>();
    for (const b of data.bars) {
      const arr = m.get(b.row_key) ?? [];
      arr.push({ bar: b, s: Date.parse(b.start), e: Date.parse(b.end) });
      m.set(b.row_key, arr);
    }
    for (const arr of m.values()) arr.sort((a, b) => a.s - b.s);
    return m;
  }, [data.bars]);
  const bandsByRow = useMemo(() => {
    const m = new Map<string, { kind: BandKind; s: number; e: number }[]>();
    for (const b of data.bands) {
      const arr = m.get(b.row_key) ?? [];
      arr.push({ kind: b.kind, s: Date.parse(b.start), e: Date.parse(b.end) });
      m.set(b.row_key, arr);
    }
    return m;
  }, [data.bands]);

  const totalW = Math.max(400, (to - from) * pxPerMs);
  const totalH = visibleRows.length * ROW_H;

  // ---------------------------------------------------------------- viewport tracking
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setView((v) => ({ ...v, w: el.clientWidth, h: el.clientHeight - HEAD_H }));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const onScroll = () => {
    if (raf.current !== null) return;
    raf.current = requestAnimationFrame(() => {
      raf.current = null;
      const el = scrollRef.current;
      if (el) setView((v) => ({ ...v, left: el.scrollLeft, top: el.scrollTop }));
    });
  };
  useEffect(() => () => void (raf.current !== null && cancelAnimationFrame(raf.current)), []);

  // keep the centre time when zooming
  const prevZoom = useRef(zoom);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || prevZoom.current === zoom) return;
    const old = ZOOMS[prevZoom.current] / HOUR;
    const centre = (el.scrollLeft + el.clientWidth / 2) / old;
    el.scrollLeft = Math.max(0, centre * pxPerMs - el.clientWidth / 2);
    prevZoom.current = zoom;
    setView((v) => ({ ...v, left: el.scrollLeft }));
  }, [zoom, pxPerMs]);

  // bring the selected bar into view (e.g. `?op=` deep link), also after zooming
  useEffect(() => {
    if (selected === null) return;
    const b = data.bars.find((x) => x.op_no === selected);
    const el = scrollRef.current;
    if (!b || !el) return;
    const ri = rowIndex.get(b.row_key);
    const x = (Date.parse(b.start) - from) * pxPerMs;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 100) el.scrollLeft = Math.max(0, x - 120);
    if (ri !== undefined) {
      const y = ri * ROW_H;
      if (y < el.scrollTop || y > el.scrollTop + el.clientHeight - HEAD_H - ROW_H) el.scrollTop = Math.max(0, y - 80);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, pxPerMs]);

  const timeAt = useCallback((x: number) => from + x / pxPerMs, [from, pxPerMs]);

  // ---------------------------------------------------------------- drawing
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const W = view.w;
    const H = view.h + HEAD_H;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
      cv.width = Math.round(W * dpr);
      cv.height = Math.round(H * dpr);
      cv.style.width = `${W}px`;
      cv.style.height = `${H}px`;
    }
    const g = cv.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const C = {
      bg: css("--surface", "#fff"),
      alt: css("--surface-2", "#f1f3f6"),
      grid: css("--grid", "rgba(100,116,139,.16)"),
      gridStrong: css("--grid-strong", "rgba(100,116,139,.32)"),
      text: css("--text", "#1a1f29"),
      muted: css("--text-muted", "#5b6474"),
      bar: css("--bar", "#3b82f6"),
      barCrit: css("--bar-crit", "#1e40af"),
      barAlt: css("--bar-alt", "#64748b"),
      barText: css("--bar-text", "#fff"),
      danger: css("--danger", "#b91c1c"),
      warn: css("--warn", "#b45309"),
      ok: css("--ok", "#15803d"),
      accent: css("--accent", "#2563eb"),
      shade: css("--shade", "rgba(100,116,139,.12)"),
    };
    g.clearRect(0, 0, W, H);
    g.fillStyle = C.bg;
    g.fillRect(0, 0, W, H);
    const t0 = timeAt(view.left);
    const t1 = timeAt(view.left + W);
    const X = (ms: number) => (ms - from) * pxPerMs - view.left;

    // header ticks: days (and hours when zoomed in)
    g.font = "11px system-ui, sans-serif";
    g.textBaseline = "middle";
    const dayStep = ZOOMS[zoom] < 3 ? 7 : 1;
    // local midnights: walk in 15-minute steps (covers +05:30, +05:45 zones and DST) and keep exact 00:00
    const Q = 15 * 60000;
    let cursor = Math.floor((t0 - 2 * 86400000) / Q) * Q;
    const dayLines: number[] = [];
    const hourLines: number[] = [];
    while (cursor < t1 + 86400000) {
      const p = clock.parts(cursor);
      if (p.mi === 0) {
        if (p.h === 0 && (dayStep === 1 || p.wd === 1)) dayLines.push(cursor);
        else if (p.h !== 0) hourLines.push(cursor);
      }
      cursor += p.mi === 0 && p.h !== 23 ? HOUR : Q;
    }
    for (const ms of dayLines) {
      const x = X(ms);
      g.strokeStyle = C.gridStrong;
      g.beginPath();
      g.moveTo(x + 0.5, 0);
      g.lineTo(x + 0.5, H);
      g.stroke();
      g.fillStyle = C.text;
      const s = clock.dateTime(new Date(ms).toISOString()).replace(/ 00:00$/, "");
      g.fillText(s, x + 4, 12);
    }
    if (ZOOMS[zoom] >= 24) {
      const step = ZOOMS[zoom] >= 96 ? 1 : ZOOMS[zoom] >= 48 ? 2 : 4;
      for (const ms of hourLines) {
        const p = clock.parts(ms);
        if (p.h % step) continue;
        const x = X(ms);
        g.strokeStyle = C.grid;
        g.beginPath();
        g.moveTo(x + 0.5, 22);
        g.lineTo(x + 0.5, H);
        g.stroke();
        g.fillStyle = C.muted;
        g.fillText(`${String(p.h).padStart(2, "0")}:00`, x + 3, 30);
      }
    }
    g.strokeStyle = C.gridStrong;
    g.beginPath();
    g.moveTo(0, HEAD_H - 0.5);
    g.lineTo(W, HEAD_H - 0.5);
    g.stroke();

    // rows in view
    const firstRow = Math.max(0, Math.floor(view.top / ROW_H) - 1);
    const lastRow = Math.min(visibleRows.length, Math.ceil((view.top + view.h) / ROW_H) + 1);
    g.save();
    g.beginPath();
    g.rect(0, HEAD_H, W, H - HEAD_H);
    g.clip();
    const Y = (ri: number) => HEAD_H + ri * ROW_H - view.top;
    for (let ri = firstRow; ri < lastRow; ri++) {
      const row = visibleRows[ri];
      const y = Y(ri);
      if (ri % 2) {
        g.fillStyle = C.alt;
        g.fillRect(0, y, W, ROW_H);
      }
      // bands
      for (const b of bandsByRow.get(row.key) ?? []) {
        if (b.e < t0 || b.s > t1) continue;
        const xa = Math.max(-2, X(b.s));
        const xb = Math.min(W + 2, X(b.e));
        if (b.kind === "base") {
          g.fillStyle = C.shade;
          g.fillRect(xa, y + 2, xb - xa, ROW_H - 4);
        } else if (b.kind === "optional_opened") {
          g.fillStyle = C.shade;
          g.fillRect(xa, y + 2, xb - xa, ROW_H - 4);
          g.strokeStyle = C.warn;
          g.setLineDash([]);
          g.strokeRect(xa + 0.5, y + 2.5, xb - xa - 1, ROW_H - 5);
        } else if (b.kind === "optional_suggested") {
          g.strokeStyle = C.warn;
          g.setLineDash([3, 3]);
          g.strokeRect(xa + 0.5, y + 2.5, xb - xa - 1, ROW_H - 5);
          g.setLineDash([]);
        } else {
          // closed / absence: diagonal hatching
          g.save();
          g.beginPath();
          g.rect(xa, y + 1, xb - xa, ROW_H - 2);
          g.clip();
          g.strokeStyle = b.kind === "closed" ? C.danger : C.muted;
          g.globalAlpha = 0.35;
          for (let hx = xa - ROW_H; hx < xb; hx += 6) {
            g.beginPath();
            g.moveTo(hx, y + ROW_H);
            g.lineTo(hx + ROW_H, y);
            g.stroke();
          }
          g.restore();
        }
      }
      g.strokeStyle = C.grid;
      g.beginPath();
      g.moveTo(0, y + ROW_H - 0.5);
      g.lineTo(W, y + ROW_H - 0.5);
      g.stroke();
      // bars
      const d = drag.current;
      for (const it of barsByRow.get(row.key) ?? []) {
        if (it.e < t0 || it.s > t1) continue;
        const b = it.bar;
        const dragging = d && d.moved && d.bar.op_no === b.op_no;
        drawBar(g, b, X(it.s), X(it.e), y, it.s, b.setup_end ? X(Date.parse(b.setup_end)) : null, b.pieces.map((pc) => [X(Date.parse(pc.start)), X(Date.parse(pc.end))]), C, selected === b.op_no, dragging ? 0.35 : 1);
      }
    }
    // drag ghost / preview
    const ghost = (bar: GanttBar, ri: number, startMs: number) => {
      const dur = Date.parse(bar.end) - Date.parse(bar.start);
      const xa = X(startMs);
      const xb = X(startMs + dur);
      const y = Y(ri);
      g.fillStyle = C.accent;
      g.globalAlpha = 0.25;
      g.fillRect(xa, y + 4, Math.max(3, xb - xa), ROW_H - 8);
      g.globalAlpha = 1;
      g.strokeStyle = C.accent;
      g.lineWidth = 2;
      g.setLineDash([5, 3]);
      g.strokeRect(xa, y + 4, Math.max(3, xb - xa), ROW_H - 8);
      g.setLineDash([]);
      g.lineWidth = 1;
    };
    const d = drag.current;
    if (d && d.moved) {
      const target = dropTarget(d);
      if (target) ghost(d.bar, rowIndex.get(target.row.key) ?? 0, Date.parse(target.start));
    } else if (preview) {
      const ri = rowIndex.get(preview.row.key);
      if (ri !== undefined) ghost(preview.bar, ri, Date.parse(preview.start));
    }
    g.restore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, visibleRows, barsByRow, bandsByRow, from, pxPerMs, zoom, selected, preview, dragTick, clock]);

  // ---------------------------------------------------------------- hit testing and drag
  const hit = (clientX: number, clientY: number): { bar: GanttBar; x: number; y: number } | null => {
    const cv = canvasRef.current;
    if (!cv) return null;
    const rect = cv.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    if (y < HEAD_H) return null;
    const ri = Math.floor((y - HEAD_H + view.top) / ROW_H);
    const row = visibleRows[ri];
    if (!row) return null;
    const t = timeAt(x + view.left);
    const tol = 3 / pxPerMs;
    const arr = barsByRow.get(row.key) ?? [];
    for (let i = arr.length - 1; i >= 0; i--) if (t >= arr[i].s - tol && t <= arr[i].e + tol) return { bar: arr[i].bar, x, y };
    return null;
  };

  function dropTarget(d: { bar: GanttBar; dx: number; dy: number }): { row: GanttRow; start: string } | null {
    const srcRi = rowIndex.get(d.bar.row_key);
    if (srcRi === undefined) return null;
    let ri = srcRi;
    if (rowsAreLines) {
      ri = Math.max(0, Math.min(visibleRows.length - 1, srcRi + Math.round(d.dy / ROW_H)));
      if (!lineIdOfRow(visibleRows[ri].key)) ri = srcRi;
    }
    const snap = SNAP_MIN * 60000;
    const startMs = Math.round((Date.parse(d.bar.start) + d.dx / pxPerMs) / snap) * snap;
    return { row: visibleRows[ri], start: new Date(startMs).toISOString() };
  }

  const onMouseDown = (e: RMouseEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const h = hit(e.clientX, e.clientY);
    onSelect(h ? h.bar.op_no : null);
    if (h && editable && h.bar.op_no >= 0) drag.current = { bar: h.bar, x0: e.clientX, y0: e.clientY, moved: false, dx: 0, dy: 0 };
  };
  useEffect(() => {
    const move = (e: MouseEvent) => {
      const d = drag.current;
      if (!d) return;
      d.dx = e.clientX - d.x0;
      d.dy = e.clientY - d.y0;
      if (!d.moved && Math.abs(d.dx) + Math.abs(d.dy) > 4) d.moved = true;
      if (d.moved) setDragTick((t) => t + 1);
    };
    const up = () => {
      const d = drag.current;
      drag.current = null;
      if (!d || !d.moved) return;
      setDragTick((t) => t + 1);
      const target = dropTarget(d);
      if (!target) return;
      const sameRow = target.row.key === d.bar.row_key;
      const lineBars = (barsByRow.get(target.row.key) ?? []).filter((x) => x.bar.op_no !== d.bar.op_no);
      const newStart = Date.parse(target.start);
      const order = [...lineBars.map((x) => ({ op: x.bar.op_no, s: x.s })), { op: d.bar.op_no, s: newStart }].sort((a, b) => a.s - b.s).map((x) => x.op);
      onDrop({ bar: d.bar, row: target.row, start: target.start, sameRow, order: [...new Set(order)] });
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [barsByRow, rowIndex, visibleRows, pxPerMs, onDrop]);

  const onMouseMove = (e: RMouseEvent<HTMLCanvasElement>) => {
    if (drag.current?.moved) return;
    const h = hit(e.clientX, e.clientY);
    setHover(h ? { ...h, x: e.clientX, y: e.clientY } : null);
    onHover(h ? h.bar.op_no : null);
    e.currentTarget.style.cursor = h ? (editable ? "grab" : "pointer") : "default";
  };

  const onWheel = (e: WheelEvent<HTMLDivElement>) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    onZoom(Math.max(0, Math.min(ZOOMS.length - 1, zoom + (e.deltaY < 0 ? 1 : -1))));
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const el = scrollRef.current;
    if (!el) return;
    const stepX = el.clientWidth / 4;
    if (e.key === "ArrowRight") el.scrollLeft += stepX;
    else if (e.key === "ArrowLeft") el.scrollLeft -= stepX;
    else if (e.key === "ArrowDown") el.scrollTop += ROW_H * 3;
    else if (e.key === "ArrowUp") el.scrollTop -= ROW_H * 3;
    else if (e.key === "+" || e.key === "=") onZoom(Math.min(ZOOMS.length - 1, zoom + 1));
    else if (e.key === "-") onZoom(Math.max(0, zoom - 1));
    else if (e.key === "Escape") onSelect(null);
    else return;
    e.preventDefault();
  };

  // ---------------------------------------------------------------- label pane (windowed DOM)
  const firstLabel = Math.max(0, Math.floor(view.top / ROW_H) - OVERSCAN);
  const lastLabel = Math.min(visibleRows.length, Math.ceil((view.top + view.h) / ROW_H) + OVERSCAN);
  const labels = visibleRows.slice(firstLabel, lastLabel);
  const hoverReason = hover ? reasonOf(hover.bar.op_no) : null;

  return (
    <div className="pg" data-testid="prod-gantt" style={{ height: `min(68vh, ${Math.max(totalH, ROW_H * 4) + HEAD_H + 18}px)` }}>
      <div className="pg-labels" aria-hidden={false} style={{ width: LABEL_W }}>
        <div className="pg-labels-head" style={{ height: HEAD_H }}>
          {clock.zoneLabel}
        </div>
        <div className="pg-labels-body" style={{ height: view.h }}>
          <div style={{ height: totalH, position: "relative", transform: `translateY(${-view.top}px)` }}>
            {labels.map((r, i) => {
              const ri = firstLabel + i;
              const level = r.parent_key ? 1 : 0;
              return (
                <div key={r.key} className={`pg-label pg-kind-${r.kind}`} style={{ top: ri * ROW_H, height: ROW_H, paddingLeft: 6 + level * 14 }} data-testid="gantt-row" data-row-kind={r.kind} data-label={r.label}>
                  {hasKids.has(r.key) ? (
                    <button
                      type="button"
                      className="mfg-chevron"
                      aria-expanded={!collapsed.has(r.key)}
                      aria-label={`${collapsed.has(r.key) ? "Expand" : "Collapse"} ${r.label}`}
                      onClick={() =>
                        setCollapsed((s) => {
                          const n = new Set(s);
                          if (n.has(r.key)) n.delete(r.key);
                          else n.add(r.key);
                          return n;
                        })
                      }
                    >
                      <Icon name={collapsed.has(r.key) ? "chevron-right" : "chevron-down"} size={14} />
                    </button>
                  ) : (
                    <span className="mfg-chevron-space" />
                  )}
                  <span className="mfg-ellipsis" title={r.label}>
                    {r.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div ref={scrollRef} className="pg-scroll" onScroll={onScroll} onWheel={onWheel} onKeyDown={onKeyDown} tabIndex={0} aria-label="Gantt chart: arrow keys scroll, + and - zoom, Escape clears the selection">
        <div style={{ width: totalW, height: totalH + HEAD_H, position: "relative" }}>
          <canvas
            ref={canvasRef}
            className="pg-canvas"
            style={{ position: "sticky", left: 0, top: 0 }}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseLeave={() => {
              setHover(null);
              onHover(null);
            }}
            role="img"
            aria-label={`Gantt chart with ${data.bars.length} operations on ${visibleRows.length} rows`}
            data-testid="gantt-canvas"
            data-bars={data.bars.length}
            data-rows={visibleRows.length}
          />
        </div>
      </div>
      {hover && !drag.current?.moved ? (
        <div className="pg-tip" role="tooltip" style={{ position: "fixed", left: Math.min(hover.x + 14, window.innerWidth - 360), top: Math.min(hover.y + 14, window.innerHeight - 160) }} data-testid="gantt-tooltip">
          <strong>{hover.bar.label}</strong>
          <div className="mono small">
            {hover.bar.item_part_number} x {hover.bar.qty}
          </div>
          <div className="small">
            {clock.dateTime(hover.bar.start)} – {clock.dateTime(hover.bar.end)}
            {hover.bar.setup_end ? ` · setup until ${clock.time(hover.bar.setup_end)}` : ""}
          </div>
          {hover.bar.late_minutes > 0 ? <div className="small mfg-neg">Late by {fmtDuration(hover.bar.late_minutes)}</div> : null}
          {hover.bar.frozen ? <div className="small">Frozen (inside the freeze window of the published plan)</div> : null}
          {hover.bar.locked ? <div className="small">Locked by an edit</div> : null}
          {hover.bar.split && hover.bar.split.count > 1 ? (
            <div className="small">
              Split part {hover.bar.split.index + 1} of {hover.bar.split.count}
            </div>
          ) : null}
          <div className="small muted">{hoverReason ?? "Why it starts here: loading…"}</div>
        </div>
      ) : null}
    </div>
  );
}

type Colors = Record<string, string>;

function drawBar(
  g: CanvasRenderingContext2D,
  b: GanttBar,
  xa: number,
  xb: number,
  y: number,
  _s: number,
  setupX: number | null,
  pieces: number[][],
  C: Colors,
  selected: boolean,
  alpha: number,
) {
  const top = y + 5;
  const h = ROW_H - 10;
  const late = b.late_minutes > 0;
  const fill = b.frozen ? C.barAlt : late ? C.danger : b.status_color === "critical" ? C.barCrit : C.bar;
  g.globalAlpha = alpha;
  const segs = pieces.length > 1 ? pieces : [[xa, xb]];
  // connector between pieces (paused at shift ends)
  if (segs.length > 1) {
    g.strokeStyle = fill;
    g.setLineDash([2, 2]);
    g.beginPath();
    g.moveTo(segs[0][0], top + h / 2);
    g.lineTo(segs[segs.length - 1][1], top + h / 2);
    g.stroke();
    g.setLineDash([]);
  }
  for (const [a, z] of segs) {
    g.fillStyle = fill;
    g.fillRect(a, top, Math.max(2, z - a), h);
  }
  // setup part: darker overlay with stripes
  if (setupX !== null && setupX > xa) {
    g.save();
    g.beginPath();
    g.rect(xa, top, Math.min(setupX, xb) - xa, h);
    g.clip();
    g.fillStyle = "rgba(0,0,0,0.25)";
    g.fillRect(xa, top, setupX - xa, h);
    g.strokeStyle = "rgba(255,255,255,0.35)";
    for (let hx = xa - h; hx < setupX; hx += 5) {
      g.beginPath();
      g.moveTo(hx, top + h);
      g.lineTo(hx + h, top);
      g.stroke();
    }
    g.restore();
  }
  // status outlines (not colour alone)
  for (const [a, z] of segs) {
    if (late) {
      g.strokeStyle = C.danger;
      g.lineWidth = 2;
      g.strokeRect(a - 1, top - 1, Math.max(2, z - a) + 2, h + 2);
      g.lineWidth = 1;
    }
    if (b.frozen) {
      g.strokeStyle = C.text;
      g.setLineDash([3, 2]);
      g.strokeRect(a + 0.5, top + 0.5, Math.max(2, z - a) - 1, h - 1);
      g.setLineDash([]);
    }
  }
  if (selected) {
    g.strokeStyle = C.accent;
    g.lineWidth = 3;
    g.strokeRect(xa - 2, top - 2, Math.max(2, xb - xa) + 4, h + 4);
    g.lineWidth = 1;
  }
  // label with markers
  const w = xb - xa;
  if (w > 14) {
    const marks = `${late ? "! " : ""}${b.frozen ? "F " : ""}${b.locked ? "L " : ""}${b.split && b.split.count > 1 ? `${b.split.index + 1}/${b.split.count} ` : ""}`;
    g.save();
    g.beginPath();
    g.rect(xa, top, w, h);
    g.clip();
    g.fillStyle = C.barText;
    g.font = "11px system-ui, sans-serif";
    g.textBaseline = "middle";
    g.fillText(`${marks}${b.order_number} ${b.item_part_number}`, Math.max(xa, 0) + 3, top + h / 2 + 0.5);
    g.restore();
  }
  g.globalAlpha = 1;
}

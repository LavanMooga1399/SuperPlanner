import { useMemo } from "react";
import type { Dependency, Task } from "../api/types";
import { cycleEdges, edgeKey, layeredLayout } from "../lib/graphLayout";
import { fmtDuration } from "../lib/time";

const NODE_W = 168;
const NODE_H = 46;
const COL_GAP = 72;
const ROW_GAP = 18;
const PAD = 24;

export interface DependencyGraphProps {
  tasks: Task[];
  dependencies: Dependency[];
  criticalPath: string[];
  critical: Set<string>;
  showCritical: boolean;
  selected: string | null;
  onSelect(id: string | null): void;
  milestoneLabel: string;
}

/** Layered left-to-right SVG of tasks and dependencies; critical path accent, cycle edges red. */
export function DependencyGraph({
  tasks,
  dependencies,
  criticalPath,
  critical,
  showCritical,
  selected,
  onSelect,
  milestoneLabel,
}: DependencyGraphProps) {
  const ids = useMemo(() => tasks.map((t) => t.id), [tasks]);
  const edges = useMemo(() => dependencies.map((d) => ({ from: d.predecessor, to: d.successor })), [dependencies]);
  const layout = useMemo(() => layeredLayout(ids, edges), [ids, edges]);
  const cyc = useMemo(() => cycleEdges(ids, edges), [ids, edges]);
  const taskById = useMemo(() => new Map(tasks.map((t) => [t.id, t])), [tasks]);

  const critEdges = useMemo(() => {
    const s = new Set<string>();
    for (let i = 0; i + 1 < criticalPath.length; i++) s.add(edgeKey(criticalPath[i], criticalPath[i + 1]));
    return s;
  }, [criticalPath]);

  const pos = new Map<string, { x: number; y: number }>();
  layout.layers.forEach((layer, li) =>
    layer.forEach((id, k) => pos.set(id, { x: PAD + li * (NODE_W + COL_GAP), y: PAD + k * (NODE_H + ROW_GAP) })),
  );
  const maxRows = Math.max(1, ...layout.layers.map((l) => l.length));
  const width = PAD * 2 + layout.layers.length * (NODE_W + COL_GAP) - COL_GAP;
  const height = PAD * 2 + maxRows * (NODE_H + ROW_GAP) - ROW_GAP + 20;

  const related = selected
    ? new Set(dependencies.filter((d) => d.predecessor === selected || d.successor === selected).flatMap((d) => [d.predecessor, d.successor]))
    : null;

  return (
    <svg
      width={Math.max(width, 320)}
      height={Math.max(height, 120)}
      role="img"
      aria-label={`Dependency graph with ${tasks.length} nodes and ${dependencies.length} dependencies`}
      onClick={() => onSelect(null)}
    >
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--text-faint)" />
        </marker>
        <marker id="arrow-crit" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--accent)" />
        </marker>
        <marker id="arrow-cycle" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--danger)" />
        </marker>
      </defs>
      <g>
        {dependencies.map((d) => {
          const a = pos.get(d.predecessor);
          const b = pos.get(d.successor);
          if (!a || !b) return null;
          const key = edgeKey(d.predecessor, d.successor);
          const isCycle = cyc.has(key);
          const isCrit = showCritical && critEdges.has(key);
          const dim = related && !(related.has(d.predecessor) && related.has(d.successor) && (d.predecessor === selected || d.successor === selected));
          let path: string;
          let labelX: number;
          let labelY: number;
          if (d.predecessor === d.successor) {
            const x = a.x + NODE_W / 2;
            path = `M${x - 20},${a.y} C${x - 30},${a.y - 34} ${x + 30},${a.y - 34} ${x + 20},${a.y}`;
            labelX = x;
            labelY = a.y - 30;
          } else if (b.x > a.x) {
            const x1 = a.x + NODE_W;
            const y1 = a.y + NODE_H / 2;
            const x2 = b.x;
            const y2 = b.y + NODE_H / 2;
            const c = Math.max(30, (x2 - x1) / 2);
            path = `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`;
            labelX = (x1 + x2) / 2;
            labelY = (y1 + y2) / 2 - 4;
          } else {
            // Back edge (cycle or same layer): route below the nodes.
            const x1 = a.x + NODE_W / 2;
            const y1 = a.y + NODE_H;
            const x2 = b.x + NODE_W / 2;
            const y2 = b.y + NODE_H;
            const dip = Math.max(y1, y2) + 36;
            path = `M${x1},${y1} C${x1},${dip} ${x2},${dip} ${x2},${y2}`;
            labelX = (x1 + x2) / 2;
            labelY = dip - 4;
          }
          const stroke = isCycle ? "var(--danger)" : isCrit ? "var(--accent)" : "var(--border-strong)";
          const showLabel = d.type !== "FS" || d.lag_minutes !== 0;
          return (
            <g key={key} opacity={dim ? 0.25 : 1}>
              <path
                d={path}
                fill="none"
                stroke={stroke}
                strokeWidth={isCycle || isCrit ? 2.4 : 1.4}
                strokeDasharray={isCycle ? "6 4" : undefined}
                markerEnd={`url(#${isCycle ? "arrow-cycle" : isCrit ? "arrow-crit" : "arrow"})`}
              >
                <title>
                  {(taskById.get(d.predecessor)?.name ?? d.predecessor) + " → " + (taskById.get(d.successor)?.name ?? d.successor)}
                  {` (${d.type}${d.lag_minutes ? `, lag ${fmtDuration(d.lag_minutes)}` : ""})`}
                  {isCycle ? " - part of a loop" : ""}
                </title>
              </path>
              {showLabel || isCycle ? (
                <text x={labelX} y={labelY} textAnchor="middle" fontSize={10.5} fill={isCycle ? "var(--danger)" : "var(--text-muted)"} fontWeight={isCycle ? 700 : 500}>
                  {isCycle ? "loop · " : ""}
                  {d.type}
                  {d.lag_minutes ? ` ${d.lag_minutes > 0 ? "+" : ""}${fmtDuration(d.lag_minutes)}` : ""}
                </text>
              ) : null}
            </g>
          );
        })}
      </g>
      <g>
        {tasks.map((t) => {
          const p = pos.get(t.id);
          if (!p) return null;
          const isCrit = showCritical && critical.has(t.id);
          const inCycle = edges.some((e) => (e.from === t.id || e.to === t.id) && cyc.has(edgeKey(e.from, e.to)));
          const isSel = selected === t.id;
          const dim = related && !related.has(t.id) && !isSel;
          const milestone = t.type === "milestone";
          return (
            <g
              key={t.id}
              className={`graph-node${isSel ? " selected" : ""}`}
              transform={`translate(${p.x},${p.y})`}
              tabIndex={0}
              role="button"
              aria-pressed={isSel}
              aria-label={`${t.name}${milestone ? `, ${milestoneLabel}` : `, ${fmtDuration(t.duration_minutes)}`}${isCrit ? ", on critical path" : ""}${inCycle ? ", part of a loop" : ""}`}
              opacity={dim ? 0.35 : 1}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(isSel ? null : t.id);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(isSel ? null : t.id);
                }
              }}
              data-testid={`graph-node-${t.id}`}
            >
              <rect
                width={NODE_W}
                height={NODE_H}
                rx={milestone ? 22 : 7}
                fill={isCrit ? "var(--accent-soft)" : "var(--surface)"}
                stroke={inCycle ? "var(--danger)" : isCrit ? "var(--accent)" : "var(--border-strong)"}
                strokeWidth={inCycle || isCrit ? 2 : 1}
              />
              {milestone ? <path d={`M12,${NODE_H / 2} l6,-6 l6,6 l-6,6 z`} fill="var(--text-muted)" /> : null}
              <text x={milestone ? 30 : 10} y={19} fontSize={12.5} fontWeight={600} fill="var(--text)">
                {t.name.length > 22 ? t.name.slice(0, 21) + "…" : t.name}
              </text>
              <text x={milestone ? 30 : 10} y={35} fontSize={11} fill="var(--text-muted)">
                {milestone ? milestoneLabel : fmtDuration(t.duration_minutes)}
                {t.group ? ` · ${t.group}` : ""}
                {isCrit ? " · critical" : ""}
                {inCycle ? " · loop!" : ""}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

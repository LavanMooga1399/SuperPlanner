/**
 * Layered layout for the dependency graph: longest-path layering (cycles are
 * broken by ignoring DFS back edges) and a few barycenter sweeps to reduce
 * crossings.
 */

export interface LayoutEdge {
  from: string;
  to: string;
}

export interface LayoutResult {
  layer: Map<string, number>;
  order: Map<string, number>;
  layers: string[][];
  backEdges: Set<string>; // "from->to"
}

export const edgeKey = (from: string, to: string) => `${from}->${to}`;

export function layeredLayout(nodes: string[], edges: LayoutEdge[]): LayoutResult {
  const nodeSet = new Set(nodes);
  const out = new Map<string, string[]>();
  const inc = new Map<string, string[]>();
  for (const n of nodes) {
    out.set(n, []);
    inc.set(n, []);
  }
  const valid = edges.filter((e) => nodeSet.has(e.from) && nodeSet.has(e.to) && e.from !== e.to);
  for (const e of valid) out.get(e.from)!.push(e.to);

  // Find back edges with an iterative DFS.
  const backEdges = new Set<string>();
  const state = new Map<string, 0 | 1 | 2>();
  for (const root of nodes) {
    if (state.get(root)) continue;
    const stack: Array<{ n: string; i: number }> = [{ n: root, i: 0 }];
    state.set(root, 1);
    while (stack.length) {
      const top = stack[stack.length - 1];
      const succ = out.get(top.n)!;
      if (top.i < succ.length) {
        const m = succ[top.i++];
        const s = state.get(m) ?? 0;
        if (s === 0) {
          state.set(m, 1);
          stack.push({ n: m, i: 0 });
        } else if (s === 1) {
          backEdges.add(edgeKey(top.n, m));
        }
      } else {
        state.set(top.n, 2);
        stack.pop();
      }
    }
  }

  const dag = valid.filter((e) => !backEdges.has(edgeKey(e.from, e.to)));
  const dagOut = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  for (const n of nodes) {
    dagOut.set(n, []);
    indeg.set(n, 0);
  }
  for (const e of dag) {
    dagOut.get(e.from)!.push(e.to);
    inc.get(e.to)!.push(e.from);
    indeg.set(e.to, (indeg.get(e.to) ?? 0) + 1);
  }

  // Kahn + longest path layering.
  const layer = new Map<string, number>();
  const queue: string[] = nodes.filter((n) => indeg.get(n) === 0);
  for (const n of queue) layer.set(n, 0);
  let qi = 0;
  while (qi < queue.length) {
    const n = queue[qi++];
    for (const m of dagOut.get(n)!) {
      layer.set(m, Math.max(layer.get(m) ?? 0, (layer.get(n) ?? 0) + 1));
      indeg.set(m, indeg.get(m)! - 1);
      if (indeg.get(m) === 0) queue.push(m);
    }
  }
  for (const n of nodes) if (!layer.has(n)) layer.set(n, 0);

  const maxLayer = Math.max(0, ...Array.from(layer.values()));
  const layers: string[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const n of nodes) layers[layer.get(n)!].push(n);

  const order = new Map<string, number>();
  const setOrder = () => layers.forEach((l) => l.forEach((n, i) => order.set(n, i)));
  setOrder();

  const bary = (n: string, neighbors: string[]) => {
    if (!neighbors.length) return order.get(n)!;
    return neighbors.reduce((s, m) => s + order.get(m)!, 0) / neighbors.length;
  };

  for (let iter = 0; iter < 4; iter++) {
    for (let i = 1; i < layers.length; i++) {
      const b = new Map(layers[i].map((n) => [n, bary(n, inc.get(n)!)]));
      layers[i].sort((x, y) => b.get(x)! - b.get(y)!);
      layers[i].forEach((n, k) => order.set(n, k));
    }
    for (let i = layers.length - 2; i >= 0; i--) {
      const b = new Map(layers[i].map((n) => [n, bary(n, dagOut.get(n)!)]));
      layers[i].sort((x, y) => b.get(x)! - b.get(y)!);
      layers[i].forEach((n, k) => order.set(n, k));
    }
  }
  setOrder();

  return { layer, order, layers, backEdges };
}

/**
 * Simple client-side CPM over durations and dependencies (no resources, no calendars),
 * used only to highlight a critical path before /validate has been run.
 * Returns null when the graph has a cycle.
 */
export function quickCriticalPath(
  tasks: Array<{ id: string; duration: number }>,
  deps: Array<{ predecessor: string; successor: string; type: string; lag_minutes: number }>,
): { critical: Set<string>; path: string[]; makespan: number } | null {
  const ids = tasks.map((t) => t.id);
  const dur = new Map(tasks.map((t) => [t.id, t.duration]));
  const valid = deps.filter((d) => dur.has(d.predecessor) && dur.has(d.successor) && d.predecessor !== d.successor);
  const lay = layeredLayout(ids, valid.map((d) => ({ from: d.predecessor, to: d.successor })));
  if (lay.backEdges.size) return null;
  const topo = lay.layers.flat();
  const es = new Map<string, number>();
  const preds = new Map<string, typeof valid>();
  const succs = new Map<string, typeof valid>();
  for (const id of ids) {
    preds.set(id, []);
    succs.set(id, []);
  }
  for (const d of valid) {
    preds.get(d.successor)!.push(d);
    succs.get(d.predecessor)!.push(d);
  }
  const bound = (d: (typeof valid)[number], esA: number, dB: number) => {
    const dA = dur.get(d.predecessor)!;
    switch (d.type) {
      case "SS":
        return esA + d.lag_minutes;
      case "FF":
        return esA + dA + d.lag_minutes - dB;
      case "SF":
        return esA + d.lag_minutes - dB;
      default:
        return esA + dA + d.lag_minutes;
    }
  };
  for (const id of topo) {
    let v = 0;
    for (const d of preds.get(id)!) v = Math.max(v, bound(d, es.get(d.predecessor)!, dur.get(id)!));
    es.set(id, v);
  }
  let pe = 0;
  for (const id of ids) pe = Math.max(pe, es.get(id)! + dur.get(id)!);
  // Backward pass
  const lf = new Map<string, number>();
  for (const id of [...topo].reverse()) {
    let v = pe;
    const dA = dur.get(id)!;
    for (const d of succs.get(id)!) {
      const lfB = lf.get(d.successor)!;
      const lsB = lfB - dur.get(d.successor)!;
      let c: number;
      switch (d.type) {
        case "SS":
          c = lsB - d.lag_minutes + dA;
          break;
        case "FF":
          c = lfB - d.lag_minutes;
          break;
        case "SF":
          c = lfB - d.lag_minutes + dA;
          break;
        default:
          c = lsB - d.lag_minutes;
      }
      v = Math.min(v, c);
    }
    lf.set(id, v);
  }
  const critical = new Set<string>();
  for (const id of ids) {
    const slack = lf.get(id)! - dur.get(id)! - es.get(id)!;
    if (slack === 0) critical.add(id);
  }
  // Chain: from a task with EF == PE back through binding predecessors.
  const path: string[] = [];
  const ends = ids.filter((id) => es.get(id)! + dur.get(id)! === pe && critical.has(id));
  let cur: string | undefined = ends.find((id) => succs.get(id)!.length === 0) ?? ends[0];
  const seen = new Set<string>();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    path.push(cur);
    const c: string = cur;
    const binding = preds.get(c)!.find((d) => bound(d, es.get(d.predecessor)!, dur.get(c)!) === es.get(c) && es.get(c)! > 0);
    cur = binding?.predecessor;
  }
  return { critical, path: path.reverse(), makespan: pe };
}

/** Edges that lie on a directed cycle (both endpoints in the same strongly connected component). */
export function cycleEdges(nodes: string[], edges: LayoutEdge[]): Set<string> {
  const adj = new Map<string, string[]>(nodes.map((n) => [n, []]));
  for (const e of edges) if (adj.has(e.from) && adj.has(e.to)) adj.get(e.from)!.push(e.to);
  let index = 0;
  const idx = new Map<string, number>();
  const low = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const comp = new Map<string, number>();
  let compId = 0;
  const compSize = new Map<number, number>();
  for (const root of nodes) {
    if (idx.has(root)) continue;
    const work: Array<{ n: string; i: number }> = [{ n: root, i: 0 }];
    idx.set(root, index);
    low.set(root, index++);
    stack.push(root);
    onStack.add(root);
    while (work.length) {
      const top = work[work.length - 1];
      const succ = adj.get(top.n)!;
      if (top.i < succ.length) {
        const m = succ[top.i++];
        if (!idx.has(m)) {
          idx.set(m, index);
          low.set(m, index++);
          stack.push(m);
          onStack.add(m);
          work.push({ n: m, i: 0 });
        } else if (onStack.has(m)) {
          low.set(top.n, Math.min(low.get(top.n)!, idx.get(m)!));
        }
      } else {
        work.pop();
        if (work.length) {
          const parent = work[work.length - 1].n;
          low.set(parent, Math.min(low.get(parent)!, low.get(top.n)!));
        }
        if (low.get(top.n) === idx.get(top.n)) {
          let size = 0;
          for (;;) {
            const w = stack.pop()!;
            onStack.delete(w);
            comp.set(w, compId);
            size++;
            if (w === top.n) break;
          }
          compSize.set(compId, size);
          compId++;
        }
      }
    }
  }
  const out = new Set<string>();
  for (const e of edges) {
    if (e.from === e.to) {
      out.add(edgeKey(e.from, e.to));
      continue;
    }
    const c = comp.get(e.from);
    if (c !== undefined && c === comp.get(e.to) && (compSize.get(c) ?? 0) > 1) out.add(edgeKey(e.from, e.to));
  }
  return out;
}

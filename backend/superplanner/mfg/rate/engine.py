"""Rate engine orchestration (M8-DESIGN 7.2; pure): assignment of items to flow lines, construction and CP-SAT
improvement per line (lines in a process pool, `problem.workers`), the independent validator over the whole plan,
objective, shortages and explanations.

Assignment: an item eligible on several lines goes to the line with the lowest load ratio (cumulative demand hours
/ available hours) after adding it, ties by line code; an item is split across lines only when its demand hours
exceed the free hours of the best line (demands in due-date order fill the best line first; `RATE_SPLIT` info).
"""

from __future__ import annotations

import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date
from typing import Any

from . import explain
from .construct import construct_line
from .improve import improve_line
from .model import RateBlock, RateDemand, RateLine, RateProblem, RateResult
from .validator import validate


def available_hours(problem: RateProblem, line: RateLine) -> float:
    return sum((min(w.end, problem.horizon_end) - max(w.start, problem.as_of)).total_seconds() / 3600.0
               for w in line.windows if w.end > problem.as_of and w.start < problem.horizon_end)


def assign(problem: RateProblem) -> tuple[dict[str, list[RateDemand]], set[str], list[dict[str, Any]]]:
    """-> (line id -> demands, items without a line, info explanations)."""
    by_item: dict[str, list[RateDemand]] = defaultdict(list)
    for d in problem.demands:
        by_item[d.item_id].append(d)
    avail = {ln.id: available_hours(problem, ln) for ln in problem.lines}
    load = {ln.id: 0.0 for ln in problem.lines}
    for b in problem.firm_blocks:
        if b.line_id in load:
            load[b.line_id] += (b.end - b.start).total_seconds() / 3600.0
    out: dict[str, list[RateDemand]] = defaultdict(list)
    no_line: set[str] = set()
    info: list[dict[str, Any]] = []

    def hours(i: str, ln: RateLine, q: float) -> float:
        return q / ln.rates[i]

    order = sorted(by_item, key=lambda i: (-sum(d.qty for d in by_item[i]), problem.items[i].part_number
                                           if i in problem.items else i))
    for i in order:
        elig = [ln for ln in problem.lines if i in ln.rates]
        if not elig or i not in problem.items:
            no_line.add(i)
            continue
        tot = sum(d.qty for d in by_item[i])

        def ratio(ln: RateLine, extra: float) -> float:
            return (load[ln.id] + extra) / avail[ln.id] if avail[ln.id] > 0 else float("inf")
        elig.sort(key=lambda ln: (ratio(ln, hours(i, ln, tot)), ln.code))
        best = elig[0]
        free = avail[best.id] - load[best.id]
        if hours(i, best, tot) <= free + 1e-9 or len(elig) == 1:
            out[best.id] += by_item[i]
            load[best.id] += hours(i, best, tot)
            continue
        # split: due-date order, fill lines by ascending ratio
        split_lines = []
        for d in sorted(by_item[i], key=lambda x: (x.due, x.priority)):
            elig.sort(key=lambda ln: (ratio(ln, hours(i, ln, d.qty)), ln.code))
            ln = elig[0]
            out[ln.id].append(d)
            load[ln.id] += hours(i, ln, d.qty)
            if ln.id not in split_lines:
                split_lines.append(ln.id)
        if len(split_lines) > 1:
            info.append({"code": "RATE_SPLIT", "severity": "info", "item_id": i, "line_id": None,
                         "message": f"{problem.items[i].part_number} is split over {len(split_lines)} lines.",
                         "detail": {"line_ids": split_lines}})
    return out, no_line, info


def sub_problem(problem: RateProblem, line: RateLine, demands: list[RateDemand]) -> RateProblem:
    items = {d.item_id for d in demands}
    # an item split over lines starts with its stock on the first line only (stock is not double counted)
    return replace(problem, lines=(line,), demands=tuple(demands),
                   items={i: problem.items[i] for i in items},
                   firm_blocks=tuple(b for b in problem.firm_blocks if b.line_id == line.id))


def solve_line(sub: RateProblem, budget_s: float, improve: bool = True) -> tuple[list[RateBlock], dict[str, Any]]:
    line = sub.lines[0]
    items = sorted({d.item_id for d in sub.demands}, key=lambda i: (sub.items[i].part_number, i))
    dem: dict[str, list[tuple[date, float, int]]] = defaultdict(list)
    for d in sub.demands:
        dem[d.item_id].append((d.due, d.qty, d.priority))
    t0 = time.monotonic()
    firm = [replace(b, firm=True) for b in sub.firm_blocks]
    blocks = construct_line(sub, line, items, dem, firm)
    stats: dict[str, Any] = {"construct_ms": int((time.monotonic() - t0) * 1000)}
    if improve and budget_s > 0 and len(items) > 1:
        t1 = time.monotonic()
        blocks, st = improve_line(sub, line, blocks, budget_s)
        stats.update(st, improve_ms=int((time.monotonic() - t1) * 1000))
    return blocks, stats


def _solve_line_task(args: tuple[RateProblem, float, bool]) -> tuple[list[RateBlock], dict[str, Any]]:
    return solve_line(*args)


def solve(problem: RateProblem, improve: bool = True) -> RateResult:
    t0 = time.monotonic()
    parts, no_line, info = assign(problem)
    # stock of split items: given to the line with the earliest demand; other lines start at 0
    seen: set[str] = set()
    subs = []
    for ln in sorted(problem.lines, key=lambda x: x.code):
        dem = parts.get(ln.id, [])
        sub = sub_problem(problem, ln, dem)
        items = dict(sub.items)
        for i in sorted(items):
            if i in seen:
                items[i] = replace(items[i], initial_stock=0.0)
            seen.add(i)
        subs.append(replace(sub, items=items))
    active = [s for s in subs if s.demands or s.firm_blocks]
    budget = max(problem.time_budget_s - (time.monotonic() - t0), 0.0)
    n_par = max(1, min(problem.workers, len(active)))
    per_line = budget * n_par / max(len(active), 1) if improve else 0.0
    tasks = [(s, per_line, improve) for s in active]
    results: list[tuple[list[RateBlock], dict[str, Any]]]
    if n_par > 1:
        import multiprocessing as mp

        with ProcessPoolExecutor(max_workers=n_par, mp_context=mp.get_context("spawn")) as ex:
            results = list(ex.map(_solve_line_task, tasks))
    else:
        results = [_solve_line_task(t) for t in tasks]
    blocks: list[RateBlock] = []
    line_stats = {}
    for s, (bl, st) in zip(active, results):
        blocks += bl
        line_stats[s.lines[0].id] = st
    for b in blocks:
        b.firm = b.firm or False
    val = validate(problem, blocks)
    obj = explain.evaluate(problem, blocks)
    shorts = explain.shortages(problem, blocks, no_line)
    assignment = {lid: sorted({d.item_id for d in ds}) for lid, ds in parts.items()}
    expl = info + explain.explain(problem, blocks, shorts, assignment)
    return RateResult(blocks=sorted(blocks, key=lambda b: (b.line_id, b.start)), shortages=shorts,
                      objective={k: v for k, v in obj.items() if k != "shortage_weighted"}, explanations=expl,
                      validator=val, stats={"lines": line_stats, "assignment": assignment,
                                            "duration_ms": int((time.monotonic() - t0) * 1000)})

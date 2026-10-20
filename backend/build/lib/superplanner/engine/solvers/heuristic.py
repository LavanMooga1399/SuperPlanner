"""Priority-rule heuristic (ARCHITECTURE 8.3): one serial-SGS decode per rule."""

from __future__ import annotations

import math
import threading
import time
from typing import ClassVar

from ..compiled import CompiledProblem
from ..decoder import DecodeResult, decode
from ..evaluate import Evaluated, evaluate_decode
from ..graph import CpmResult, cpm
from ..objectives import ObjectiveRefs, compute_refs, make_values, rank_key
from .base import (ALL_RULES, Alternative, ProgressCallback, ProgressEvent, SolveResult, SolverCapabilities,
                   SolverConfig)


def rule_priorities(problem: CompiledProblem, rule: str, cpm_result: CpmResult) -> list[float]:
    """Priority per task (lower = scheduled first): tuple keys turned into rank / n."""
    tasks = problem.tasks
    n = len(tasks)
    ls = [cpm_result.tasks[t.id].ls for t in tasks]
    inf = math.inf

    def key(i: int):
        t = tasks[i]
        if rule == "edf":
            return (t.deadline if t.deadline is not None else inf, ls[i], -t.priority)
        if rule == "slack":
            return (ls[i], -t.priority)
        if rule == "spt":
            return (t.duration, ls[i])
        if rule == "lpt":
            return (-t.duration, ls[i])
        if rule == "priority":
            return (-t.priority, ls[i])
        raise ValueError(f"unknown heuristic rule {rule!r}")

    order = sorted(range(n), key=lambda i: (key(i), i))
    pri = [0.0] * n
    for pos, i in enumerate(order):
        pri[i] = pos / max(1, n)
    return pri


def run_rules(problem: CompiledProblem, config: SolverConfig, cpm_result: CpmResult,
              progress_cb: ProgressCallback | None = None, cancel_event: threading.Event | None = None,
              t0: float | None = None) -> tuple[list[tuple[str, DecodeResult, Evaluated]], ObjectiveRefs, bool]:
    t0 = time.monotonic() if t0 is None else t0
    outs: list[tuple[str, DecodeResult, Evaluated]] = []
    cancelled = False
    for idx, rule in enumerate(config.heuristic_rules or list(ALL_RULES)):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        dr = decode(problem, rule_priorities(problem, rule, cpm_result))
        ev = evaluate_decode(problem, dr, config.weights, config.refs, f"heuristic:{rule}")
        outs.append((rule, dr, ev))
        if progress_cb is not None:
            progress_cb(ProgressEvent(type="progress", solver="heuristic", elapsed_seconds=time.monotonic() - t0,
                                      iteration=idx + 1, best_score=None, best_objectives=None,
                                      feasible_found=any(o[2].feasible for o in outs), extra={"rule": rule}))
    refs = config.refs
    if refs is None:
        refs = compute_refs([ev.values if ev.complete else None for _, _, ev in outs], problem, cpm_result)
    for _, _, ev in outs:
        ev.values = make_values(ev.values.makespan_minutes, ev.values.weighted_tardiness, ev.values.cost,
                                config.weights, refs)
        ev.key = rank_key(ev.feasible, ev.hvs, ev.values.score)
    return outs, refs, cancelled


class HeuristicSolver:
    name: ClassVar[str] = "heuristic"
    capabilities: ClassVar[SolverCapabilities] = SolverCapabilities(
        alternative_resources=True, calendars=True, multi_objective=False, proves_optimality=False,
        proves_infeasibility=False, uses_hint=False, deterministic_with_seed=True)

    def solve(self, problem: CompiledProblem, config: SolverConfig, progress_cb: ProgressCallback | None = None,
              cancel_event: threading.Event | None = None, cpm_result: CpmResult | None = None) -> SolveResult:
        result, _, _ = self.solve_with_refs(problem, config, progress_cb, cancel_event, cpm_result)
        return result

    def solve_with_refs(self, problem: CompiledProblem, config: SolverConfig,
                        progress_cb: ProgressCallback | None = None, cancel_event: threading.Event | None = None,
                        cpm_result: CpmResult | None = None):
        t0 = time.monotonic()
        cpm_result = cpm_result or cpm(problem)
        outs, refs, cancelled = run_rules(problem, config, cpm_result, progress_cb, cancel_event, t0)
        elapsed = time.monotonic() - t0
        if not outs:
            return SolveResult(solver="heuristic", status="cancelled", feasibility="unknown",
                               termination_reason="cancelled", optimality_proven=False, objectives=None,
                               placements=[], iterations=0, elapsed_seconds=elapsed), refs, outs
        best_rule, _, best = min(outs, key=lambda o: o[2].key)
        alts = [Alternative(label="", solver=ev.solver, objectives=ev.values, placements=ev.placements)
                for rule, _, ev in outs if rule != best_rule and ev.feasible]
        result = SolveResult(
            solver=f"heuristic:{best_rule}", status="cancelled" if cancelled else "completed",
            feasibility="feasible" if best.feasible else "unknown",
            termination_reason="cancelled" if cancelled else "completed", optimality_proven=False,
            objectives=best.values if best.placements else None, placements=best.placements,
            iterations=len(outs), elapsed_seconds=elapsed, alternatives=alts)
        return result, refs, outs

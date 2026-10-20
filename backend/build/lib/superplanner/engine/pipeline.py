"""Optimization pipeline (ARCHITECTURE 8.6, 8.7): preflight -> baseline -> search -> pick -> validate."""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from typing import Literal

from pydantic import BaseModel, Field

from .compiled import CompiledProblem, build_compiled
from .decoder import left_shift
from .evaluate import Evaluated, evaluate_validated
from .explain import ScheduleExplanation, explain
from .graph import CpmResult, cpm
from .model import Objectives, Placement, Problem
from .objectives import ObjectiveRefs, ObjectiveValues, compute_refs, dominates, make_values
from .preflight import PROVEN_INFEASIBLE_CODES, PreflightReport, preflight
from .selector import CPM_REASON, FALLBACK_REASON, MIN_BUDGET_FOR_SEARCH, Selection, is_resource_free, plan_strategy
from .solvers import get_solver
from .solvers.base import (Alternative, CpSatParams, GaParams, ProgressCallback, ProgressEvent, SolveResult,
                           SolverConfig)
from .solvers.heuristic import HeuristicSolver, run_rules
from .timeutil import fmt_duration

log = logging.getLogger(__name__)

MIN_PHASE_SECONDS = 0.5
BASELINE_REASON = "Baseline: priority rules give a first schedule, the reference values and a starting point."
MAX_ALTERNATIVE_CANDIDATES = 12


class OptimizeRequest(BaseModel):
    strategy: Literal["auto", "heuristic", "cpsat", "ga", "hybrid"] = "auto"
    time_limit_seconds: float = Field(default=10.0, ge=1, le=300)
    seed: int = 0
    objectives: Objectives | None = None
    ga: GaParams = Field(default_factory=GaParams)
    cpsat: CpSatParams = Field(default_factory=CpSatParams)
    max_alternatives: int = Field(default=2, ge=0, le=5)
    initial_solution: list[Placement] | None = None


class PhaseSummary(BaseModel):
    solver: str
    status: str
    feasibility: str
    termination_reason: str
    objectives: ObjectiveValues | None = None
    elapsed_seconds: float


class OptimizeOutcome(BaseModel):
    selection: Selection
    result: SolveResult
    explanation: ScheduleExplanation | None
    preflight: PreflightReport
    refs: ObjectiveRefs
    phases: list[PhaseSummary]


def _phase_name(detailed: str) -> str:
    return detailed.split(":", 1)[0]


class _Run:
    def __init__(self, request: OptimizeRequest, progress_cb: ProgressCallback | None,
                 cancel_event: threading.Event | None):
        self.request = request
        self.user_cb = progress_cb
        self.cancel_event = cancel_event
        self.t0 = time.monotonic()
        self.deadline = self.t0 + request.time_limit_seconds

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def emit(self, ev: ProgressEvent) -> None:
        if self.user_cb is not None:
            self.user_cb(ev)

    def cb_for(self, phase: str) -> ProgressCallback:
        def cb(ev: ProgressEvent) -> None:
            self.emit(ev.model_copy(update={"elapsed_seconds": round(self.elapsed(), 3), "solver": phase}))
        return cb

    def phase_started(self, phase: str, reason: str) -> None:
        self.emit(ProgressEvent(type="phase_started", solver=phase, elapsed_seconds=round(self.elapsed(), 3),
                                extra={"reason": reason}))

    def phase_completed(self, phase: str, res: SolveResult) -> None:
        self.emit(ProgressEvent(
            type="phase_completed", solver=phase, elapsed_seconds=round(self.elapsed(), 3),
            iteration=res.iterations, best_score=res.objectives.score if res.objectives else None,
            best_objectives=res.objectives, feasible_found=res.feasibility == "feasible",
            extra={"status": res.status, "termination_reason": res.termination_reason,
                   "feasibility": res.feasibility}))


def _summary(phase: str, res: SolveResult) -> PhaseSummary:
    return PhaseSummary(solver=phase, status=res.status, feasibility=res.feasibility,
                        termination_reason=res.termination_reason, objectives=res.objectives,
                        elapsed_seconds=round(res.elapsed_seconds, 4))


def _vec(ev: Evaluated) -> tuple[int, int, float]:
    return (ev.values.makespan_minutes, ev.values.weighted_tardiness, ev.values.cost)


def optimize(problem: Problem, request: OptimizeRequest | None = None, progress_cb: ProgressCallback | None = None,
             cancel_event: threading.Event | None = None) -> "OptimizeOutcome":
    request = request or OptimizeRequest()
    run = _Run(request, progress_cb, cancel_event)

    # 1. preflight
    pf = preflight(problem)
    if not pf.ok:
        errors = [i for i in pf.issues if i.severity == "error"]
        proven = any(i.code in PROVEN_INFEASIBLE_CODES for i in errors)
        result = SolveResult(
            solver="preflight", status="completed", feasibility="infeasible" if proven else "unknown",
            termination_reason="preflight_failed", optimality_proven=False, objectives=None, placements=[],
            iterations=0, elapsed_seconds=round(run.elapsed(), 4), diagnostics=[i.message for i in errors])
        return OptimizeOutcome(
            selection=Selection(requested=request.strategy, used=[],
                                reasons=[f"Preflight found {len(errors)} blocking problem(s); nothing was solved."]),
            result=result, explanation=None, preflight=pf, refs=ObjectiveRefs(), phases=[])

    # 2. compile + CPM
    cp = build_compiled(problem, request.objectives)
    cpm_res = cpm(cp)
    weights = cp.weights

    # 3. resource-free shortcut
    if is_resource_free(cp):
        return _cpm_shortcut(cp, cpm_res, request, run, pf)

    # 4. baseline
    base_cfg = SolverConfig(time_limit_seconds=max(MIN_PHASE_SECONDS, min(300.0, run.remaining())),
                            seed=request.seed, weights=weights, refs=None, cpsat=request.cpsat, ga=request.ga,
                            max_alternatives=request.max_alternatives)
    run.phase_started("heuristic", BASELINE_REASON)
    base_res, refs, _rule_outs = HeuristicSolver().solve_with_refs(cp, base_cfg, run.cb_for("heuristic"),
                                                                  cancel_event, cpm_res)
    run.phase_completed("heuristic", base_res)
    results: list[tuple[str, SolveResult]] = [("heuristic", base_res)]
    phases = [_summary("heuristic", base_res)]
    diagnostics: list[str] = []

    # 5. strategy resolution
    plan = plan_strategy(request.strategy, cp, request.time_limit_seconds)
    selection = Selection(requested=request.strategy, used=["heuristic"], reasons=list(plan.reasons))
    queue = [(n, sh, plan.reasons[0] if plan.reasons else n) for n, sh in plan.phases]
    cfg = base_cfg.model_copy(update={"refs": refs})
    while queue:
        name, share, reason = queue.pop(0)
        if run.cancelled():
            break
        remaining = run.remaining()
        if remaining < MIN_PHASE_SECONDS:
            selection.reasons.append(f"Skipped {name}: less than {MIN_PHASE_SECONDS} s of the time budget left.")
            continue
        limit = max(MIN_PHASE_SECONDS, min(300.0, remaining * share))
        if request.initial_solution:
            init = request.initial_solution
        else:
            init = _best_raw(cp, results, weights, refs).placements
        phase_cfg = cfg.model_copy(update={"time_limit_seconds": limit, "initial_solution": init})
        run.phase_started(name, reason)
        try:
            res = get_solver(name).solve(cp, phase_cfg, run.cb_for(name), cancel_event)
        except Exception as exc:  # programming error in a search phase: keep the baseline
            log.exception("solver phase %s failed", name)
            res = SolveResult(solver=name, status="failed", feasibility="unknown", termination_reason="error",
                              optimality_proven=False, objectives=None, placements=[],
                              elapsed_seconds=0.0)
            diagnostics.append(f"The {name} phase failed ({exc.__class__.__name__}); the best schedule from the "
                               "other phases is used.")
        run.phase_completed(name, res)
        selection.used.append(name)
        results.append((name, res))
        phases.append(_summary(name, res))
        diagnostics.extend(res.diagnostics)
        if (request.strategy == "auto" and name == "cpsat" and res.feasibility == "unknown"
                and not run.cancelled() and run.remaining() >= MIN_BUDGET_FOR_SEARCH
                and not any(q[0] == "ga" for q in queue)):
            queue.append(("ga", 1.0, FALLBACK_REASON))
            selection.reasons.append(FALLBACK_REASON)

    # 6. final pick (left-shift + independent validation of every phase result)
    finals: list[tuple[Evaluated, str, SolveResult, float]] = []
    for order, (name, res) in enumerate(results):
        if not res.placements and cp.tasks:
            continue
        shifted = left_shift(cp, res.placements)
        ev = evaluate_validated(cp, shifted, weights, refs, res.solver)
        raw_score = res.objectives.score if res.objectives else ev.values.score
        finals.append((ev, name, res, raw_score))
    proven_infeasible = any(r.termination_reason == "proven_infeasible" for _, r in results)
    if not finals:
        ev = evaluate_validated(cp, [], weights, refs, base_res.solver)
        finals.append((ev, "heuristic", base_res, ev.values.score))
    finals.sort(key=lambda f: (f[0].key, 0 if f[2].optimality_proven else 1))
    best_ev, best_name, best_res, best_raw = finals[0]
    report = best_ev.report
    assert report is not None
    if best_ev.feasible:
        feasibility = "feasible"
    elif proven_infeasible:
        feasibility = "infeasible"
    else:
        feasibility = "unknown"
    optimality = bool(best_res.optimality_proven and abs(best_ev.values.score - best_raw) < 1e-9
                      and best_ev.feasible)
    cancelled = run.cancelled()
    if cancelled:
        term = "cancelled"
    elif feasibility == "infeasible":
        term = "proven_infeasible"
    elif optimality:
        term = "optimal"
    elif best_name == "heuristic" and len(results) > 1:
        term = results[-1][1].termination_reason
    else:
        term = best_res.termination_reason
    if feasibility != "feasible" and term in ("optimal", "completed") and not best_ev.complete:
        term = "no_solution"

    # 7. infeasibility probe
    if feasibility != "feasible" and not cancelled:
        diagnostics.extend(_probe(cp, cpm_res, weights, refs, report, request, run))

    # 8. alternatives + explanation
    alternatives: list[Alternative] = []
    if request.max_alternatives > 0 and best_ev.feasible:
        alternatives = _alternatives(cp, results, best_ev, weights, refs, request.max_alternatives)
    explanation = explain(cp, best_ev.placements, cpm_res)
    result = SolveResult(
        solver=best_res.solver, status="cancelled" if cancelled else "completed",
        feasibility=feasibility, termination_reason=term, optimality_proven=optimality,
        objectives=best_ev.values if (best_ev.placements or not cp.tasks) else None,
        placements=best_ev.placements, violations=report.violations, metrics=report.metrics,
        iterations=sum(r.iterations for _, r in results), elapsed_seconds=round(run.elapsed(), 4),
        best_bound=next((r.best_bound for n, r in results if n == "cpsat" and r.best_bound is not None), None),
        alternatives=alternatives, diagnostics=list(dict.fromkeys(diagnostics)))
    return OptimizeOutcome(selection=selection, result=result, explanation=explanation, preflight=pf, refs=refs,
                           phases=phases)


def _best_raw(cp: CompiledProblem, results: list[tuple[str, SolveResult]], weights, refs) -> Evaluated:
    best: Evaluated | None = None
    for _, res in results:
        if not res.placements:
            continue
        ev = evaluate_validated(cp, res.placements, weights, refs, res.solver)
        if best is None or ev.key < best.key:
            best = ev
    if best is None:
        return evaluate_validated(cp, [], weights, refs)
    return best


def _cpm_shortcut(cp: CompiledProblem, cpm_res: CpmResult, request: OptimizeRequest, run: _Run,
                  pf: PreflightReport) -> OptimizeOutcome:
    run.phase_started("cpm", CPM_REASON)
    placements = [Placement(task_id=t.id, start=cpm_res.tasks[t.id].es, end=cpm_res.tasks[t.id].ef, resource_ids=[])
                  for t in cp.tasks]
    raw = evaluate_validated(cp, placements, cp.weights, None)
    refs = compute_refs([raw.values], cp, cpm_res)
    ev = evaluate_validated(cp, placements, cp.weights, refs, "cpm")
    report = ev.report
    assert report is not None
    feasible = ev.feasible
    res = SolveResult(
        solver="cpm", status="completed", feasibility="feasible" if feasible else "unknown",
        termination_reason="optimal" if feasible else "no_solution", optimality_proven=feasible,
        objectives=ev.values, placements=placements, violations=report.violations, metrics=report.metrics,
        iterations=1, elapsed_seconds=round(run.elapsed(), 4))
    run.phase_completed("cpm", res)
    return OptimizeOutcome(
        selection=Selection(requested=request.strategy, used=["cpm"], reasons=[CPM_REASON]), result=res,
        explanation=explain(cp, placements, cpm_res), preflight=pf, refs=refs, phases=[_summary("cpm", res)])


def _probe(cp: CompiledProblem, cpm_res: CpmResult, weights, refs, report, request: OptimizeRequest,
           run: _Run) -> list[str]:
    out: list[str] = []
    hard = [t for t in cp.tasks if t.deadline_hard and t.deadline is not None]
    locked = [t for t in cp.tasks if t.locked_start is not None]
    if not hard and not locked:
        return out
    if run.remaining() < 1.0:
        return out
    budget = min(run.remaining(), 0.25 * request.time_limit_seconds)
    probe_deadline = time.monotonic() + budget
    cfg = SolverConfig(time_limit_seconds=max(MIN_PHASE_SECONDS, min(300.0, budget)), weights=weights, refs=refs)
    term = cp.terminology
    if hard and time.monotonic() < probe_deadline:
        relaxed = dataclasses.replace(cp, tasks=tuple(dataclasses.replace(t, deadline_hard=False) for t in cp.tasks))
        outs, _, _ = run_rules(relaxed, cfg, cpm_res, None, run.cancel_event)
        if outs:
            best = min(outs, key=lambda o: o[2].key)[2]
            ev = evaluate_validated(relaxed, left_shift(relaxed, best.placements), weights, refs)
            if ev.feasible:
                pos = {p.task_id: p for p in ev.placements}
                late = [(t, pos[t.id].end - t.deadline) for t in hard
                        if t.id in pos and pos[t.id].end > t.deadline]  # type: ignore[operator]
                if late:
                    names = ", ".join(f'"{t.name}"' for t, _ in late)
                    amounts = " and ".join(fmt_duration(m) for _, m in late) if len(late) <= 2 else \
                        ", ".join(fmt_duration(m) for _, m in late)
                    out.append(f"If the hard {term.deadline.lower()}s of {names} were relaxed, a schedule exists; "
                               f"{'it' if len(late) == 1 else 'they'} would be late by {amounts}.")
    if locked and time.monotonic() < probe_deadline:
        unlocked = dataclasses.replace(cp, tasks=tuple(dataclasses.replace(t, locked_start=None, locked_resources=None)
                                                       for t in cp.tasks))
        free_cpm = cpm(unlocked)
        outs, _, _ = run_rules(unlocked, cfg, free_cpm, None, run.cancel_event)
        if outs:
            best = min(outs, key=lambda o: o[2].key)[2]
            ev = evaluate_validated(unlocked, left_shift(unlocked, best.placements), weights, refs)
            if ev.feasible:
                locked_ids = {t.id for t in locked}
                involved = []
                for v in report.violations:
                    if v.severity == "hard":
                        for tid in v.task_ids:
                            if tid in locked_ids and tid not in involved:
                                involved.append(tid)
                named = involved or [t.id for t in locked]
                names = ", ".join(f'"{cp.tasks[cp.task_index[i]].name}"' for i in named)
                out.append(f"Unlocking {names} would remove the conflict: without "
                           f"{'this lock' if len(named) == 1 else 'these locks'} a valid {term.schedule.lower()} exists.")
    return out


def _alternatives(cp: CompiledProblem, results: list[tuple[str, SolveResult]], primary: Evaluated, weights, refs,
                  max_alternatives: int) -> list[Alternative]:
    raw: list[tuple[float, str, list[Placement]]] = []
    for _, res in results:
        if res.placements:
            raw.append((res.objectives.score if res.objectives else 0.0, res.solver, res.placements))
        for a in res.alternatives:
            raw.append((a.objectives.score, a.solver, a.placements))
    raw.sort(key=lambda r: r[0])
    seen: set = set()
    cands: list[Evaluated] = []
    pv = _vec(primary)
    for _, solver, pls in raw[:MAX_ALTERNATIVE_CANDIDATES * 2]:
        if len(cands) >= MAX_ALTERNATIVE_CANDIDATES:
            break
        ev = evaluate_validated(cp, left_shift(cp, pls), weights, refs, solver)
        v = _vec(ev)
        if not ev.feasible or v == pv or v in seen:
            continue
        seen.add(v)
        cands.append(ev)
    pool = cands + [primary]
    nd = [c for c in cands if not any(dominates(_vec(o), _vec(c)) for o in pool if o is not c)]
    chosen: list[tuple[str, Evaluated]] = []
    for label, keyf in (("Fastest", lambda e: (e.values.makespan_minutes, e.values.score)),
                        ("Fewest late", lambda e: (e.values.weighted_tardiness, e.values.score)),
                        ("Cheapest", lambda e: (e.values.cost, e.values.score))):
        if len(chosen) >= max_alternatives or not nd:
            break
        best = min(nd, key=keyf)
        if keyf(best)[0] >= keyf(primary)[0]:
            continue  # does not beat the primary on this objective
        if any(best is c for _, c in chosen):
            continue
        chosen.append((label, best))
    for c in sorted(nd, key=lambda e: e.values.score):
        if len(chosen) >= max_alternatives:
            break
        if any(c is x for _, x in chosen):
            continue
        chosen.append((f"Alternative {len(chosen) + 1}", c))
    return [Alternative(label=label, solver=ev.solver, objectives=make_values(
        ev.values.makespan_minutes, ev.values.weighted_tardiness, ev.values.cost, weights, refs),
        placements=ev.placements) for label, ev in chosen]

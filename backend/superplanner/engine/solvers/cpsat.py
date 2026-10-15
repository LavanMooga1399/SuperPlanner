"""OR-Tools CP-SAT solver (ARCHITECTURE 8.4)."""

from __future__ import annotations

import threading
import time
from typing import ClassVar

from ortools.sat.python import cp_model
from ortools.util.python.sorted_interval_list import Domain

from ..compiled import CompiledProblem
from ..model import Placement
from ..objectives import ObjectiveRefs, cost_of, make_values
from ..validator import compute_metrics
from .base import (ProgressCallback, ProgressEvent, SolveResult, SolverCapabilities, SolverConfig, SolverError)

POINTS = 10_000_000


def _coef(weight: float, ref: float) -> int:
    if weight <= 0:
        return 0
    return max(1, round(POINTS * weight / ref))


class _Model:
    def __init__(self, problem: CompiledProblem, config: SolverConfig, refs: ObjectiveRefs):
        self.problem = problem
        m = self.m = cp_model.CpModel()
        H = problem.H
        w = config.weights
        self.S: list[cp_model.IntVar] = []
        self.x: dict[tuple[int, int, int], cp_model.IntVar] = {}
        per_res: dict[int, list[tuple[cp_model.IntervalVar, int]]] = {}
        cost_terms = []
        ends = []
        tard_terms = []
        tard_vars: list[tuple[int, cp_model.IntVar]] = []
        for t in problem.tasks:
            d = t.duration
            lo, hi = max(t.release, 0), H - d
            if t.deadline_hard and t.deadline is not None:
                hi = min(hi, t.deadline - d)
            if t.locked_start is not None:
                lo = hi = t.locked_start
                s = m.NewIntVar(lo, lo, f"S{t.idx}")
                # Horizon, release and hard deadline still hold for locked tasks.
                if t.locked_start < max(t.release, 0) or t.locked_start + d > H or (
                        t.deadline_hard and t.deadline is not None and t.locked_start + d > t.deadline):
                    self._infeasible()
            elif lo > hi:
                s = m.NewIntVar(lo, lo, f"S{t.idx}")
                self._infeasible()  # empty domain: proven infeasible
            else:
                s = m.NewIntVar(lo, hi, f"S{t.idx}")
            self.S.append(s)
            ends.append(s + d)
            res_used: dict[int, list[cp_model.IntVar]] = {}
            for i, req in enumerate(t.requirements):
                lits = []
                for j, k in enumerate(req.alternatives):
                    lit = m.NewBoolVar(f"x{t.idx}_{i}_{j}")
                    self.x[(t.idx, i, j)] = lit
                    lits.append(lit)
                    res = problem.resources[k]
                    fit = [[ws, we - d] for ws, we in res.windows if we - ws >= d]
                    if not fit:
                        m.Add(lit == 0)
                    else:
                        m.AddLinearExpressionInDomain(s, Domain.FromIntervals(fit)).OnlyEnforceIf(lit)
                    if t.locked_resources is not None:
                        m.Add(lit == (1 if t.locked_resources[i] == k else 0))
                    if d > 0:
                        iv = m.NewOptionalFixedSizeIntervalVar(s, d, lit, f"O{t.idx}_{i}_{j}")
                        per_res.setdefault(k, []).append((iv, req.units))
                    c = 0
                    raw_cost = cost_of(t, res, req.units)
                    if w.cost > 0 and raw_cost > 0:
                        c = max(1, round(POINTS * w.cost * raw_cost / refs.cost))
                    if c:
                        cost_terms.append(c * lit)
                    res_used.setdefault(k, []).append(lit)
                if lits:
                    m.AddExactlyOne(lits)
                else:
                    self._infeasible()  # requirement with no usable alternative
            for k, ls in res_used.items():
                if len(ls) > 1:
                    m.Add(sum(ls) <= 1)
            if t.deadline is not None and not t.deadline_hard:
                tv = m.NewIntVar(0, H, f"T{t.idx}")
                m.Add(tv >= s + d - t.deadline)
                tard_terms.append(t.priority * tv)
                tard_vars.append((t.idx, tv))
        for k, items in per_res.items():
            cap = problem.resources[k].capacity
            if cap == 1 and all(u == 1 for _, u in items):
                m.AddNoOverlap([iv for iv, _ in items])
            else:
                m.AddCumulative([iv for iv, _ in items], [u for _, u in items], cap)
        for dep in problem.deps:
            a, b = self.S[dep.pred], self.S[dep.succ]
            da, db = problem.tasks[dep.pred].duration, problem.tasks[dep.succ].duration
            if dep.type == "FS":
                m.Add(b >= a + da + dep.lag)
            elif dep.type == "SS":
                m.Add(b >= a + dep.lag)
            elif dep.type == "FF":
                m.Add(b + db >= a + da + dep.lag)
            else:
                m.Add(b + db >= a + dep.lag)
        self.M = m.NewIntVar(0, H, "M")
        for e in ends:
            m.Add(self.M >= e)
        self.tard: list[tuple[int, cp_model.IntVar]] = tard_vars
        cm = _coef(w.makespan, refs.makespan)
        ct = _coef(w.tardiness, refs.weighted_tardiness)
        obj = []
        if cm:
            obj.append(cm * self.M)
        if ct and tard_terms:
            obj.append(ct * sum(tard_terms))
        obj.extend(cost_terms)
        if obj:
            m.Minimize(sum(obj))
        if config.initial_solution:
            self._hint(config.initial_solution)

    def _infeasible(self) -> None:
        z = self.m.NewIntVar(0, 0, "false")
        self.m.Add(z == 1)

    def _hint(self, placements: list[Placement]) -> None:
        pr = self.problem
        starts: dict[int, int] = {}
        for p in placements:
            idx = pr.task_index.get(p.task_id)
            if idx is not None:
                starts[idx] = p.start
        if len(starts) == len(pr.tasks):
            self.m.AddHint(self.M, max((starts[t.idx] + t.duration for t in pr.tasks), default=0))
            for idx, tv in self.tard:
                t = pr.tasks[idx]
                self.m.AddHint(tv, max(0, starts[idx] + t.duration - (t.deadline or 0)))
        for p in placements:
            idx = pr.task_index.get(p.task_id)
            if idx is None:
                continue
            t = pr.tasks[idx]
            if t.locked_start is None:
                self.m.AddHint(self.S[idx], p.start)
            for i, req in enumerate(t.requirements):
                rid = p.resource_ids[i] if i < len(p.resource_ids) else None
                k = pr.resource_index.get(rid) if rid is not None else None
                for j, kk in enumerate(req.alternatives):
                    self.m.AddHint(self.x[(idx, i, j)], 1 if kk == k else 0)

    def extract(self, value, bool_value) -> list[Placement]:
        pr = self.problem
        out = []
        for t in pr.tasks:
            s = int(value(self.S[t.idx]))
            rids = []
            for i, req in enumerate(t.requirements):
                for j, k in enumerate(req.alternatives):
                    if bool_value(self.x[(t.idx, i, j)]):
                        rids.append(pr.resources[k].id)
                        break
            out.append(Placement(task_id=t.id, start=s, end=s + t.duration, resource_ids=rids))
        return out


class _Callback(cp_model.CpSolverSolutionCallback):
    def __init__(self, model: _Model, config: SolverConfig, refs: ObjectiveRefs, progress_cb, cancel_event, t0):
        super().__init__()
        self.model, self.config, self.refs = model, config, refs
        self.progress_cb, self.cancel_event, self.t0 = progress_cb, cancel_event, t0
        self.count = 0
        self.best: list[Placement] | None = None

    def on_solution_callback(self) -> None:  # noqa: N802 (OR-Tools API)
        self.count += 1
        self.best = self.model.extract(self.Value, self.BooleanValue)
        if self.progress_cb is not None:
            met = compute_metrics(self.model.problem, self.best)
            vals = make_values(met.makespan_minutes, met.weighted_tardiness, met.cost, self.config.weights, self.refs)
            self.progress_cb(ProgressEvent(
                type="progress", solver="cpsat", elapsed_seconds=time.monotonic() - self.t0, iteration=self.count,
                best_score=vals.score, best_objectives=vals, feasible_found=True,
                extra={"best_bound": round(self.BestObjectiveBound() / POINTS, 6)}))
        if self.cancel_event is not None and self.cancel_event.is_set():
            self.StopSearch()


class CpSatSolver:
    name: ClassVar[str] = "cpsat"
    capabilities: ClassVar[SolverCapabilities] = SolverCapabilities(
        alternative_resources=True, calendars=True, multi_objective=False, proves_optimality=True,
        proves_infeasibility=True, uses_hint=True, deterministic_with_seed=False)

    def solve(self, problem: CompiledProblem, config: SolverConfig, progress_cb: ProgressCallback | None = None,
              cancel_event: threading.Event | None = None) -> SolveResult:
        t0 = time.monotonic()
        refs = config.refs or ObjectiveRefs()
        model = _Model(problem, config, refs)
        solver = cp_model.CpSolver()
        prm = solver.parameters
        prm.max_time_in_seconds = max(0.1, config.time_limit_seconds - (time.monotonic() - t0))
        prm.num_workers = config.cpsat.num_workers
        prm.random_seed = config.seed
        prm.relative_gap_limit = config.cpsat.relative_gap
        # Probing in presolve can eat most of a short budget on medium models; scale it with the budget.
        probe_dtime = max(0.05, min(1.0, 0.05 * config.time_limit_seconds))
        prm.probing_deterministic_time_limit = probe_dtime
        prm.presolve_probing_deterministic_time_limit = probe_dtime
        cb = _Callback(model, config, refs, progress_cb, cancel_event, t0)
        done = threading.Event()

        def watchdog() -> None:
            while not done.wait(0.2):
                if cancel_event is not None and cancel_event.is_set():
                    solver.StopSearch()
                    return

        wd = threading.Thread(target=watchdog, daemon=True)
        wd.start()
        try:
            status = solver.Solve(model.m, cb)
        finally:
            done.set()
            wd.join(timeout=1.0)
        elapsed = time.monotonic() - t0
        cancelled = cancel_event is not None and cancel_event.is_set()
        if status == cp_model.MODEL_INVALID:
            raise SolverError(f"CP-SAT model invalid: {model.m.Validate()}")
        placements: list[Placement] = []
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            placements = model.extract(solver.Value, solver.BooleanValue)
        objectives = None
        if placements:
            met = compute_metrics(problem, placements)
            objectives = make_values(met.makespan_minutes, met.weighted_tardiness, met.cost, config.weights, refs)
        bound = None
        try:
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                bound = round(solver.BestObjectiveBound() / POINTS, 6)
        except Exception:  # pragma: no cover - defensive
            bound = None
        if status == cp_model.OPTIMAL:
            feas, term, opt = "feasible", "optimal", True
        elif status == cp_model.FEASIBLE:
            feas, term, opt = "feasible", ("cancelled" if cancelled else "time_limit"), False
        elif status == cp_model.INFEASIBLE:
            feas, term, opt = "infeasible", "proven_infeasible", False
        else:
            feas, term, opt = "unknown", ("cancelled" if cancelled else "time_limit"), False
        return SolveResult(
            solver="cpsat", status="cancelled" if cancelled and not opt else "completed", feasibility=feas,
            termination_reason=term, optimality_proven=opt, objectives=objectives, placements=placements,
            iterations=cb.count, elapsed_seconds=elapsed, best_bound=bound)

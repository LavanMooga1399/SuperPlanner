"""Lexicographic LP / MILP over goals x asset classes x blocks (FINANCE.md section 8).

Money is scaled by 1/1000 inside the model. `FinanceLP` builds the model of section 8.3/8.4 once; the
lexicographic tiers of 8.5 (and the single re-solves of the fix search, 12.3) reuse it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ortools.linear_solver import pywraplp

from . import defaults as Dfl
from . import timegrid as tg
from .cashflow import ef_complete_t
from .model import CashflowProjection, FinanceCancelled, FinancePlan, Goal, TierDiagnostic
from .returns import (active_caps, allowed_classes, annuity_due, gamma, goal_cap, inflation_vol, is_equity, is_risky,
                      mix_cap_applies, pi_general,
                      planning_rho,
                      real_target)

SCALE = 1e-3
TIER_ABS_EPS = 1e-4
TIER_REL_EPS = 1e-6
SMOOTH_REL_TOL = 0.05
TIERS_ORDER = ("must", "should", "nice")


@dataclass
class GoalData:
    goal: Goal
    index: int
    D: int
    TR: float
    tier: str
    z: float
    rho: dict[str, float]
    blocks: list[tuple[int, int, int]]
    allowed: list[str]
    bucket_classes: list[str]
    caps: list[float]
    earmarks: list[tuple[str, str, float, int | None]]   # holding_id, class, amount, locked_until_index


@dataclass
class XVar:
    g: str
    a: str
    k: int
    pay_start: int
    pay_end: int          # inclusive
    phi: float
    var: object


@dataclass
class OptimizerSolution:
    status: str
    termination_reason: str
    optimality_proven: bool
    solver: str
    x: dict[tuple[str, str, int], float]                      # real level amount per paying month
    x_pay: dict[tuple[str, str, int], tuple[int, int]]
    y: dict[tuple[str, str], float]
    w: dict[str, float]
    F: dict[tuple[str, str, int], float]
    H: dict[tuple[str, str, int], float]
    b: dict[tuple[str, str, int], float]
    u: dict[tuple[str, str, int], float]
    short: dict[str, float]
    B: list[float]
    d: list[float]
    cash_deficit: float
    tiers: list[TierDiagnostic]
    tier_values: dict[str, float]
    cash_binding: list[int]
    variables: int
    constraints: int
    warnings: list[str] = field(default_factory=list)
    goals: dict[str, GoalData] = field(default_factory=dict)
    extra_savings: float | None = None


def build_goal_data(plan: FinancePlan, proj: CashflowProjection, z: dict[str, float]) -> dict[str, GoalData]:
    start = plan.start_month
    pi = pi_general(plan)
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    L = plan.constraints.contribution_block_months
    holdings = {h.id: h for h in plan.holdings}
    out: dict[str, GoalData] = {}
    for i, g in enumerate(plan.goals):
        if not g.enabled:
            continue
        D = tg.month_index(start, g.target_month)
        zg = z[g.id]
        allowed = allowed_classes(plan, g)
        ems: list[tuple[str, str, float, int | None]] = []
        for s in proj.initial_splits:
            if s.source == "earmark" and s.goal_id == g.id:
                h = holdings[s.holding_id]
                li = None
                if h.locked_until_month:
                    li = tg.month_index(start, h.locked_until_month)
                    li = li if li > 0 else None
                ems.append((h.id, h.asset_class_id, s.amount, li))
        bc = list(allowed) + [c for (_, c, _, _) in ems if c not in allowed and c in classes]
        bc = list(dict.fromkeys(bc))
        blocks = tg.blocks(D, L)
        out[g.id] = GoalData(goal=g, index=i, D=D, TR=real_target(plan, g, D), tier=g.priority, z=zg,
                             rho={a: planning_rho(ac, pi, zg, D, inflation_vol(plan)) for a, ac in classes.items()}, blocks=blocks,
                             allowed=allowed, bucket_classes=bc, caps=[goal_cap(plan, g, D, s) for (_, s, _) in blocks],
                             earmarks=ems)
    return out


class _Expr:
    __slots__ = ("terms", "const")

    def __init__(self) -> None:
        self.terms: dict[int, tuple[object, float]] = {}
        self.const = 0.0

    def add(self, var, coef: float) -> "_Expr":
        if var is None or coef == 0.0:
            return self
        key = id(var)
        if key in self.terms:
            self.terms[key] = (var, self.terms[key][1] + coef)
        else:
            self.terms[key] = (var, coef)
        return self

    def add_expr(self, other: "_Expr", mult: float = 1.0) -> "_Expr":
        for v, c in other.terms.values():
            self.add(v, c * mult)
        self.const += other.const * mult
        return self


class FinanceLP:
    def __init__(self, plan: FinancePlan, proj: CashflowProjection, z: dict[str, float], *,
                 extra_savings_profile: list[float] | None = None, ignore_mins: bool | None = None,
                 cancel_event: threading.Event | None = None):
        self.plan = plan
        self.cancel_event = cancel_event
        self.proj = proj
        self.T = proj.T
        self.tE = ef_complete_t(proj)
        self.goals = build_goal_data(plan, proj, z)
        self.classes = {a.id: a for a in plan.assumptions.asset_classes}
        self.class_order = [a.id for a in plan.assumptions.asset_classes]
        self.tau = plan.constraints.rebalance_cost_pct / 100.0
        self.m_buf = plan.constraints.min_cash_buffer
        pi = pi_general(plan)
        cash_ac = self.classes.get(plan.assumptions.cash_class_id)
        self.gamma_c = gamma(cash_ac, pi) if cash_ac is not None else 1.0
        self.pool = list(proj.assignable)
        self.warnings: list[str] = []
        mins = {a: ac.min_monthly_contribution for a, ac in self.classes.items() if ac.min_monthly_contribution > 0}
        self.milp = bool(mins)
        self.mins = mins
        self._extra_profile = extra_savings_profile
        # Count candidate binaries first (8.6).
        if self.milp:
            nbin = sum(1 for _ in self._x_candidates() if _[1] in mins)
            if nbin > Dfl.MAX_BINARIES or ignore_mins:
                self.milp = False
                if nbin > Dfl.MAX_BINARIES:
                    self.warnings.append("MIN_CONTRIBUTION_IGNORED")
        self.solver_name = "SCIP" if self.milp else "GLOP"
        self.solver = pywraplp.Solver.CreateSolver(self.solver_name)
        if self.solver is None:  # pragma: no cover
            raise RuntimeError(f"OR-Tools solver {self.solver_name} is not available")
        self._build()

    # ------------------------------------------------------------ helpers
    def _x_candidates(self):
        """(goal_id, class, k, pay_start, pay_end, n_x) of every contribution variable (8.3 rules)."""
        for gid, gd in self.goals.items():
            for (k, s, n) in gd.blocks:
                p0, p1 = s, s + n - 1
                if gd.tier in ("should", "nice"):
                    if s + n <= self.tE:
                        continue
                    p0 = max(s, self.tE)
                for a in gd.allowed:
                    lk = self.classes[a].lock_in_months
                    if lk > 0 and s + n - 1 + lk > gd.D:
                        continue
                    yield gid, a, k, p0, p1, p1 - p0 + 1

    def _check(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise FinanceCancelled()

    def _num(self, lb: float = 0.0, ub: float | None = None):
        return self.solver.NumVar(lb, self.solver.infinity() if ub is None else ub, "")

    def _cons(self, expr: _Expr, lb: float, ub: float):
        """Add `lb <= expr <= ub` (constants of expr are moved to the bounds)."""
        inf = self.solver.infinity()
        c = self.solver.Constraint(-inf if lb == -inf else lb - expr.const, inf if ub == inf else ub - expr.const)
        for v, coef in expr.terms.values():
            c.SetCoefficient(v, coef)
        return c

    # ------------------------------------------------------------ model
    def _build(self) -> None:
        S = SCALE
        inf = self.solver.infinity()
        T = self.T
        tau = self.tau
        pool = self.pool
        self.w = {p.holding_id: self._num() for p in pool if p.locked_until_index is None}
        self.y: dict[tuple[str, str], object] = {}
        for gid, gd in self.goals.items():
            for p in pool:
                li = p.locked_until_index
                if (li is None or li <= gd.D) and p.asset_class_id in gd.allowed:
                    self.y[(gid, p.holding_id)] = self._num()
        for p in pool:
            e = _Expr()
            for gid in self.goals:
                e.add(self.y.get((gid, p.holding_id)), 1.0)
            e.add(self.w.get(p.holding_id), 1.0)
            if e.terms:
                self._cons(e, -inf, p.amount * S)

        # contribution variables
        self.xvars: list[XVar] = []
        self.xmap: dict[tuple[str, str, int], XVar] = {}
        M = (self.proj.cash_buffer_initial + sum(p.amount for p in pool)
             + sum(max(v, 0.0) for v in self.proj.investable)) * S
        if self._extra_profile is not None:
            M += 1e6 * S
        self.zbin: dict[tuple[str, str, int], object] = {}
        for gid, a, k, p0, p1, nx in self._x_candidates():
            gd = self.goals[gid]
            v = self._num()
            xv = XVar(gid, a, k, p0, p1, annuity_due(gd.rho[a], nx), v)
            self.xvars.append(xv)
            self.xmap[(gid, a, k)] = xv
            if self.milp and a in self.mins:
                zb = self.solver.BoolVar("")
                self.zbin[(gid, a, k)] = zb
                self._cons(_Expr().add(v, 1.0).add(zb, -(self.mins[a] + 0.005) * S), 0.0, inf)
                self._cons(_Expr().add(v, 1.0).add(zb, -max(M, (self.mins[a] + 1.0) * S)), -inf, 0.0)

        pool_by_id = {p.holding_id: p for p in pool}
        self.F: dict[tuple[str, str, int], object] = {}
        self.H: dict[tuple[str, str, int], object] = {}
        self.b: dict[tuple[str, str, int], object] = {}
        self.u: dict[tuple[str, str, int], object] = {}
        self.short: dict[str, object] = {}
        self.headroom: dict[str, float] = {}
        self.LR_eq: dict[int, _Expr] = {}
        self.LR_cls: dict[tuple[int, str], _Expr] = {}
        self.Hblock: dict[int, list[tuple[str, str, object]]] = {}
        for gid, gd in self.goals.items():
            self._check()
            K = len(gd.blocks)
            # locked positions of this goal: (class, const_amount, y_var or None, locked_until_index)
            locked: list[tuple[str, float, object, int]] = []
            for (_, c, amt, li) in gd.earmarks:
                if li is not None:
                    locked.append((c, amt, None, li))
            for (g2, hid), yv in self.y.items():
                if g2 == gid and pool_by_id[hid].locked_until_index is not None:
                    locked.append((pool_by_id[hid].asset_class_id, 0.0, yv, pool_by_id[hid].locked_until_index))
            for a in gd.bucket_classes:
                for k in range(K + 1):
                    self.F[(gid, a, k)] = self._num()
                init = _Expr().add(self.F[(gid, a, 0)], 1.0)
                init.const -= sum(amt for (_, c, amt, _) in gd.earmarks if c == a) * S
                for (g2, hid), yv in self.y.items():
                    if g2 == gid and pool_by_id[hid].asset_class_id == a:
                        init.add(yv, -1.0)
                self._cons(init, 0.0, 0.0)
            for (k, s, n) in gd.blocks:
                bsum = _Expr()
                usum = _Expr()
                for a in gd.bucket_classes:
                    ac = self.classes[a]
                    lk = ac.lock_in_months
                    Hv = self._num()
                    self.H[(gid, a, k)] = Hv
                    bv = None
                    if a in gd.allowed and (lk == 0 or s + lk <= gd.D):
                        bv = self._num()
                        self.b[(gid, a, k)] = bv
                        bsum.add(bv, 1.0)
                    uv = None
                    if lk == 0:
                        uv = self._num()
                        self.u[(gid, a, k)] = uv
                        usum.add(uv, 1.0)
                    e = _Expr().add(Hv, 1.0).add(self.F[(gid, a, k)], -1.0).add(bv, -1.0).add(uv, 1.0)
                    self._cons(e, 0.0, 0.0)
                    if uv is not None:
                        lk_e = _Expr().add(uv, 1.0).add(self.F[(gid, a, k)], -1.0)
                        has = False
                        for (c, amt, yv, li) in locked:
                            if c == a and li > s:
                                has = True
                                lk_e.const += amt * S * gd.rho[a] ** s
                                lk_e.add(yv, gd.rho[a] ** s)
                        if has:
                            self._cons(lk_e, -inf, 0.0)
                    gr = _Expr().add(self.F[(gid, a, k + 1)], 1.0).add(Hv, -(gd.rho[a] ** n))
                    xv = self.xmap.get((gid, a, k))
                    if xv is not None:
                        gr.add(xv.var, -xv.phi)
                    self._cons(gr, 0.0, 0.0)
                    self.Hblock.setdefault(k, []).append((gid, a, Hv))
                if bsum.terms or usum.terms:
                    self._cons(_Expr().add_expr(bsum).add_expr(usum, -(1.0 - tau)), 0.0, 0.0)
                # allowances (8.4 rule 7 / 9)
                LR = _Expr()
                for (c, amt, yv, li) in locked:
                    if li > s:
                        f = gd.rho[c] ** s
                        part = _Expr().add(yv, f)
                        part.const += amt * S * f
                        if is_risky(self.classes[c]):
                            LR.add_expr(part)
                        if is_equity(self.classes[c]):
                            self.LR_eq.setdefault(k, _Expr()).add_expr(part)
                        self.LR_cls.setdefault((k, c), _Expr()).add_expr(part)
                for a in gd.bucket_classes:
                    ac = self.classes[a]
                    if ac.lock_in_months > 0:
                        Fk = _Expr().add(self.F[(gid, a, k)], 1.0)
                        if is_risky(ac):
                            LR.add_expr(Fk)
                        if is_equity(ac):
                            self.LR_eq.setdefault(k, _Expr()).add_expr(Fk)
                        self.LR_cls.setdefault((k, a), _Expr()).add_expr(Fk)
                cap = gd.caps[k]
                if (any(is_risky(self.classes[a]) for a in gd.bucket_classes) and cap < 1.0
                        and active_caps(self.plan, gd.goal, gd.D, s).risk):
                    e = _Expr()
                    for a in gd.bucket_classes:
                        e.add(self.H[(gid, a, k)], (1.0 if is_risky(self.classes[a]) else 0.0) - cap)
                    e.add_expr(LR, -1.0)
                    self._cons(e, -inf, 0.0)
                xs = [self.xmap[(gid, a, k)] for a in gd.allowed if (gid, a, k) in self.xmap]
                if (cap < 1.0 and any(is_risky(self.classes[x.a]) for x in xs)
                        and mix_cap_applies(self.plan, gd.goal, gd.D, s, n)):
                    e = _Expr()
                    for x in xs:
                        e.add(x.var, (1.0 if is_risky(self.classes[x.a]) else 0.0) - cap)
                    self._cons(e, -inf, 0.0)
            # flooring headroom (F.24.3): published amounts are floored to 0.01 (8.8); planning to TR + the
            # largest possible flooring loss keeps the published plan-basis value >= TR.
            head = 0.0
            for (k, s, n) in gd.blocks:
                for a in gd.allowed:
                    xv = self.xmap.get((gid, a, k))
                    if xv is not None:
                        head += 0.01 * xv.phi * gd.rho[a] ** (gd.D - (s + n))
            self.headroom[gid] = head
            sh = self._num(0.0, (gd.TR + head) * S)
            self.short[gid] = sh
            goal = _Expr().add(sh, 1.0)
            for a in gd.bucket_classes:
                goal.add(self.F[(gid, a, K)], 1.0)
            self._cons(goal, (gd.TR + head) * S, inf)

        # global caps (8.4 rule 9)
        maxeq = self.plan.constraints.max_equity_pct
        L = self.plan.constraints.contribution_block_months
        for k, entries in self.Hblock.items():
            s_k = k * L
            act = {g: active_caps(self.plan, self.goals[g].goal, self.goals[g].D, s_k)
                   for g in {e_[0] for e_ in entries}}
            if maxeq is not None:
                e = _Expr()
                for (g_, a, Hv) in entries:
                    e.add(Hv, (1.0 if is_equity(self.classes[a]) and act[g_].equity else 0.0) - maxeq / 100.0)
                e.add_expr(self.LR_eq.get(k, _Expr()), -1.0)
                self._cons(e, -inf, 0.0)
            for a_cap, pct in self.plan.constraints.max_class_pct.items():
                if a_cap not in self.classes:
                    continue
                e = _Expr()
                for (g_, a, Hv) in entries:
                    e.add(Hv, (1.0 if a == a_cap and a_cap in act[g_].classes else 0.0) - pct / 100.0)
                e.add_expr(self.LR_cls.get((k, a_cap), _Expr()), -1.0)
                self._cons(e, -inf, 0.0)

        # smoothing helpers (rule 11)
        self.delta: list[tuple[object, float]] = []
        for gid, gd in self.goals.items():
            prev = None
            for (k, s, n) in gd.blocks:
                xs = [self.xmap[(gid, a, k)] for a in gd.allowed if (gid, a, k) in self.xmap]
                if not xs:
                    prev = None
                    continue
                if prev is not None:
                    dv = self._num()
                    e1 = _Expr().add(dv, 1.0)
                    e2 = _Expr().add(dv, 1.0)
                    for x in xs:
                        e1.add(x.var, -1.0)
                        e2.add(x.var, 1.0)
                    for x in prev:
                        e1.add(x.var, 1.0)
                        e2.add(x.var, -1.0)
                    self._cons(e1, 0.0, inf)
                    self._cons(e2, 0.0, inf)
                    self.delta.append((dv, 1.0 / max(gd.TR * S, 1e-9)))
                prev = xs

        # cash (rule 10): B_{t+1} = (B_t + A_t - X_t + d_t) * gamma_c, B_{t+1} >= m_buf * gamma_c
        gc = self.gamma_c
        self.Bv = [None] + [self._num(self.m_buf * S * gc) for _ in range(T)]
        self.dv = [self._num() for _ in range(T)]
        self.e_var = self._num() if self._extra_profile is not None else None
        pay_at: list[list[XVar]] = [[] for _ in range(T)]
        for xv in self.xvars:
            for t in range(xv.pay_start, xv.pay_end + 1):
                pay_at[t].append(xv)
        self.cash_cons = []
        for t in range(T):
            if t % 100 == 0:
                self._check()
            e = _Expr().add(self.Bv[t + 1], 1.0)
            if t == 0:
                for hid, wv in self.w.items():
                    e.add(wv, -gc * (1.0 - tau))
                e.const -= gc * self.proj.cash_buffer_initial * S
            else:
                e.add(self.Bv[t], -gc)
            for xv in pay_at[t]:
                e.add(xv.var, gc)
            e.add(self.dv[t], -gc)
            if self.e_var is not None and self._extra_profile[t] != 0.0:
                e.add(self.e_var, -gc * self._extra_profile[t])
            A = self.proj.investable[t] * S
            self.cash_cons.append(self._cons(e, gc * A, gc * A))

        # objective expressions
        self.obj_T0 = _Expr()
        for d in self.dv:
            self.obj_T0.add(d, 1.0)
        self.eta: dict[str, object] = {}
        self.obj_frac: dict[str, _Expr] = {}
        for tier in TIERS_ORDER:
            gids = [g for g, gd in self.goals.items() if gd.tier == tier]
            if not gids:
                continue
            eta = self._num(0.0, 1.0)
            self.eta[tier] = eta
            fr = _Expr()
            for gid in gids:
                # short_g <= eta * (TR_g + head_g): the shortfall of an unfunded goal is TR + flooring headroom,
                # so eta <= 1 must allow it (otherwise `head` of value is forced into every enabled goal: a fake
                # cash deficit in MILP mode, micro-contributions to unfunded goals in LP mode). The constraint is
                # kept homogeneous (no constant right-hand side): with a `head` offset, fixing eta at ~0 left GLOP
                # with a near-degenerate face on which the next tier (T4) ended ABNORMAL.
                TRs = max(self.goals[gid].TR * S, 1e-12)
                THs = max((self.goals[gid].TR + self.headroom.get(gid, 0.0)) * S, 1e-12)
                self._cons(_Expr().add(self.short[gid], 1.0).add(eta, -THs), -inf, 0.0)
                fr.add(self.short[gid], 1.0 / TRs)
            self.obj_frac[tier] = fr
        self.obj_T4 = _Expr()
        for dv, c in self.delta:
            self.obj_T4.add(dv, c)
        self.obj_T5 = _Expr()
        for xv in self.xvars:
            self.obj_T5.add(xv.var, sum(gc ** (-t) for t in range(xv.pay_start, xv.pay_end + 1)))
        for wv in self.w.values():
            self.obj_T5.add(wv, 1e-3)
        for uv in self.u.values():
            self.obj_T5.add(uv, 1e-4)

    # ------------------------------------------------------------ solving
    def tier_list(self) -> list[tuple[str, _Expr]]:
        tiers: list[tuple[str, _Expr]] = [("T0", self.obj_T0)]
        names = {"must": "T1", "should": "T2", "nice": "T3"}
        for tier in TIERS_ORDER:
            if tier in self.eta:
                tiers.append((names[tier] + "a", _Expr().add(self.eta[tier], 1.0)))
                tiers.append((names[tier] + "b", self.obj_frac[tier]))
        if self.obj_T4.terms:
            tiers.append(("T4", self.obj_T4))
        tiers.append(("T5", self.obj_T5))
        return tiers

    def tier_eps(self, name: str, v: float) -> float:
        """Slack added when tier `name` with optimum `v` is fixed (8.5). Currency tiers use 1e-4 scaled (0.1
        currency); shortfall-fraction tiers use the same 0.1 currency expressed as a fraction of the largest target
        of the tier (F.24.3); T4 keeps its 5 % relative tolerance."""
        if name == "T4":
            return v * SMOOTH_REL_TOL + 1e-6
        if name in ("T0", "T5"):
            return max(TIER_ABS_EPS, TIER_REL_EPS * abs(v))
        tier = {"T1": "must", "T2": "should", "T3": "nice"}[name[:2]]
        trmax = max((gd.TR for gd in self.goals.values() if gd.tier == tier), default=1.0) * SCALE
        return max(TIER_ABS_EPS / max(trmax, 1e-9), 1e-12)

    def _set_objective(self, expr: _Expr) -> None:
        obj = self.solver.Objective()
        obj.Clear()
        for v, c in expr.terms.values():
            obj.SetCoefficient(v, c)
        obj.SetOffset(expr.const)
        obj.SetMinimization()

    def _solve_once(self, deadline: float, cancel_event: threading.Event | None, fresh: int = 0) -> int:
        """One solve. `fresh` >= 1 re-solves from scratch (no warm start), 2 also with presolve off: the
        retries of a tier that ended INFEASIBLE / ABNORMAL on GLOP's incremental (warm-started) path."""
        remaining = max(0.05, deadline - time.monotonic())
        self.solver.SetTimeLimit(int(remaining * 1000))
        done = threading.Event()
        watcher = None
        if cancel_event is not None:
            if cancel_event.is_set():
                raise FinanceCancelled()

            def watch() -> None:
                while not done.is_set():
                    if cancel_event.wait(0.05):
                        self.solver.InterruptSolve()
                        return
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
        try:
            params = pywraplp.MPSolverParameters()
            if self.milp:
                params.SetDoubleParam(params.RELATIVE_MIP_GAP, 1e-4)
            if fresh >= 1:
                params.SetIntegerParam(params.INCREMENTALITY, params.INCREMENTALITY_OFF)
            if fresh >= 2:
                params.SetIntegerParam(params.PRESOLVE, params.PRESOLVE_OFF)
            status = self.solver.Solve(params)
        finally:
            done.set()
            if watcher is not None:
                watcher.join(timeout=1.0)
        if cancel_event is not None and cancel_event.is_set():
            raise FinanceCancelled()
        return status

    def _snapshot(self) -> list[float]:
        return [v.solution_value() for v in self.solver.variables()]

    _OK = (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

    def _solve_retry(self, deadline: float, cancel_event: threading.Event | None) -> int:
        """Solve; on a numerical failure (INFEASIBLE / ABNORMAL after earlier tiers were fixed) retry from
        scratch, then from scratch without presolve. GLOP's warm-started path occasionally reports ABNORMAL on
        the tiny tier slacks of 8.5 where a cold solve is fine."""
        status = self._solve_once(deadline, cancel_event)
        for fresh in (1, 2):
            if status in self._OK or status == pywraplp.Solver.NOT_SOLVED or time.monotonic() >= deadline:
                break
            status = self._solve_once(deadline, cancel_event, fresh=fresh)
        return status

    def lexicographic(self, deadline: float, cancel_event: threading.Event | None = None,
                      progress: Callable[[str, int, int], None] | None = None) -> OptimizerSolution:
        tiers = self.tier_list()
        diags: list[TierDiagnostic] = []
        values: dict[str, float] = {}
        snap: list[float] | None = None
        termination = "optimal"
        proven = True
        warnings = list(self.warnings)

        def attempt(name: str, expr: _Expr) -> bool:
            nonlocal snap, termination, proven
            self._set_objective(expr)
            t0 = time.monotonic()
            status = self._solve_retry(deadline, cancel_event)
            secs = round(time.monotonic() - t0, 4)
            sname = _STATUS.get(status, str(status))
            if status not in self._OK:
                diags.append(TierDiagnostic(tier=name, status=sname, objective=None, seconds=secs))
                self._last_status = status
                return False
            v = self.solver.Objective().Value()
            if status == pywraplp.Solver.FEASIBLE:
                proven = False
                termination = "gap" if termination == "optimal" else termination
            diags.append(TierDiagnostic(tier=name, status=sname, objective=self._report(name, v), seconds=secs))
            values[name] = v
            snap = self._snapshot()
            return True

        for j, (name, expr) in enumerate(tiers):
            if progress:
                progress(name, j, len(tiers))
            if attempt(name, expr):
                if j < len(tiers) - 1:
                    self._cons(expr, -self.solver.infinity(), values[name] + self.tier_eps(name, values[name]))
                continue
            if self._last_status == pywraplp.Solver.NOT_SOLVED or time.monotonic() >= deadline:
                termination = "time_limit"
                proven = False
                break
            if j == 0:
                raise RuntimeError(f"finance LP returned {diags[-1].status} at T0")
            warnings.append("TIER_NUMERIC_FALLBACK")
            # The previous tier's vertex is arbitrary in everything later tiers decide (smoothing and, via T5,
            # the 1e-4 penalty on sells u), so it can carry pure churn: sell u, buy (1 - tau) u of the same
            # class. Try the cleanup tier T5 alone on top of the tiers already fixed; keep its solution only
            # if it solves, otherwise the previous tier's (publishing then drops sell-without-buy rebalances).
            if j < len(tiers) - 1 and time.monotonic() < deadline:
                attempt(*tiers[-1])
            break
        if snap is None:
            return self._zero_solution(diags, termination, warnings)
        return self._extract(snap, diags, values, termination, proven, warnings)

    def _report(self, name: str, v: float) -> float:
        if name in ("T0", "T5"):
            return round(v / SCALE, 4)
        return round(v, 8)

    def solve_single(self, objective: _Expr, deadline: float, cancel_event: threading.Event | None = None,
                     bounds: list[tuple[_Expr, float]] | None = None) -> OptimizerSolution | None:
        for e, ub in bounds or []:
            self._cons(e, -self.solver.infinity(), ub)
        self._set_objective(objective)
        status = self._solve_once(deadline, cancel_event)
        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            return None
        snap = self._snapshot()
        return self._extract(snap, [], {}, "optimal", status == pywraplp.Solver.OPTIMAL, list(self.warnings))

    def _zero_solution(self, diags, termination, warnings) -> OptimizerSolution:
        snap = [0.0] * self.solver.NumVariables()
        return self._extract(snap, diags, {}, termination, False, warnings, zero=True)

    def _extract(self, snap: list[float], diags, values, termination, proven, warnings,
                 zero: bool = False) -> OptimizerSolution:
        S = SCALE

        def val(v) -> float:
            return max(0.0, snap[v.index()]) / S

        x = {(xv.g, xv.a, xv.k): val(xv.var) for xv in self.xvars}
        x_pay = {(xv.g, xv.a, xv.k): (xv.pay_start, xv.pay_end) for xv in self.xvars}
        y = {k: val(v) for k, v in self.y.items()}
        w = {k: val(v) for k, v in self.w.items()}
        d = [val(v) for v in self.dv]
        B = [self.proj.cash_buffer_initial + (1 - self.tau) * sum(w.values())] + [val(v) for v in self.Bv[1:]]
        if zero:
            # greedy just-in-time deficits of the zero-contribution plan
            Bc = self.proj.cash_buffer_initial
            d = []
            B = [Bc]
            for t in range(self.T):
                avail = Bc + self.proj.investable[t]
                dt = max(0.0, self.m_buf - avail)
                d.append(dt)
                Bc = (avail + dt) * self.gamma_c
                B.append(Bc)
        binding = []
        tol = 1.0
        for t in range(self.T):
            if B[t + 1] / self.gamma_c <= self.m_buf + tol:
                binding.append(t)
        return OptimizerSolution(
            status="ok", termination_reason=termination, optimality_proven=proven, solver=self.solver_name,
            x=x, x_pay=x_pay, y=y, w=w,
            F={k: val(v) for k, v in self.F.items()}, H={k: val(v) for k, v in self.H.items()},
            b={k: val(v) for k, v in self.b.items()}, u={k: val(v) for k, v in self.u.items()},
            short={k: val(v) for k, v in self.short.items()} if not zero else
            {g: gd.TR for g, gd in self.goals.items()},
            B=B, d=d, cash_deficit=sum(d), tiers=diags, tier_values=values, cash_binding=binding,
            variables=self.solver.NumVariables(), constraints=self.solver.NumConstraints(), warnings=warnings,
            goals=self.goals, extra_savings=(val(self.e_var) if self.e_var is not None else None))


_STATUS = {pywraplp.Solver.OPTIMAL: "OPTIMAL", pywraplp.Solver.FEASIBLE: "FEASIBLE",
           pywraplp.Solver.INFEASIBLE: "INFEASIBLE", pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
           pywraplp.Solver.ABNORMAL: "ABNORMAL", pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED"}


def optimize(plan: FinancePlan, proj: CashflowProjection, z: dict[str, float], *, deadline: float,
             cancel_event: threading.Event | None = None,
             progress: Callable[[str, int, int], None] | None = None) -> OptimizerSolution:
    lp = FinanceLP(plan, proj, z, cancel_event=cancel_event)
    return lp.lexicographic(deadline, cancel_event, progress)

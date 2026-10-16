"""Finance run pipeline (FINANCE.md section 10): preflight -> cash flow -> LP -> Monte Carlo -> calibration
-> independent validation -> explanations and fixes -> `FinanceResult`."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .cashflow import FlowComponents, ef_complete_t, flow_components, locked_index, project_cashflow
from .model import (AssumptionsUsed, CashflowProjection, ContributionLine, Diagnostics, FinanceCancelled,
                    FinancePlan, FinancePreflightError, FinanceProgress, FinanceResult, FinanceRunRequest, GlidePoint,
                    GoalResult, HoldingAssignment, Rebalance, ResultCashflow, ResultSeries, ResultSimulationSettings,
                    ResultSummary, Scenarios)
from .optimizer import FinanceLP, OptimizerSolution
from .preflight import preflight
from .returns import floor2, gamma, goal_cap, initial_z, is_risky, min_probability, pi_general
from .simulate import Policy, SimOutput, scenario_inputs, simulate
from .validator import BlockRecord, hard_violations, replay_goal, tolerances, validate_result

ProgressCb = Callable[[FinanceProgress], None]
Z_STEP = 0.25
Z_MAX = 3.0


@dataclass
class Published:
    """The exact, published decisions of one optimizer solution and their plan-basis values (8.8)."""
    plan: FinancePlan
    proj: CashflowProjection
    sol: OptimizerSolution
    z: dict[str, float]
    lines: list[ContributionLine]
    assignment: list[HoldingAssignment]
    rebalances: list[Rebalance]
    x_month: dict[str, dict[str, dict[int, float]]]
    records: dict[str, list[BlockRecord]]
    values: dict[str, float]
    X_total: list[float]
    policy: Policy
    sold_to_cash: float
    cash_end: list[float] = field(default_factory=list)


def _r2(v: float) -> float:
    return round(v + 0.0, 2)


def publish(plan: FinancePlan, proj: CashflowProjection, sol: OptimizerSolution, z: dict[str, float]) -> Published:
    T = proj.T
    months = proj.months
    P = proj.price_index
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    order = [a.id for a in plan.assumptions.asset_classes]
    cidx = {a: i for i, a in enumerate(order)}
    tau = plan.constraints.rebalance_cost_pct / 100.0
    holdings = {h.id: h for h in plan.holdings}
    goals = sol.goals
    gids = list(goals)

    # contributions, floored, merged only when identical (R10)
    x_month: dict[str, dict[str, dict[int, float]]] = {g: defaultdict(dict) for g in gids}
    lines: list[ContributionLine] = []
    X_total = [0.0] * T
    for gid in gids:
        gd = goals[gid]
        for a in gd.allowed:
            cur: list | None = None
            for (k, s, n) in gd.blocks:
                key = (gid, a, k)
                amt = floor2(sol.x.get(key, 0.0))
                if key not in sol.x or amt <= 0.0:
                    if cur:
                        lines.append(_line(gid, a, cur, months, P))
                    cur = None
                    continue
                p0, p1 = sol.x_pay[key]
                for t in range(p0, p1 + 1):
                    x_month[gid][a][t] = amt
                    X_total[t] += amt
                if cur and cur[2] == amt and cur[1] + 1 == p0:
                    cur[1] = p1
                else:
                    if cur:
                        lines.append(_line(gid, a, cur, months, P))
                    cur = [p0, p1, amt]
            if cur:
                lines.append(_line(gid, a, cur, months, P))
    # EF lines (informational, goal_id "emergency_fund")
    ef_cls = plan.emergency_fund.asset_class_id
    cur = None
    for t in range(T):
        v = _r2(proj.ef_contribution[t])
        if v <= 0:
            if cur:
                lines.append(_line("emergency_fund", ef_cls, cur, months, P))
            cur = None
            continue
        if cur and cur[2] == v and cur[1] + 1 == t:
            cur[1] = t
        else:
            if cur:
                lines.append(_line("emergency_fund", ef_cls, cur, months, P))
            cur = [t, t, v]
    if cur:
        lines.append(_line("emergency_fund", ef_cls, cur, months, P))

    # holdings assignment rows partition every holding (R26)
    rows: list[HoldingAssignment] = []
    used: dict[str, float] = defaultdict(float)
    for sp in proj.initial_splits:
        if sp.source == "pool":
            continue
        amt = _r2(sp.amount)
        if amt <= 0:
            continue
        rows.append(HoldingAssignment(holding_id=sp.holding_id, goal_id=sp.goal_id or "cash_buffer", amount=amt,
                                      source=sp.source))
        used[sp.holding_id] += amt
    sold = 0.0
    for p in proj.assignable:
        for gid in gids:
            v = floor2(sol.y.get((gid, p.holding_id), 0.0))
            if v > 0:
                rows.append(HoldingAssignment(holding_id=p.holding_id, goal_id=gid, amount=v, source="assigned"))
                used[p.holding_id] += v
        wv = floor2(sol.w.get(p.holding_id, 0.0))
        if wv > 0:
            rows.append(HoldingAssignment(holding_id=p.holding_id, goal_id="cash_buffer", amount=wv,
                                          source="sold_to_cash"))
            used[p.holding_id] += wv
            sold += wv
    for h in plan.holdings:
        rest = _r2(h.amount - used.get(h.id, 0.0))
        if rest > 0:
            rows.append(HoldingAssignment(holding_id=h.id, goal_id="unallocated", amount=rest, source="unallocated"))

    # rebalances and plan-basis values: replay with the validator's code (R10)
    rebalances: list[Rebalance] = []
    records: dict[str, list[BlockRecord]] = {}
    values: dict[str, float] = {}
    F0s: dict[str, dict[str, float]] = {}
    for gid in gids:
        gd = goals[gid]
        F0: dict[str, float] = defaultdict(float)
        locked_pos: list[tuple[str, float, int]] = []
        for r in rows:
            if r.goal_id == gid and r.source in ("earmark", "assigned"):
                h = holdings[r.holding_id]
                F0[h.asset_class_id] += r.amount
                li = locked_index(plan, h.locked_until_month)
                if li is not None and li > 0:
                    locked_pos.append((h.asset_class_id, r.amount, li))
        F0s[gid] = dict(F0)

        def reb_fn(k: int, s: int, F: dict[str, float], gid=gid, gd=gd, locked_pos=locked_pos):
            # net out same-class buy and sell (churn), then never sell more than the bucket holds
            u_net: dict[str, float] = {}
            b_net: dict[str, float] = {}
            for a in gd.bucket_classes:
                u = sol.u.get((gid, a, k), 0.0)
                b = sol.b.get((gid, a, k), 0.0)
                m = min(u, b)
                u_net[a], b_net[a] = u - m, b - m
            sells: dict[str, float] = {}
            for a in gd.bucket_classes:
                u = u_net[a]
                if u <= 0.005:
                    continue
                lockv = sum(amt * gd.rho[c] ** s for (c, amt, li) in locked_pos if c == a and li > s)
                v = floor2(min(u, max(0.0, F.get(a, 0.0) - lockv)))
                if v > 0:
                    sells[a] = v
            bsum = sum(b_net.values())
            buys: dict[str, float] = {}
            if bsum > 0 and sells:
                ratio = (1.0 - tau) * sum(sells.values()) / bsum
                for a in gd.bucket_classes:
                    b = b_net[a]
                    if b > 0.005:
                        v = floor2(b * ratio)
                        if v > 0:
                            buys[a] = v
            if sells or buys:
                rebalances.append(Rebalance(month=months[s], goal_id=gid, sells=sells, buys=buys))
            return sells, buys

        recs, Fend = replay_goal(classes, gd.rho, F0, gd.blocks, reb_fn, x_month[gid])
        records[gid] = recs
        values[gid] = sum(Fend.values())
    rebalances.sort(key=lambda r: (r.month, gids.index(r.goal_id)))

    # cash buffer recomputed from the published decisions
    pi = pi_general(plan)
    cash_ac = classes.get(plan.assumptions.cash_class_id)
    gc = gamma(cash_ac, pi) if cash_ac is not None else 1.0
    B = proj.cash_buffer_initial + (1.0 - tau) * sold
    cash_end = []
    for t in range(T):
        B = (B + proj.investable[t] - X_total[t]) * gc
        cash_end.append(B)

    # Monte Carlo policy
    G, A = len(gids), len(order)
    X = np.zeros((G, A, T))
    F0a = np.zeros((G, A))
    reb_at: dict[int, list[tuple[int, np.ndarray]]] = defaultdict(list)
    for gi, gid in enumerate(gids):
        for a, by_t in x_month[gid].items():
            for t, v in by_t.items():
                X[gi, cidx[a], t] = v
        for a, v in F0s[gid].items():
            F0a[gi, cidx[a]] = v
        for rec in records[gid]:
            tot = sum(rec.H.values())
            if tot > 1e-9:
                w = np.zeros(A)
                for a, v in rec.H.items():
                    w[cidx[a]] = max(v, 0.0) / tot
                reb_at[rec.s].append((gi, w))
    U0 = np.zeros(A)
    for r in rows:
        if r.source == "unallocated":
            U0[cidx[holdings[r.holding_id].asset_class_id]] += r.amount
    tier_map = {"must": 0, "should": 1, "nice": 2}
    policy = Policy(goal_ids=gids, D=np.array([goals[g].D for g in gids], dtype=int),
                    TR=np.array([goals[g].TR for g in gids]), tier=np.array([tier_map[goals[g].tier] for g in gids]),
                    X=X, F0=F0a, rebalance=dict(reb_at), ef0=proj.ef_initial,
                    b0=proj.cash_buffer_initial + (1.0 - tau) * sold, U0=U0)
    return Published(plan=plan, proj=proj, sol=sol, z=dict(z), lines=lines, assignment=rows, rebalances=rebalances,
                     x_month=x_month, records=records, values=values, X_total=X_total, policy=policy,
                     sold_to_cash=sold, cash_end=cash_end)


def _line(gid: str, a: str, cur: list, months: list[str], P: list[float]) -> ContributionLine:
    p0, p1, amt = cur
    return ContributionLine(goal_id=gid, asset_class_id=a, start_month=months[p0], end_month=months[p1],
                            monthly_amount_real=amt, monthly_amount_nominal_start=_r2(amt * P[p0]),
                            monthly_amount_nominal_end=_r2(amt * P[p1]))


@dataclass
class Evaluated:
    pub: Published
    sim: SimOutput


class _Run:
    def __init__(self, plan: FinancePlan, request: FinanceRunRequest, progress_cb: ProgressCb | None,
                 cancel_event: threading.Event | None):
        self.plan = plan
        self.req = request
        self.cb = progress_cb
        self.cancel = cancel_event
        self.t0 = time.monotonic()
        self.deadline = self.t0 + request.time_limit_seconds

    def emit(self, stage: str, fraction: float, message: str = "", **detail) -> None:
        if self.cb is not None:
            self.cb(FinanceProgress(stage=stage, fraction=max(0.0, min(1.0, fraction)), message=message,
                                    detail=detail))

    def check(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise FinanceCancelled()

    def solve(self, plan: FinancePlan, proj: CashflowProjection, z: dict[str, float], stage: str) -> OptimizerSolution:
        lp = FinanceLP(plan, proj, z, cancel_event=self.cancel)

        def prog(name: str, j: int, n: int) -> None:
            self.emit(stage, j / max(1, n), f"Optimizing ({name})", tier=name)
        return lp.lexicographic(self.deadline, self.cancel, prog)

    def evaluate(self, plan, fc, proj, z, n_paths: int, stage: str) -> Evaluated:
        sol = self.solve(plan, proj, z, "optimize" if stage == "optimize" else stage)
        self.check()
        pub = publish(plan, proj, sol, z)
        sim = self.simulate(plan, fc, proj, pub, n_paths, stage="simulate" if stage == "optimize" else stage)
        return Evaluated(pub=pub, sim=sim)

    def simulate(self, plan, fc, proj, pub: Published, n_paths: int, stage: str = "simulate") -> SimOutput:
        def prog(t: int, T: int) -> None:
            self.emit(stage, t / max(1, T), "Simulating outcomes", paths=n_paths, month=t)
        return simulate(plan, fc, proj, pub.policy, n_paths=n_paths, seed=self.req.seed,
                        interruption=self.req.simulation.income_interruption, cancel_event=self.cancel,
                        progress=prog)


def run_plan(plan: FinancePlan, request: FinanceRunRequest | None = None, progress_cb: ProgressCb | None = None,
             cancel_event: threading.Event | None = None) -> FinanceResult:
    request = request or FinanceRunRequest()
    run = _Run(plan, request, progress_cb, cancel_event)

    run.emit("preflight", 0.0, "Checking the plan")
    report = preflight(plan)
    if not report.ok:
        raise FinancePreflightError(report)
    run.emit("preflight", 1.0, "Plan checked")
    run.check()

    run.emit("cashflow", 0.0, "Projecting cash flow")
    proj = project_cashflow(plan)
    fc = flow_components(plan)
    run.emit("cashflow", 1.0, "Cash flow projected")
    run.check()

    goals = [g for g in plan.goals if g.enabled]
    z = {g.id: initial_z(g) for g in goals}
    n_paths = request.simulation.n_paths
    run.emit("optimize", 0.0, "Optimizing")
    cur = run.evaluate(plan, fc, proj, z, n_paths, "optimize")
    run.emit("simulate", 1.0, "Simulation complete")
    run.check()

    # ---- calibration (10.2 step 5)
    rounds_done = 0
    if request.calibration_rounds > 0 and goals:
        run.emit("calibrate", 0.0, "Calibrating caution")
    for rnd in range(request.calibration_rounds):
        if time.monotonic() >= run.deadline:
            break
        idx = {g: i for i, g in enumerate(cur.pub.policy.goal_ids)}
        new_z = dict(cur.pub.z)
        changed = []
        for g in goals:
            prob = float(cur.sim.success[idx[g.id]])
            if cur.pub.sol.short.get(g.id, 0.0) <= 1.0 and prob < min_probability(g) - 0.02 and new_z[g.id] < Z_MAX:
                new_z[g.id] = min(Z_MAX, new_z[g.id] + Z_STEP)
                changed.append(g.id)
        if not changed:
            break
        run.emit("calibrate", rnd / max(1, request.calibration_rounds), f"Calibration round {rnd + 1}",
                 round=rnd + 1)
        cand = run.evaluate(plan, fc, proj, new_z, n_paths, "calibrate")
        run.check()
        must_old = sum(v for g, v in cur.pub.sol.short.items() if cur.pub.sol.goals[g].tier == "must")
        must_new = sum(v for g, v in cand.pub.sol.short.items() if cand.pub.sol.goals[g].tier == "must")
        cidx = {g: i for i, g in enumerate(cand.pub.policy.goal_ids)}
        prob_drop = any(cand.sim.success[cidx[g]] < cur.sim.success[idx[g]] - 1e-12 for g in changed)
        if must_new > must_old + 1.0 or prob_drop:
            break
        cur = cand
        rounds_done += 1
    if request.calibration_rounds > 0 and goals:
        run.emit("calibrate", 1.0, "Calibration complete", round=rounds_done)

    result = assemble(plan, proj, fc, cur.pub, cur.sim, request, rounds_done)
    run.check()

    # ---- independent validation decides feasibility (10.2 step 6)
    run.emit("validate", 0.0, "Checking every rule")
    violations = validate_result(plan, result)
    result.violations = violations
    hard = hard_violations(violations)
    if cur.pub.sol.cash_deficit > 1.0:
        result.feasibility = "infeasible"
    elif not hard:
        result.feasibility = "feasible"
    else:
        result.feasibility = "unknown"
    run.emit("validate", 1.0, "Rules checked")
    run.check()

    # ---- explanations and fixes
    from .advisor.explain import explain
    from .advisor.fixes import compute_fixes

    fixes: dict = {}
    fix_solves = 0
    truncated = False
    if request.compute_fixes and time.monotonic() < run.deadline:
        run.emit("fixes", 0.0, "Looking for fixes")

        def quick_probability(plan2: FinancePlan, proj2: CashflowProjection, sol2: OptimizerSolution,
                              z2: dict[str, float], gid: str) -> float | None:
            pub2 = publish(plan2, proj2, sol2, z2)
            fc2 = flow_components(plan2)
            sim2 = simulate(plan2, fc2, proj2, pub2.policy, n_paths=500, seed=request.seed,
                            interruption=request.simulation.income_interruption, cancel_event=cancel_event)
            if gid not in pub2.policy.goal_ids:
                return None
            return float(sim2.success[pub2.policy.goal_ids.index(gid)])

        fixes, fix_solves, truncated = compute_fixes(
            plan, proj, cur.pub.sol, result, deadline=min(run.deadline, time.monotonic() + 10.0),
            cancel_event=cancel_event, quick_probability=quick_probability,
            progress=lambda f: run.emit("fixes", f, "Looking for fixes"))
        run.emit("fixes", 1.0, "Fixes ready")
    run.check()
    result.explanation = explain(plan, proj, cur.pub, result, fixes)
    result.diagnostics.fix_solves = fix_solves
    if truncated:
        result.diagnostics.warnings.append("FIXES_TRUNCATED")
    result.diagnostics.seconds_total = round(time.monotonic() - run.t0, 3)
    return result


def goal_status(shortfall_fraction: float, prob: float, minp: float) -> str:
    if shortfall_fraction <= 0.001 and prob >= minp:
        return "on_track"
    if prob >= minp - 0.20 or shortfall_fraction <= 0.10:
        return "at_risk"
    return "off_track"


def assemble(plan: FinancePlan, proj: CashflowProjection, fc: FlowComponents, pub: Published, sim: SimOutput,
             request: FinanceRunRequest, rounds_done: int) -> FinanceResult:
    T = proj.T
    months = proj.months
    sol = pub.sol
    classes = {a.id: a for a in plan.assumptions.asset_classes}
    order = [a.id for a in plan.assumptions.asset_classes]
    pi = pi_general(plan)
    scen = {w: simulate(plan, fc, proj, pub.policy, n_paths=1, seed=0, scenario=scenario_inputs(plan, w))
            for w in ("low", "central", "high")}
    central = scen["central"]
    goal_results: list[GoalResult] = []
    sc_goals: dict[str, dict[str, float]] = {}
    planning_returns: dict[str, dict[str, float]] = {}
    glide_paths: dict[str, list[GlidePoint]] = {}
    for gi, gid in enumerate(pub.policy.goal_ids):
        gd = sol.goals[gid]
        g = gd.goal
        value = pub.values[gid]
        short = max(0.0, gd.TR - value)
        frac = short / gd.TR if gd.TR > 0 else 0.0
        prob = float(sim.success[gi])
        minp = min_probability(g)
        xs = pub.x_month[gid]
        paying = sorted({t for a in xs for t, v in xs[a].items() if v > 0})
        now = sum(xs[a].get(0, 0.0) for a in xs)
        total = sum(v for a in xs for v in xs[a].values())
        held = sum(r.amount for r in pub.assignment if r.goal_id == gid and r.source in ("earmark", "assigned"))
        alloc: dict[str, float] = {}
        if paying:
            t1 = paying[0]
            tot = sum(xs[a].get(t1, 0.0) for a in xs)
            alloc = {a: round(100.0 * xs[a].get(t1, 0.0) / tot, 1) for a in order if xs.get(a, {}).get(t1, 0.0) > 0}
        elif pub.records[gid]:
            H = pub.records[gid][0].H
            tot = sum(H.values())
            if tot > 0:
                alloc = {a: round(100.0 * H[a] / tot, 1) for a in order if H.get(a, 0.0) > 0.005}
        sc = {w: float(scen[w].values[0, gi]) for w in scen}
        sc_goals[gid] = {w: round(v, 2) for w, v in sc.items()}
        planning_returns[gid] = {a: round(100.0 * (gd.rho[a] ** 12 - 1.0), 2) for a in gd.bucket_classes}
        pts = []
        for rec in pub.records[gid]:
            tot = sum(rec.H.values())
            risky = sum(v for a, v in rec.H.items() if is_risky(classes[a]))
            pts.append(GlidePoint(month=months[rec.s], months_to_goal=gd.D - rec.s,
                                  risky_cap_pct=round(100.0 * goal_cap(plan, g, gd.D, rec.s), 2),
                                  risky_share_pct=round(100.0 * risky / tot, 2) if tot > 1e-9 else 0.0,
                                  weights_pct={a: round(100.0 * v / tot, 2) for a, v in rec.H.items()
                                               if tot > 1e-9 and v > 0.005}))
        glide_paths[gid] = pts
        goal_results.append(GoalResult(
            goal_id=gid, name=g.name, kind=g.kind, priority=g.priority, target_month=g.target_month,
            months_to_goal=gd.D, target_amount=g.target_amount, target_real=_r2(gd.TR),
            target_nominal_expected=_r2(gd.TR * (1.0 + pi) ** (gd.D / 12.0)), planned_value_real=_r2(value),
            projected_central_real=_r2(sc["central"]), shortfall_real=_r2(short), shortfall_fraction=round(frac, 6),
            success_probability=round(prob, 4), min_success_probability=minp, p10_real=_r2(float(sim.p10[gi])),
            p50_real=_r2(float(sim.p50[gi])), p90_real=_r2(float(sim.p90[gi])),
            expected_shortfall_real=_r2(float(sim.expected_shortfall[gi])), scenario_low_real=_r2(sc["low"]),
            scenario_high_real=_r2(sc["high"]), status=goal_status(frac, prob, minp),
            contribution_start_month=months[paying[0]] if paying else None,
            contribution_end_month=months[paying[-1]] if paying else None, monthly_contribution_now=_r2(now),
            total_contributions_real=_r2(total), holdings_used_real=_r2(held), allocation_now_pct=alloc,
            planning_z=pub.z[gid]))
    tE = ef_complete_t(proj)
    summary = ResultSummary(
        goals_total=len(goal_results), goals_on_track=sum(1 for g in goal_results if g.status == "on_track"),
        goals_at_risk=sum(1 for g in goal_results if g.status == "at_risk"),
        goals_off_track=sum(1 for g in goal_results if g.status == "off_track"),
        monthly_investable_now=_r2(proj.investable[0]), monthly_contribution_now=_r2(pub.X_total[0]),
        emergency_fund_target=_r2(proj.ef_target), emergency_fund_now=_r2(proj.ef_initial),
        emergency_fund_complete_month=months[tE] if tE < T else None,
        liquidity_risk_probability=round(sim.liquidity_risk, 4), total_contributions_real=_r2(sum(pub.X_total)))
    corpus = {}
    for i, a in enumerate(order):
        series = central.corpus_by_class[i]
        if np.any(series > 0.005):
            corpus[a] = [_r2(v) for v in series]
    series = ResultSeries(months=months, corpus_by_class=corpus, emergency_fund=[_r2(v) for v in central.ef_series],
                          cash_buffer=[_r2(v) for v in central.cash_series],
                          unallocated=[_r2(v) for v in central.unallocated_series],
                          goal_withdrawals=[_r2(v) for v in central.withdrawals],
                          total_p10=[_r2(v) for v in sim.total_q[0]], total_p50=[_r2(v) for v in sim.total_q[1]],
                          total_p90=[_r2(v) for v in sim.total_q[2]])
    cash = ResultCashflow(months=months, income=_l(proj.income), essential=_l(proj.essential),
                          discretionary=_l(proj.discretionary), debt_payments=_l(proj.debt_payments),
                          one_off_net=_l(proj.one_off_net), surplus=_l(proj.surplus),
                          emergency_fund_contribution=_l(proj.ef_contribution), goal_contribution=_l(pub.X_total),
                          cash_buffer_end=_l(pub.cash_end))
    assumptions_used = AssumptionsUsed(
        inflation_pct=plan.assumptions.inflation_pct,
        asset_classes=[classes[a] for a in order], glide_path=list(plan.assumptions.glide_path),
        risky_cap_by_tolerance_pct=list(plan.assumptions.risky_cap_by_tolerance_pct),
        planning_returns_pct=planning_returns, source_note=plan.assumptions.source_note)
    diag = Diagnostics(solver=sol.solver, variables=sol.variables, constraints=sol.constraints, tiers=sol.tiers,
                       calibration_rounds=rounds_done, simulation_seconds=round(sim.seconds, 3),
                       warnings=list(sol.warnings), cash_deficit_real=round(sol.cash_deficit, 2))
    return FinanceResult(
        start_month=plan.start_month, horizon_months=T, end_month=months[-1], currency=plan.profile.currency,
        termination_reason=sol.termination_reason, optimality_proven=sol.optimality_proven, summary=summary,
        goals=goal_results, contributions=pub.lines, holdings_assignment=pub.assignment, rebalances=pub.rebalances,
        glide_paths=glide_paths, series=series, cashflow=cash,
        scenarios=Scenarios(goals=sc_goals), assumptions_used=assumptions_used,
        simulation_settings=ResultSimulationSettings(
            n_paths=request.simulation.n_paths, income_interruption=request.simulation.income_interruption,
            seed=request.seed),
        diagnostics=diag)


def _l(xs) -> list[float]:
    return [_r2(float(v)) for v in xs]


__all__ = ["run_plan", "publish", "assemble", "goal_status", "Published", "tolerances"]

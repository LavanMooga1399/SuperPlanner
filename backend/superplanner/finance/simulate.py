"""Monte Carlo and deterministic scenarios (FINANCE.md section 9). numpy only, vectorized over paths.

The simulator executes the plan's *policy* (planned real contribution amounts, rebalance target weights per
goal and block, EF rules, cash priority) under random returns, inflation and income interruptions.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .cashflow import FlowComponents
from .model import CashflowProjection, FinanceCancelled, FinancePlan, IncomeInterruption
from .preflight import correlation_matrix

TIER_INDEX = {"must": 0, "should": 1, "nice": 2}


@dataclass
class Policy:
    goal_ids: list[str]
    D: np.ndarray                 # (G,)
    TR: np.ndarray                # (G,) real targets
    tier: np.ndarray              # (G,) 0 must, 1 should, 2 nice
    X: np.ndarray                 # (G, A, T) planned real contributions
    F0: np.ndarray                # (G, A) initial buckets (earmarks + assignments)
    rebalance: dict[int, list[tuple[int, np.ndarray]]]   # t -> [(goal index, target weights (A,))]
    ef0: float
    b0: float
    U0: np.ndarray                # (A,) unallocated holdings by class


@dataclass
class SimOutput:
    values: np.ndarray            # (n, G) real value at D_g
    success: np.ndarray           # (G,)
    p10: np.ndarray
    p50: np.ndarray
    p90: np.ndarray
    expected_shortfall: np.ndarray
    liquidity_risk: float
    total_q: np.ndarray           # (3, T) p10/p50/p90 of total real wealth
    # filled for single-path runs (scenarios)
    corpus_by_class: np.ndarray | None = None   # (A, T)
    ef_series: np.ndarray | None = None
    cash_series: np.ndarray | None = None
    unallocated_series: np.ndarray | None = None
    withdrawals: np.ndarray | None = None
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)


def repair_correlation(C: np.ndarray) -> tuple[np.ndarray, bool]:
    """Eigenvalue clip at 1e-8 and diagonal rescale to 1 when C is not PSD (9.1)."""
    w, V = np.linalg.eigh(C)
    if w.min() >= -1e-10:
        return C, False
    w = np.clip(w, 1e-8, None)
    R = (V * w) @ V.T
    d = np.sqrt(np.diag(R))
    R = R / np.outer(d, d)
    np.fill_diagonal(R, 1.0)
    return R, True


def cholesky(C: np.ndarray) -> np.ndarray:
    C, _ = repair_correlation(C)
    try:
        return np.linalg.cholesky(C)
    except np.linalg.LinAlgError:
        return np.linalg.cholesky(C + 1e-9 * np.eye(len(C)))


def lognormal_params(plan: FinancePlan) -> tuple[np.ndarray, np.ndarray]:
    """Monthly log-return mean `m_a` and annual log std `s_a` per class (9.1)."""
    m, s = [], []
    for ac in plan.assumptions.asset_classes:
        mu = ac.expected_return_pct / 100.0
        net = 1.0 + mu - ac.expense_ratio_pct / 100.0 - ac.tax_drag_pct / 100.0
        sig = ac.volatility_pct / 100.0
        sa = float(np.sqrt(np.log(1.0 + (sig / (1.0 + mu)) ** 2))) if 1.0 + mu > 0 else 0.0
        m.append((np.log(max(net, 1e-6)) - sa ** 2 / 2.0) / 12.0)
        s.append(sa)
    return np.array(m), np.array(s)


def sample_monthly_log_returns(plan: FinancePlan, n: int, seed: int) -> np.ndarray:
    """(n, A) draws of one month of correlated log returns (used by tests of the return model)."""
    rng = np.random.default_rng(seed)
    m, s = lognormal_params(plan)
    Lc = cholesky(correlation_matrix(plan))
    eps = rng.standard_normal((n, len(m)))
    return m + (s / np.sqrt(12.0)) * (eps @ Lc.T)


def simulate(plan: FinancePlan, fc: FlowComponents, proj: CashflowProjection, policy: Policy, *, n_paths: int,
             seed: int, interruption: IncomeInterruption | None = None,
             scenario: tuple[np.ndarray, float] | None = None,
             cancel_event: threading.Event | None = None,
             progress: Callable[[int, int], None] | None = None) -> SimOutput:
    """Run the policy. `scenario = (annual net returns per class, annual inflation)` gives a single
    deterministic path (9.4); otherwise `n_paths` random paths with `seed`."""
    import time

    t_start = time.monotonic()
    T = proj.T
    classes = plan.assumptions.asset_classes
    A = len(classes)
    cidx = {a.id: i for i, a in enumerate(classes)}
    ef_i = cidx.get(plan.emergency_fund.asset_class_id, 0)
    cash_i = cidx.get(plan.assumptions.cash_class_id, 0)
    lock = np.array([a.lock_in_months > 0 for a in classes])
    free = ~lock
    G = len(policy.goal_ids)
    tau = plan.constraints.rebalance_cost_pct / 100.0
    m_buf = plan.constraints.min_cash_buffer
    ef_star = proj.ef_target
    share = plan.emergency_fund.build_share
    pi = plan.assumptions.inflation_pct / 100.0
    Y = (T + 11) // 12

    if scenario is None:
        n = n_paths
        rng = np.random.default_rng(seed)
        sig_pi = plan.assumptions.inflation_volatility_pct / 100.0
        infl = np.maximum(-0.02, pi + sig_pi * rng.standard_normal((n, Y)))
        flags_u = rng.random((n, Y))
        offsets = rng.integers(0, 12, size=(n, Y))
        m, s = lognormal_params(plan)
        Lc = cholesky(correlation_matrix(plan))
        sd = s / np.sqrt(12.0)
    else:
        n = 1
        rng = None
        r_ann, pi_s = scenario
        infl = np.full((1, Y), pi_s)
        flags_u = np.ones((1, Y))
        offsets = np.zeros((1, Y), dtype=int)
        fixed_l = np.log(np.maximum(1.0 + r_ann, 1e-6)) / 12.0
    spells_on = scenario is None and interruption is not None and interruption.enabled
    if spells_on:
        flags = flags_u < interruption.annual_probability
        dur = interruption.duration_months
        starts = 12 * np.arange(Y)[None, :] + offsets
    monthly_infl = (1.0 + infl) ** (1.0 / 12.0)

    buckets = np.repeat(policy.F0[None, :, :], n, axis=0).astype(float)   # (n, G, A) nominal
    EF = np.full(n, policy.ef0)
    B = np.full(n, policy.b0)
    U = np.repeat(policy.U0[None, :], n, axis=0).astype(float)
    P = np.ones(n)
    values = np.zeros((n, G))
    short_flag = np.zeros(n, dtype=bool)
    total_q = np.zeros((3, T))
    single = scenario is not None
    if single:
        corpus = np.zeros((A, T))
        ef_s = np.zeros(T)
        cash_s = np.zeros(T)
        un_s = np.zeros(T)
        wd = np.zeros(T)
    goal_at: dict[int, list[int]] = {}
    for gi, D in enumerate(policy.D):
        goal_at.setdefault(int(D), []).append(gi)
    tiers = [np.where(policy.tier == k)[0] for k in range(3)]

    for t in range(T):
        if t % 12 == 0:
            if cancel_event is not None and cancel_event.is_set():
                raise FinanceCancelled()
            if progress is not None:
                progress(t, T)
        # goal payments at the start of month t
        paid_real = np.zeros(n)
        for gi in goal_at.get(t, []):
            tot = buckets[:, gi, :].sum(axis=1)
            V = tot / P
            values[:, gi] = V
            need = policy.TR[gi] * P
            B += np.maximum(tot - need, 0.0)
            paid_real += np.minimum(V, policy.TR[gi])
            buckets[:, gi, :] = 0.0
        W = (buckets.sum(axis=(1, 2)) + EF + B + U.sum(axis=1)) / P
        if single:
            corpus[:, t] = buckets[0].sum(axis=0) / P[0]
            ef_s[t] = EF[0] / P[0]
            cash_s[t] = B[0] / P[0]
            un_s[t] = U[0].sum() / P[0]
            wd[t] = paid_real[0]
            total_q[:, t] = W[0]
        else:
            total_q[:, t] = np.quantile(W, [0.1, 0.5, 0.9])

        # 1. cash flow of the month (nominal)
        inc = fc.inc_nonint[t] + fc.inc_int[t] * np.ones(n)
        if spells_on:
            yt = t // 12
            in_spell = np.zeros(n, dtype=bool)
            for y in range(max(0, yt - 2), yt + 1):
                in_spell |= flags[:, y] & (starts[:, y] <= t) & (t < starts[:, y] + dur)
            inc = fc.inc_nonint[t] + np.where(in_spell, 0.0, fc.inc_int[t])
        C = B + inc + fc.real_linked[t] * P + fc.nominal_fixed[t]
        # 2. cover a deficit from the EF
        neg = C < 0
        if neg.any():
            draw = np.where(neg, np.minimum(EF, -C), 0.0)
            EF -= draw
            C += draw
            short_flag |= C < -1.0 * P
            C = np.maximum(C, 0.0)
        # 3. EF build / rebuild
        target = ef_star * P
        if ef_star > 0:
            ef = np.minimum(share * np.maximum(C - m_buf * P, 0.0), np.maximum(target - EF, 0.0))
            EF += ef
            C -= ef
        # 4. rebalance goals whose block starts now
        for gi, w in policy.rebalance.get(t, []):
            cur = buckets[:, gi, :]
            wf = w * free
            ws = wf.sum()
            if ws <= 0:
                continue
            tot_free = (cur * free).sum(axis=1)
            tgt = tot_free[:, None] * (wf / ws)[None, :]
            cost = tau * 0.5 * np.abs(tgt - cur * free).sum(axis=1)
            scale = np.where(tot_free > 0, (tot_free - cost) / np.where(tot_free > 0, tot_free, 1.0), 0.0)
            tgt = tgt * scale[:, None]
            buckets[:, gi, :] = np.where(free[None, :], tgt, cur)
        # 5. contributions, tier by tier from the free cash above the buffer
        avail = np.maximum(C - m_buf * P, 0.0)
        ef_ok = EF >= target - 1.0 * P
        for k in range(3):
            gis = tiers[k]
            if len(gis) == 0:
                continue
            need = policy.X[gis, :, t][None, :, :] * P[:, None, None]       # (n, g, A)
            tot = need.sum(axis=(1, 2))
            if k > 0:
                tot = np.where(ef_ok, tot, 0.0)
            if not tot.any():
                continue
            frac = np.where(tot > 0, np.minimum(1.0, avail / np.where(tot > 0, tot, 1.0)), 0.0)
            pay = need * frac[:, None, None]
            buckets[:, gis, :] += pay
            paid = pay.sum(axis=(1, 2))
            C -= paid
            avail -= paid
        B = C
        # 6. returns over the month
        if single:
            growth = np.exp(fixed_l)[None, :]
        else:
            eps = rng.standard_normal((n, A))
            growth = np.exp(m[None, :] + sd[None, :] * (eps @ Lc.T))
        buckets *= growth[:, None, :]
        EF *= growth[:, ef_i]
        B *= growth[:, cash_i]
        U *= growth
        P = P * monthly_infl[:, t // 12]

    TRv = policy.TR[None, :]
    success = (values >= TRv - 1.0).mean(axis=0) if G else np.zeros(0)
    q = np.quantile(values, [0.1, 0.5, 0.9], axis=0) if G else np.zeros((3, 0))
    es = np.maximum(TRv - values, 0.0).mean(axis=0) if G else np.zeros(0)
    out = SimOutput(values=values, success=success, p10=q[0], p50=q[1], p90=q[2], expected_shortfall=es,
                    liquidity_risk=float(short_flag.mean()), total_q=total_q,
                    seconds=time.monotonic() - t_start)
    if single:
        out.corpus_by_class = corpus
        out.ef_series = ef_s
        out.cash_series = cash_s
        out.unallocated_series = un_s
        out.withdrawals = wd
    return out


def scenario_inputs(plan: FinancePlan, which: str) -> tuple[np.ndarray, float]:
    """Fixed annual net returns and inflation of the low / central / high scenarios (9.4)."""
    pi = plan.assumptions.inflation_pct / 100.0
    r = []
    for ac in plan.assumptions.asset_classes:
        mu = ac.expected_return_pct / 100.0
        sig = ac.volatility_pct / 100.0
        shift = {"low": -0.5, "central": 0.0, "high": 0.5}[which] * sig
        r.append(mu + shift - ac.expense_ratio_pct / 100.0 - ac.tax_drag_pct / 100.0)
    dpi = {"low": 0.01, "central": 0.0, "high": -0.01}[which]
    return np.array(r), pi + dpi

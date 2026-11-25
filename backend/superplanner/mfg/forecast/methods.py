"""Vectorised forecasting models (M8-DESIGN 4.2). Pure numpy, deterministic, no randomness.

Every model works on `Y[items, n]` (all rows of the same length, aligned at the first non-zero period) and returns
`Fit(fitted, forecast, params)`:

- `fitted[i, t]` = the one-step-ahead forecast of `Y[i, t]` made at `t - 1` (NaN where the model has no forecast
  yet, e.g. during the first season of Holt-Winters);
- `forecast[i, k]` = the k+1-step forecast from the end of the series;
- `params[i]` = the chosen grid point per item.

Grid fits: for each grid point the whole matrix is run at once; per item the point with the minimum in-sample
mean squared one-step error wins (the first grid point on ties: fixed grid order). Negative forecasts are clipped
at 0 by the caller (`select.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable

import numpy as np

ALPHAS = (0.05, 0.1, 0.2, 0.3, 0.5)
BETAS = (0.02, 0.05, 0.1, 0.2)
PHIS = (0.9, 0.95, 0.98)
GAMMAS = (0.05, 0.1, 0.2)
MA_NS = (3, 6, 12)
CROSTON_ALPHAS = (0.05, 0.1, 0.2)
#: simplest first (selection tie-break, 4.2)
SIMPLICITY = ("zero", "snaive", "ma", "ses", "croston", "sba", "holt_damped", "hw_add", "hw_mul")


@dataclass
class Fit:
    fitted: np.ndarray            # (N, n)
    forecast: np.ndarray          # (N, h)
    params: list[dict[str, float]]


def _mse(Y: np.ndarray, fitted: np.ndarray) -> np.ndarray:
    err = Y - fitted
    ok = ~np.isnan(err)
    cnt = ok.sum(axis=1)
    sse = np.where(ok, err, 0.0) ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, sse.sum(axis=1) / np.maximum(cnt, 1), np.inf)


def _grid(Y: np.ndarray, h: int, grid: list[dict[str, float]],
          run: Callable[[np.ndarray, int, dict[str, float]], tuple[np.ndarray, np.ndarray]]) -> Fit:
    N = Y.shape[0]
    best = np.full(N, np.inf)
    fitted = np.full(Y.shape, np.nan)
    fc = np.zeros((N, h))
    choice = np.zeros(N, dtype=int)
    for gi, g in enumerate(grid):
        f, p = run(Y, h, g)
        score = _mse(Y, f)
        better = score < best - 1e-12
        if gi == 0:
            better = np.ones(N, dtype=bool)
        best = np.where(better, score, best)
        fitted[better] = f[better]
        fc[better] = p[better]
        choice[better] = gi
    return Fit(fitted, fc, [dict(grid[c]) for c in choice])


# ---------------------------------------------------------------- simple models

def zero(Y: np.ndarray, h: int) -> Fit:
    N, n = Y.shape
    return Fit(np.zeros((N, n)), np.zeros((N, h)), [{} for _ in range(N)])


def snaive(Y: np.ndarray, h: int, m: int) -> Fit:
    N, n = Y.shape
    fitted = np.full((N, n), np.nan)
    if n > m:
        fitted[:, m:] = Y[:, :-m]
    idx = [n - m + (k % m) for k in range(h)]
    fc = Y[:, idx] if n >= m else np.repeat(Y[:, -1:], h, axis=1)
    return Fit(fitted, fc.astype(float), [{"m": float(m)} for _ in range(N)])


def _ma_run(Y: np.ndarray, h: int, g: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    k = int(g["n"])
    N, n = Y.shape
    fitted = np.full((N, n), np.nan)
    if n <= k:
        return fitted, np.repeat(Y.mean(axis=1, keepdims=True), h, axis=1)
    c = np.cumsum(np.concatenate([np.zeros((N, 1)), Y], axis=1), axis=1)
    fitted[:, k:] = (c[:, k:n] - c[:, 0:n - k]) / k
    last = (c[:, n] - c[:, n - k]) / k
    return fitted, np.repeat(last[:, None], h, axis=1)


def ma(Y: np.ndarray, h: int) -> Fit:
    n = Y.shape[1]
    grid = [{"n": float(k)} for k in MA_NS if k < n] or [{"n": float(max(1, n - 1))}]
    return _grid(Y, h, grid, _ma_run)


def _ses_run(Y: np.ndarray, h: int, g: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    a = g["alpha"]
    N, n = Y.shape
    fitted = np.full((N, n), np.nan)
    lvl = Y[:, 0].astype(float).copy()
    for t in range(1, n):
        fitted[:, t] = lvl
        lvl = a * Y[:, t] + (1 - a) * lvl
    return fitted, np.repeat(lvl[:, None], h, axis=1)


def ses(Y: np.ndarray, h: int) -> Fit:
    return _grid(Y, h, [{"alpha": a} for a in ALPHAS], _ses_run)


def _holt_run(Y: np.ndarray, h: int, g: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    a, b, phi = g["alpha"], g["beta"], g["phi"]
    N, n = Y.shape
    fitted = np.full((N, n), np.nan)
    lvl = Y[:, 0].astype(float).copy()
    k0 = min(n - 1, 3)
    trend = (Y[:, k0] - Y[:, 0]) / k0 if k0 > 0 else np.zeros(N)
    for t in range(1, n):
        f = lvl + phi * trend
        fitted[:, t] = f
        new = a * Y[:, t] + (1 - a) * f
        trend = b * (new - lvl) + (1 - b) * phi * trend
        lvl = new
    damp = np.cumsum(phi ** np.arange(1, h + 1))
    return fitted, lvl[:, None] + damp[None, :] * trend[:, None]


def holt_damped(Y: np.ndarray, h: int) -> Fit:
    grid = [{"alpha": a, "beta": b, "phi": p} for a, b, p in product(ALPHAS, BETAS, PHIS)]
    return _grid(Y, h, grid, _holt_run)


def _hw_init(Y: np.ndarray, m: int, mul: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    s1 = Y[:, :m].mean(axis=1)
    s2 = Y[:, m:2 * m].mean(axis=1)
    lvl = s1.copy()
    trend = (s2 - s1) / m
    # seasonal indices from the first season around its mean, centred on the level of each period
    centre = s1[:, None] + trend[:, None] * (np.arange(m)[None, :] - (m - 1) / 2)
    if mul:
        seas = Y[:, :m] / np.where(centre > 0, centre, 1.0)
        seas = seas / np.maximum(seas.mean(axis=1, keepdims=True), 1e-12)
    else:
        seas = Y[:, :m] - centre
        seas = seas - seas.mean(axis=1, keepdims=True)
    # level / trend at the end of the first season
    lvl = s1 + trend * (m - 1) / 2
    return lvl, trend, seas


def _hw_run(mul: bool, m: int) -> Callable[[np.ndarray, int, dict[str, float]], tuple[np.ndarray, np.ndarray]]:
    def run(Y: np.ndarray, h: int, g: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        a, b, gm = g["alpha"], g["beta"], g["gamma"]
        N, n = Y.shape
        fitted = np.full((N, n), np.nan)
        lvl, trend, seas = _hw_init(Y, m, mul)
        seas = seas.copy()
        for t in range(m, n):
            s = seas[:, t % m]
            base = lvl + trend
            f = base * s if mul else base + s
            fitted[:, t] = f
            y = Y[:, t]
            if mul:
                new = a * (y / np.where(s > 1e-12, s, 1e-12)) + (1 - a) * base
                seas[:, t % m] = gm * (y / np.where(new > 1e-12, new, 1e-12)) + (1 - gm) * s
            else:
                new = a * (y - s) + (1 - a) * base
                seas[:, t % m] = gm * (y - new) + (1 - gm) * s
            trend = b * (new - lvl) + (1 - b) * trend
            lvl = new
        steps = np.arange(1, h + 1)
        s_idx = [(n + k) % m for k in range(h)]
        base = lvl[:, None] + steps[None, :] * trend[:, None]
        fc = base * seas[:, s_idx] if mul else base + seas[:, s_idx]
        return fitted, fc
    return run


def hw_add(Y: np.ndarray, h: int, m: int) -> Fit:
    grid = [{"alpha": a, "beta": b, "gamma": g} for a, b, g in product(ALPHAS, BETAS, GAMMAS)]
    return _grid(Y, h, grid, _hw_run(False, m))


def hw_mul(Y: np.ndarray, h: int, m: int) -> Fit:
    grid = [{"alpha": a, "beta": b, "gamma": g} for a, b, g in product(ALPHAS, BETAS, GAMMAS)]
    return _grid(Y, h, grid, _hw_run(True, m))


def _croston_run(factor: Callable[[float], float]) -> Callable[[np.ndarray, int, dict[str, float]],
                                                                  tuple[np.ndarray, np.ndarray]]:
    def run(Y: np.ndarray, h: int, g: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        a = g["alpha"]
        N, n = Y.shape
        fitted = np.full((N, n), np.nan)
        nz = Y > 0
        cnt = nz.sum(axis=1)
        # initial size = first non-zero demand, initial interval = mean interval of the series
        first = np.argmax(nz, axis=1)
        z = Y[np.arange(N), first].astype(float)
        p = np.where(cnt > 0, n / np.maximum(cnt, 1), 1.0).astype(float)
        q = np.ones(N)
        fac = factor(a)
        started = np.zeros(N, dtype=bool)
        for t in range(n):
            fitted[:, t] = np.where(started, fac * z / p, np.nan)
            d = nz[:, t]
            upd = d & started
            z = np.where(upd, z + a * (Y[:, t] - z), z)
            p = np.where(upd, p + a * (q - p), p)
            q = np.where(d, 1.0, q + 1.0)
            started = started | d
        return fitted, np.repeat((fac * z / p)[:, None], h, axis=1)
    return run


def croston(Y: np.ndarray, h: int) -> Fit:
    return _grid(Y, h, [{"alpha": a} for a in CROSTON_ALPHAS], _croston_run(lambda a: 1.0))


def sba(Y: np.ndarray, h: int) -> Fit:
    """Syntetos-Boylan approximation: Croston x (1 - alpha / 2)."""
    return _grid(Y, h, [{"alpha": a} for a in CROSTON_ALPHAS], _croston_run(lambda a: 1.0 - a / 2.0))


def run_method(name: str, Y: np.ndarray, h: int, m: int) -> Fit:
    if name == "zero":
        return zero(Y, h)
    if name == "snaive":
        return snaive(Y, h, m)
    if name == "ma":
        return ma(Y, h)
    if name == "ses":
        return ses(Y, h)
    if name == "holt_damped":
        return holt_damped(Y, h)
    if name == "hw_add":
        return hw_add(Y, h, m)
    if name == "hw_mul":
        return hw_mul(Y, h, m)
    if name == "croston":
        return croston(Y, h)
    if name == "sba":
        return sba(Y, h)
    raise ValueError(f"unknown method {name!r}")


def run_fixed(name: str, Y: np.ndarray, h: int, m: int, params: dict[str, float]) -> Fit:
    """One model with fixed parameters (refit of a chosen grid point / tests)."""
    if name in ("zero", "snaive"):
        return run_method(name, Y, h, m)
    runner = {"ma": _ma_run, "ses": _ses_run, "holt_damped": _holt_run, "hw_add": _hw_run(False, m),
              "hw_mul": _hw_run(True, m), "croston": _croston_run(lambda a: 1.0),
              "sba": _croston_run(lambda a: 1.0 - a / 2.0)}[name]
    f, p = runner(Y, h, params)
    return Fit(f, p, [dict(params) for _ in range(Y.shape[0])])

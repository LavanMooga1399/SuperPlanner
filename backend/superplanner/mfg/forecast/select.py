"""Demand classes and model selection by holdout WAPE (M8-DESIGN 4.2).

`select(series, bucket, horizon)` takes `{item_id: values}` (cleaned history, starting at the first non-zero
period, ending with the last closed period) and returns one result dict per item (`ItemResult` fields without
`part_number` / `abc`). Items are grouped by series length so every model runs vectorised over a group.

Rules: Syntetos-Boylan class (ADI 1.32, CV^2 0.49) restricts candidates; fewer than 3 non-zero periods -> zero
forecast + `FC_HISTORY_SHORT`. Holdout h = min(6, n // 4) (weekly min(13, n // 4)); each candidate is fitted on the
first n - h periods, forecasts h steps, WAPE = sum|e| / sum(y), bias = sum(e) / sum(y) (e = forecast - actual). The
winner (min WAPE; ties: lower |bias|, then simpler) is refitted on all n periods. Deterministic.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np

from . import methods as M

ADI_CUT = 1.32
CV2_CUT = 0.49
TIE = 1e-9


def season_length(bucket: str) -> int:
    return 52 if bucket == "w" else 12


def classify(y: np.ndarray) -> tuple[str, float | None, float | None]:
    nz = y[y > 0]
    if nz.size < 3:
        return "short", (float(y.size / nz.size) if nz.size else None), None
    adi = float(y.size / nz.size)
    mean = float(nz.mean())
    cv2 = float((nz.std() / mean) ** 2) if mean > 0 else 0.0
    if adi < ADI_CUT:
        return ("smooth" if cv2 < CV2_CUT else "erratic"), adi, cv2
    return ("intermittent" if cv2 < CV2_CUT else "lumpy"), adi, cv2


def holdout_len(n: int, bucket: str) -> int:
    return min(13 if bucket == "w" else 6, n // 4)


def candidates(cls: str, n: int, h: int, m: int, positive: bool, allowed: Iterable[str] | None = None) -> list[str]:
    """Eligible methods for a class and history length n (holdout h)."""
    if cls == "short":
        return ["zero"]
    if cls in ("intermittent", "lumpy"):
        out = [x for x in ("ma", "croston", "sba") if n >= 6] or ["ma"]
    else:
        out = []
        if n - h > m:
            out.append("snaive")
        if n >= 3:
            out += ["ma", "ses"]
        if n >= 8:
            out.append("holt_damped")
        if n >= 2 * m + h:
            out.append("hw_add")
            if positive:
                out.append("hw_mul")
        out = out or ["ma"]
    if allowed is not None:
        allowed = set(allowed)
        kept = [x for x in out if x in allowed]
        out = kept or out[:1]
    return out


def _score(actual: np.ndarray, fc: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per row: (rank score, WAPE or NaN, bias or NaN)."""
    e = fc - actual
    tot = actual.sum(axis=1)
    abs_e = np.abs(e).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        wape = np.where(tot > 0, abs_e / np.where(tot > 0, tot, 1.0), np.nan)
        bias = np.where(tot > 0, e.sum(axis=1) / np.where(tot > 0, tot, 1.0), np.nan)
    # no actual demand in the holdout: rank by absolute error (zero forecast = perfect)
    score = np.where(tot > 0, wape, abs_e * 1e6)
    return score, wape, bias


def _rmse(Y: np.ndarray, fitted: np.ndarray) -> np.ndarray:
    err = Y - fitted
    ok = ~np.isnan(err)
    cnt = ok.sum(axis=1)
    sse = (np.where(ok, err, 0.0) ** 2).sum(axis=1)
    return np.sqrt(np.where(cnt > 0, sse / np.maximum(cnt, 1), 0.0))


def select(series: dict[str, Iterable[float]], bucket: str = "m", horizon: int = 18,
           allowed: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    m = season_length(bucket)
    allowed_l = list(allowed) if allowed is not None else None
    info: dict[str, dict[str, Any]] = {}
    groups: dict[int, list[str]] = defaultdict(list)
    for item_id in sorted(series):
        y = np.asarray(list(series[item_id]), dtype=float)
        y = np.clip(y, 0, None)
        cls, adi, cv2 = classify(y)
        n = int(y.size)
        h = holdout_len(n, bucket)
        info[item_id] = {"y": y, "class": cls, "adi": adi, "cv2": cv2, "n": n, "h": h,
                         "cands": candidates(cls, n, h, m, bool(np.all(y > 0)), allowed_l)}
        groups[n].append(item_id)
    out: dict[str, dict[str, Any]] = {}
    for n, ids in groups.items():
        Y = np.vstack([info[i]["y"] for i in ids]) if n else np.zeros((len(ids), 0))
        h = holdout_len(n, bucket)
        needed = sorted({c for i in ids for c in info[i]["cands"]}, key=M.SIMPLICITY.index)
        # holdout evaluation
        scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        if h >= 1 and n - h >= 2:
            train, test = Y[:, :n - h], Y[:, n - h:]
            for meth in needed:
                rows = [k for k, i in enumerate(ids) if meth in info[i]["cands"]]
                if not rows:
                    continue
                fit = M.run_method(meth, train[rows], h, m)
                s, w, b = _score(test[rows], np.clip(fit.forecast, 0, None))
                full = [np.full(len(ids), np.inf), np.full(len(ids), np.nan), np.full(len(ids), np.nan)]
                for arr, src in zip(full, (s, w, b)):
                    arr[rows] = src
                scores[meth] = (full[0], full[1], full[2])
        winners: dict[str, str] = {}
        for k, i in enumerate(ids):
            cands = info[i]["cands"]
            if not scores or len(cands) == 1:
                winners[i] = cands[0] if cands else "zero"
                continue
            best = None
            for meth in sorted(cands, key=M.SIMPLICITY.index):
                if meth not in scores:
                    continue
                sc, _w, bi = scores[meth][0][k], scores[meth][1][k], scores[meth][2][k]
                key = (sc, abs(bi) if not np.isnan(bi) else 0.0)
                if best is None or key[0] < best[0][0] - TIE or (
                        abs(key[0] - best[0][0]) <= TIE and key[1] < best[0][1] - TIE):
                    best = (key, meth)
            winners[i] = best[1] if best else cands[0]
        # refit winners on the full series
        by_meth: dict[str, list[int]] = defaultdict(list)
        for k, i in enumerate(ids):
            by_meth[winners[i]].append(k)
        for meth, rows in by_meth.items():
            fit = M.run_method(meth, Y[rows], horizon, m)
            rmse = _rmse(Y[rows], fit.fitted)
            fcs = np.clip(fit.forecast, 0, None)
            for j, k in enumerate(rows):
                i = ids[k]
                inf = info[i]
                cand_scores = {c: (None if c not in scores or np.isnan(scores[c][1][k]) else
                                   round(float(scores[c][1][k]), 6)) for c in inf["cands"]}
                w = scores.get(meth, (None, np.array([np.nan] * len(ids)), np.array([np.nan] * len(ids))))
                wape = None if np.isnan(w[1][k]) else float(w[1][k])
                bias = None if np.isnan(w[2][k]) else float(w[2][k])
                flags = ["FC_HISTORY_SHORT"] if inf["class"] == "short" else []
                tail = [float(v) if not np.isnan(v) else 0.0 for v in fit.fitted[j, -12:]]
                out[i] = {"item_id": i, "demand_class": inf["class"], "adi": inf["adi"], "cv2": inf["cv2"],
                          "method": meth, "params": {k2: float(v) for k2, v in fit.params[j].items()},
                          "holdout_wape": wape, "bias": bias, "rmse1": float(rmse[j]),
                          "mean": float(inf["y"].mean()) if n else 0.0, "n_periods": n, "flags": flags,
                          "fitted_tail": tail, "forecast": [float(v) for v in fcs[j]], "candidates": cand_scores}
    return out

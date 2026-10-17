"""F4 finance integration helpers: HTTP helpers plus a checker that is independent of the finance engine.

`independent_check(plan, result)` re-derives the hard rules of FINANCE.md 7, 8.4 and 11 straight from the
JSON plan document and the JSON result (contribution lines, holdings assignment, rebalances, planning z).
It does not import anything from `superplanner.finance` (no cashflow, returns, validator or timegrid code),
so a bug shared by the optimizer and the engine validator still shows up here.
"""

from __future__ import annotations

import copy
import math
import random
import time
from typing import Any

from fastapi.testclient import TestClient

from superplanner.api.config import Settings
from superplanner.api.main import create_app

API = "/api/v1"
FIN = f"{API}/finance"
START = "2026-11"
TEMPLATE_IDS = ["young_professional", "family", "near_retirement", "blank"]
FAST: dict[str, Any] = {"time_limit_seconds": 20, "seed": 0, "simulation": {"n_paths": 300},
                        "compute_fixes": False, "calibration_rounds": 0}
RISKY = {"equity", "gold", "other"}
FREQ_PERIOD = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12, "once": 0}
FREQ_Q = {"monthly": 1.0, "quarterly": 1 / 3, "half_yearly": 1 / 6, "yearly": 1 / 12, "once": 0.0}
DISCLAIMER_START = "SuperPlanner Finance is an educational planning tool."
# F.21 rule 4 (own copy, independent of advisor/messages.py)
FORBIDDEN = ["guarantee", "guaranteed", "assured", "risk-free", "sure", "will earn", "will grow to",
             "you should buy"]


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


# --------------------------------------------------------------------------- HTTP helpers

class Fin:
    def __init__(self, client: TestClient):
        self.c = client

    def instantiate(self, template: str, name: str | None = None, **params: Any) -> dict[str, Any]:
        body: dict[str, Any] = {"start_month": START, "parameters": params}
        if name:
            body["name"] = name
        r = self.c.post(f"{FIN}/templates/{template}/instantiate", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def create(self, doc: dict[str, Any]):
        return self.c.post(f"{FIN}/plans", json=doc)

    def get(self, plan_id: str) -> dict[str, Any]:
        r = self.c.get(f"{FIN}/plans/{plan_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def post_run(self, plan_id: str, req: dict[str, Any] | None = None):
        return self.c.post(f"{FIN}/plans/{plan_id}/runs", json=copy.deepcopy(FAST if req is None else req))

    def start_run(self, plan_id: str, req: dict[str, Any] | None = None) -> str:
        r = self.post_run(plan_id, req)
        assert r.status_code == 202, r.text
        return r.json()["run_id"]

    def what_if(self, plan_id: str, changes: dict[str, Any], run: dict[str, Any] | None = None, **extra: Any):
        body: dict[str, Any] = {"changes": changes, "run": copy.deepcopy(FAST if run is None else run)}
        body.update(extra)
        return self.c.post(f"{FIN}/plans/{plan_id}/what-if", json=body)

    def run(self, run_id: str) -> dict[str, Any]:
        r = self.c.get(f"{FIN}/runs/{run_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def wait(self, run_id: str, timeout: float = 120.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.run(run_id)
            if run["status"] not in ("queued", "running"):
                return run
            if time.monotonic() > deadline:
                raise AssertionError(f"finance run {run_id} still {run['status']} after {timeout}s")
            time.sleep(0.05)

    def solve(self, plan_id: str, req: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run and return the FinanceResultRecord (summary + result + plan snapshot)."""
        run = self.wait(self.start_run(plan_id, req))
        assert run["status"] == "completed", run
        return self.result(run["result_id"])

    def solve_what_if(self, plan_id: str, changes: dict[str, Any], run: dict[str, Any] | None = None,
                      **extra: Any) -> dict[str, Any]:
        r = self.what_if(plan_id, changes, run, **extra)
        assert r.status_code == 202, r.text
        done = self.wait(r.json()["run_id"])
        assert done["status"] == "completed", done
        return self.result(done["result_id"])

    def result(self, result_id: str) -> dict[str, Any]:
        r = self.c.get(f"{FIN}/results/{result_id}")
        assert r.status_code == 200, r.text
        return r.json()


def assert_error(resp, status: int, code: str | None = None) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    err = resp.json()["error"]
    if code is not None:
        assert err["code"] == code, err
    return err


# --------------------------------------------------------------------------- independent model

def midx(start: str, m: str) -> int:
    ys, ms = int(start[:4]), int(start[5:7])
    y, mo = int(m[:4]), int(m[5:7])
    return (y - ys) * 12 + (mo - ms)


def mstr(start: str, t: int) -> str:
    y, m = int(start[:4]), int(start[5:7]) - 1 + t
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF by bisection on erf (own implementation)."""
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


class Model:
    """Everything derived from the plan document alone (real terms, FINANCE.md 3 and 7)."""

    def __init__(self, plan: dict[str, Any], T: int):
        self.plan = plan
        self.start = plan["start_month"]
        self.T = T
        a = plan["assumptions"]
        self.pi = a["inflation_pct"] / 100
        self.sig_pi = a["inflation_volatility_pct"] / 100
        self.classes = {c["id"]: c for c in a["asset_classes"]}
        self.class_order = [c["id"] for c in a["asset_classes"]]
        self.cash_id = a["cash_class_id"]
        self.ef_id = plan["emergency_fund"]["asset_class_id"]
        con = plan["constraints"]
        self.L = con["contribution_block_months"]
        self.tau = con["rebalance_cost_pct"] / 100
        self.m_buf = con["min_cash_buffer"]
        self.goals = [g for g in plan["goals"] if g.get("enabled", True)]
        self.gmap = {g["id"]: g for g in self.goals}
        self.D = {g["id"]: midx(self.start, g["target_month"]) for g in self.goals}
        self.TR = {}
        for g in self.goals:
            pig = (g["inflation_pct"] if g.get("inflation_pct") is not None else a["inflation_pct"]) / 100
            self.TR[g["id"]] = g["target_amount"] * ((1 + pig) / (1 + self.pi)) ** (self.D[g["id"]] / 12)
        self.tol = max(1.0, 1e-6 * max(self.TR.values(), default=0.0))
        self.holdings = {h["id"]: h for h in plan["holdings"]}
        self._cashflow()

    # ---- helpers
    def P(self, t: float) -> float:
        return (1 + self.pi) ** (t / 12)

    def real_return(self, cid: str) -> float:
        c = self.classes[cid]
        mu = c["expected_return_pct"] / 100
        return (1 + mu - c.get("expense_ratio_pct", 0) / 100 - c.get("tax_drag_pct", 0) / 100) / (1 + self.pi) - 1

    def gamma(self, cid: str) -> float:
        return (1 + self.real_return(cid)) ** (1 / 12)

    def lock(self, cid: str) -> int:
        return int(self.classes[cid].get("lock_in_months", 0))

    def risky(self, cid: str) -> bool:
        return self.classes[cid]["category"] in RISKY

    def allowed(self, gid: str) -> list[str]:
        al = self.gmap[gid].get("allowed_asset_class_ids")
        return list(self.class_order) if al is None else list(al)

    def locked_until(self, hid: str) -> int | None:
        lu = self.holdings[hid].get("locked_until_month")
        return None if lu is None else midx(self.start, lu)

    def base_cap(self, gid: str) -> float:
        g = self.gmap[gid]
        tol = g.get("risk_tolerance") or self.plan["profile"]["risk_tolerance"]
        return self.plan["assumptions"]["risky_cap_by_tolerance_pct"][tol - 1] / 100

    def glide(self, m: int) -> float:
        steps = sorted(self.plan["assumptions"]["glide_path"], key=lambda s: s["min_months_to_goal"])
        mult = steps[0]["multiplier"]
        for s in steps:
            if s["min_months_to_goal"] <= m:
                mult = s["multiplier"]
        return mult

    def cap(self, gid: str, s_k: int) -> float:
        return self.base_cap(gid) * self.glide(self.D[gid] - s_k)

    def _span(self, item: dict[str, Any]) -> tuple[int, int] | None:
        t0 = max(0, midx(self.start, item["start_month"])) if item.get("start_month") else 0
        t1 = midx(self.start, item["end_month"]) if item.get("end_month") else self.T - 1
        if t1 < 0:
            return None
        return t0, min(t1, self.T - 1)

    def _occurs(self, item: dict[str, Any], t: int, span: tuple[int, int]) -> bool:
        t0, t1 = span
        if t < t0 or t > t1:
            return False
        p = FREQ_PERIOD[item.get("frequency", "monthly")]
        return t == t0 if p == 0 else (t - t0) % p == 0

    # ---- FINANCE.md 7
    def _cashflow(self) -> None:
        T, plan = self.T, self.plan
        inc = [0.0] * T
        ess = [0.0] * T
        dis = [0.0] * T
        emi = [0.0] * T
        one = [0.0] * T
        for i in plan["incomes"]:
            sp = self._span(i)
            if sp is None:
                continue
            # PHASE2 1.7: an inflation-linked income is in today's money with a real yearly raise
            per = 1.0 if i.get("inflation_linked", False) else None
            for t in range(T):
                if self._occurs(i, t, sp):
                    inc[t] += i["amount"] * (1 + i.get("growth_pct", 0) / 100) ** ((t - sp[0]) // 12) / (
                        per if per is not None else self.P(t))
        for e in plan["expenses"]:
            sp = self._span(e)
            if sp is None:
                continue
            pie = (e["inflation_pct"] if e.get("inflation_pct") is not None else plan["assumptions"]["inflation_pct"]) / 100
            for t in range(T):
                if self._occurs(e, t, sp):
                    f = ((1 + pie) / (1 + self.pi)) ** (t / 12) if e.get("inflation_linked", True) else 1 / self.P(t)
                    (ess if e.get("essential", True) else dis)[t] += e["amount"] * f
        emi0 = 0.0
        for d in plan["debts"]:
            bal, j = d["balance"], d["interest_rate_pct"] / 100 / 12
            if bal > 0:
                emi0 += d["emi"]
            for t in range(T):
                if bal <= 1e-9:
                    break
                pay = min(d["emi"], bal * (1 + j))
                bal = bal * (1 + j) - pay
                emi[t] += pay / self.P(t)
        for o in plan["one_offs"]:
            t = midx(self.start, o["month"])
            if 0 <= t < T:
                amt = o["amount"] if o.get("inflation_linked", True) else o["amount"] / self.P(t)
                one[t] += amt if o.get("kind", "expense") == "inflow" else -amt
        S = [inc[t] - ess[t] - dis[t] - emi[t] + one[t] for t in range(T)]
        self.income, self.essential, self.discretionary, self.emi, self.one_off, self.S = inc, ess, dis, emi, one, S

        # EF target: essentials active at t = 0 (not whatif_), monthly equivalent, plus EMIs of open debts
        efs = plan["emergency_fund"]
        base = 0.0
        for e in plan["expenses"]:
            sp = self._span(e)
            if not e.get("essential", True) or e["id"].startswith("whatif_") or sp is None or sp[0] > 0:
                continue
            base += e["amount"] * FREQ_Q[e.get("frequency", "monthly")]
        self.ef_target = efs["months_of_essentials"] * (base + emi0)

        # holdings split: free amounts after earmarks of enabled goals
        ear: dict[str, float] = {}
        for g in self.goals:
            for em in g.get("earmarked", []):
                ear[em["holding_id"]] = ear.get(em["holding_id"], 0.0) + em["amount"]
        self.free = {h["id"]: h["amount"] - ear.get(h["id"], 0.0) for h in plan["holdings"]}
        self.earmarks = ear
        ef0 = 0.0
        cash_left = 0.0
        self.left = dict(self.free)       # free amount left after the EF / cash split, per holding
        order = [self.ef_id] + ([self.cash_id] if self.cash_id != self.ef_id else [])
        for cid in order:
            for h in plan["holdings"]:
                lu = self.locked_until(h["id"])
                if h["asset_class_id"] != cid or (lu is not None and lu > 0):
                    continue
                take = min(self.free[h["id"]], max(0.0, self.ef_target - ef0))
                ef0 += take
                self.left[h["id"]] = self.free[h["id"]] - take
                if cid == self.cash_id:
                    cash_left += self.free[h["id"]] - take
        self.ef_initial, self.cash_initial = ef0, cash_left

        gef = self.gamma(self.ef_id)
        EF = ef0
        efc = [0.0] * T
        tE = None
        for t in range(T):
            if tE is None and EF >= self.ef_target - 1.0:
                tE = t
            efc[t] = min(efs["build_share"] * max(S[t], 0.0), max(0.0, self.ef_target - EF))
            EF = (EF + efc[t]) * gef
        self.tE = T if tE is None else tE
        self.ef_contrib = efc
        self.A = [S[t] - efc[t] for t in range(T)]

    def unlocked_pool(self) -> float:
        """Free amounts left after the EF fill of every non-cash holding not locked at t = 0 (what T0 may sell, 8.4 rule 2)."""
        tot = 0.0
        for h in self.plan["holdings"]:
            lu = self.locked_until(h["id"])
            if h["asset_class_id"] == self.cash_id or (lu is not None and lu > 0):
                continue
            tot += max(0.0, self.left[h["id"]])
        return tot

    def zero_contribution_deficit(self) -> float:
        """T0 lower bound: zero contributions, every unlocked pool item sold into cash, deficits as late as possible."""
        g = self.gamma(self.cash_id)
        B = self.cash_initial + (1 - self.tau) * self.unlocked_pool()
        tot = 0.0
        for t in range(self.T):
            avail = B + self.A[t]
            d = max(0.0, self.m_buf - avail)
            tot += d
            B = (avail + d) * g
        return tot

    # ---- FINANCE.md 8.2 as amended in 24.3 (lognormal real-return quantile) and PHASE2 1.5 (cautious margin)
    def plan_rho(self, gid: str, cid: str, z: float) -> float:
        c = self.classes[cid]
        R = self.real_return(cid)
        sig = math.sqrt((c["volatility_pct"] / 100) ** 2 + self.sig_pi ** 2)
        Y = max(1.0, self.D[gid] / 12)
        if sig <= 0:
            return (1 + max(-0.5, R)) ** (1 / 12)
        s = math.sqrt(math.log(1 + (sig / (1 + R)) ** 2))
        q = (1 + R) * math.exp(-s * s / 2 - z * s / math.sqrt(Y)) - 1
        cau = {"floor_share": 0.5, "floor_start_years": 3.0, "floor_full_years": 10.0, "floor_step_pct_per_z": 2.0}
        cau.update(self.plan["assumptions"].get("caution") or {})
        ramp = min(1.0, max(0.0, (Y - cau["floor_start_years"]) / (cau["floor_full_years"] - cau["floor_start_years"])))
        phi = cau["floor_share"] * ramp
        if phi <= 0:
            rp = max(-0.5, q)
        else:
            g = self.gmap[gid]
            p_min = g.get("min_success_probability")
            if p_min is None:
                p_min = {"must": 0.85, "should": 0.70, "nice": 0.50}[g.get("priority", "should")]
            z0 = norm_ppf(p_min)
            med = (1 + R) * math.exp(-s * s / 2) - 1
            delta = cau["floor_step_pct_per_z"] / 100 * max(0.0, z - z0)
            rp = max(-0.5, max(q, phi * max(med, 0.0)) - ramp * delta)
        return (1 + rp) ** (1 / 12)


def expand_lines(model: Model, result: dict[str, Any]) -> dict[tuple[str, str], dict[int, float]]:
    out: dict[tuple[str, str], dict[int, float]] = {}
    for ln in result["contributions"]:
        t0, t1 = midx(model.start, ln["start_month"]), midx(model.start, ln["end_month"])
        cell = out.setdefault((ln["goal_id"], ln["asset_class_id"]), {})
        for t in range(t0, t1 + 1):
            cell[t] = cell.get(t, 0.0) + ln["monthly_amount_real"]
    return out


def independent_check(plan: dict[str, Any], result: dict[str, Any], *, check_cash: bool = True) -> list[str]:
    """Return hard-rule violations (strings); [] means every hard rule of F.11 holds for this result."""
    errs: list[str] = []
    T = result["horizon_months"]
    m = Model(plan, T)
    tol, start = m.tol, m.start
    lines = expand_lines(m, result)

    # -- cash flow series agree with the plan document (F.7)
    cf = result["cashflow"]
    for name, mine in (("income", m.income), ("essential", m.essential), ("discretionary", m.discretionary),
                       ("debt_payments", m.emi), ("one_off_net", m.one_off), ("surplus", m.S),
                       ("emergency_fund_contribution", m.ef_contrib)):
        theirs = cf[name]
        if len(theirs) != T:
            errs.append(f"CF {name} length {len(theirs)} != {T}")
            continue
        bad = [t for t in range(T) if abs(theirs[t] - mine[t]) > max(0.05, 1e-6 * abs(mine[t]))]
        if bad:
            t = bad[0]
            errs.append(f"CF {name} differs in {len(bad)} months, first {mstr(start, t)}: {theirs[t]} vs {mine[t]:.2f}")
    if abs(result["summary"]["emergency_fund_target"] - m.ef_target) > 0.05:
        errs.append(f"EF target {result['summary']['emergency_fund_target']} vs {m.ef_target:.2f}")

    # -- contribution lines: sign, goal, timing, class, lock-in, EF gating (F.11)
    X = [0.0] * T
    for (gid, cid), cells in lines.items():
        for t, amt in cells.items():
            if amt < 0:
                errs.append(f"CONTRIBUTION_NEGATIVE {gid}/{cid} {mstr(start, t)}")
            if not 0 <= t < T:
                errs.append(f"contribution outside horizon {gid}/{cid} t={t}")
                continue
        if gid == "emergency_fund":
            if cid != m.ef_id:
                errs.append(f"EF line in class {cid}, expected {m.ef_id}")
            for t in range(T):
                if abs(cells.get(t, 0.0) - m.ef_contrib[t]) > 0.05:
                    errs.append(f"EF line {mstr(start, t)} {cells.get(t, 0.0)} vs waterfall {m.ef_contrib[t]:.2f}")
                    break
            continue
        if gid not in m.gmap:
            errs.append(f"contribution for unknown/disabled goal {gid}")
            continue
        D = m.D[gid]
        if cid not in m.allowed(gid):
            errs.append(f"CLASS_NOT_ALLOWED {gid}/{cid}")
        for t, amt in cells.items():
            if 0 <= t < T:
                X[t] += amt
            if t >= D:
                errs.append(f"CONTRIBUTION_AFTER_GOAL {gid}/{cid} {mstr(start, t)} (goal {mstr(start, D)})")
            if m.lock(cid) and t + m.lock(cid) > D:
                errs.append(f"LOCKIN_PAST_GOAL {gid}/{cid} contribution {mstr(start, t)} lock {m.lock(cid)}")
            if m.gmap[gid].get("priority", "should") in ("should", "nice") and t < m.tE:
                errs.append(f"EF_BEFORE_DISCRETIONARY {gid} contributes {mstr(start, t)} before EF complete "
                            f"{mstr(start, m.tE)}")
    gc = cf["goal_contribution"]
    bad = [t for t in range(T) if abs(gc[t] - X[t]) > 0.05]
    if bad:
        errs.append(f"CF goal_contribution != sum of lines in {len(bad)} months, first {mstr(start, bad[0])}")

    # -- holdings assignment partitions every holding (F.14 [R26]) and respects locks
    per_h: dict[str, float] = {}
    sold = 0.0
    for row in result["holdings_assignment"]:
        hid = row["holding_id"]
        if hid not in m.holdings:
            errs.append(f"assignment of unknown holding {hid}")
            continue
        if row["amount"] < -0.005:
            errs.append(f"negative assignment {row}")
        per_h[hid] = per_h.get(hid, 0.0) + row["amount"]
        lu = m.locked_until(hid)
        if row["source"] == "sold_to_cash":
            sold += row["amount"]
            if lu is not None and lu > 0:
                errs.append(f"LOCKED_SOLD holding {hid} sold to cash at start but locked until "
                            f"{m.holdings[hid]['locked_until_month']}")
        if row["source"] in ("assigned", "earmark"):
            gid = row["goal_id"]
            if gid not in m.gmap:
                errs.append(f"{row['source']} to unknown goal {gid}")
                continue
            if lu is not None and lu > m.D[gid]:
                errs.append(f"holding {hid} locked past goal {gid} but {row['source']}")
            if row["source"] == "assigned" and m.holdings[hid]["asset_class_id"] not in m.allowed(gid):
                errs.append(f"CLASS_NOT_ALLOWED assigned holding {hid} to {gid}")
    for hid, h in m.holdings.items():
        if abs(per_h.get(hid, 0.0) - h["amount"]) > 0.05:
            errs.append(f"HOLDING partition {hid}: rows sum {per_h.get(hid, 0.0):.2f} != amount {h['amount']}")

    # -- cash never below the buffer; contributions within surplus + cash (F.8.4 rule 10, F.11 CASH_NEGATIVE)
    gc_ = m.gamma(m.cash_id)
    B = m.cash_initial + (1 - m.tau) * sold
    cash_end = cf["cash_buffer_end"]
    worst = None
    series_ok = check_cash
    for t in range(T):
        avail = B + m.A[t] - X[t]
        if check_cash and avail < m.m_buf - tol and worst is None:
            worst = t
        B = avail * gc_                       # series value = end of month, after the month's return
        if series_ok and abs(cash_end[t] - B) > max(1.0, 1e-6 * abs(B)):
            errs.append(f"cash_buffer_end {mstr(start, t)} {cash_end[t]} vs recomputed {B:.2f}")
            series_ok = False
    if worst is not None:
        errs.append(f"CASH_NEGATIVE from {mstr(start, worst)}: contributions exceed surplus plus free cash")

    # -- goal buckets: replay with planning returns, rebalances, locks and caps (F.8.4 rules 1-9)
    rebs: dict[tuple[str, int], dict[str, Any]] = {}
    for rb in result["rebalances"]:
        key = (rb["goal_id"], midx(start, rb["month"]))
        if key in rebs:
            errs.append(f"duplicate rebalance {key}")
        rebs[key] = rb
    gres = {g["goal_id"]: g for g in result["goals"]}
    plan_ret = result["assumptions_used"]["planning_returns_pct"]
    H_at: dict[int, dict[str, dict[str, float]]] = {}       # s_k -> goal -> class -> H (for global caps)
    LRq_at: dict[int, dict[str, dict[str, float]]] = {}     # locked values per class (allowance)
    for gid, g in m.gmap.items():
        D = m.D[gid]
        gr = gres.get(gid)
        if gr is None:
            errs.append(f"goal {gid} missing from result")
            continue
        z = gr["planning_z"]
        al = m.allowed(gid)
        bucket = set(al)
        F: dict[str, float] = {}
        locked: list[list[Any]] = []      # [class, value, unlock index]
        for row in result["holdings_assignment"]:
            if row["goal_id"] != gid or row["source"] not in ("earmark", "assigned") or row["holding_id"] not in m.holdings:
                continue
            cid = m.holdings[row["holding_id"]]["asset_class_id"]
            bucket.add(cid)
            F[cid] = F.get(cid, 0.0) + row["amount"]
            lu = m.locked_until(row["holding_id"])
            if lu is not None and lu > 0:
                locked.append([cid, row["amount"], lu])
        rho = {c: m.plan_rho(gid, c, z) for c in bucket}
        for c in bucket:
            rep = plan_ret.get(gid, {}).get(c)
            mine = (rho[c] ** 12 - 1) * 100
            if rep is not None and abs(rep - mine) > 0.011:
                errs.append(f"planning return {gid}/{c} reported {rep} vs formula {mine:.3f}")
        for (lg, c) in lines:
            if lg == gid:
                bucket.add(c)
                rho.setdefault(c, m.plan_rho(gid, c, z))
        for c in bucket:
            F.setdefault(c, 0.0)
        K = math.ceil(D / m.L)
        for k in range(K):
            s_k = k * m.L
            n = min(m.L, D - s_k)
            lockv: dict[str, float] = {}
            for c, v, lu in locked:
                if lu > s_k:
                    lockv[c] = lockv.get(c, 0.0) + v
            rb = rebs.pop((gid, s_k), None)
            if rb is not None:
                sells, buys = rb.get("sells", {}), rb.get("buys", {})
                for c, v in sells.items():
                    if v < -0.005:
                        errs.append(f"negative sell {gid} {c}")
                    if m.lock(c) and v > 0.005:
                        errs.append(f"LOCKED_SOLD {gid} sells lock-in class {c} at {mstr(start, s_k)}")
                    if v > F.get(c, 0.0) - lockv.get(c, 0.0) + tol:
                        errs.append(f"LOCKED_SOLD/oversell {gid} {c} at {mstr(start, s_k)}: sells {v:.2f} of "
                                    f"{F.get(c, 0.0):.2f} (locked {lockv.get(c, 0.0):.2f})")
                    F[c] = F.get(c, 0.0) - v
                for c, v in buys.items():
                    if v < -0.005:
                        errs.append(f"negative buy {gid} {c}")
                    if v > 0.005 and c not in al:
                        errs.append(f"CLASS_NOT_ALLOWED {gid} buys {c} at {mstr(start, s_k)}")
                    if v > 0.005 and m.lock(c) and s_k + m.lock(c) > D:
                        errs.append(f"LOCKIN_PAST_GOAL {gid} buys {c} at {mstr(start, s_k)}")
                    F[c] = F.get(c, 0.0) + v
                    rho.setdefault(c, m.plan_rho(gid, c, z))
                if abs(sum(buys.values()) - (1 - m.tau) * sum(sells.values())) > tol:
                    errs.append(f"REBALANCE_UNBALANCED {gid} {mstr(start, s_k)}")
            # bucket risk cap (rule 7) with the locked-position allowance [R8], only where it can be met (24.3)
            tot = sum(F.values())
            risky_v = sum(v for c, v in F.items() if m.risky(c))
            allow = sum(v for c, v in lockv.items() if m.risky(c)) + sum(
                v for c, v in F.items() if m.risky(c) and m.lock(c))
            can_dilute = any(not m.risky(c) and (not m.lock(c) or s_k + m.lock(c) <= D) for c in al)
            cap = m.cap(gid, s_k)
            if can_dilute and tot > tol and risky_v > cap * tot + allow + 0.005 * tot + tol:
                errs.append(f"RISK_CAP_EXCEEDED {gid} at {mstr(start, s_k)}: risky {risky_v / tot:.3f} > cap {cap:.3f}")
            H_at.setdefault(s_k, {})[gid] = dict(F)
            lq = dict(lockv)
            for c, v in F.items():
                if m.lock(c):
                    lq[c] = lq.get(c, 0.0) + v
            LRq_at.setdefault(s_k, {})[gid] = lq
            # contribution mix cap (rule 8)
            xs_any = {c: max(lines.get((gid, c), {}).get(t, 0.0) for t in range(s_k, s_k + n)) for c in bucket}
            xt = sum(xs_any.values())
            xr = sum(v for c, v in xs_any.items() if m.risky(c))
            mix_ok = any(not m.risky(c) and (not m.lock(c) or s_k + n - 1 + m.lock(c) <= D) for c in al)
            if mix_ok and xt > 0.01 and xr > cap * xt + 0.005 * xt + 0.02:
                errs.append(f"RISK_CAP_EXCEEDED contribution mix {gid} block {mstr(start, s_k)}: {xr / xt:.3f} > {cap:.3f}")
            # growth over the block: contributions at the start of each month, then returns (F.3)
            for t in range(s_k, s_k + n):
                for c in list(F):
                    F[c] = (F[c] + lines.get((gid, c), {}).get(t, 0.0)) * rho.setdefault(c, m.plan_rho(gid, c, z))
                for lk in locked:
                    lk[1] *= rho[lk[0]]
        final = sum(F.values())
        if abs(final - gr["planned_value_real"]) > max(tol, 0.001 * m.TR[gid]):
            errs.append(f"BUCKET_MISMATCH {gid}: recomputed {final:.2f} vs planned_value_real {gr['planned_value_real']}")
        if abs(gr["target_real"] - m.TR[gid]) > max(0.05, 1e-7 * m.TR[gid]):
            errs.append(f"target_real {gid} {gr['target_real']} vs {m.TR[gid]:.2f}")
    for key in rebs:
        errs.append(f"rebalance {key} not at a block start of an enabled goal before its date")

    # -- global equity / class caps (rule 9), allowance for locked positions and goals that cannot dilute
    con = plan["constraints"]
    caps: list[tuple[str, set[str], float]] = []
    if con.get("max_equity_pct") is not None:
        caps.append(("EQUITY_CAP_EXCEEDED", {c for c in m.classes if m.classes[c]["category"] == "equity"},
                     con["max_equity_pct"] / 100))
    for c, p in con.get("max_class_pct", {}).items():
        caps.append(("CLASS_CAP_EXCEEDED", {c}, p / 100))

    def binding(gid: str, s_k: int) -> set[int]:
        # F.24.3 rule 4 for several caps: the goal's risky cap, then the global caps in order, each binding only
        # when it can hold together with the caps already binding, given the classes the goal can buy.
        buy = [c for c in m.allowed(gid) if c in m.classes and (not m.lock(c) or s_k + m.lock(c) <= m.D[gid])]
        eq_set = {c for c in m.classes if m.classes[c]["category"] == "equity"}

        def fits(sets: list[tuple[str, set[str], float]]) -> bool:
            # laminar sets (single classes, equity within risky): largest mass that meets every cap
            def mass(group: list[str]) -> float:
                return sum(min([1.0] + [cp_ for k, cs, cp_ in sets if k == "CLASS_CAP_EXCEEDED" and c in cs])
                           for c in group)
            eq_lim = min([cp_ for k, _, cp_ in sets if k == "EQUITY_CAP_EXCEEDED"] + [9.0])
            r_lim = min([cp_ for k, _, cp_ in sets if k == "RISK"] + [9.0])
            e = min(eq_lim, mass([c for c in buy if c in eq_set]))
            r = min(r_lim, e + mass([c for c in buy if m.risky(c) and c not in eq_set]))
            return mass([c for c in buy if not m.risky(c)]) + r >= 1 - 1e-12
        chosen: list[tuple[str, set[str], float]] = []
        rc = m.cap(gid, s_k)
        if rc < 1 and fits([("RISK", set(), rc)]):
            chosen.append(("RISK", set(), rc))
        out: set[int] = set()
        for i, cap_ in enumerate(caps):
            if fits(chosen + [cap_]):
                chosen.append(cap_)
                out.add(i)
        return out

    for ci, (code, cset, cp) in enumerate(caps):
        for s_k, per_goal in H_at.items():
            tot = capped = allow = 0.0
            for gid, F in per_goal.items():
                if m.D[gid] <= s_k:
                    continue
                tot += sum(F.values())
                cv = sum(v for c, v in F.items() if c in cset)
                capped += cv
                can = ci in binding(gid, s_k)
                if not can:
                    allow += cv
                else:
                    allow += sum(v for c, v in LRq_at[s_k][gid].items() if c in cset)
            if tot > tol and capped > cp * tot + allow + 0.005 * tot + tol:
                errs.append(f"{code} {sorted(cset)} at {mstr(start, s_k)}: {capped / tot:.3f} > {cp:.3f}")
    return errs


def hard_violations(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [v for v in result["violations"] if v["severity"] == "hard"]


def all_text(obj: Any) -> str:
    """Every string inside a JSON value, joined (for compliance scans)."""
    out: list[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return "\n".join(out)


def forbidden_hits(text: str) -> list[str]:
    import re
    return [w for w in FORBIDDEN if re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", text, re.IGNORECASE)]


# --------------------------------------------------------------------------- random plans (stdlib random)

CLASS_IDS = ["cash", "fixed_deposit", "short_debt", "govt_long", "equity_index", "gold"]


def random_plan(seed: int, hard: bool = False) -> dict[str, Any]:
    """Random small plan; `hard` adds locked risky holdings, MILP minimums and tight caps."""
    rnd = random.Random(seed * 2 + (1 if hard else 0))
    start = START
    horizon_years = rnd.choice([2, 4, 8, 15])

    def month(min_m: int, max_m: int) -> str:
        return mstr(start, rnd.randint(min_m, max_m))

    take_home = rnd.choice([30000, 60000, 120000, 250000])
    incomes = [{"id": "salary", "name": "Salary", "amount": take_home, "growth_pct": rnd.choice([0, 3, 6, 10])}]
    if rnd.random() < 0.3:
        incomes.append({"id": "rent_in", "name": "Rental", "kind": "rental", "amount": rnd.choice([5000, 15000]),
                        "frequency": rnd.choice(["monthly", "quarterly"]), "start_month": month(0, 24)})
    if rnd.random() < 0.15:
        incomes.append({"id": "bonus", "name": "Bonus", "amount": take_home, "frequency": "yearly",
                        "end_month": month(12, 60)})
    share = rnd.choice([0.3, 0.5, 0.7, 0.9, 1.05])
    expenses = [{"id": "living", "name": "Living", "amount": round(take_home * share * 0.7),
                 "essential": True}]
    expenses.append({"id": "fun", "name": "Fun", "amount": round(take_home * share * 0.3), "essential": False,
                     "inflation_linked": rnd.random() < 0.7})
    if rnd.random() < 0.3:
        expenses.append({"id": "fees", "name": "Fees", "amount": rnd.choice([20000, 60000]), "frequency": "yearly",
                         "inflation_pct": 9.0, "start_month": month(0, 12)})
    debts = []
    if rnd.random() < 0.35:
        bal = rnd.choice([100000, 500000])
        rate = rnd.choice([8.0, 12.0])
        debts.append({"id": "loan", "name": "Loan", "balance": bal, "interest_rate_pct": rate,
                      "emi": round(bal * rate / 1200 + bal / rnd.choice([24, 60]), 0)})
    holdings = []
    if rnd.random() < 0.8:
        holdings.append({"id": "h_cash", "name": "Savings", "asset_class_id": "cash",
                         "amount": rnd.choice([0, 20000, 100000, 500000])})
    if rnd.random() < 0.5:
        holdings.append({"id": "h_eq", "name": "Shares", "asset_class_id": "equity_index",
                         "amount": rnd.choice([50000, 300000, 1000000])})
        if hard and rnd.random() < 0.5:
            holdings[-1]["locked_until_month"] = month(1, 30)
    if hard and rnd.random() < 0.4:
        holdings.append({"id": "h_gold", "name": "Gold coins", "asset_class_id": "gold",
                         "amount": rnd.choice([100000, 400000]), "locked_until_month": month(0, 20)})
    if rnd.random() < 0.3:
        holdings.append({"id": "h_lock", "name": "Locked savings", "asset_class_id": "govt_long",
                         "amount": rnd.choice([100000, 400000]), "locked_until_month": month(6, 48)})
    if rnd.random() < 0.2:
        holdings.append({"id": "h_fd", "name": "Deposit", "asset_class_id": "fixed_deposit",
                         "amount": rnd.choice([50000, 200000])})
    one_offs = []
    if rnd.random() < 0.4:
        one_offs.append({"id": "oo1", "name": "Trip", "kind": rnd.choice(["expense", "inflow"]),
                         "month": month(1, 36), "amount": rnd.choice([50000, 300000]),
                         "inflation_linked": rnd.random() < 0.5})
    goals = []
    for i in range(rnd.randint(1, 4)):
        g: dict[str, Any] = {"id": f"g{i}", "name": f"Goal {i}",
                             "target_amount": rnd.choice([100000, 500000, 2000000, 10000000]),
                             "target_month": month(6, 12 * horizon_years),
                             "priority": rnd.choice(["must", "should", "nice"])}
        if rnd.random() < 0.25:
            al = rnd.sample(CLASS_IDS[1:], rnd.randint(1, 3))
            if al == ["govt_long"]:
                al.append("short_debt")
            g["allowed_asset_class_ids"] = al
        if rnd.random() < 0.25:
            g["risk_tolerance"] = rnd.randint(1, 5)
        if rnd.random() < 0.2:
            g["inflation_pct"] = 9.0
        goals.append(g)
    # earmarks: only from unlocked holdings or locked ones maturing before the goal
    for g in goals:
        if holdings and rnd.random() < 0.3:
            h = rnd.choice(holdings)
            used = sum(e["amount"] for gg in goals for e in gg.get("earmarked", []) if e["holding_id"] == h["id"])
            free = h["amount"] - used
            lu = h.get("locked_until_month")
            if free > 0 and (lu is None or lu <= g["target_month"]):
                g["earmarked"] = [{"holding_id": h["id"], "amount": round(free * rnd.choice([0.3, 1.0]), 2)}]
    constraints: dict[str, Any] = {}
    if rnd.random() < 0.3:
        constraints["max_equity_pct"] = rnd.choice([10, 30, 50])
    if rnd.random() < 0.2:
        constraints["min_cash_buffer"] = rnd.choice([10000, 50000])
    if rnd.random() < 0.3:
        constraints["contribution_block_months"] = 6
    if rnd.random() < 0.5:
        constraints["rebalance_cost_pct"] = rnd.choice([0.0, 0.5])
    if rnd.random() < 0.15:
        constraints["max_class_pct"] = {"gold": 10}
    if hard:
        if rnd.random() < 0.5:
            constraints["max_equity_pct"] = rnd.choice([0, 5, 20])
        if rnd.random() < 0.5:
            constraints["rebalance_cost_pct"] = 0.0
        if rnd.random() < 0.3:
            constraints["max_class_pct"] = {"equity_index": 15, "fixed_deposit": 40}
    doc: dict[str, Any] = {"name": f"random {seed}", "start_month": start, "incomes": incomes,
                           "expenses": expenses, "debts": debts, "holdings": holdings, "one_offs": one_offs,
                           "goals": goals, "constraints": constraints,
                           "profile": {"risk_tolerance": rnd.randint(1, 5)},
                           "emergency_fund": {"months_of_essentials": rnd.choice([0, 3, 6]),
                                              "build_share": rnd.choice([0.5, 1.0])}}
    if hard and rnd.random() < 0.3:
        classes = copy.deepcopy(DEFAULT_CLASSES)
        for c in classes:
            if c["id"] in ("equity_index", "short_debt") and rnd.random() < 0.7:
                c["min_monthly_contribution"] = rnd.choice([500, 2000, 10000])
        doc["assumptions"] = {"asset_classes": classes, "correlations": []}
    return doc


# F.5.1 defaults (own copy, used to build plans with MILP minimum contributions)
DEFAULT_CLASSES: list[dict[str, Any]] = [
    {"id": "cash", "name": "Cash / savings account", "category": "cash", "expected_return_pct": 3.0, "volatility_pct": 0.5},
    {"id": "fixed_deposit", "name": "Fixed deposit", "category": "debt", "expected_return_pct": 6.75, "volatility_pct": 1.0,
     "liquidity_days": 2},
    {"id": "short_debt", "name": "Short-term debt fund", "category": "debt", "expected_return_pct": 7.0,
     "volatility_pct": 2.0, "expense_ratio_pct": 0.35, "liquidity_days": 2},
    {"id": "govt_long", "name": "Government long lock-in savings", "category": "debt", "expected_return_pct": 7.1,
     "volatility_pct": 0.5, "liquidity_days": 7, "lock_in_months": 180},
    {"id": "equity_index", "name": "Diversified equity index fund", "category": "equity", "expected_return_pct": 11.5,
     "volatility_pct": 18.0, "expense_ratio_pct": 0.2, "liquidity_days": 3},
    {"id": "gold", "name": "Gold", "category": "gold", "expected_return_pct": 8.0, "volatility_pct": 15.0,
     "expense_ratio_pct": 0.4, "liquidity_days": 3},
]

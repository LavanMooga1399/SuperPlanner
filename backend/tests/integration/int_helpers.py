"""WP4 integration helpers: HTTP client helpers plus a checker that is independent of the engine.

`independent_check` re-derives every hard constraint of ARCHITECTURE 5.1 straight from the JSON
Problem document (it does not use `compile_problem`, `timeutil` or the engine validator), so a
bug shared by the compiler, the solvers and the validator still shows up here.
"""

from __future__ import annotations

import json
import random
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from superplanner.api.config import Settings
from superplanner.api.main import create_app

API = "/api/v1"
START = "2026-10-19"
OFFSET = "+05:30"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
TEMPLATE_IDS = ["manufacturing", "exam_prep", "project"]
STRATEGIES = ["auto", "heuristic", "cpsat", "ga", "hybrid"]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


def load_export(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


# --------------------------------------------------------------------------- HTTP helpers

class Api:
    def __init__(self, client: TestClient):
        self.c = client

    def instantiate(self, template: str = "manufacturing", **params: Any) -> dict[str, Any]:
        r = self.c.post(f"{API}/templates/{template}/instantiate",
                        json={"start_date": START, "utc_offset": OFFSET, "parameters": params})
        assert r.status_code == 201, r.text
        assert r.headers["etag"] == '"1"'
        return r.json()

    def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        r = self.c.post(f"{API}/problems", json=doc)
        assert r.status_code == 201, r.text
        return r.json()

    def import_file(self, export: dict[str, Any]) -> dict[str, Any]:
        r = self.c.post(f"{API}/problems/import", json=export)
        assert r.status_code == 201, r.text
        return r.json()

    def get(self, pid: str) -> dict[str, Any]:
        r = self.c.get(f"{API}/problems/{pid}")
        assert r.status_code == 200, r.text
        return r.json()

    def put(self, pid: str, doc: dict[str, Any], version: Any):
        headers = {} if version is None else {"If-Match": f'"{version}"' if isinstance(version, int) else version}
        return self.c.put(f"{API}/problems/{pid}", json=doc, headers=headers)

    def validate(self, pid: str) -> dict[str, Any]:
        r = self.c.post(f"{API}/problems/{pid}/validate")
        assert r.status_code == 200, r.text
        return r.json()

    def post_run(self, pid: str, **req: Any):
        return self.c.post(f"{API}/problems/{pid}/solver-runs", json=req)

    def start_run(self, pid: str, **req: Any) -> dict[str, Any]:
        req.setdefault("time_limit_seconds", 2)
        r = self.post_run(pid, **req)
        assert r.status_code == 202, r.text
        return r.json()

    def run(self, run_id: str) -> dict[str, Any]:
        r = self.c.get(f"{API}/solver-runs/{run_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def wait(self, run_id: str, timeout: float = 40.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.run(run_id)
            if run["status"] not in ("queued", "running"):
                return run
            if time.monotonic() > deadline:
                raise AssertionError(f"run {run_id} still {run['status']} after {timeout}s")
            time.sleep(0.1)

    def wait_status(self, run_id: str, status: str, timeout: float = 15.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.run(run_id)
            if run["status"] == status:
                return run
            if time.monotonic() > deadline:
                raise AssertionError(f"run {run_id} is {run['status']}, expected {status}")
            time.sleep(0.05)

    def solve(self, pid: str, **req: Any) -> dict[str, Any]:
        run = self.wait(self.start_run(pid, **req)["run_id"])
        assert run["status"] == "completed", run
        return run

    def schedule(self, sid: str) -> dict[str, Any]:
        r = self.c.get(f"{API}/schedules/{sid}")
        assert r.status_code == 200, r.text
        return r.json()

    def schedules(self, pid: str, status: str | None = None) -> list[dict[str, Any]]:
        q = f"?status={status}" if status else ""
        r = self.c.get(f"{API}/problems/{pid}/schedules{q}")
        assert r.status_code == 200, r.text
        return r.json()["items"]

    def approve(self, sid: str, **body: Any):
        return self.c.post(f"{API}/schedules/{sid}/approve", json=body)

    def events(self, run_id: str, after: int | None = None) -> list[dict[str, Any]]:
        q = "" if after is None else f"&after={after}"
        r = self.c.get(f"{API}/solver-runs/{run_id}/events?stream=false{q}")
        assert r.status_code == 200, r.text
        return r.json()["items"]


def assert_error(resp, status: int, code: str | None = None) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "details"}, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    if code is not None:
        assert body["error"]["code"] == code, body
    return body["error"]


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Parse a text/event-stream body into [{"id", "event", "data"}] frames (comments skipped)."""
    frames, cur = [], {}
    for line in text.splitlines():
        if line == "":
            if cur:
                frames.append(cur)
                cur = {}
            continue
        if line.startswith(":"):
            continue
        key, _, val = line.partition(":")
        val = val[1:] if val.startswith(" ") else val
        if key == "data":
            cur["data"] = json.loads(val)
        else:
            cur[key] = val
    if cur:
        frames.append(cur)
    return frames


# --------------------------------------------------------------------------- independent checker

def _dt(s: str | None) -> datetime | None:
    return None if s is None else datetime.fromisoformat(s)


def _minute(dt: datetime, hs: datetime) -> int:
    return int((dt - hs).total_seconds() // 60)


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def availability(resource: dict[str, Any], hs: datetime, H: int) -> bytearray:
    """Per-minute availability (1 = open) of a resource over [0, H), from its raw calendar."""
    cal = resource.get("calendar")
    if cal is None:
        return bytearray(b"\x01") * H
    weekly = cal.get("weekly")
    if weekly is None:
        avail = bytearray(b"\x01") * H
    else:
        avail = bytearray(H)
        local_midnight = hs.replace(hour=0, minute=0, second=0, microsecond=0)
        day0 = _minute(local_midnight, hs)  # <= 0
        k = 0
        while day0 + k * 1440 < H:
            day_start = day0 + k * 1440
            wd = WEEKDAYS[(local_midnight + timedelta(days=k)).weekday()]
            for a, b in weekly.get(wd, []) or []:
                s, e = max(0, day_start + _hhmm(a)), min(H, day_start + _hhmm(b))
                for m in range(s, e):
                    avail[m] = 1
            k += 1
    for blk in cal.get("blocked", []) or []:
        s = max(0, _minute(_dt(blk["start"]), hs))
        e = min(H, _minute(_dt(blk["end"]), hs))
        for m in range(s, e):
            avail[m] = 0
    return avail


def independent_check(problem: dict[str, Any], placements: list[dict[str, Any]],
                      horizon_start: str | None = None) -> list[str]:
    """Return a list of hard-constraint violations (strings); [] means the schedule is valid."""
    errs: list[str] = []
    hs = _dt(horizon_start or problem["horizon_start"])
    H = int(problem.get("horizon_days", 30)) * 1440
    tasks = {t["id"]: t for t in problem.get("tasks", [])}
    res = {r["id"]: r for r in problem.get("resources", [])}
    by_task: dict[str, dict[str, Any]] = {}
    for p in placements:
        if p["task_id"] not in tasks:
            errs.append(f"H1 unknown task {p['task_id']}")
            continue
        if p["task_id"] in by_task:
            errs.append(f"H1 duplicate {p['task_id']}")
        by_task[p["task_id"]] = p
    for tid in tasks:
        if tid not in by_task:
            errs.append(f"H1 missing {tid}")
    avail_cache: dict[str, bytearray] = {}
    usage: dict[str, list[tuple[int, int, int]]] = {}
    for tid, p in by_task.items():
        t = tasks[tid]
        s, e = p["start"], p["end"]
        d = t.get("duration_minutes", 0)
        if e - s != d:
            errs.append(f"H2 {tid} duration {e - s} != {d}")
        if s < 0 or e > H:
            errs.append(f"H3 {tid} [{s},{e}) outside [0,{H})")
        if t.get("earliest_start"):
            r = max(0, _minute(_dt(t["earliest_start"]), hs))
            if s < r:
                errs.append(f"H4 {tid} start {s} < earliest {r}")
        reqs = t.get("requirements", [])
        rids = p["resource_ids"]
        if len(rids) != len(reqs):
            errs.append(f"H6 {tid} {len(rids)} resources for {len(reqs)} requirements")
        else:
            if len(set(rids)) != len(rids):
                errs.append(f"H6 {tid} duplicate resources {rids}")
            for i, (rq, rid) in enumerate(zip(reqs, rids)):
                if rid not in rq["alternatives"]:
                    errs.append(f"H6 {tid} req {i}: {rid} not in {rq['alternatives']}")
                if rid in res:
                    usage.setdefault(rid, []).append((s, e, rq.get("units", 1)))
                    if t.get("type", "activity") == "activity" and d > 0:
                        if rid not in avail_cache:
                            avail_cache[rid] = availability(res[rid], hs, H)
                        av = avail_cache[rid]
                        lo, hi = max(0, s), min(H, e)
                        if lo < hi and not all(av[lo:hi]):
                            errs.append(f"H8 {tid} on {rid} [{s},{e}) not inside one availability window")
        lk = t.get("locked")
        if lk:
            ls = _minute(_dt(lk["start"]), hs)
            if s != ls:
                errs.append(f"H9 {tid} start {s} != locked {ls}")
            if lk.get("resource_ids") is not None and rids != lk["resource_ids"]:
                errs.append(f"H9 {tid} resources {rids} != locked {lk['resource_ids']}")
        if t.get("deadline") and t.get("deadline_hard"):
            D = _minute(_dt(t["deadline"]), hs)
            if e > D:
                errs.append(f"H10 {tid} ends {e} after hard deadline {D}")
    for dp in problem.get("dependencies", []):
        a, b = by_task.get(dp["predecessor"]), by_task.get(dp["successor"])
        if a is None or b is None:
            continue
        typ, lag = dp.get("type", "FS"), dp.get("lag_minutes", 0)
        lhs = {"FS": b["start"], "SS": b["start"], "FF": b["end"], "SF": b["end"]}[typ]
        rhs = {"FS": a["end"], "SS": a["start"], "FF": a["end"], "SF": a["start"]}[typ] + lag
        if lhs < rhs:
            errs.append(f"H5 {typ} {dp['predecessor']}->{dp['successor']} lag {lag}: {lhs} < {rhs}")
    for rid, ivs in usage.items():
        cap = res[rid].get("capacity", 1)
        ev = sorted([(s, u) for s, e, u in ivs if e > s] + [(e, -u) for s, e, u in ivs if e > s],
                    key=lambda x: (x[0], x[1]))
        cur = 0
        for m, u in ev:
            cur += u
            if cur > cap:
                errs.append(f"H7 {rid} usage {cur} > capacity {cap} at minute {m}")
                break
    return errs


def objective_check(problem: dict[str, Any], placements: list[dict[str, Any]], metrics: dict[str, Any],
                    horizon_start: str | None = None) -> list[str]:
    """Recompute makespan, weighted tardiness and cost (5.2) and compare to reported metrics."""
    hs = _dt(horizon_start or problem["horizon_start"])
    tasks = {t["id"]: t for t in problem["tasks"]}
    res = {r["id"]: r for r in problem["resources"]}
    mk = max((p["end"] for p in placements), default=0)
    wt = tard = late = 0
    cost = 0.0
    for p in placements:
        t = tasks[p["task_id"]]
        if t.get("deadline") and not t.get("deadline_hard"):
            T = max(0, p["end"] - _minute(_dt(t["deadline"]), hs))
            tard += T
            wt += t.get("priority", 5) * T
            late += 1 if T > 0 else 0
        for rq, rid in zip(t.get("requirements", []), p["resource_ids"]):
            cost += res[rid].get("cost_per_hour", 0.0) * rq.get("units", 1) * t["duration_minutes"] / 60
    out = []
    if metrics["makespan_minutes"] != mk:
        out.append(f"makespan {metrics['makespan_minutes']} != {mk}")
    if metrics["weighted_tardiness"] != wt:
        out.append(f"weighted_tardiness {metrics['weighted_tardiness']} != {wt}")
    if metrics["total_tardiness_minutes"] != tard:
        out.append(f"total_tardiness {metrics['total_tardiness_minutes']} != {tard}")
    if metrics["late_tasks"] != late:
        out.append(f"late_tasks {metrics['late_tasks']} != {late}")
    if abs(metrics["cost"] - round(cost, 2)) > 0.011:
        out.append(f"cost {metrics['cost']} != {round(cost, 2)}")
    return out


# --------------------------------------------------------------------------- random problems

def random_doc(seed: int) -> dict[str, Any]:
    """A random small Problem document (JSON). Not guaranteed to pass preflight (that is the point:
    preflight-rejected problems must come back `infeasible`/`unknown`, never `feasible`)."""
    rng = random.Random(1000 + seed)
    offset = rng.choice(["+00:00", "+05:30", "-04:00", "+09:45"])
    hour = rng.choice([0, 0, 7, 13])
    hs = datetime.fromisoformat(f"2026-11-0{rng.randint(1, 7)}T{hour:02d}:00:00{offset}")
    days = rng.choice([3, 5, 10])
    H = days * 1440

    def iso(m: int) -> str:
        return (hs + timedelta(minutes=m)).isoformat()

    n_res = rng.randint(1, 4)
    resources = []
    for i in range(n_res):
        cal = None
        kind = rng.random()
        if kind < 0.35:
            cal = {"weekly": {d: [["06:00", "14:00"], ["14:00", "22:00"]] for d in WEEKDAYS[:rng.choice([5, 6, 7])]},
                   "blocked": []}
        elif kind < 0.5:
            cal = {"weekly": {d: [["22:00", "24:00"], ["00:00", "06:00"]] for d in WEEKDAYS}, "blocked": []}
        elif kind < 0.6:
            cal = {"weekly": None, "blocked": [{"start": iso(rng.randint(0, 2000)), "end": iso(rng.randint(2100, 3000)),
                                                "reason": "maint"}]}
        if cal and cal["weekly"] is not None and rng.random() < 0.3:
            s = rng.randint(0, 3000)
            cal["blocked"].append({"start": iso(s), "end": iso(s + rng.randint(30, 300)), "reason": "x"})
        resources.append({"id": f"R{i}", "name": f"Res {i}", "capacity": rng.choice([1, 1, 1, 2, 3]),
                          "cost_per_hour": float(rng.randint(0, 80)), "calendar": cal})
    n = rng.randint(2, 9)
    tasks = []
    for i in range(n):
        if rng.random() < 0.08:
            tasks.append({"id": f"T{i}", "name": f"Mile {i}", "type": "milestone", "duration_minutes": 0})
            continue
        reqs = []
        if rng.random() < 0.9:
            k = 2 if (n_res >= 2 and rng.random() < 0.2) else 1
            pool = [r["id"] for r in resources]
            rng.shuffle(pool)
            for j in range(k):
                alts = pool[j:j + 1] + [x for x in pool[k:] if rng.random() < 0.4]
                alts = list(dict.fromkeys(alts))
                caps = min(r["capacity"] for r in resources if r["id"] in alts)
                units = 2 if ((caps >= 2 and rng.random() < 0.4) or rng.random() < 0.03) else 1
                reqs.append({"alternatives": alts, "units": units})
        t = {"id": f"T{i}", "name": f"Task {i}", "duration_minutes": rng.randint(15, 240),
             "priority": rng.randint(1, 10), "requirements": reqs}
        if rng.random() < 0.35:
            t["deadline"] = iso(rng.randint(240, H))
            t["deadline_hard"] = rng.random() < 0.3
        if rng.random() < 0.2:
            t["earliest_start"] = iso(rng.randint(0, 900))
        tasks.append(t)
    deps, seen = [], set()
    for i in range(1, n):
        for _ in range(rng.choice([0, 1, 1, 2])):
            j = rng.randrange(0, i)
            if (j, i) in seen:
                continue
            seen.add((j, i))
            deps.append({"predecessor": f"T{j}", "successor": f"T{i}",
                         "type": rng.choice(["FS", "FS", "SS", "FF", "SF"]),
                         "lag_minutes": rng.choice([0, 0, 30, -20, 120])})
    # occasional lock (start-only or with resources) on a task without predecessors
    if rng.random() < 0.15:
        cand = [t for t in tasks if t.get("type", "activity") == "activity" and not any(
            d["successor"] == t["id"] for d in deps)]
        if cand:
            t = rng.choice(cand)
            lk = {"start": iso(rng.randint(0, 600))}
            if t["requirements"] and rng.random() < 0.5:
                lk["resource_ids"] = [rq["alternatives"][0] for rq in t["requirements"]]
            t["locked"] = lk
    return {"name": f"Random {seed}", "horizon_start": hs.isoformat(), "horizon_days": days,
            "tasks": tasks, "resources": resources, "dependencies": deps}


def today_str() -> str:
    return date.today().isoformat()

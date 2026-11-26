"""Fake model clients (no network): `FakeClient` replays scripted responses for tests; `DemoClient` is the
development-only scripted assistant (`ASSISTANT_AI_DEMO=true`, refused outside APP_ENV=development) that drives the
real tools like the S0 fixture's turn: demand status of the page's demand line (or the first late one), overtime
options, an overtime draft, then a cited answer. Neither ever calls the real API."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any, Callable


def text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def tool_use(name: str, args: dict[str, Any], id_: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_ or f"toolu_{name}_{abs(hash(json.dumps(args, default=str))) % 10**8}",
                           name=name, input=args)


def response(*blocks: Any, stop: str | None = None, model: str = "claude-opus-5-5", usage: tuple[int, int, int] = (
        1200, 150, 800)) -> SimpleNamespace:
    uses = any(getattr(b, "type", None) == "tool_use" for b in blocks)
    return SimpleNamespace(content=list(blocks), stop_reason=stop or ("tool_use" if uses else "end_turn"),
                           model=model, usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1],
                                                              cache_read_input_tokens=usage[2],
                                                              cache_creation_input_tokens=0))


class _Messages:
    def __init__(self, owner: "FakeClient"):
        self.owner = owner

    def create(self, **kw: Any) -> Any:
        return self.owner._next(kw)


class FakeClient:
    """`script`: a list of responses / exceptions (consumed in order) or a callable(kwargs, call_no) -> response."""

    api_key = "fake-key"

    def __init__(self, script: list[Any] | Callable[[dict[str, Any], int], Any]):
        self.script = script
        self.calls: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.beta = SimpleNamespace(messages=_Messages(self))
        self._lock = threading.Lock()

    def _next(self, kw: dict[str, Any]) -> Any:
        with self._lock:
            n = len(self.calls)
            self.calls.append(json.loads(json.dumps(kw, default=str)))
        if callable(self.script):
            try:
                out = self.script(kw, n)
            except Exception as exc:          # tests: keep the script's own failure visible
                import traceback

                self.errors.append(traceback.format_exc())
                raise exc
        else:
            if n >= len(self.script):
                return response(text("(end of script)"))
            out = self.script[n]
        if isinstance(out, BaseException):
            raise out
        return out


def last_tool_results(kw: dict[str, Any]) -> list[dict[str, Any]]:
    """The tool_result payloads of the latest user message (decoded)."""
    msgs = kw.get("messages") or []
    if not msgs or not isinstance(msgs[-1].get("content"), list):
        return []
    out = []
    for b in msgs[-1]["content"]:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            try:
                out.append(json.loads(b["content"]))
            except (TypeError, ValueError):
                out.append({})
    return out


def refs_in(payload: Any) -> list[str]:
    found: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            r = v.get("ref")
            if isinstance(r, str) and r.startswith("R"):
                found.append(r)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(payload)
    return list(dict.fromkeys(found))


def _all_tool_results(kw: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in kw.get("messages") or []:
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    try:
                        out.append(json.loads(b["content"]))
                    except (TypeError, ValueError):
                        out.append({})
    return out


def _used(kw: dict[str, Any], name: str) -> bool:
    for m in kw.get("messages") or []:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            for b in m["content"]:
                if (b.get("type") if isinstance(b, dict) else getattr(b, "type", None)) == "tool_use" and \
                        (b.get("name") if isinstance(b, dict) else getattr(b, "name", None)) == name:
                    return True
    return False


def demo_drafts(results: list[dict[str, Any]], today: Any = None) -> list[dict[str, Any]]:
    """Draft actions the data supports (demo review): open the suggested overtime; for a late demand line, expedite
    the purchase order on its limiting path, or a purchase request for a bought item that cannot arrive in time;
    raise the order's priority when it is not top priority; always also a what-if schedule with overtime allowed
    (never live). Each becomes one `draft_action` call; invalid ones are reported by the tool, the rest stand."""
    from datetime import date as _date, timedelta

    today = today or _date.today()
    out: list[dict[str, Any]] = []
    for r in results:
        d = r.get("data") if isinstance(r, dict) else None
        if isinstance(d, dict) and d.get("items") and isinstance(d["items"], list) and \
                isinstance(d["items"][0], dict) and d["items"][0].get("line_id") and d["items"][0].get("start"):
            x = d["items"][0]
            out.append({"kind": "open_overtime", "args": {"open_shifts": [{"line_id": x["line_id"],
                                                                           "start": x["start"], "end": x["end"]}],
                                                          "summary": "Accept the suggested overtime."}})
    for r in results:
        d = r.get("data") if isinstance(r, dict) else None
        if not isinstance(d, dict) or "order" not in d:
            continue
        order = d.get("order") or {}
        rows = ((d.get("mrp") or {}).get("lines") or [])
        late = [x for x in rows if (x.get("late_days") or 0) > 0 or x.get("status") in ("late", "past_due")]
        for row in late[:1]:
            due = row.get("due_date")
            try:
                due_d = _date.fromisoformat(str(due)[:10])
            except ValueError:
                due_d = today
            need = max(today, due_d - timedelta(days=3)).isoformat()
            for st in row.get("limiting") or []:
                label = str(st.get("label") or "")
                if label.upper().startswith("PO-"):
                    out.append({"kind": "expedite_po_schedule", "args": {
                        "purchase_order": label.split("/")[0], "needed_date": need,
                        "summary": f"{label.split('/')[0]} limits {order.get('number')}: pull it forward."}})
                    break
                if label.startswith("Planned PR") or st.get("reason") in ("lead_time", "start_in_past") and \
                        "PR" in label:
                    out.append({"kind": "create_pr", "args": {
                        "item": st.get("part_number"), "qty": float(row.get("qty") or 1), "needed_date": need,
                        "summary": f"Order {st.get('part_number')} now for {order.get('number')}."}})
                    break
        if late and (order.get("priority") or 1) > 1:
            out.append({"kind": "raise_priority", "args": {"demand_order": order.get("number"), "priority": 1,
                                                           "summary": "Plan this order first."}})
        if late:
            out.append({"kind": "whatif_run", "args": {"target": "aps", "whatif_aps": {
                "overtime": "allow", "label": f"Overtime for {order.get('number')}"[:60]},
                "summary": "See whether overtime recovers the date (what-if, never live)."}})
    seen, uniq = set(), []
    for x in out:
        if x["kind"] not in seen:
            seen.add(x["kind"])
            uniq.append(x)
    return uniq[:3]


def demo_script(kw: dict[str, Any], n: int) -> Any:
    tools = {t["name"] for t in kw.get("tools") or []}
    if not _all_tool_results(kw):
        q = (kw["messages"][-1]["content"] if isinstance(kw["messages"][-1]["content"], str) else "")
        order = next((w.strip(".,?") for w in q.split() if w.upper().startswith("DO-")), None)
        uses = []
        if order and "demand_status" in tools:
            uses.append(tool_use("demand_status", {"order": order, "line": None}, "toolu_demo_1"))
        if "overtime_options" in tools:
            uses.append(tool_use("overtime_options", {}, "toolu_demo_2"))
        if not uses:
            return response(text("I can only look at planning data here."))
        return response(text("Let me look at the plan."), *uses)
    res = _all_tool_results(kw)
    if "draft_action" in tools and not _used(kw, "draft_action"):
        drafts = demo_drafts(res)
        if drafts:
            return response(text("These actions could help; nothing changes until you apply one."),
                            *[tool_use("draft_action", d, f"toolu_demo_d{k}") for k, d in enumerate(drafts)])
    refs = [r for p in res for r in refs_in(p)]
    cite = " ".join(f"[{r}]" for r in list(dict.fromkeys(refs))[:3])
    return response(text(f"Here is what I found {cite}. Review the drafts below; nothing has been changed."))


class DemoClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(demo_script)

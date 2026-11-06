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
        self.beta = SimpleNamespace(messages=_Messages(self))
        self._lock = threading.Lock()

    def _next(self, kw: dict[str, Any]) -> Any:
        with self._lock:
            n = len(self.calls)
            self.calls.append(json.loads(json.dumps(kw, default=str)))
        if callable(self.script):
            out = self.script(kw, n)
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


def demo_script(kw: dict[str, Any], n: int) -> Any:
    tools = {t["name"] for t in kw.get("tools") or []}
    if n == 0:
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
    res = last_tool_results(kw)
    if n == 1 and "draft_action" in tools:
        ot = next((r for r in res if isinstance(r.get("data"), dict) and "items" in r["data"]), None)
        items = (ot or {}).get("data", {}).get("items") or []
        if items:
            x = items[0]
            return response(tool_use("draft_action", {"kind": "open_overtime", "args": {
                "open_shifts": [{"line_id": x.get("line_id"), "start": x.get("start"), "end": x.get("end")}],
                "summary": "Accept the suggested overtime."}}, "toolu_demo_3"))
    refs = [r for p in res for r in refs_in(p)]
    cite = " ".join(f"[{r}]" for r in refs[:3])
    return response(text(f"Here is what I found {cite}. Review the drafts below; nothing has been changed."))


class DemoClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(demo_script)

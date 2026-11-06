"""The assistant turn: a server-side tool-use loop (M6-DESIGN 1.2) running in a background thread of the API
process inside an AI slot; progress is written to the turn row (polled by the UI).

Per round: budget check (refuse before calling the model), one model call (`client.create`), audit
`assistant_call`, usage; every `tool_use` block runs through `tools.run_call` (permission re-check, audit
`assistant_tool`) and is answered with a `tool_result`. Stops on `end_turn`, `refusal` (AI_REFUSED), `max_tokens`
(AI_TRUNCATED), cancel, or the round limit (answer with what is known + a note). Logs carry ids, counts and codes
only - never the question, tool data or the answer (1.6)."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from ..api.db import utcnow
from ..api.db.ownership import bind_actor, bind_owner, owner_scope
from ..api.mfg.db_models_m6 import AssistantConversationRow, AssistantTurnRow
from . import budget, citations, client as C, prompts, tools as T

log = logging.getLogger("superplanner.assistant")
HISTORY_TURNS = 10
STALE_SECONDS = 180
MESSAGES = {
    "AI_DISABLED": "The assistant is switched off on this server.",
    "AI_SDK_MISSING": "The AI library is not installed on this server.",
    "AI_NO_CREDENTIALS": "The AI service is not set up (no credentials).",
    "AI_PLANT_OPTED_OUT": "The assistant is switched off for this plant.",
    "AI_BUSY": "The assistant is busy; try again in a moment.",
    "AI_BUDGET_EXCEEDED": "The daily assistant budget is used up; the built-in explanations still work.",
    "AI_RATE_LIMITED": "The AI service is rate limited; try again later.",
    "AI_AUTH_FAILED": "The AI service rejected the server's credentials.",
    "AI_API_ERROR": "The AI service returned an error.",
    "AI_CONNECTION_ERROR": "The AI service could not be reached. Use the quick explanations, or try again later.",
    "AI_UNEXPECTED": "The assistant failed unexpectedly.",
    "AI_REFUSED": "The AI declined to answer this question.",
    "AI_TRUNCATED": "The answer was too long and was cut off.",
    "AI_TURN_LOST": "The answer was interrupted (server restart); ask again.",
    "AI_CANCELLED": "Cancelled.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _step(kind: str, summary: str, name: str | None = None, ok: bool = True) -> dict[str, Any]:
    return {"at": _now().isoformat(), "kind": kind, "name": name, "summary": summary[:200], "ok": ok}


class Turn:
    """State of one running turn (in the worker thread)."""

    def __init__(self, ctx: Any, app_state: Any, turn_id: str, owner_id: str, user_id: str):
        self.ctx = ctx
        self.state = app_state
        self.turn_id = turn_id
        self.owner_id = owner_id
        self.user_id = user_id
        self.steps: list[dict[str, Any]] = []
        self.tokens = [0, 0, 0]
        self.rounds = 0
        self.model: str | None = None
        self.fallback: str | None = None

    # ------------------------------------------------------------ persistence

    def _update(self, **vals: Any) -> bool:
        """Write progress; returns cancel_requested."""
        with self.ctx.write_guard(), self.ctx.db.write() as s:
            t = s.get(AssistantTurnRow, self.turn_id, with_for_update=True)
            if t is None:
                return True
            for k, v in vals.items():
                setattr(t, k, v)
            t.steps = list(self.steps)
            t.tokens_in, t.tokens_out, t.tokens_cache_read = self.tokens
            t.rounds = self.rounds
            t.heartbeat_at = utcnow()
            return bool(t.cancel_requested)

    def finish(self, status: str, *, answer: str | None = None, cites: list[dict[str, Any]] | None = None,
               drafts: list[dict[str, Any]] | None = None, code: str | None = None,
               tool_log: list[dict[str, Any]] | None = None, refs: citations.RefRegistry | None = None) -> None:
        err = {"code": code, "message": MESSAGES.get(code or "", code or "")} if code and status != "completed" \
            else None
        with self.ctx.write_guard(), self.ctx.db.write() as s:
            t = s.get(AssistantTurnRow, self.turn_id, with_for_update=True)
            if t is None:
                return
            if refs is not None:
                refs.flush(s)
            t.status = status
            t.steps = list(self.steps)
            t.answer = answer
            t.citations = cites or []
            t.drafts = drafts or []
            t.error = err
            t.tool_log = tool_log
            t.model = self.model
            t.fallback_code = self.fallback if status == "completed" else (code or self.fallback)
            t.tokens_in, t.tokens_out, t.tokens_cache_read = self.tokens
            t.rounds = self.rounds
            t.finished_at = t.heartbeat_at = utcnow()
            conv = s.get(AssistantConversationRow, t.conversation_id)
            if conv is not None:
                conv.updated_at = utcnow()
        log.info("assistant turn %s %s (rounds %d, tokens %d/%d, code %s)", self.turn_id, status, self.rounds,
                 self.tokens[0], self.tokens[1], code or "-")


def start(ctx: Any, app_state: Any, turn_id: str, owner_id: str, user_id: str) -> threading.Thread:
    th = threading.Thread(target=run, args=(ctx, app_state, turn_id, owner_id, user_id),
                          name=f"sp-assistant-{turn_id[-6:]}", daemon=True)
    th.start()
    return th


def run(ctx: Any, app_state: Any, turn_id: str, owner_id: str, user_id: str) -> None:
    """Thread body: bound to the plant (owner) and the user (actor) like a request in that workspace."""
    bind_owner(owner_id)
    bind_actor(user_id)
    turn = Turn(ctx, app_state, turn_id, owner_id, user_id)
    slots = getattr(app_state, "assistant_ai_slots", None)
    if slots is not None and not slots.acquire():
        turn.finish("failed", code="AI_BUSY")
        return
    try:
        _run(turn)
    except Exception as exc:  # noqa: BLE001 - a turn never dies silently
        log.warning("assistant turn %s failed: %s", turn_id, type(exc).__name__)
        try:
            turn.finish("failed", code="AI_UNEXPECTED")
        except Exception:  # pragma: no cover
            pass
    finally:
        if slots is not None:
            slots.release()


def _load(turn: Turn) -> tuple[AssistantTurnRow, AssistantConversationRow, list[AssistantTurnRow], Any]:
    """The turn, its conversation, the previous completed turns (oldest first) and (plant, refs, what-if allowed)."""
    from ..api.mfg import repo

    with turn.ctx.db.read() as s:
        t = s.get(AssistantTurnRow, turn.turn_id)
        conv = s.get(AssistantConversationRow, t.conversation_id) if t is not None else None
        if t is None or conv is None:
            raise LookupError("turn gone")
        prev = list(s.execute(select(AssistantTurnRow).where(
            AssistantTurnRow.conversation_id == conv.id, AssistantTurnRow.id != t.id,
            AssistantTurnRow.status == "completed").order_by(AssistantTurnRow.created_at.desc())
            .limit(HISTORY_TURNS - 1)).scalars())
        plant = repo.plant_or_default(s)
        from .service import plant_settings

        allow = plant_settings(s)["assistant_allow_whatif"]
        refs = citations.RefRegistry(conv.id, turn.owner_id).load(s)
        s.expunge_all()
    prev.reverse()
    return t, conv, prev, (plant, refs, allow)


def _history(prev: list[AssistantTurnRow], refs: citations.RefRegistry, user_text: str,
             context: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Last 10 turns: user text + final answers; earlier tool results are replaced by their reference lists."""
    msgs: list[dict[str, Any]] = []
    for p in prev:
        msgs.append({"role": "user", "content": p.user_text})
        used = sorted({c["ref"] for c in (p.citations or [])} | {r["ref"] for e in (p.tool_log or [])
                                                                  for r in e.get("refs", [])},
                      key=lambda r: int(r[1:]))
        ref_lines = "; ".join(f"{r} {refs.records[r]['type']} {refs.records[r]['label']}" for r in used
                              if r in refs.records)
        text = (p.answer or "(no answer)") + (f"\n\nReferences from earlier tools: {ref_lines}" if ref_lines else "")
        msgs.append({"role": "assistant", "content": text[:8000]})
    q = user_text
    if context:
        q = f"{user_text}\n\n(The user is looking at {context.get('type')} {context.get('id')}.)"
    msgs.append({"role": "user", "content": q})
    return msgs


def _run(turn: Turn) -> None:
    ctx = turn.ctx
    settings = ctx.settings
    t, conv, prev, (plant, refs, plant_whatif) = _load(turn)
    if t.status not in ("queued",):
        return
    turn.steps = [_step("thinking", "thinking")]
    if turn._update(status="running", started_at=utcnow()):
        turn.finish("cancelled", code="AI_CANCELLED")
        return
    ok, code, cl = C.status_client(C.options_of(settings))
    if not ok:
        turn.finish("failed", code=code)
        return
    tctx = T.ToolContext(ctx=ctx, user_id=turn.user_id, owner_id=turn.owner_id, permissions=frozenset(),
                         conversation_id=conv.id, allow_whatif=bool(t.allow_whatif and plant_whatif), refs=refs)
    tctx.permissions = T.current_permissions(tctx)
    if "assistant_use" not in tctx.permissions:
        turn.finish("failed", code="AI_FORBIDDEN")
        return
    offered = T.offered(tctx.permissions, tctx.allow_whatif)
    offered_names = {x.name for x in offered}
    tool_defs = T.definitions(offered)
    from ..mfg.tz import plant_tz

    tz = plant_tz(plant)
    today = datetime.now(UTC).astimezone(tz).date().isoformat()
    system = prompts.system_blocks(plant.name, today, getattr(plant, "time_zone", None) or plant.utc_offset,
                                   tctx.allow_whatif)
    messages = _history(prev, refs, t.user_text, t.context)
    tool_log: list[dict[str, Any]] = []
    max_rounds = int(settings.assistant_max_tool_rounds)
    answer_parts: list[str] = []
    stop = None
    while turn.rounds < max_rounds:
        with ctx.db.read() as s:
            u_left, p_left = budget.left(s, settings, turn.user_id, turn.owner_id)
        if min(u_left, p_left) < budget.MIN_TURN_TOKENS:
            turn.finish("failed", code="AI_BUDGET_EXCEEDED", refs=refs, tool_log=tool_log)
            return
        t0 = time.monotonic()
        try:
            resp = C.create(cl, system=system, tools=tool_defs, messages=messages,
                            max_tokens=int(settings.assistant_max_output_tokens))
        except C.AssistantFallback as fb:
            _audit_call(turn, conv.id, None, int((time.monotonic() - t0) * 1000), [], (0, 0, 0), fb.code)
            turn.finish("failed", code=fb.code, refs=refs, tool_log=tool_log)
            return
        turn.rounds += 1
        used = C.usage_of(resp)
        turn.tokens = [turn.tokens[0] + used[0], turn.tokens[1] + used[1], turn.tokens[2] + used[2]]
        turn.model = str(getattr(resp, "model", None) or C.MODEL)[:64]
        if turn.model != C.MODEL:
            turn.fallback = "AI_FALLBACK_MODEL"
        blocks = C.blocks_of(resp)
        uses = [b for b in blocks if b["type"] == "tool_use"]
        _audit_call(turn, conv.id, resp, int((time.monotonic() - t0) * 1000), [u["name"] for u in uses], used, None)
        stop = getattr(resp, "stop_reason", None)
        texts = [b["text"] for b in blocks if b["type"] == "text" and b["text"].strip()]
        if stop == "refusal":
            turn.finish("failed", code="AI_REFUSED", refs=refs, tool_log=tool_log)
            return
        if stop == "max_tokens":
            turn.finish("failed", code="AI_TRUNCATED", refs=refs, tool_log=tool_log)
            return
        if not uses:
            answer_parts = texts
            break
        messages.append({"role": "assistant", "content": [b for b in blocks
                                                          if b["type"] != "text" or b["text"].strip()]})
        results: list[dict[str, Any]] = []
        for u in uses:
            if turn._update():
                turn.finish("cancelled", code="AI_CANCELLED", refs=refs, tool_log=tool_log)
                return
            turn.steps.append(_step("tool", T.summary_of(u["name"], u["input"]), u["name"]))
            t1 = time.monotonic()
            payload, okk, rows = T.run_call(tctx, u["name"], u["input"], offered_names)
            ms = int((time.monotonic() - t1) * 1000)
            if not okk:
                turn.steps[-1]["ok"] = False
            _audit_tool(turn, conv.id, u["name"], u["input"], rows, okk, ms, payload.get("error"))
            tool_log.append({"tool": u["name"], "ok": okk, "ms": ms, "refs": payload.get("refs", [])
                             if okk else [], "result": payload})
            results.append({"type": "tool_result", "tool_use_id": u["id"],
                            "content": json.dumps(payload, default=str), **({"is_error": True} if not okk else {})})
        messages.append({"role": "user", "content": results})
        if turn._update():
            turn.finish("cancelled", code="AI_CANCELLED", refs=refs, tool_log=tool_log)
            return
    else:
        tctx.notes.append("The assistant reached its tool-round limit; the answer covers what was found so far.")
        answer_parts = answer_parts or ["I could not finish looking this up within the allowed number of steps."]
    answer = citations.sanitize("\n\n".join(answer_parts).strip())
    answer, cites = citations.resolve(answer, refs)
    if tctx.notes:
        answer += "\n\n" + "\n".join(f"_Note: {n}_" for n in tctx.notes)
    turn.steps.append(_step("answer", "answer"))
    # tool results stay on this turn for audit / next-turn reference lists only (data stays in the plant's DB)
    turn.finish("completed", answer=answer, cites=cites, drafts=tctx.drafts, refs=refs,
                tool_log=[{k: v for k, v in e.items() if k != "result"} for e in tool_log])


def _audit_call(turn: Turn, conv_id: str, resp: Any, latency_ms: int, tool_names: list[str],
                used: tuple[int, int, int], code: str | None) -> None:
    from ..api.mfg.services.common import audit

    with turn.ctx.write_guard(), turn.ctx.db.write() as s:
        if used[0] or used[1]:
            budget.add(s, turn.user_id, turn.owner_id, used[0] + used[1])
        audit(s, "assistant", conv_id, "assistant_call", {
            "turn": turn.turn_id, "round": turn.rounds, "user": turn.user_id, "plant": turn.owner_id,
            "model": str(getattr(resp, "model", None) or C.MODEL)[:64] if resp is not None else None,
            "fallback": turn.fallback, "input_tokens": used[0], "output_tokens": used[1],
            "cache_read_tokens": used[2], "latency_ms": latency_ms, "tools": tool_names[:20],
            **({"code": code} if code else {})})


def _audit_tool(turn: Turn, conv_id: str, name: str, args: Any, rows: int, ok: bool, ms: int,
                err: str | None) -> None:
    from ..api.mfg.services.common import audit

    with turn.ctx.write_guard(), turn.ctx.db.write() as s:
        audit(s, "assistant", conv_id, "assistant_tool", {
            "turn": turn.turn_id, "name": name[:64], "args_digest": T.args_digest(args), "rows": rows, "ok": ok,
            "ms": ms, **({"error": str(err)[:64]} if err else {})})


def reap_stale(s: Any, now: datetime | None = None) -> int:
    """1.2: a queued / running turn without progress for 3 minutes is failed (its process died)."""
    cut = (now or _now()) - timedelta(seconds=STALE_SECONDS)
    n = 0
    for t in s.execute(select(AssistantTurnRow).where(AssistantTurnRow.status.in_(("queued", "running")))
                       .with_for_update(skip_locked=True)).scalars():
        last = t.heartbeat_at or t.started_at or t.created_at
        if last is not None and (last if last.tzinfo else last.replace(tzinfo=UTC)) < cut:
            t.status = "failed"
            t.error = {"code": "AI_TURN_LOST", "message": MESSAGES["AI_TURN_LOST"]}
            t.finished_at = utcnow()
            n += 1
    return n


__all__ = ["MESSAGES", "reap_stale", "run", "start"]
_unused = owner_scope

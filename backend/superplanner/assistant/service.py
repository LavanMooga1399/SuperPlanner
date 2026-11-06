"""Assistant endpoints' services (M6-DESIGN 1.1, 1.2, 5 A1-A10): availability, conversations (own only), turns,
draft application reports, plant opt-out. Turns run in `loop` (background thread, AI slots per app)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..api.config import Settings
from ..api.db import new_id, utcnow
from ..api.db.locks import is_unique_violation
from ..api.db.ownership import system_scope
from ..api.errors import ApiError, not_found
from ..api.intake.service import AiSlots
from ..api.mfg.db_models import MfgPlantRow
from ..api.mfg.db_models_m6 import AssistantConversationRow, AssistantTurnRow
from ..api.schemas import as_utc
from . import budget, client as C, loop
from .model import PRIVACY_NOTICE, AssistantPlantSettings, ConversationInput, DraftApplied, TurnInput

SLOT_WAIT_SECONDS = 5.0


def install(app: FastAPI, settings: Settings) -> None:
    app.state.assistant_ai_slots = AiSlots(settings.assistant_ai_max_concurrent, SLOT_WAIT_SECONDS)


# ---------------------------------------------------------------- plant settings and availability

def plant_settings(s: Any) -> dict[str, Any]:
    row = s.execute(select(MfgPlantRow.assistant_enabled, MfgPlantRow.assistant_allow_whatif)).first()
    if row is None:
        return {"assistant_enabled": True, "assistant_allow_whatif": True}
    return {"assistant_enabled": bool(row[0]), "assistant_allow_whatif": bool(row[1])}


def put_plant_settings(ctx: Any, body: AssistantPlantSettings) -> dict[str, Any]:
    from ..api.mfg.services.common import audit, write_tx

    with write_tx(ctx) as (s, plant):
        assert plant is not None
        plant.assistant_enabled = body.assistant_enabled
        plant.assistant_allow_whatif = body.assistant_allow_whatif
        audit(s, "plant", plant.id, "assistant_settings", body.model_dump())
        s.flush()
    return body.model_dump()


def _availability(ctx: Any, p: Any) -> tuple[str | None, dict[str, Any], tuple[int, int]]:
    ok, code, _client = C.status_client(C.options_of(ctx.settings))
    with ctx.db.read() as s:
        ps = plant_settings(s)
        left = budget.left(s, ctx.settings, p.user_id, p.owner_id)
    if ok and not ps["assistant_enabled"]:
        code = "AI_PLANT_OPTED_OUT"
    elif ok and min(left) < budget.MIN_TURN_TOKENS:
        code = "AI_BUDGET_EXCEEDED"
    return (None if ok and code is None else code), ps, left


def status(ctx: Any, app: Any, p: Any) -> dict[str, Any]:
    code, ps, left = _availability(ctx, p)
    return {"available": code is None, "code": code, "message": loop.MESSAGES.get(code or "", "") if code else "",
            "privacy_notice": PRIVACY_NOTICE, "budget_left": {"user": left[0], "plant": left[1]}, "plant": ps,
            "model": C.MODEL, "max_text_chars": 4000, "max_tool_rounds": int(ctx.settings.assistant_max_tool_rounds),
            "quick_kinds": ["why_late", "limits", "changes"]}


def _refuse(code: str, extra: dict[str, Any] | None = None) -> ApiError:
    return ApiError(422, code, loop.MESSAGES.get(code, code), {"code": code, **(extra or {})})


# ---------------------------------------------------------------- records

def turn_record(t: AssistantTurnRow) -> dict[str, Any]:
    return {"id": t.id, "conversation_id": t.conversation_id, "status": t.status, "user_text": t.user_text,
            "context": t.context, "allow_whatif": t.allow_whatif, "steps": list(t.steps or []), "answer": t.answer,
            "citations": list(t.citations or []), "drafts": list(t.drafts or []), "error": t.error, "model": t.model,
            "fallback_code": t.fallback_code,
            "tokens": {"input": t.tokens_in, "output": t.tokens_out, "cache_read": t.tokens_cache_read},
            "rounds": t.rounds, "created_at": as_utc(t.created_at), "started_at": as_utc(t.started_at),
            "finished_at": as_utc(t.finished_at)}


def conversation_record(c: AssistantConversationRow, turns: int) -> dict[str, Any]:
    return {"id": c.id, "title": c.title, "allow_whatif": c.allow_whatif, "created_at": as_utc(c.created_at),
            "updated_at": as_utc(c.updated_at), "turns": turns}


def _own_conversation(s: Any, p: Any, conversation_id: str, lock: bool = False) -> AssistantConversationRow:
    q = select(AssistantConversationRow).where(AssistantConversationRow.id == conversation_id,
                                               AssistantConversationRow.user_id == p.user_id)
    c = s.execute(q.with_for_update() if lock else q).scalars().first()
    if c is None:
        raise not_found("Conversation", conversation_id)
    return c


def _own_turn(s: Any, p: Any, turn_id: str, lock: bool = False) -> AssistantTurnRow:
    q = select(AssistantTurnRow).where(AssistantTurnRow.id == turn_id, AssistantTurnRow.user_id == p.user_id)
    t = s.execute(q.with_for_update() if lock else q).scalars().first()
    if t is None:
        raise not_found("Turn", turn_id)
    return t


# ---------------------------------------------------------------- conversations

def list_conversations(ctx: Any, p: Any, limit: int, offset: int) -> dict[str, Any]:
    C_ = AssistantConversationRow
    with ctx.db.read() as s:
        conds = [C_.user_id == p.user_id]
        rows = list(s.execute(select(C_).where(*conds).order_by(C_.updated_at.desc()).limit(limit).offset(offset))
                    .scalars())
        total = int(s.execute(select(func.count()).select_from(C_).where(*conds)).scalar() or 0)
        counts = dict(s.execute(select(AssistantTurnRow.conversation_id, func.count()).where(
            AssistantTurnRow.conversation_id.in_([r.id for r in rows])).group_by(AssistantTurnRow.conversation_id))
            .all()) if rows else {}
        return {"items": [conversation_record(r, int(counts.get(r.id, 0))) for r in rows], "total": total,
                "limit": limit, "offset": offset}


def create_conversation(ctx: Any, app: Any, p: Any, body: ConversationInput) -> dict[str, Any]:
    with ctx.write_guard(), ctx.db.write() as s:
        if body.allow_whatif and not plant_settings(s)["assistant_allow_whatif"]:
            raise _refuse("AI_WHATIF_NOT_ALLOWED")
        now = utcnow()
        c = AssistantConversationRow(id=new_id("asc_"), owner_id=p.owner_id, user_id=p.user_id,
                                     title=body.title or "", allow_whatif=body.allow_whatif, created_at=now,
                                     updated_at=now)
        s.add(c)
        s.flush()
        return conversation_record(c, 0)


def get_conversation(ctx: Any, p: Any, conversation_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        c = _own_conversation(s, p, conversation_id)
        turns = list(s.execute(select(AssistantTurnRow).where(AssistantTurnRow.conversation_id == c.id)
                               .order_by(AssistantTurnRow.created_at)).scalars())
        out = conversation_record(c, len(turns))
        out["history"] = [turn_record(t) for t in turns]
        return out


def delete_conversation(ctx: Any, p: Any, conversation_id: str) -> None:
    from ..api.mfg.services.common import audit

    with ctx.write_guard(), ctx.db.write() as s:
        c = _own_conversation(s, p, conversation_id, lock=True)
        running = s.execute(select(AssistantTurnRow.id).where(AssistantTurnRow.conversation_id == c.id,
                                                              AssistantTurnRow.status.in_(("queued", "running")))
                            ).first()
        if running is not None:
            raise ApiError(409, "AI_TURN_RUNNING", "Wait for the running answer (or cancel it) first.",
                           {"turn_id": running[0]})
        s.delete(c)
        audit(s, "assistant", c.id, "delete", {})


# ---------------------------------------------------------------- turns

def start_turn(ctx: Any, app: Any, p: Any, conversation_id: str, body: TurnInput) -> dict[str, Any]:
    code, ps, left = _availability(ctx, p)
    if code is not None:
        extra = {"budget_left": {"user": left[0], "plant": left[1]}} if code == "AI_BUDGET_EXCEEDED" else {}
        raise _refuse(code, extra)
    if body.allow_whatif and not ps["assistant_allow_whatif"]:
        raise _refuse("AI_WHATIF_NOT_ALLOWED")
    with system_scope(), ctx.write_guard(), ctx.db.write() as s:     # one running turn per user, any plant
        loop.reap_stale(s)
    now = utcnow()
    try:
        with ctx.write_guard(), ctx.db.write() as s:
            c = _own_conversation(s, p, conversation_id, lock=True)
            c.allow_whatif = body.allow_whatif
            if not c.title:
                c.title = body.text[:80]
            c.updated_at = now
            t = AssistantTurnRow(id=new_id("ast_"), owner_id=p.owner_id, conversation_id=c.id, user_id=p.user_id,
                                 user_text=body.text, context=body.context.model_dump() if body.context else None,
                                 allow_whatif=body.allow_whatif, status="queued", steps=[], answer=None, citations=[],
                                 drafts=[], tool_log=None, error=None, model=None, fallback_code=None, tokens_in=0,
                                 tokens_out=0, tokens_cache_read=0, rounds=0, cancel_requested=False, created_at=now,
                                 started_at=None, finished_at=None, heartbeat_at=now)
            s.add(t)
            s.flush()
            turn_id = t.id
    except IntegrityError as exc:
        if is_unique_violation(exc, "uq_assistant_turns_running"):
            with system_scope(), ctx.db.read() as s:
                rid = s.execute(select(AssistantTurnRow.id).where(
                    AssistantTurnRow.user_id == p.user_id, AssistantTurnRow.status.in_(("queued", "running")))
                    ).scalar()
            raise ApiError(409, "AI_TURN_RUNNING", "Your previous question is still being answered.",
                           {"turn_id": rid}) from None
        raise
    loop.start(ctx, app.state, turn_id, p.owner_id, p.user_id)
    return {"turn_id": turn_id, "conversation_id": conversation_id, "status": "queued"}


def get_turn(ctx: Any, p: Any, turn_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        t = _own_turn(s, p, turn_id)
        stale = t.status in ("queued", "running")
        rec = turn_record(t)
    if stale:
        with ctx.write_guard(), ctx.db.write() as s:
            if loop.reap_stale(s):
                rec = turn_record(_own_turn(s, p, turn_id))
    return rec


def cancel_turn(ctx: Any, p: Any, turn_id: str) -> dict[str, Any]:
    with ctx.write_guard(), ctx.db.write() as s:
        t = _own_turn(s, p, turn_id, lock=True)
        if t.status == "queued":
            t.status, t.finished_at = "cancelled", utcnow()
            t.error = {"code": "AI_CANCELLED", "message": loop.MESSAGES["AI_CANCELLED"]}
        elif t.status == "running":
            t.cancel_requested = True
        return turn_record(t)


def draft_applied(ctx: Any, p: Any, draft_id: str, body: DraftApplied) -> dict[str, Any]:
    from ..api.mfg.services.common import audit

    with ctx.write_guard(), ctx.db.write() as s:
        rows = s.execute(select(AssistantTurnRow).where(AssistantTurnRow.user_id == p.user_id,
                                                        AssistantTurnRow.status == "completed")
                         .order_by(AssistantTurnRow.created_at.desc()).limit(500).with_for_update()).scalars()
        for t in rows:
            drafts = list(t.drafts or [])
            for i, d in enumerate(drafts):
                if d.get("draft_id") == draft_id:
                    d = dict(d, applied_at=utcnow().isoformat(), applied_status=body.status,
                             response_ref=body.response_ref)
                    drafts[i] = d
                    t.drafts = drafts
                    audit(s, "assistant", t.conversation_id, "draft_applied", {
                        "turn": t.id, "draft_id": draft_id, "kind": d.get("kind"), "status": body.status,
                        "method": d.get("method"), "path": d.get("path"), "response_ref": body.response_ref})
                    return d
    raise not_found("Draft", draft_id)


# ---------------------------------------------------------------- retention (1.1: ASSISTANT_RETENTION_DAYS)

def purge(s: Any, days: int, now: Any = None) -> int:
    from datetime import timedelta

    from sqlalchemy import delete

    cut = (now or utcnow()) - timedelta(days=int(days))
    res = s.execute(delete(AssistantConversationRow).where(AssistantConversationRow.updated_at < cut)
                    .execution_options(synchronize_session=False))
    return int(res.rowcount or 0)

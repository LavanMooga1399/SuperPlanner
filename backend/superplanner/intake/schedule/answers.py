"""Apply answers to a `ScheduleDraft` (PHASE2 2.8)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..models import Answer, ExtractContext, IntakeError, Provenance, Question, ScheduleDraft, WorkingTime
from ..qa import (AnswerError, ApplyOutcome, apply_answers, as_choice, as_confirm, as_date, as_duration, as_multi,
                  as_working_time, mark_answered, value_text)
from .extract import _Extractor, extract_schedule
from .questions import DEFAULT_DURATION, DETECTED_NOTE, IMPLIED_NOTE, questions


def parse_working_time_text(text: str, ctx: ExtractContext, kind: str) -> WorkingTime | None:
    ex = _Extractor(text, ctx.model_copy(update={"kind": kind}))
    ex.pass_working_time()
    return ex.working_time


def append_draft(base: ScheduleDraft, extra: ScheduleDraft) -> None:
    """Append tasks/resources of `extra` to `base` with fresh keys (no collisions)."""
    used_t = {t.key for t in base.tasks}
    used_r = {r.key for r in base.resources}
    rmap: dict[str, str] = {}
    for r in extra.resources:
        same = next((x for x in base.resources if x.name.lower() == r.name.lower()), None)
        if same is not None:
            rmap[r.key] = same.key
            continue
        k, i = r.key, 2
        while k in used_r:
            k = f"{r.key[:28]}_{i}"
            i += 1
        used_r.add(k)
        rmap[r.key] = k
        base.resources.append(r.model_copy(update={"key": k}))
    n = len(base.tasks)
    tmap: dict[str, str] = {}
    for t in extra.tasks:
        n += 1
        k = f"t{n}"
        while k in used_t:
            n += 1
            k = f"t{n}"
        used_t.add(k)
        tmap[t.key] = k
    for t in extra.tasks:
        base.tasks.append(t.model_copy(update={"key": tmap[t.key], "after": [tmap[a] for a in t.after],
                                               "resources": [rmap[r] for r in t.resources]}))
    for path, p in extra.provenance.items():
        parts = path.split("/")
        if len(parts) >= 3 and parts[1] == "tasks" and parts[2] in tmap:
            parts[2] = tmap[parts[2]]
        elif len(parts) >= 3 and parts[1] == "resources" and parts[2] in rmap:
            parts[2] = rmap[parts[2]]
        elif len(parts) == 2:
            continue
        # spans refer to the answer text, not to the original description
        base.provenance["/".join(parts)] = Provenance(source="answer", confidence=1.0, note=p.note)


def _task(draft: ScheduleDraft, path: str):
    key = path.split("/")[2]
    t = next((x for x in draft.tasks if x.key == key), None)
    if t is None:
        raise AnswerError("That item no longer exists.")
    return t


def _apply_one(ctx: ExtractContext):
    def apply(draft: ScheduleDraft, q: Question, value: Any) -> None:
        prov = draft.provenance
        code = q.code
        if code == "SCHED_NO_TASKS":
            text = value_text(value) if not isinstance(value, str) else value
            if not text or not text.strip():
                raise AnswerError("Please list at least one task.")
            extra = extract_schedule(text[:20000], ctx.model_copy(update={"kind": draft.kind})).draft
            if not extra.tasks:
                raise AnswerError("We could not find any tasks in that text; write one task per line.")
            append_draft(draft, extra)
        elif code == "SCHED_TASK_DURATION":
            t = _task(draft, q.path or "")
            t.duration = as_duration(value, DEFAULT_DURATION[draft.kind][1])
            mark_answered(prov, q.path or "", keep_span=False)
        elif code == "SCHED_DEP_REFERENCE":
            t = _task(draft, q.path or "")
            choice = as_choice(value, q)
            if choice != "none" and choice != t.key and choice not in t.after:
                t.after.append(choice)
            mark_answered(prov, q.path or "")
            prov[f"/tasks/{t.key}/after"] = Provenance(source="answer", confidence=1.0)
        elif code == "SCHED_DATE_AMBIGUOUS":
            t = _task(draft, q.path or "")
            choice = as_choice(value, q)
            fld = (q.path or "").split("/")[-1]
            setattr(t, fld, as_date(choice, ctx))
            mark_answered(prov, q.path or "")
        elif code == "SCHED_START_DATE":
            draft.start_date = as_date(value, ctx)
            mark_answered(prov, "/start_date", keep_span=False)
        elif code == "SCHED_SEQUENTIAL":
            yes = as_confirm(value)
            for path, p in list(prov.items()):
                if p.source == "derived" and p.note == IMPLIED_NOTE:
                    if not yes:
                        t = _task(draft, path)
                        t.after = []
                    prov[path] = Provenance(source="answer", confidence=1.0)
            prov["/answers/SCHED_SEQUENTIAL"] = Provenance(source="answer", confidence=1.0)
        elif code == "SCHED_PEOPLE":
            yes = as_confirm(value)
            if not yes:
                gone = {r.key for r in draft.resources
                        if (p := prov.get(f"/resources/{r.key}/name")) is not None and p.note == DETECTED_NOTE}
                draft.resources = [r for r in draft.resources if r.key not in gone]
                for t in draft.tasks:
                    t.resources = [r for r in t.resources if r not in gone]
                for k in gone:
                    prov.pop(f"/resources/{k}/name", None)
            prov["/answers/SCHED_PEOPLE"] = Provenance(source="answer", confidence=1.0)
        elif code == "SCHED_WHO":
            t = _task(draft, q.path or "")
            keys = as_multi(value, q)
            t.resources = keys
            t.resource_mode = "any"
            mark_answered(prov, q.path or "", keep_span=False)
        elif code == "SCHED_WORKING_TIME":
            draft.working_time = as_working_time(value, lambda s: parse_working_time_text(s, ctx, draft.kind))
            mark_answered(prov, "/working_time", keep_span=False)
        elif code == "SCHED_LOW_CONFIDENCE":
            yes = as_confirm(value)
            path = q.path or ""
            if not yes and path.endswith("/duration") and path.startswith("/tasks/"):
                _task(draft, path).duration = None
                prov.pop(path, None)
                return
            mark_answered(prov, path)
        else:  # pragma: no cover - every catalog code is handled above
            raise AnswerError("This question cannot be answered here.")
    return apply


def answer_schedule_draft(draft: ScheduleDraft, answers: list[Answer], ctx: ExtractContext) \
        -> tuple[ScheduleDraft, ApplyOutcome]:
    work = draft.model_copy(deep=True)
    outcome = apply_answers(work, answers, questions(work, ctx), _apply_one(ctx))
    try:
        work = ScheduleDraft.model_validate(work.model_dump())
    except ValidationError as exc:  # pragma: no cover - answers keep references consistent
        raise IntakeError("VALIDATION_ERROR", "The answers would make the draft invalid.",
                          {"errors": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                                      for e in exc.errors()]}) from None
    return work, outcome

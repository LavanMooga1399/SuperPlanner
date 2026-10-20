"""Schedule follow-up questions (PHASE2 2.8): a pure function of the draft."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .. import messages as M
from ..models import ExtractContext, Question, QuestionOption, ScheduleDraft, WorkingTime
from ..qa import answered, order, pathless_done, qid
from ..text.names import NameIndex
from .extract import default_working_time

DEFAULT_DURATION = {"project": (1.0, "days"), "generic": (1.0, "days"), "study": (6.0, "hours"),
                    "production": (1.0, "hours")}
_UNIT_LABEL = {"minutes": ("minute", "minutes"), "hours": ("hour", "hours"), "days": ("day", "days"),
               "weeks": ("week", "weeks")}
IMPLIED_NOTE = "From the order of the list"
DETECTED_NOTE = "Detected name"
_DAY_ABBR = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def fmt_amount(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def duration_label(value: float, unit: str) -> str:
    one, many = _UNIT_LABEL[unit]
    return f"{fmt_amount(value)} {one if value == 1 else many}"


def _days_label(days: list[str]) -> str:
    idx = sorted(_ORDER.index(d) for d in days)
    if len(idx) >= 3 and idx == list(range(idx[0], idx[-1] + 1)):
        return f"{_DAY_ABBR[_ORDER[idx[0]]]}-{_DAY_ABBR[_ORDER[idx[-1]]]}"
    return ", ".join(_DAY_ABBR[_ORDER[i]] for i in idx)


def working_time_label(wt: WorkingTime) -> str:
    def win(ws) -> str:
        return ", ".join(f"{w.start}-{w.end}" for w in ws)
    out = f"{_days_label(wt.days)} {win(wt.windows)}"
    if wt.weekend_windows:
        out += f"; Sat-Sun {win(wt.weekend_windows)}"
    return out


def working_days(wt: WorkingTime) -> set[str]:
    days = set(wt.days)
    if wt.weekend_windows:
        days |= {"sat", "sun"}
    return days


def next_working_day(today: date, wt: WorkingTime) -> date:
    days = working_days(wt)
    for k in range(8):
        try:
            d = today + timedelta(days=k)
        except OverflowError:       # date.max: no later day exists
            return today
        if _ORDER[d.weekday()] in days:
            return d
    return today  # pragma: no cover


_NUMBERED_RE = re.compile(r"^(?P<base>.{1,190}?) (?P<i>\d{1,3})$")
_REVISION_RE = re.compile(r"^(?P<base>Revise .{1,180}?) \((?P<i>\d{1,2})/(?P<n>\d{1,2})\)$")


def duration_families(draft: ScheduleDraft) -> dict[str, list[str]]:
    """Activities without a duration that are copies of one item ("Mock test 1..10" from a count, or the
    revisions "Revise x (k/N)" of one subject): first key -> all keys. One duration question per family; the
    answer applies to every member (fix round)."""
    groups: dict[tuple[str, str], list[str]] = {}
    for t in draft.tasks:
        if t.milestone or t.duration is not None:
            continue
        m = _REVISION_RE.match(t.name)
        if m:
            k = ("rev", m.group("base").lower() + "|" + (t.group or ""))
        else:
            m = _NUMBERED_RE.match(t.name)
            if not m:
                continue
            k = ("num", m.group("base").lower() + "|" + (t.group or ""))
        groups.setdefault(k, []).append(t.key)
    return {keys[0]: keys for keys in groups.values() if len(keys) >= 2}


def family_label(draft: ScheduleDraft, keys: list[str]) -> str:
    first = next(t for t in draft.tasks if t.key == keys[0])
    m = _REVISION_RE.match(first.name) or _NUMBERED_RE.match(first.name)
    base = m.group("base") if m else first.name
    return f"{base} (each of {len(keys)})"


def questions(draft: ScheduleDraft, ctx: ExtractContext) -> list[Question]:
    prov = draft.provenance
    out: list[Question] = []
    dismissed = set(draft.dismissed)
    wt = draft.working_time or default_working_time(draft.kind)

    def add(q: Question) -> None:
        if q.id not in dismissed:
            out.append(q)

    if not draft.tasks:
        add(Question(id=qid("SCHED_NO_TASKS", "/tasks"), code="SCHED_NO_TASKS", path="/tasks", kind="text",
                     prompt=M.prompt("SCHED_NO_TASKS"), required=True, reason="missing"))
    if draft.start_date is None and not answered(prov, "/start_date"):
        d = next_working_day(ctx.today, wt)
        add(Question(id=qid("SCHED_START_DATE", "/start_date"), code="SCHED_START_DATE", path="/start_date",
                     kind="date", prompt=M.prompt("SCHED_START_DATE"), default=d.isoformat(),
                     default_label=d.strftime("%a %d %b %Y"), required=False, reason="missing"))
    implied = [p for p, v in prov.items() if v.source == "derived" and v.note == IMPLIED_NOTE]
    if implied and not pathless_done(prov, "SCHED_SEQUENTIAL"):
        add(Question(id=qid("SCHED_SEQUENTIAL", None), code="SCHED_SEQUENTIAL", path=None, kind="confirm",
                     prompt=M.prompt("SCHED_SEQUENTIAL"), default=True, default_label="Yes", required=False,
                     reason="confirm_default"))
    detected = [r for r in draft.resources
                if (p := prov.get(f"/resources/{r.key}/name")) is not None and p.source == "text"
                and p.note == DETECTED_NOTE]
    if detected and not pathless_done(prov, "SCHED_PEOPLE"):
        add(Question(id=qid("SCHED_PEOPLE", None), code="SCHED_PEOPLE", path=None, kind="confirm",
                     prompt=M.prompt("SCHED_PEOPLE", names=M.join_names([r.name for r in detected])),
                     default=True, default_label="Yes", required=False, reason="confirm_default"))
    cands = [(t.key, t.name) for t in draft.tasks]
    index = NameIndex(cands)
    name_of = dict(cands)
    families = duration_families(draft)
    in_family = {k for keys in families.values() for k in keys[1:]}
    for t in draft.tasks:
        base = f"/tasks/{t.key}"
        if not t.milestone and t.duration is None and t.key not in in_family:
            v, u = DEFAULT_DURATION[draft.kind]
            label = family_label(draft, families[t.key]) if t.key in families else t.name
            add(Question(id=qid("SCHED_TASK_DURATION", f"{base}/duration"), code="SCHED_TASK_DURATION",
                         path=f"{base}/duration", kind="duration", prompt=M.prompt("SCHED_TASK_DURATION", task=label),
                         default={"optimistic": v, "likely": v, "pessimistic": v, "unit": u},
                         default_label=duration_label(v, u), required=True, reason="missing",
                         span=prov[f"{base}/name"].span if f"{base}/name" in prov else None))
        ref = prov.get(f"{base}/after_ref")
        if ref is not None and ref.source not in ("answer", "edit") and ref.note.startswith("REF:"):
            text = ref.note[4:]
            ranked = index.resolve(text, exclude=t.key).ranked[:3]
            opts = [QuestionOption(value=k, label=name_of[k]) for k, _ in ranked]
            opts.append(QuestionOption(value="none", label="None of these"))
            add(Question(id=qid("SCHED_DEP_REFERENCE", f"{base}/after_ref"), code="SCHED_DEP_REFERENCE",
                         path=f"{base}/after_ref", kind="choice",
                         prompt=M.prompt("SCHED_DEP_REFERENCE", task=t.name, ref=text), options=opts,
                         required=True, reason="ambiguous", span=ref.span))
        for fld in ("deadline", "earliest_start"):
            p = prov.get(f"{base}/{fld}")
            if p is not None and p.source == "text" and p.note.startswith("AMBIGUOUS:"):
                current = getattr(t, fld)
                if current is None:
                    continue
                alt = p.note.split(":", 1)[1]
                opts = [QuestionOption(value=current.isoformat(), label=current.strftime("%d %b %Y")),
                        QuestionOption(value=alt, label=date.fromisoformat(alt).strftime("%d %b %Y"))]
                add(Question(id=qid("SCHED_DATE_AMBIGUOUS", f"{base}/{fld}"), code="SCHED_DATE_AMBIGUOUS",
                             path=f"{base}/{fld}", kind="choice",
                             prompt=M.prompt("SCHED_DATE_AMBIGUOUS", text=p.span.text if p.span else current.isoformat()),
                             options=opts, default=current.isoformat(), default_label=opts[0].label, required=True,
                             reason="ambiguous", span=p.span))
        if not t.milestone and not t.resources and len(draft.resources) >= 2 \
                and not answered(prov, f"{base}/resources"):
            names = [r.name for r in draft.resources]
            add(Question(id=qid("SCHED_WHO", f"{base}/resources"), code="SCHED_WHO", path=f"{base}/resources",
                         kind="multi_choice", prompt=M.prompt("SCHED_WHO", task=t.name),
                         options=[QuestionOption(value=r.key, label=r.name) for r in draft.resources],
                         default=[r.key for r in draft.resources],
                         default_label=("Either " + M.join_names(names, "or")) if len(names) == 2
                         else "Any of " + M.join_names(names, "or"),
                         required=False, reason="missing"))
    if draft.working_time is None and not answered(prov, "/working_time"):
        d = default_working_time(draft.kind)
        add(Question(id=qid("SCHED_WORKING_TIME", "/working_time"), code="SCHED_WORKING_TIME", path="/working_time",
                     kind="working_time", prompt=M.prompt("SCHED_WORKING_TIME"), default=d.model_dump(mode="json"),
                     default_label=working_time_label(d), required=False, reason="confirm_default"))
    for path, p in prov.items():
        if p.confidence < 0.5 and p.source in ("text", "table", "ai", "derived") and not path.endswith("/after_ref") \
                and not p.note.startswith("AMBIGUOUS:") and _path_exists(draft, path):
            t_unq = _unquoted_duration(draft, path, p)
            if t_unq is not None:
                # an AI duration with no supporting quote: required, "No" clears it (fix round, 2.10)
                add(Question(id=qid("SCHED_LOW_CONFIDENCE", path), code="SCHED_LOW_CONFIDENCE", path=path,
                             kind="confirm", prompt=M.prompt("SCHED_AI_UNQUOTED", name=t_unq[0], value=t_unq[1]),
                             required=True, reason="low_confidence"))
                continue
            if p.source == "ai" and p.note == "AI_UNQUOTED" and path.startswith(("/tasks/", "/resources/")):
                continue    # one question per unquoted AI task: its duration (above), not its name or links
            add(Question(id=qid("SCHED_LOW_CONFIDENCE", path), code="SCHED_LOW_CONFIDENCE", path=path, kind="confirm",
                         prompt=M.prompt("SCHED_LOW_CONFIDENCE", text=p.span.text if p.span else path),
                         default=True, default_label="Yes", required=False, reason="low_confidence", span=p.span))
    return order(out)


def _unquoted_duration(draft: ScheduleDraft, path: str, p) -> tuple[str, str] | None:
    if p.source != "ai" or p.note != "AI_UNQUOTED" or not (path.startswith("/tasks/") and path.endswith("/duration")):
        return None
    key = path.split("/")[2]
    t = next((x for x in draft.tasks if x.key == key), None)
    if t is None or t.duration is None:
        return None
    d = t.duration
    value = duration_label(d.likely, d.unit) if d.optimistic == d.pessimistic else \
        f"{fmt_amount(d.optimistic)}-{duration_label(d.pessimistic, d.unit)}"
    return t.name, value


def _path_exists(draft: ScheduleDraft, path: str) -> bool:
    parts = path.strip("/").split("/")
    if parts[0] == "tasks" and len(parts) == 3:
        return any(t.key == parts[1] for t in draft.tasks)
    if parts[0] == "resources" and len(parts) == 3:
        return any(r.key == parts[1] for r in draft.resources)
    return len(parts) == 1 and parts[0] in ScheduleDraft.model_fields

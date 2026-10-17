"""Rule-based + AI merge (PHASE2 2.11). Typed numbers win; AI-only values keep AI provenance (confidence <= 0.8);
an invalid merged draft discards the AI result (AI_SCHEMA_MISMATCH)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from ..extractors import AiFallback
from ..messages import note_text
from ..models import FinanceDraft, IntakeNote, Provenance, ScheduleDraft
from ..text.names import jaccard, norm_tokens

AI_CAP = 0.8
SCHEDULE_TASK_FIELDS = ("duration", "deadline", "deadline_hard", "earliest_start", "group")   # milestone: R decides
FIN_FIELDS = {
    "incomes": ("amount", "frequency", "kind"),
    "expenses": ("amount", "frequency", "essential", "category"),
    "debts": ("balance", "emi", "interest_rate_pct", "remaining_months"),
    "holdings": ("amount", "asset_class_id", "locked_until_month"),
    "goals": ("target", "target_month", "priority"),
}
FIN_PREFIX = {"incomes": "i", "expenses": "e", "debts": "d", "holdings": "h", "goals": "g"}


def _empty(v: Any) -> bool:
    return v is None or v == [] or v == ""


def _fmt(v: Any) -> str:
    if isinstance(v, BaseModel):
        d = v.model_dump()
        if set(d) == {"low", "high"}:
            lo, hi = d["low"], d["high"]
            f = lambda x: f"{x:,.0f}" if float(x).is_integer() else f"{x:,}"  # noqa: E731
            return f(lo) if lo == hi else f"{f(lo)}-{f(hi)}"
        if "unit" in d:
            o, m, p, u = d["optimistic"], d["likely"], d["pessimistic"], d["unit"]
            g = lambda x: f"{x:g}"  # noqa: E731
            return f"{g(o)} {u}" if o == p else f"{g(o)}-{g(p)} {u}"
        return str(d)
    return str(v)


def _typed(p: Provenance | None) -> bool:
    return p is not None and p.source == "text" and p.span is not None and any(ch.isdigit() for ch in p.span.text)


def _cap(p: Provenance | None) -> Provenance:
    if p is None:
        return Provenance(source="ai", confidence=0.5)
    return p.model_copy(update={"source": "ai", "confidence": min(p.confidence, AI_CAP)})


def _match(r_items: list[Any], a_items: list[Any], amount_attr: str | None = None) -> dict[int, int]:
    """A index -> R index, one-to-one, by name token-Jaccard >= 0.6 (or amount within 10 %)."""
    pairs: list[tuple[float, int, int]] = []
    for ai, a in enumerate(a_items):
        at = norm_tokens(a.name)
        for ri, r in enumerate(r_items):
            score = jaccard(at, norm_tokens(r.name))
            if score < 0.6 and amount_attr:
                ra, aa = getattr(r, amount_attr), getattr(a, amount_attr)
                if ra is not None and aa is not None and ra.mid > 0 and abs(aa.mid - ra.mid) <= 0.1 * ra.mid:
                    score = 0.6
            if score >= 0.6:
                pairs.append((score, ai, ri))
    pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
    out: dict[int, int] = {}
    used: set[int] = set()
    for _, ai, ri in pairs:
        if ai not in out and ri not in used:
            out[ai] = ri
            used.add(ri)
    return out


def _merge_fields(r: Any, a: Any, fields: tuple[str, ...], r_base: str, a_base: str, prov: dict[str, Provenance],
                  a_prov: dict[str, Provenance], notes: list[IntakeNote]) -> None:
    for f in fields:
        rv, av = getattr(r, f), getattr(a, f)
        if _empty(av) or (isinstance(av, bool) and av is False and isinstance(rv, bool)):
            continue
        rp, ap = prov.get(f"{r_base}/{f}"), a_prov.get(f"{a_base}/{f}")
        if _empty(rv):
            setattr(r, f, av)
            prov[f"{r_base}/{f}"] = _cap(ap)
            continue
        if rv == av:
            continue
        if _typed(rp):
            notes.append(IntakeNote(code="KEPT_TYPED_NUMBER", severity="info",
                                    message=note_text("KEPT_TYPED_NUMBER", a=_fmt(av), r=_fmt(rv)), span=rp.span))
            continue
        rc = rp.confidence if rp is not None else 0.6
        ac = min(ap.confidence, AI_CAP) if ap is not None else 0.5
        if ac > rc:
            setattr(r, f, av)
            prov[f"{r_base}/{f}"] = _cap(ap)


def merge_schedule(R: ScheduleDraft, A: ScheduleDraft, a_notes: list[IntakeNote]) -> tuple[ScheduleDraft, list[IntakeNote]]:
    out = R.model_copy(deep=True)
    prov = out.provenance
    notes: list[IntakeNote] = []
    # resources
    rmap: dict[str, str] = {}
    rm = _match(out.resources, A.resources)
    for ai, a in enumerate(A.resources):
        if ai in rm:
            rmap[a.key] = out.resources[rm[ai]].key
            continue
        key, k = a.key, 2
        while any(x.key == key for x in out.resources):
            key = f"{a.key[:28]}_{k}"
            k += 1
        out.resources.append(a.model_copy(update={"key": key}))
        rmap[a.key] = key
        prov[f"/resources/{key}/name"] = _cap(A.provenance.get(f"/resources/{a.key}/name"))
    # tasks
    tmap: dict[str, str] = {}
    tm = _match(out.tasks, A.tasks)
    n = len(out.tasks)
    used = {t.key for t in out.tasks}
    appended = []
    for ai, a in enumerate(A.tasks):
        if ai in tm:
            tmap[a.key] = out.tasks[tm[ai]].key
            continue
        n += 1
        key = f"t{n}"
        while key in used:
            n += 1
            key = f"t{n}"
        used.add(key)
        tmap[a.key] = key
        appended.append((a, key))
    for ai, ri in tm.items():
        a, r = A.tasks[ai], out.tasks[ri]
        _merge_fields(r, a, SCHEDULE_TASK_FIELDS, f"/tasks/{r.key}", f"/tasks/{a.key}", prov, A.provenance, notes)
        for f, mp in (("after", tmap), ("resources", rmap)):
            refs = [mp.get(x) for x in getattr(a, f)]
            dropped = [x for x, m in zip(getattr(a, f), refs) if m is None]
            for x in dropped:
                notes.append(IntakeNote(code="AI_REFERENCE_DROPPED", severity="info",
                                        message=note_text("AI_REFERENCE_DROPPED", name=x)))
            refs = [x for x in refs if x is not None and x != r.key]
            if not getattr(r, f) and refs:
                setattr(r, f, list(dict.fromkeys(refs)))
                prov[f"/tasks/{r.key}/{f}"] = _cap(A.provenance.get(f"/tasks/{a.key}/{f}"))
        if r.milestone:
            r.duration = None
            r.resources = []
    for a, key in appended:
        after = [tmap[x] for x in a.after if x in tmap and tmap[x] != key]
        res = [rmap[x] for x in a.resources if x in rmap]
        for x in a.after + a.resources:
            if x not in tmap and x not in rmap:
                notes.append(IntakeNote(code="AI_REFERENCE_DROPPED", severity="info",
                                        message=note_text("AI_REFERENCE_DROPPED", name=x)))
        out.tasks.append(a.model_copy(update={"key": key, "after": list(dict.fromkeys(after)), "resources": res}))
        for path, p in A.provenance.items():
            if path.startswith(f"/tasks/{a.key}/"):
                prov[f"/tasks/{key}/" + path.split("/", 3)[3]] = _cap(p)
    # top level
    for f, path in (("start_date", "/start_date"), ("working_time", "/working_time")):
        if getattr(out, f) is None and getattr(A, f) is not None:
            setattr(out, f, getattr(A, f))
            prov[path] = _cap(A.provenance.get(path))
    if out.name == "My plan" and A.name != "My plan":
        out.name = A.name
    notes.extend(a_notes)
    try:
        merged = ScheduleDraft.model_validate(out.model_dump())
    except ValidationError:
        raise AiFallback("AI_SCHEMA_MISMATCH") from None
    return merged, notes


def merge_finance(R: FinanceDraft, A: FinanceDraft, a_notes: list[IntakeNote]) -> tuple[FinanceDraft, list[IntakeNote]]:
    out = R.model_copy(deep=True)
    prov = out.provenance
    notes: list[IntakeNote] = []
    for f in ("age", "retirement_age", "risk_tolerance"):
        rv, av = getattr(out.profile, f), getattr(A.profile, f)
        path = f"/profile/{f}"
        if av is None:
            continue
        if rv is None:
            setattr(out.profile, f, av)
            prov[path] = _cap(A.provenance.get(path))
        elif rv != av and _typed(prov.get(path)):
            notes.append(IntakeNote(code="KEPT_TYPED_NUMBER", severity="info",
                                    message=note_text("KEPT_TYPED_NUMBER", a=_fmt(av), r=_fmt(rv)),
                                    span=prov[path].span))
    for coll, fields in FIN_FIELDS.items():
        r_items, a_items = getattr(out, coll), getattr(A, coll)
        amount_attr = "amount" if coll in ("incomes", "expenses") else None
        m = _match(r_items, a_items, amount_attr)
        keys = {x.key for x in r_items}
        k = len(r_items)
        for ai, a in enumerate(a_items):
            if ai in m:
                r = r_items[m[ai]]
                _merge_fields(r, a, fields, f"/{coll}/{r.key}", f"/{coll}/{a.key}", prov, A.provenance, notes)
                continue
            k += 1
            key = f"{FIN_PREFIX[coll]}{k}"
            while key in keys:
                k += 1
                key = f"{FIN_PREFIX[coll]}{k}"
            keys.add(key)
            r_items.append(a.model_copy(update={"key": key}))
            for path, p in A.provenance.items():
                if path.startswith(f"/{coll}/{a.key}/"):
                    prov[f"/{coll}/{key}/" + path.split("/", 3)[3]] = _cap(p) if not p.note.startswith("AT_AGE:") \
                        else p.model_copy(update={"source": "ai"})
    if out.emergency_fund_months is None and A.emergency_fund_months is not None:
        out.emergency_fund_months = A.emergency_fund_months
        prov["/emergency_fund_months"] = Provenance(source="ai", confidence=0.5)
    notes.extend(a_notes)
    try:
        merged = FinanceDraft.model_validate(out.model_dump())
    except ValidationError:
        raise AiFallback("AI_SCHEMA_MISMATCH") from None
    return merged, notes

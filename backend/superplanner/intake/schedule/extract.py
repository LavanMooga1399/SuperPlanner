"""Rule-based `ScheduleDraft` extraction (PHASE2 2.7.5-2.7.8, 2.7.10).

Deterministic and pure. Offsets are handled in the normalised text and mapped back to code points of the
submitted text for every span. All patterns are bounded (linear time).
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..messages import note_text
from ..models import (DraftDuration, DraftResource, DraftTask, ExtractContext, IntakeNote, Provenance, ScheduleDraft,
                      ScheduleKind, TimeWindow, WorkingTime)
from ..text.dates import HARD_RE, DateMatch, find_dates, out_of_range_dates, role_of
from ..text.durations import DurMatch, find_durations
from ..text.names import NOT_NAMES, NameIndex, capitalised_names, norm_tokens, resolve, slug
from ..text.numbers import NUM, parse_number
from ..text.segment import Segment, Text, blank, clean_name, normalise, segments

KIND_CUES: dict[str, tuple[str, ...]] = {
    "study": ("exam", "study", "revise", "syllabus", "chapter", "mock", "subject"),
    "production": ("machine", "order", "batch", "job", "shift", "operation", "assembly"),
    "project": ("launch", "release", "client", "sprint", "design", "build", "deploy", "milestone"),
}
_KIND_RES = {k: re.compile(r"\b(?:" + "|".join(v) + r")\w{0,4}\b", re.I) for k, v in KIND_CUES.items()}

TASK_VERBS = (r"build|write|design|test|prepare|study|revise|review|cut|assemble|paint|pack|deliver|install|plan|"
              r"launch|finish|complete|do|make")
TASK_VERB_RE = re.compile(rf"\b(?:{TASK_VERBS})(?:s|es|ed|ing)?\b", re.I)
MILESTONE_RE = re.compile(r"\b(?:launch|release|go-live|go live|deadline|exam|delivery|handover|milestone|submission|"
                          r"demo day)\b", re.I)
FILLER_RE = re.compile(r"^(?:(?:we|i)\s+(?:need|have|want|plan)\s+to|(?:we|i)\s+(?:must|will|should)|need\s+to|"
                       r"have\s+to|we'll|i'll|and then|then|also|finally|first(?:ly)?|next|lastly|after that|and)\s+",
                       re.I)
RULE_CUE_RE = re.compile(r"\b(?:only|never|not on|no more than|at most|at least|maximum|minimum|every other|alternate|"
                         r"unless|except|budget|cost limit)\b", re.I)

# dependencies (2.7.6); every reference is bounded to 80 characters
_REF = r"(?P<ref>[^,;()\n]{1,80})"
AFTER_RE = re.compile(r"\b(?P<w>after|following|depends on|depending on|requires|needs)\s+" + _REF, re.I)
ONCE_RE = re.compile(r"\b(?:once|when|as soon as)\s+(?P<ref>[^,;()\n]{1,80}?)\s+(?:(?:is|are|has been|have been)\s+)?"
                     r"(?:done|finished|complete|completed|ready|approved|over|ends|ended)\b", re.I)
BEFORE_RE = re.compile(r"\bbefore\s+" + _REF, re.I)
PARALLEL_RE = re.compile(r"\b(?:in parallel with|at the same time as|alongside)\s+" + _REF, re.I)
END_RE = re.compile(r"\b(?:after everything else|after all of the above|after all the rest|after everything|"
                    r"at the (?:very )?end|last of all)\b", re.I)
_REF_STOP_RE = re.compile(r"\s+(?:by|before|then|and then|once|so|because|but|first|done|is done)\b.*$", re.I)
CROSS_BEFORE_RE = re.compile(r"^(?P<x>[^\n]{1,80}?)\s+(?:must|should|has to|have to|needs to|need to)?\s*"
                             r"(?:be\s+(?:done|finished|completed)\s+)?before\s+(?P<y>[^\n]{1,80})$", re.I)
CROSS_AFTER_RE = re.compile(r"^(?P<y>[^\n]{1,80}?)\s+(?:comes\s+|happens\s+|starts\s+)?after\s+(?P<x>[^\n]{1,80})$", re.I)
CROSS_WHEN_RE = re.compile(r"^(?P<y>[^\n]{1,80}?)\s+can\s+start\s+(?:when|once|after)\s+(?P<x>[^\n]{1,80}?)"
                           r"(?:\s+(?:ends|is done|finishes|is finished))?$", re.I)
THEN_SPLIT_RE = re.compile(r"\s*,?\s*\bthen\b\s*|\s*->\s*|\s*→\s*|\s+>\s+", re.I)

# counts (2.7.5)
COUNT_NOUNS = r"mock tests?|mock exams?|practice tests?|chapters?|modules?|units?|lessons?|orders?|jobs?|batches?|" \
              r"episodes?|interviews?|papers?"
COUNT_RE = re.compile(rf"\b(?P<n>{NUM})\s+(?P<noun>{COUNT_NOUNS})\b", re.I)
EACH_CHAIN_RE = re.compile(r"\beach\s+(?:one\s+)?(?:needs|goes through|is|requires|has)\s+(?P<ops>[^.;\n]{1,200})", re.I)
REVISE_RE = re.compile(rf"\brevis(?:e|ing)\s+(?:everything|it all|all|all of it|each(?:\s+\w+)?|every\s+\w+|the lot)\s+"
                       rf"(?P<n>twice|thrice|once|(?:{NUM})\s+times)\b", re.I)

# study exam (2.7.5)
EXAM_DAYS_RE = re.compile(rf"\b(?P<n>{NUM})\s+(?P<u>days?|weeks?|months?)\s+(?:left\s+)?(?:to|until|before)\s+"
                          r"(?:prepare|study|revise|get ready|the exam|my exam|the test|exam)\b", re.I)
EXAM_DATE_RE = re.compile(r"\b(?:exam|test|paper)\b[^.\n]{0,40}?\b(?P<w>on|in|by)\s+", re.I)

# study subjects (2.7.5): "Subjects: Physics, Chemistry and Maths" -> one study task (and group) per subject
SUBJECTS_RE = re.compile(r"^\s*(?:(?:my|the|our)\s+)?subjects?\s*(?::|-|are\b|is\b|include\b)\s*(?P<list>[^\n]{1,300})$",
                         re.I)
_LIST_SPLIT_RE = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*|\s*/\s*", re.I)
# deadline wording left before a removed date ("..., must be done by 25 Oct") is not part of the name
DEADLINE_LEAD_RE = re.compile(
    r"(?:,\s*|\s+)(?:and\s+)?(?:(?:it|this|that)\s+)?(?:(?:must|should|has to|have to|needs? to|is to|will)\s+be\s+"
    r"(?:done|finished|completed?|ready|delivered|submitted|paid|sent|over)|(?:must|should)\s+(?:finish|end)|"
    r"(?:hard\s+)?deadline(?:\s+is)?|at the latest|latest)\s*$", re.I)
# "Order A: cutting 3 h, ..." / "Steps: design, build and test": a short label before a colon
LABEL_RE = re.compile(r"^\s*(?P<label>[^:\n]{1,40}):\s*(?P<rest>\S.*)$")

# resources (2.7.7)
COUNTED_RES_NOUNS = {"machines": "machine", "machine": "machine", "cnc machines": "machine", "ovens": "machine",
                     "lathes": "machine", "printers": "machine", "people": "person", "developers": "person",
                     "designers": "person", "testers": "person", "operators": "person", "workers": "person",
                     "teachers": "person", "rooms": "room", "trucks": "equipment"}
_RES_ALT = "|".join(sorted(COUNTED_RES_NOUNS, key=len, reverse=True))
COUNTED_RES_RE = re.compile(rf"\b(?P<n>{NUM})\s+(?P<noun>{_RES_ALT})\b", re.I)
TEAM_OF_RE = re.compile(rf"\bteam\s+of\s+(?P<n>{NUM})\b", re.I)
ASSIGN_RE = re.compile(r"\b(?:assigned to|assign to|owned by|done by|owner\s*:|by|with)\s+", re.I)
LEAD_NAME_RE = re.compile(r"^(?P<name>[A-Z][a-z]{1,29}(?:\s{0,3}(?:,|and|&)\s{0,3}[A-Z][a-z]{1,29}){0,5})\s+"
                          r"(?:will|can|should|does|is going to)\s+", re.U)
_NAME_SPLIT_RE = re.compile(r"\s*(?:,|\band\b|&)\s*")
ME_RE = re.compile(r"\b(?:by me|\(me\)|myself)\b|^i\s+(?:will|can|should)\b", re.I)
TOGETHER_RE = re.compile(r"\b(?:together|both)\b", re.I)

# working time (2.7.8)
HOURS_RE = re.compile(rf"\b(?P<n>{NUM})\s+hours?\s+(?:(?:on|every|each|per|a)\s+)?(?P<when>weekdays?|weekends?|"
                      r"week-?days?|weekend days|days?|daily|evenings?|mornings?)\b", re.I)
CLOCK_RE = re.compile(r"\b(?P<a>\d{1,2})(?::(?P<am>\d{2}))?\s*(?P<ap>am|pm)?\s*(?:-|to|till|until)\s*"
                      r"(?P<b>\d{1,2})(?::(?P<bm>\d{2}))?\s*(?P<bp>am|pm)?(?!\s*(?:days?|weeks?|hours?|h\b|d\b|w\b))",
                      re.I)
DAYS_RE = re.compile(r"\b(?P<d>monday\s+to\s+friday|mon\s*-\s*fri|mon\s+to\s+fri|monday\s*-\s*friday|weekdays|"
                     r"monday\s+to\s+saturday|mon\s*-\s*sat|mon\s+to\s+sat|six days a week|every day|daily|"
                     r"7 days a week|seven days a week|no weekends)\b", re.I)
SHIFTS_RE = re.compile(r"\b(?:two|2)\s+shifts\b", re.I)
WT_CONTEXT_RE = re.compile(r"\b(?:work|works|working|hours|shift|available|from|study|office)\b", re.I)

START_HOUR = {"study": 18 * 60, "project": 9 * 60, "production": 6 * 60, "generic": 9 * 60}
WEEKDAYS5 = ["mon", "tue", "wed", "thu", "fri"]
DEFAULT_RESOURCE = {"project": ("Me", "person"), "study": ("Study time", "generic"),
                    "production": ("Machine", "machine"), "generic": ("Me", "person")}


def default_working_time(kind: str) -> WorkingTime:
    if kind == "study":
        return WorkingTime(days=WEEKDAYS5, windows=[TimeWindow(start="18:00", end="21:00")],
                           weekend_windows=[TimeWindow(start="09:00", end="13:00"),
                                            TimeWindow(start="14:00", end="18:00")])
    if kind == "production":
        return WorkingTime(days=WEEKDAYS5 + ["sat"], windows=[TimeWindow(start="06:00", end="14:00"),
                                                              TimeWindow(start="14:00", end="22:00")])
    return WorkingTime(days=WEEKDAYS5, windows=[TimeWindow(start="09:00", end="17:00")])


def detect_kind(norm: str, ctx_kind: ScheduleKind | None) -> ScheduleKind:
    if ctx_kind is not None:
        return ctx_kind
    counts = {k: len(rx.findall(norm)) for k, rx in _KIND_RES.items()}
    best = max(counts.values())
    if best < 2:
        return "generic"
    for k in ("study", "production", "project"):
        if counts[k] == best:
            return k  # type: ignore[return-value]
    return "generic"  # pragma: no cover


def _hhmm(m: int) -> str:
    m = max(0, min(m, 1440))
    return f"{m // 60:02d}:{m % 60:02d}"


def windows_for_hours(n_hours: float, start: int) -> list[TimeWindow]:
    minutes = int(round(n_hours * 60))
    minutes = max(30, min(minutes, 16 * 60))
    if n_hours > 4:
        start = 9 * 60
        first = 13 * 60 - start
        second = minutes - first
        if second <= 0:
            return [TimeWindow(start=_hhmm(start), end=_hhmm(start + minutes))]
        return [TimeWindow(start=_hhmm(start), end="13:00"), TimeWindow(start="14:00", end=_hhmm(14 * 60 + second))]
    end = start + minutes
    if end > 1440:
        start = max(0, 1440 - minutes)
        end = 1440
    return [TimeWindow(start=_hhmm(start), end=_hhmm(end))]


@dataclass
class _Res:
    key: str
    name: str
    kind: str = "person"
    count: int = 1
    span: tuple[int, int] | None = None
    confidence: float = 0.7
    detected: bool = False


@dataclass
class _Item:
    start: int
    end: int
    seg: Segment
    work: str                                   # norm slice with extracted phrases blanked
    name: str = ""
    duration: DurMatch | None = None            # absolute offsets
    deadline: tuple[date, bool, int, int, float] | None = None
    earliest: tuple[date, int, int, float] | None = None
    after_refs: list[tuple[str, int, int, float]] = field(default_factory=list)
    before_refs: list[tuple[str, int, int, float]] = field(default_factory=list)
    explicit_dep: bool = False
    at_end: bool = False
    res_names: list[str] = field(default_factory=list)
    res_span: tuple[int, int] | None = None
    mode: str = "any"
    count: tuple[int, str, float] | None = None
    chain_ops: list[str] | None = None
    milestone: bool = False
    group: str | None = None
    chain_prev: "_Item | None" = None           # then-chain predecessor
    keys: list[str] = field(default_factory=list)
    ambiguous_date: DateMatch | None = None
    low_conf: list[tuple[str, float]] = field(default_factory=list)
    is_revision_rule: int = 0


@dataclass
class ScheduleExtractionResult:
    draft: ScheduleDraft
    notes: list[IntakeNote]


class _Extractor:
    def __init__(self, text: str, ctx: ExtractContext):
        self.ctx = ctx
        self.t: Text = normalise(text)
        self.s = self.t.norm
        self.segs = segments(self.t)
        self._seg_starts = [g.start for g in self.segs]
        self.kind: ScheduleKind = detect_kind(self.s, ctx.kind)
        self.prov: dict[str, Provenance] = {}
        self.notes: list[IntakeNote] = []
        self.resources: list[_Res] = []
        self.claimed: list[tuple[int, int]] = []
        self.working_time: WorkingTime | None = None
        self.start_date: date | None = None
        self.name: str | None = None
        self.exam: tuple[date, int, int, float] | None = None
        self.revise_times = 0
        self.revise_span: tuple[int, int] | None = None
        self._dropped: list[_Item] = []
        self.subject_items: list[_Item] = []
        self.subject_spans: list[tuple[int, int]] = []
        self.cross: list[tuple[_Item, _Item, int, int]] = []

    # ------------------------------------------------------------ helpers
    def span(self, a: int, b: int):
        return self.t.span(a, b)

    def p_text(self, path: str, a: int, b: int, conf: float, note: str = "") -> None:
        self.prov[path] = Provenance(source="text", confidence=round(conf, 3), span=self.span(a, b), note=note)

    def p_derived(self, path: str, conf: float, note: str, a: int | None = None, b: int | None = None) -> None:
        self.prov[path] = Provenance(source="derived", confidence=conf, note=note,
                                     span=self.span(a, b) if a is not None and b is not None else None)

    def note(self, code: str, severity: str, message: str, a: int | None = None, b: int | None = None) -> None:
        self.notes.append(IntakeNote(code=code, severity=severity, message=message,  # type: ignore[arg-type]
                                     span=self.span(a, b) if a is not None and b is not None else None))

    def resource_by_name(self, name: str) -> _Res | None:
        low = name.lower()
        return next((r for r in self.resources if r.name.lower() == low), None)

    def add_person(self, name: str, a: int, b: int, conf: float = 0.7, detected: bool = True) -> _Res:
        r = self.resource_by_name(name)
        if r is not None:
            return r
        key = "r_" + slug(name)
        base, k = key, 2
        while any(x.key == key for x in self.resources):
            key = f"{base[:28]}_{k}"
            k += 1
        r = _Res(key=key, name=name, kind="person", span=(a, b), confidence=conf, detected=detected)
        self.resources.append(r)
        return r

    # ------------------------------------------------------------ global passes
    def pass_working_time(self) -> None:
        s = self.s
        weekday: list[TimeWindow] | None = None
        weekend: list[TimeWindow] | None = None
        days: list[str] | None = None
        spans: list[tuple[int, int]] = []
        for m in HOURS_RE.finditer(s):
            n = parse_number(m.group("n"))
            if n is None or n[0] <= 0 or n[0] > 16:
                continue
            when = m.group("when").lower()
            if when.startswith("weekend"):
                weekend = windows_for_hours(n[0], 9 * 60)
            else:
                weekday = windows_for_hours(n[0], START_HOUR[self.kind])
            spans.append((m.start(), m.end()))
        context: dict[int, bool] = {}
        for m in CLOCK_RE.finditer(s):
            seg = self._segment_at(m.start())
            if seg is None:
                continue
            has_clock = bool(m.group("am") or m.group("bm") or m.group("ap") or m.group("bp"))
            if id(seg) not in context:      # once per segment: keeps this pass linear
                context[id(seg)] = bool(WT_CONTEXT_RE.search(seg.text))
            if not has_clock and not context[id(seg)]:
                continue
            a = int(m.group("a")) * 60 + int(m.group("am") or 0)
            b = int(m.group("b")) * 60 + int(m.group("bm") or 0)
            if m.group("ap") and m.group("ap").lower() == "pm" and a < 12 * 60:
                a += 12 * 60
            if m.group("bp") and m.group("bp").lower() == "pm" and b < 12 * 60:
                b += 12 * 60
            if not m.group("bp") and b <= a and b < 12 * 60:
                b += 12 * 60
            if not (0 <= a < b <= 1440):
                continue
            weekday = [TimeWindow(start=_hhmm(a), end=_hhmm(b))]
            spans.append((m.start(), m.end()))
        for m in DAYS_RE.finditer(s):
            d = m.group("d").lower()
            if "sat" in d or "six days" in d:
                days = WEEKDAYS5 + ["sat"]
            elif d in ("every day", "daily", "7 days a week", "seven days a week"):
                days = WEEKDAYS5 + ["sat", "sun"]
            else:
                days = WEEKDAYS5
            spans.append((m.start(), m.end()))
        if SHIFTS_RE.search(s):
            m = SHIFTS_RE.search(s)
            assert m is not None
            default = default_working_time("production")
            weekday, days = default.windows, days or default.days
            spans.append((m.start(), m.end()))
        if weekday is None and weekend is None and days is None:
            return
        base = default_working_time(self.kind)
        if weekday is None and weekend is not None and days is None:
            wt = WorkingTime(days=["sat", "sun"], windows=weekend)
        else:
            wt = WorkingTime(days=days or base.days, windows=weekday or base.windows,
                             weekend_windows=weekend if weekend is not None else (
                                 base.weekend_windows if days is None and weekday is None else None))
        self.working_time = wt
        a, b = min(x[0] for x in spans), max(x[1] for x in spans)
        self.p_text("/working_time", a, b, 0.8)
        self.claimed.extend(spans)
        for seg in self.segs:
            if not seg.bullet and any(seg.start <= x < seg.end for x, _ in spans):
                seg.consumed = True

    def _segment_at(self, pos: int) -> Segment | None:
        i = bisect.bisect_right(self._seg_starts, pos) - 1
        if i >= 0 and self.segs[i].start <= pos < self.segs[i].end:
            return self.segs[i]
        return None

    def pass_exam(self) -> None:
        if self.kind != "study" and not re.search(r"\bexam\b", self.s, re.I):
            return
        for seg in self.segs:
            m = EXAM_DAYS_RE.search(seg.text)
            if m:
                n = parse_number(m.group("n"))
                if n is None:
                    continue
                k = int(round(n[0]))
                u = m.group("u").lower().rstrip("s")
                today = self.ctx.today
                d = today + timedelta(days=k if u == "day" else 7 * k if u == "week" else 30 * k)
                self.exam = (d, seg.start + m.start(), seg.start + m.end(), 0.8 if u == "day" else 0.7)
                seg.consumed = seg.consumed or not seg.bullet
                return
            m = EXAM_DATE_RE.search(seg.text)
            if m:
                # from the role word on, so relative dates such as "in 90 days" are read too
                w0 = m.start("w")
                rest = seg.text[w0:]
                ds = find_dates(rest, self.ctx.today, self.ctx.locale)
                if ds and ds[0].start <= m.end() - w0:
                    dm = ds[0]
                    end = w0 + dm.end
                    self.exam = (dm.value, seg.start + m.start(), seg.start + end, dm.confidence)
                    if not TASK_VERB_RE.search(blank(seg.text, [(m.start(), end)])) or not seg.bullet:
                        seg.consumed = True
                    return

    def pass_subjects(self) -> None:
        """`Subjects: a, b and c` (2.7.5): one study task per subject, grouped by subject; never people."""
        for seg in self.segs:
            m = SUBJECTS_RE.match(seg.text)
            if not m:
                continue
            base = seg.start + m.start("list")
            lst = m.group("list")
            pos = 0
            pieces: list[tuple[int, int]] = []
            for sm in _LIST_SPLIT_RE.finditer(lst):
                pieces.append((pos, sm.start()))
                pos = sm.end()
            pieces.append((pos, len(lst)))
            made = 0
            for x, y in pieces[:30]:
                piece = lst[x:y]
                if not piece.strip(" .;"):
                    continue
                ds = find_durations(piece)
                work = piece
                dur = None
                if ds:
                    d = ds[0]
                    dur = DurMatch(base + x + d.start, base + x + d.end, d.optimistic, d.likely, d.pessimistic,
                                   d.unit, d.confidence, d.note, d.ranged)
                    work = piece[:d.start] + " " * (d.end - d.start) + piece[d.end:]
                name = clean_name(work, 60)
                if not name or not re.search(r"[A-Za-z]", name):
                    continue
                a, b = base + x, base + y
                it = _Item(start=a, end=b, seg=seg, work=work, name=name, duration=dur, group=name)
                if dur is not None and dur.confidence < 0.5:
                    it.low_conf.append(("duration", dur.confidence))
                self.subject_items.append(it)
                made += 1
            if made:
                seg.consumed = True
                self.subject_spans.append((seg.start, seg.end))
                self.claimed.append((seg.start, seg.end))

    def pass_people(self) -> None:
        initial = {g.start for g in self.segs}
        # also the first word after a colon or a bullet-like dash
        for seg in self.segs:
            for m in re.finditer(r"[:;]\s*", seg.text):
                initial.add(seg.start + m.end())
        hits = []
        for seg in self.segs:
            hits.extend(capitalised_names(seg.text, seg.start, initial_positions=initial, extra_stop=set()))
        for h in hits:
            if self.exam and self.exam[1] <= h.start < self.exam[2]:
                continue
            if any(a <= h.start < b for a, b in self.subject_spans):
                continue
            self.add_person(h.name, h.start, h.end)
        for m in COUNTED_RES_RE.finditer(self.s):
            n = parse_number(m.group("n"))
            if n is None or not (1 <= n[0] <= 50):
                continue
            noun = m.group("noun").lower()
            kind = COUNTED_RES_NOUNS[noun]
            name = noun[:-1] if noun.endswith("s") else noun
            name = "People" if noun == "people" else name
            name = "Person" if noun == "people" else name
            name = name[0].upper() + name[1:]
            r = _Res(key="r_" + slug(name), name=name, kind=kind, count=int(n[0]), span=(m.start(), m.end()),
                     confidence=0.95 * n[1] / 0.95 if n[1] < 0.95 else 0.95)
            if not any(x.key == r.key for x in self.resources):
                self.resources.append(r)
            self.claimed.append((m.start(), m.end()))
        for m in TEAM_OF_RE.finditer(self.s):
            n = parse_number(m.group("n"))
            if n is None or not (1 <= n[0] <= 50):
                continue
            if not any(x.key == "r_team_member" for x in self.resources):
                self.resources.append(_Res(key="r_team_member", name="Team member", kind="person", count=int(n[0]),
                                           span=(m.start(), m.end()), confidence=0.95))
            self.claimed.append((m.start(), m.end()))

    # ------------------------------------------------------------ items
    def _is_task_prose(self, seg: Segment, work: str) -> bool:
        if seg.consumed:
            return False
        return bool(TASK_VERB_RE.search(work) or find_durations(work))

    def _split_prose(self, seg: Segment) -> list[tuple[int, int]]:
        """Clauses of a prose sentence that each start with a task verb (study example), else the whole."""
        text = seg.text
        if THEN_SPLIT_RE.search(text):          # "A 1 day, then B 2 days, then C": one then-chain, not clauses
            return [(seg.start, seg.end)]
        parts: list[tuple[int, int]] = []
        pos = 0
        for m in re.finditer(rf",\s*(?:and\s+)?|\s+and\s+(?=(?:{TASK_VERBS})\b)", text, re.I):
            parts.append((pos, m.start()))
            pos = m.end()
        parts.append((pos, len(text)))
        verb_parts = [p for p in parts if TASK_VERB_RE.match(FILLER_RE.sub("", text[p[0]:p[1]].strip()))
                      or REVISE_RE.search(text[p[0]:p[1]])]
        if len(parts) >= 2 and len(verb_parts) == len(parts):
            return [(seg.start + a, seg.start + b) for a, b in parts]
        # "I need to finish X, revise Y and complete Z": first clause has a filler before the verb
        if len(parts) >= 2 and len(verb_parts) >= 2:
            return [(seg.start + a, seg.start + b) for a, b in parts]
        return [(seg.start, seg.end)]

    def build_items(self) -> list[_Item]:
        items: list[_Item] = []
        for seg in self.segs:
            work = blank(seg.text, self.claimed, seg.start)
            if seg.bullet:
                if seg.consumed:
                    continue
                ranges = [(seg.start, seg.end)]
            else:
                if not self._is_task_prose(seg, work):
                    continue
                listed = self._label_list(seg)
                if listed is not None:
                    items.extend(listed)
                    continue
                ranges = self._split_prose(seg)
            if seg.bullet:
                listed = self._label_list(seg)
                if listed is not None:
                    items.extend(listed)
                    continue
            for a, b in ranges:
                sub = self.s[a:b]
                # inline list "Steps: design, build and test"
                lm = re.match(r"^\s*(?P<label>[^:\n]{1,40}):\s*(?P<rest>.+)$", sub)
                if lm and not TASK_VERB_RE.search(lm.group("label")) and len(lm.group("label").split()) <= 4 \
                        and not find_durations(lm.group("rest")):
                    rest_start = a + lm.start("rest")
                    pieces = [(rest_start + m.start(), rest_start + m.end())
                              for m in re.finditer(r"[^,]+?(?=\s*,|\s+and\s+|$)", lm.group("rest"))
                              if m.group(0).strip() and m.group(0).strip().lower() != "and"]
                    pieces = [(x + (len(self.s[x:y]) - len(self.s[x:y].lstrip())), y) for x, y in pieces]
                    pieces = [(x, y) for x, y in pieces if self.s[x:y].strip()]
                    if len(pieces) >= 2:
                        for x, y in pieces:
                            text_xy = self.s[x:y]
                            if text_xy.lower().startswith("and "):
                                x += 4
                            items.append(self._item(seg, x, y))
                        continue
                # then-chain
                chain = [m for m in THEN_SPLIT_RE.finditer(sub)]
                if chain:
                    bounds = []
                    pos = 0
                    for m in chain:
                        bounds.append((pos, m.start()))
                        pos = m.end()
                    bounds.append((pos, len(sub)))
                    bounds = [(x, y) for x, y in bounds if sub[x:y].strip()]
                    if len(bounds) >= 2:
                        prev = None
                        label = None
                        lm2 = LABEL_RE.match(sub[bounds[0][0]:bounds[0][1]])
                        if lm2 and self._is_label(lm2.group("label")):
                            # "Order A: cutting 3 h, then ...": the label groups the chain, it is not a name
                            label = clean_name(lm2.group("label"), 60)
                            bounds[0] = (bounds[0][0] + lm2.start("rest"), bounds[0][1])
                        for x, y in bounds:
                            it = self._item(seg, a + x, a + y)
                            if label:
                                it.group = it.group or label
                            if prev is not None:
                                it.chain_prev = prev
                                it.explicit_dep = True
                            items.append(it)
                            prev = it
                        continue
                items.append(self._item(seg, a, b))
        return items

    @staticmethod
    def _is_label(label: str) -> bool:
        return bool(label.strip()) and not TASK_VERB_RE.search(label) and len(label.split()) <= 4 and \
            not find_durations(label) and not re.search(r"\d{1,2}[:.]\d{2}", label)

    def _label_list(self, seg: Segment) -> list[_Item] | None:
        """2.7.1 inline list after a colon: "Steps: design, build and test" / "Steps: design 2 days, build 5 days
        and test 2 days." -> one item per entry; the label itself is not a task. A then-chain is left alone."""
        text = seg.text
        lm = LABEL_RE.match(text)
        if not lm or not self._is_label(lm.group("label")):
            return None
        rest_off = lm.start("rest")
        rest = text[rest_off:]
        if THEN_SPLIT_RE.search(rest):
            return None
        pieces: list[tuple[int, int]] = []
        pos = 0
        for m in re.finditer(r"\s*,\s*(?:and\s+)?|\s+and\s+", rest, re.I):
            pieces.append((pos, m.start()))
            pos = m.end()
        pieces.append((pos, len(rest)))
        pieces = [(x, y) for x, y in pieces if rest[x:y].strip(" .;")]
        if len(pieces) < 2:
            return None
        # every entry must name something (not only a duration, date or person)
        for x, y in pieces:
            piece = rest[x:y]
            for d in find_durations(piece):
                piece = piece[:d.start] + " " * (d.end - d.start) + piece[d.end:]
            if not re.search(r"[A-Za-z]{2,}", piece) or len(piece.split()) > 8:
                return None
        base = seg.start + rest_off
        return [self._item(seg, base + x, base + y) for x, y in pieces]

    def _item(self, seg: Segment, a: int, b: int) -> _Item:
        sub = self.s[a:b]
        lead = len(sub) - len(sub.lstrip())
        a += lead
        sub = self.s[a:b].rstrip()
        b = a + len(sub)
        work = blank(sub, self.claimed, a)
        it = _Item(start=a, end=b, seg=seg, work=work)

        def cut(x: int, y: int) -> None:      # local offsets
            it.work = it.work[:x] + " " * (y - x) + it.work[y:]

        # revision rule ("revise everything twice")
        rm = REVISE_RE.search(it.work)
        if rm:
            w = rm.group("n").lower()
            n = {"twice": 2, "thrice": 3, "once": 1}.get(w)
            if n is None:
                pn = parse_number(re.sub(r"\s+times$", "", w))
                n = int(pn[0]) if pn else 1
            it.is_revision_rule = max(1, min(n, 10))
            self.revise_times = it.is_revision_rule
            self.revise_span = (a + rm.start(), a + rm.end())
            return it
        # dates
        for dm in find_dates(it.work, self.ctx.today, self.ctx.locale):
            role, rs = role_of(it.work, dm.start)
            if role == "start" and it.work[rs:dm.start].strip().lower().startswith("after"):
                role = "start"
            if role is None:
                role = "deadline" if dm.deadline_like else "deadline"
            conf = dm.confidence if dm.alternative is None else 0.4
            if role == "deadline":
                hard = bool(HARD_RE.search(it.work))
                lead_m = DEADLINE_LEAD_RE.search(it.work[max(0, rs - 60):rs])
                if lead_m:
                    rs = max(0, rs - 60) + lead_m.start()
                it.deadline = (dm.value, hard, a + rs, a + dm.end, conf)
            else:
                it.earliest = (dm.value, a + dm.start, a + dm.end, conf)
            if dm.alternative is not None:
                it.ambiguous_date = DateMatch(a + dm.start, a + dm.end, dm.value, dm.granularity, conf,
                                              alternative=dm.alternative)
            cut(rs, dm.end)
        # counts
        cm = COUNT_RE.search(it.work)
        if cm:
            n = parse_number(cm.group("n"))
            if n and 2 <= n[0] <= 100:
                it.count = (int(n[0]), cm.group("noun"), n[1])
                em = EACH_CHAIN_RE.search(it.work)
                if em:
                    ops = [o.strip(" .") for o in re.split(r",\s*|\s+and\s+|\s+then\s+", em.group("ops")) if o.strip(" .")]
                    if len(ops) >= 2:
                        it.chain_ops = [clean_name(o) for o in ops[:20]]
                        cut(em.start(), em.end())
        # durations
        ds = find_durations(it.work)
        if ds:
            d = ds[0]
            it.duration = DurMatch(a + d.start, a + d.end, d.optimistic, d.likely, d.pessimistic, d.unit,
                                   d.confidence, d.note, d.ranged)
            if d.confidence < 0.5:
                it.low_conf.append(("duration", d.confidence))
            cut(d.start, d.end)
        # dependencies
        if END_RE.search(it.work):
            m = END_RE.search(it.work)
            assert m is not None
            it.at_end = True
            it.explicit_dep = True
            cut(m.start(), m.end())
        for m in PARALLEL_RE.finditer(it.work):
            it.explicit_dep = True
            self.note("PARALLEL", "info", note_text("PARALLEL", text=self.s[a:b][:120]), a + m.start(), a + m.end())
            cut(m.start(), m.end())
        for m in ONCE_RE.finditer(it.work):
            ref = m.group("ref").strip()
            it.after_refs.append((ref, a + m.start(), a + m.end(), 0.9))
            it.explicit_dep = True
            cut(m.start(), m.end())
        for m in AFTER_RE.finditer(it.work):
            ref = _REF_STOP_RE.sub("", m.group("ref")).strip()
            if not ref or not ref.strip(" ."):
                continue
            end = m.start("ref") + len(m.group("ref").rstrip())
            if ref != m.group("ref").strip():
                end = m.start("ref") + m.group("ref").find(ref) + len(ref)
            it.after_refs.append((ref, a + m.start(), a + end, 0.95))
            it.explicit_dep = True
            cut(m.start(), end)
        for m in BEFORE_RE.finditer(it.work):
            ref = _REF_STOP_RE.sub("", m.group("ref")).strip()
            if not ref:
                continue
            end = m.start("ref") + m.group("ref").find(ref) + len(ref)
            it.before_refs.append((ref, a + m.start(), a + end, 0.95))
            cut(m.start(), end)
        # resources
        self._assignments(it, a)
        # rule cues left in the item text become notes and leave the name
        rc = RULE_CUE_RE.search(it.work)
        if rc:
            cstart = it.work.rfind(",", 0, rc.start()) + 1
            self.note("UNSUPPORTED_RULE", "warning",
                      note_text("UNSUPPORTED_RULE", text=self.s[a + cstart:b].strip()[:200]), a + cstart, b)
            cut(cstart, len(it.work))
        # name
        raw = FILLER_RE.sub("", it.work.strip())
        raw = FILLER_RE.sub("", raw)
        it.name = clean_name(raw)
        if it.count is not None:
            noun = it.count[1].lower()
            it.name = clean_name(re.sub(rf"\b{re.escape(noun)}\b", "", it.name, flags=re.I)) or ""
        if it.duration is None and MILESTONE_RE.search(it.name or ""):
            it.milestone = True
        return it

    def _assignments(self, it: _Item, a: int) -> None:
        w = it.work
        names: list[str] = []
        spans: list[tuple[int, int]] = []

        def known(tok: str) -> bool:
            return self.resource_by_name(tok) is not None

        def name_list(s: str) -> list[str] | None:
            toks = [x.strip() for x in re.split(r",|\band\b|&|/", s)]
            toks = [x for x in toks if x]
            if not toks:
                return None
            if all(re.fullmatch(r"[A-Z][a-z]{1,29}", x) and x.lower() not in NOT_NAMES for x in toks):
                return toks
            if all(x.lower() == "me" for x in toks):
                return ["Me"]
            return None

        # (Priya) / (Ravi and Priya)
        for m in re.finditer(r"\((?P<n>[^()\n]{1,80})\)", w):
            nl = name_list(m.group("n"))
            if nl:
                names += nl
                spans.append((m.start(), m.end()))
        # by/with/assigned to NAME[, NAME and NAME]
        for m in ASSIGN_RE.finditer(w):
            rest = w[m.end():m.end() + 80]
            nm = re.match(r"(?P<n>[A-Z][a-z]{1,29}(?:\s*(?:,|and|&)\s*[A-Z][a-z]{1,29}){0,5}|me\b)", rest)
            if nm:
                nl = name_list(nm.group("n"))
                if nl and (any(known(x) for x in nl) or m.group(0).strip().lower() not in ("with",)):
                    names += nl
                    spans.append((m.start(), m.end() + nm.end()))
        # NAME will ...
        lm = LEAD_NAME_RE.match(w.lstrip())
        lead = [x for x in _NAME_SPLIT_RE.split(lm.group("name")) if x] if lm else []
        if lead and all(x.lower() not in NOT_NAMES for x in lead):
            off = len(w) - len(w.lstrip())
            names += lead
            spans.append((off + lm.start("name"), off + lm.end()))
        if ME_RE.search(w):
            m = ME_RE.search(w)
            assert m is not None
            names.append("Me")
            spans.append((m.start(), m.end()))
        # trailing chunks that are only names: ", Priya" / ": Ravi"
        pos = 0
        for m in re.finditer(r"[,:]", w):
            pos = m.end()
            nxt = w.find(",", pos)
            chunk_end = len(w) if nxt == -1 else nxt
            chunk = w[pos:chunk_end]
            nl = name_list(chunk)
            if nl and all(known(x) or x == "Me" for x in nl):
                names += nl
                spans.append((m.start(), chunk_end))
        if not names:
            return
        if TOGETHER_RE.search(w) and len(set(names)) >= 2:
            it.mode = "all"
            tm = TOGETHER_RE.search(w)
            assert tm is not None
            spans.append((tm.start(), tm.end()))
        seen: list[str] = []
        for n in names:
            if n not in seen:
                seen.append(n)
        it.res_names = seen
        it.res_span = (a + min(x for x, _ in spans), a + max(y for _, y in spans))
        for x, y in spans:
            it.work = it.work[:x] + " " * (y - x) + it.work[y:]
        for n in seen:
            if n == "Me":
                if self.resource_by_name("Me") is None:
                    self.resources.append(_Res(key="r_me", name="Me", kind="person", span=None, confidence=0.7))
            elif not known(n):
                idx = self.s.find(n, it.start)
                self.add_person(n, idx, idx + len(n))

    # ------------------------------------------------------------ assemble
    def run(self) -> ScheduleExtractionResult:
        for a, b in out_of_range_dates(self.s, self.ctx.today, self.ctx.locale):
            self.note("DATE_OUT_OF_RANGE", "warning", note_text("DATE_OUT_OF_RANGE", text=self.s[a:b][:80]), a, b)
        self.pass_working_time()
        self.pass_exam()
        self.pass_subjects()
        self.pass_people()
        items = self.build_items()
        if self.subject_items:
            items = sorted(items + self.subject_items, key=lambda x: x.start)
        rules = [it for it in items if it.is_revision_rule]
        items = [it for it in items if not it.is_revision_rule]
        items = self._merge_assignment_sentences(items)
        # plan name and start date from non-task prose
        task_segs = {id(it.seg) for it in items} | {id(it.seg) for it in rules}
        for i, seg in enumerate(self.segs):
            if seg.bullet or id(seg) in task_segs:
                continue
            work = blank(seg.text, self.claimed, seg.start)
            ds = find_dates(work, self.ctx.today, self.ctx.locale)
            for dm in ds:
                role, rs = role_of(work, dm.start)
                if role == "start" and self.start_date is None:
                    self.start_date = dm.value
                    self.p_text("/start_date", seg.start + dm.start, seg.start + dm.end, dm.confidence)
                    work = blank(work, [(seg.start + rs, seg.start + dm.end)], seg.start)
            if i == 0 and not seg.consumed and self.name is None:
                people = {r.name for r in self.resources}
                cand = clean_name(work)
                words = cand.split()
                if cand and 1 <= len(words) <= 10 and not any(w.strip(",.") in people for w in words) \
                        and not RULE_CUE_RE.search(cand):
                    self.name = cand
                    self.p_text("/name", seg.start, seg.end, 0.6)
                    seg.consumed = True
            elif not seg.consumed and self._cross_assignment(seg, work, items):
                seg.consumed = True
            elif not seg.consumed and RULE_CUE_RE.search(work):
                self.note("UNSUPPORTED_RULE", "warning", note_text("UNSUPPORTED_RULE", text=seg.text.strip()[:200]),
                          seg.start, seg.end)
        if self.name is None and self.exam is not None:
            self.name = "Exam preparation"
        # cross-sentence dependency statements
        items = self._cross_dependencies(items)
        return self._assemble(items)

    @staticmethod
    def _merge_assignment_sentences(items: list[_Item]) -> list[_Item]:
        """"Write report 2 days. Ravi and Priya will write report together.": the second sentence only assigns
        people to the task already named, so it adds its resources to that task instead of a duplicate task."""
        out: list[_Item] = []
        by_name: dict[str, _Item] = {}
        for it in items:
            key = (it.name or "").strip().lower()
            prev = by_name.get(key)
            if (prev is not None and not it.seg.bullet and it.res_names and it.duration is None
                    and it.deadline is None and it.earliest is None and it.count is None and not it.after_refs
                    and not it.before_refs and not it.milestone):
                prev.res_names = prev.res_names + [n for n in it.res_names if n not in prev.res_names]
                prev.res_span = prev.res_span or it.res_span
                if it.mode == "all":
                    prev.mode = "all"
                continue
            if key and key not in by_name:
                by_name[key] = it
            out.append(it)
        return out

    def _cross_assignment(self, seg: Segment, work: str, items: list[_Item]) -> bool:
        """`NAME will <task words>` in a sentence that is not itself a task: assign NAME to that task (2.7.7)."""
        stripped = work.lstrip()
        lm = LEAD_NAME_RE.match(stripped)
        lead = [x for x in _NAME_SPLIT_RE.split(lm.group("name")) if x] if lm else []
        if not lead or any(x.lower() in NOT_NAMES for x in lead):
            return False
        rest = stripped[lm.end():].strip(" .!?;")
        cands = [(str(i), x.name) for i, x in enumerate(items) if x.name]
        res = resolve(rest, cands) if rest else None
        if res is None or res.key is None:
            return False
        it = items[int(res.key)]
        off = seg.start + (len(work) - len(stripped))
        it.res_span = it.res_span or (off + lm.start("name"), off + lm.end("name"))
        for name in lead:
            if name not in it.res_names:
                it.res_names = it.res_names + [name]
            if self.resource_by_name(name) is None:
                idx = self.s.find(name, off)
                self.add_person(name, idx, idx + len(name))
        if len(lead) >= 2 and TOGETHER_RE.search(rest):
            it.mode = "all"
        return True

    def _cross_dependencies(self, items: list[_Item]) -> list[_Item]:
        keep: list[_Item] = []
        index: NameIndex | None = None          # built once, on the first cross sentence (linear time)
        before = {id(x) for x in self._dropped}
        dropped_pos = {str(i) for i, x in enumerate(items) if id(x) in before}
        for pos, it in enumerate(items):
            if it.seg.bullet:
                keep.append(it)
                continue
            text = self.s[it.start:it.end].strip()
            pair = None
            for rx, xg, yg in ((CROSS_BEFORE_RE, "x", "y"), (CROSS_WHEN_RE, "x", "y"), (CROSS_AFTER_RE, "x", "y")):
                m = rx.match(text)
                if not m:
                    continue
                if index is None:
                    index = NameIndex([(str(i), x.name) for i, x in enumerate(items) if x.name])
                rx_ = index.resolve(m.group(xg), exclude=str(pos), exclude_keys=dropped_pos)
                ry_ = index.resolve(m.group(yg), exclude=str(pos), exclude_keys=dropped_pos)
                if rx_.key is not None and ry_.key is not None and rx_.key != ry_.key:
                    pair = (items[int(rx_.key)], items[int(ry_.key)])
                    break
            if pair is not None:
                self.cross.append((pair[0], pair[1], it.start, it.end))
                self._dropped.append(it)
                dropped_pos.add(str(pos))
                continue
            keep.append(it)
        return keep

    def _assemble(self, items: list[_Item]) -> ScheduleExtractionResult:
        tasks: list[DraftTask] = []
        unit_default = {"study": "hours", "production": "hours"}.get(self.kind, "days")
        key_of: dict[int, list[str]] = {}
        n = 0

        def new_key() -> str:
            nonlocal n
            n += 1
            return f"t{n}"

        res_keys = {r.name: r.key for r in self.resources}
        study_items: list[tuple[_Item, str]] = []
        pending_refs: list[tuple[str, _Item, tuple[str, int, int, float]]] = []
        for it in items:
            dur = None
            if it.duration is not None:
                d = it.duration
                dur = DraftDuration(optimistic=d.optimistic, likely=d.likely, pessimistic=d.pessimistic,
                                    unit=d.unit)  # type: ignore[arg-type]
            reskeys = [res_keys[nm] for nm in it.res_names if nm in res_keys]
            if not reskeys and it.res_names == ["Me"]:
                reskeys = ["r_me"]
            names: list[tuple[str, str | None]]
            if it.count is not None and it.chain_ops:
                cnt, noun, _ = it.count
                single = _singular(noun)
                names = [(f"{single} {i}: {op}", f"{single} {i}") for i in range(1, cnt + 1) for op in it.chain_ops]
            elif it.count is not None:
                cnt, noun, _ = it.count
                single = _singular(noun)
                base = it.name.strip()
                names = [(f"{single} {i}" if not base else f"{single} {i}", None) for i in range(1, cnt + 1)]
            else:
                names = [(it.name or "", None)]
            keys: list[str] = []
            prev_in_group: dict[str, str] = {}
            for nm, grp in names:
                k = new_key()
                keys.append(k)
                name = nm or f"Task {n}"
                after: list[str] = []
                if grp is not None:
                    if grp in prev_in_group:
                        after.append(prev_in_group[grp])
                    prev_in_group[grp] = k
                tasks.append(DraftTask(
                    key=k, name=name[:200], milestone=it.milestone, duration=None if it.milestone else dur,
                    after=after, resources=list(reskeys), resource_mode=it.mode,  # type: ignore[arg-type]
                    deadline=it.deadline[0] if it.deadline else None,
                    deadline_hard=bool(it.deadline and it.deadline[1]),
                    earliest_start=it.earliest[0] if it.earliest else None, group=grp or it.group))
                self._task_prov(k, it, dur is not None and not it.milestone, grp is not None and bool(after))
            if it.count is not None:
                self.note("EXPANDED_COUNT", "info", note_text("EXPANDED_COUNT", text=self.s[it.start:it.end][:120],
                                                              count=len(keys)), it.start, it.end)
            it.keys = keys
            key_of[id(it)] = keys
            if self.kind == "study" and not it.milestone and it.count is None:
                study_items.append((it, keys[0]))
            for ref in it.after_refs:
                pending_refs.append(("after", it, ref))
            for ref in it.before_refs:
                pending_refs.append(("before", it, ref))
        by_key = {t.key: t for t in tasks}
        # explicit references
        cands = NameIndex([(t.key, t.name) for t in tasks])
        for direction, it, (ref, ra, rb, conf) in pending_refs:
            first = it.keys[0]
            last = it.keys[-1]
            res = cands.resolve(ref)
            target = res.key if res.key not in it.keys else None
            if target is None:
                res2 = cands.resolve(ref, exclude_keys=set(it.keys))
                target = res2.key
                res = res2
            if target is None:
                if direction == "after" and f"/tasks/{first}/after_ref" not in self.prov:
                    self.prov[f"/tasks/{first}/after_ref"] = Provenance(
                        source="text", confidence=0.3, span=self.span(ra, rb), note=f"REF:{ref[:200]}")
                else:
                    self.note("UNSUPPORTED_RULE", "warning", note_text("UNSUPPORTED_RULE", text=self.s[ra:rb][:200]),
                              ra, rb)
                continue
            c = min(conf, res.confidence)
            if direction == "after":
                tgt = _last_key(target, tasks, key_of, items)
                if tgt not in by_key[first].after and tgt != first:
                    by_key[first].after.append(tgt)
                self.p_text(f"/tasks/{first}/after", ra, rb, c)
            else:
                tgt = _first_key(target, tasks, key_of, items)
                if last not in by_key[tgt].after and tgt != last:
                    by_key[tgt].after.append(last)
                self.p_text(f"/tasks/{tgt}/after", ra, rb, c)
        # then-chains and cross-sentence statements
        for it in items:
            if it.chain_prev is not None and it.chain_prev.keys:
                p = it.chain_prev.keys[-1]
                if p not in by_key[it.keys[0]].after:
                    by_key[it.keys[0]].after.append(p)
                self.p_text(f"/tasks/{it.keys[0]}/after", it.chain_prev.start, it.end, 0.9)
        for pred, succ, a, b in self.cross:
            if pred.keys and succ.keys:
                p, s_ = pred.keys[-1], succ.keys[0]
                if p != s_ and p not in by_key[s_].after:
                    by_key[s_].after.append(p)
                    self.p_text(f"/tasks/{s_}/after", a, b, 0.9)
        # numbered list order (2.7.6)
        prev: _Item | None = None
        for it in items:
            if not (it.seg.bullet and it.seg.numbered):
                prev = None
                continue
            if prev is not None and prev.seg.line == it.seg.line - 1 or (
                    prev is not None and prev.seg.line < it.seg.line and self._only_blank_between(prev, it)):
                first = it.keys[0]
                if not it.explicit_dep and not by_key[first].after:
                    by_key[first].after.append(prev.keys[-1])
                    self.p_derived(f"/tasks/{first}/after", 0.6, "From the order of the list")
            prev = it
        # revision tasks (study)
        if self.revise_times and study_items:
            ntimes = self.revise_times
            new_tasks: list[DraftTask] = []
            for t in tasks:
                new_tasks.append(t)
                match = next((it for it, k in study_items if k == t.key), None)
                if match is None:
                    continue
                x = _revision_subject(t.name)
                prev_k = t.key
                for k in range(1, ntimes + 1):
                    key = new_key()
                    new_tasks.append(DraftTask(key=key, name=f"Revise {x} ({k}/{ntimes})"[:200], after=[prev_k],
                                               resources=list(t.resources), group=t.group))
                    self.p_derived(f"/tasks/{key}/name", 0.6, "Revision from your text",
                                   *(self.revise_span or (None, None)))  # type: ignore[arg-type]
                    self.p_derived(f"/tasks/{key}/after", 0.6, "Revision after the study task")
                    prev_k = key
            tasks = new_tasks
            by_key = {t.key: t for t in tasks}
        # exam milestone
        if self.exam is not None:
            d, ea, eb, conf = self.exam
            succ = {a for t in tasks for a in t.after}
            ends = [t.key for t in tasks if t.key not in succ]
            k = new_key()
            tasks.append(DraftTask(key=k, name="Exam", milestone=True, deadline=d, deadline_hard=True, after=ends))
            self.p_text(f"/tasks/{k}/deadline", ea, eb, conf)
            self.p_derived(f"/tasks/{k}/milestone", 0.7, "The exam is the end point of the plan")
            if ends:
                self.p_derived(f"/tasks/{k}/after", 0.6, "Everything comes before the exam")
            by_key[k] = tasks[-1]
        # "at the end"
        for it in items:
            if it.at_end and it.keys:
                k0 = it.keys[0]
                succ = {a for t in tasks for a in t.after}
                for t in tasks:
                    if t.key not in it.keys and t.key not in succ and t.key not in by_key[k0].after \
                            and not (t.milestone and t.name == "Exam"):
                        by_key[k0].after.append(t.key)
        # resources
        resources = [DraftResource(key=r.key, name=r.name[:200], kind=r.kind, count=r.count)  # type: ignore[arg-type]
                     for r in self.resources]
        for r in self.resources:
            if r.span is not None:
                self.p_text(f"/resources/{r.key}/name", r.span[0], r.span[1], r.confidence,
                            "Detected name" if r.detected else "")
        if self.exam is None and self.kind == "study" and not any(MILESTONE_RE.search(t.name) for t in tasks):
            pass
        for t in tasks:
            if t.milestone:
                t.resources = []
        tasks = self._renumber(tasks)
        draft = ScheduleDraft(kind=self.kind, name=(self.name or "My plan")[:200], start_date=self.start_date,
                              working_time=self.working_time, tasks=tasks[:500], resources=resources[:100],
                              provenance=self.prov)
        if len(tasks) > 500:
            self.note("UNSUPPORTED_RULE", "warning", "Only the first 500 items were read.")
        _ = unit_default
        return ScheduleExtractionResult(draft=draft, notes=self.notes)

    def _renumber(self, tasks: list[DraftTask]) -> list[DraftTask]:
        """Keys t1..tn in list order (inserted revision tasks would otherwise be out of sequence)."""
        mapping = {t.key: f"t{i + 1}" for i, t in enumerate(tasks)}
        if all(k == v for k, v in mapping.items()):
            return tasks
        out = [t.model_copy(update={"key": mapping[t.key], "after": [mapping[a] for a in t.after]}) for t in tasks]
        prov: dict[str, Provenance] = {}
        for path, p in self.prov.items():
            m = re.match(r"^/tasks/([^/]+)(/.*)$", path)
            prov[f"/tasks/{mapping.get(m.group(1), m.group(1))}{m.group(2)}" if m else path] = p
        self.prov = prov
        return out

    def _only_blank_between(self, a: _Item, b: _Item) -> bool:
        lines = self.s.split("\n")
        return all(not lines[i].strip() for i in range(a.seg.line + 1, b.seg.line))

    def _task_prov(self, k: str, it: _Item, with_duration: bool, grouped_after: bool) -> None:
        if with_duration and it.duration is not None:
            self.p_text(f"/tasks/{k}/duration", it.duration.start, it.duration.end, it.duration.confidence,
                        "A month was counted as about 4.33 weeks" if it.duration.note else "")
        if it.res_span is not None and it.res_names:
            self.p_text(f"/tasks/{k}/resources", it.res_span[0], it.res_span[1], 0.7)
        if it.deadline is not None:
            self.p_text(f"/tasks/{k}/deadline", it.deadline[2], it.deadline[3], it.deadline[4],
                        "AMBIGUOUS:" + it.ambiguous_date.alternative.isoformat()
                        if it.ambiguous_date and it.ambiguous_date.alternative else "")
        if it.earliest is not None:
            self.p_text(f"/tasks/{k}/earliest_start", it.earliest[1], it.earliest[2], it.earliest[3],
                        "AMBIGUOUS:" + it.ambiguous_date.alternative.isoformat()
                        if it.ambiguous_date and it.ambiguous_date.alternative and it.deadline is None else "")
        if it.milestone:
            self.p_derived(f"/tasks/{k}/milestone", 0.7, "No duration and the name looks like a milestone")
        if it.count is not None:
            self.p_derived(f"/tasks/{k}/name", min(0.6, it.count[2]) if it.count[2] < 0.5 else 0.6,
                           "One of several items counted in your text", it.start, it.end)
        else:
            self.p_text(f"/tasks/{k}/name", it.start, it.end, 0.9)
        if grouped_after:
            self.p_derived(f"/tasks/{k}/after", 0.6, "Each one goes through the steps in order")


def _singular(noun: str) -> str:
    n = noun.strip()
    low = n.lower()
    if low.endswith("ches") or low.endswith("shes"):
        n = n[:-2]
    elif low.endswith("s") and not low.endswith("ss"):
        n = n[:-1]
    return n[0].upper() + n[1:]


def _revision_subject(name: str) -> str:
    x = re.sub(r"^(?:finish|complete|study|do|read|learn|cover|prepare|write|make)\s+", "", name, flags=re.I)
    x = x.strip() or name
    return x[0].lower() + x[1:] if len(x) > 1 and not x[:2].isupper() else x


def _first_key(target: str, tasks, key_of, items) -> str:
    return target


def _last_key(target: str, tasks, key_of, items) -> str:
    for it in items:
        if target in it.keys:
            return it.keys[-1] if it.count is None or it.chain_ops else target
    return target


def extract_schedule(text: str, ctx: ExtractContext) -> ScheduleExtractionResult:
    return _Extractor(text, ctx).run()


def kind_of(text: str, ctx: ExtractContext) -> ScheduleKind:
    return detect_kind(normalise(text).norm, ctx.kind)


__all__ = ["extract_schedule", "default_working_time", "DEFAULT_RESOURCE", "detect_kind", "kind_of",
           "ScheduleExtractionResult", "norm_tokens"]

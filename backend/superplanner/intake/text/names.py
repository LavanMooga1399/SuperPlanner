"""People detection and fuzzy name matching (PHASE2 2.7.6, 2.7.7)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .dates import MONTHS, WEEKDAYS

STOP_WORDS = frozenset("""
a an the is are was were be been being of to for and or it its this that these those with on in at by from into
our my we i you your their his her them us me done finished complete completed ready approved first then
all also has have had will can should does do did must need needs just so up out over""".split())

# Capitalised words that are never names.
NOT_NAMES = frozenset("""
i we you he she they it the a an and or but then after before once when while if so our my your their this that
these those there here all each every both no not yes ok also next last first final team plan project task tasks
step steps phase stage week weeks day days month months year years today tomorrow monday tuesday wednesday thursday
friday saturday sunday mon tue wed thu fri sat sun exam test tests mock chapter chapters module modules unit units
order orders job jobs batch batches machine machines shift shifts build design testing launch release review write
prepare study revise deploy deliver install finish complete do make plan meeting client customer manager lead
deadline milestone notes note total budget cost costs start end due by on in at of for to with from
""".split()) | frozenset(MONTHS) | frozenset(WEEKDAYS)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CAP_RE = re.compile(r"(?<![\w'])[A-Z][a-z]{1,29}(?![\w'])")
_FOLLOW_OK = re.compile(r"^\s+(?:will|can|does|is|should|to|has|are|and|&|,|works?|handles?|leads?)\b|^\s*,", re.I)


@lru_cache(maxsize=8192)
def stem(tok: str) -> str:
    """Light stemmer: plural s, -ing, -ed; then a final silent e and a doubled consonant (prepare/preparing,
    plan/planning) so word forms of one verb compare equal."""
    t = tok.lower()
    suffix = False
    if len(t) > 5 and t.endswith("ing"):
        t, suffix = t[:-3], True
    elif len(t) > 4 and t.endswith("ed"):
        t, suffix = t[:-2], True
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    if suffix and len(t) > 3 and t[-1] == t[-2] and t[-1] not in "lsz":
        t = t[:-1]
    elif not suffix and len(t) > 4 and t.endswith("e"):
        t = t[:-1]
    return t


def norm_tokens(s: str) -> list[str]:
    return [stem(t) for t in _TOKEN_RE.findall(s.lower()) if t not in STOP_WORDS]


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _contains(seq: list[str], sub: list[str]) -> bool:
    n = len(sub)
    return any(seq[i:i + n] == sub for i in range(len(seq) - n + 1))


@dataclass
class Resolution:
    key: str | None
    confidence: float
    ranked: list[tuple[str, float]]       # (key, score) best first


class NameIndex:
    """(key, name) candidates normalised once, with a token -> candidates map (linear-time reference resolution).

    Only candidates sharing a token with the reference can score above 0 or contain it, so only those are scored.
    Tokens shared by more than `common` candidates are skipped when the reference also has a rarer token
    (approximation: a candidate sharing only such frequent tokens is treated as scoring 0)."""

    def __init__(self, candidates: list[tuple[str, str]], common: int = 64) -> None:
        self.keys: list[str] = []
        self.toks: list[list[str]] = []
        self.post: dict[str, list[int]] = {}
        self.common = common
        for k, n in candidates:
            idx = len(self.keys)
            self.keys.append(k)
            toks = norm_tokens(n)
            self.toks.append(toks)
            for t in set(toks):
                self.post.setdefault(t, []).append(idx)

    def resolve(self, ref: str, exclude: str | None = None, exclude_keys: set[str] | None = None) -> Resolution:
        r = norm_tokens(ref)
        skip = _Skip(exclude, exclude_keys)
        if not r or not self.keys:
            return Resolution(None, 0.0, [])
        rs = set(r)
        rare = [t for t in rs if t in self.post and len(self.post[t]) <= self.common]
        use = rare or [t for t in rs if t in self.post]
        hit: set[int] = set()
        for t in use:
            hit.update(self.post[t])
        hit = {i for i in hit if self.keys[i] not in skip}
        order = sorted(hit)
        scored = sorted(((self.keys[i], jaccard(r, self.toks[i])) for i in order), key=lambda x: -x[1])
        # zero-score candidates (in candidate order) so `ranked` still offers choices; bounded
        pad: list[tuple[str, float]] = []
        for i, k in enumerate(self.keys):
            if len(pad) >= 5:
                break
            if i not in hit and k not in skip:
                pad.append((k, 0.0))
        subs = [self.keys[i] for i in order if _contains(self.toks[i], r)]
        if len(subs) == 1:
            return Resolution(subs[0], 0.95, scored + pad)
        if len(subs) > 1:
            sub_set = set(subs)
            ranked = [x for x in scored if x[0] in sub_set]
            if len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= 0.15:
                return Resolution(ranked[0][0], 0.8, scored + pad)
            return Resolution(None, 0.0, ranked + [x for x in scored if x[0] not in sub_set] + pad)
        full = scored + pad
        if not full:
            return Resolution(None, 0.0, [])
        best = full[0][1]
        second = full[1][1] if len(full) > 1 else 0.0
        if best >= 0.5 and best - second >= 0.15:
            return Resolution(full[0][0], 0.8, full)
        return Resolution(None, 0.0, full)


class _Skip:
    """Membership test for one excluded key plus a set, without copying the set (linear time)."""

    __slots__ = ("one", "many")

    def __init__(self, one: str | None, many: set[str] | None) -> None:
        self.one, self.many = one, many

    def __contains__(self, k: object) -> bool:
        return k == self.one or (self.many is not None and k in self.many)


def resolve(ref: str, candidates: list[tuple[str, str]] | NameIndex, exclude: str | None = None) -> Resolution:
    """Match a reference phrase against (key, name) candidates (2.7.6 reference resolution). Pass a `NameIndex`
    when resolving many references against the same candidates."""
    index = candidates if isinstance(candidates, NameIndex) else NameIndex(candidates)
    return index.resolve(ref, exclude=exclude)


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not s or not s[0].isalpha():
        s = "x_" + s
    return s[:29].rstrip("_")


@dataclass
class NameHit:
    name: str
    start: int      # norm offsets
    end: int


def capitalised_names(s: str, base: int, *, initial_positions: set[int], extra_stop: set[str]) -> list[NameHit]:
    """Capitalised tokens of `s` that look like person names.

    A token at a sentence or bullet start counts only when followed by a verb such as "will"/"is"/"and".
    """
    out: list[NameHit] = []
    for m in _CAP_RE.finditer(s):
        w = m.group(0)
        lw = w.lower()
        if lw in NOT_NAMES or lw in STOP_WORDS or lw in extra_stop:
            continue
        pos = base + m.start()
        if pos in initial_positions and not _FOLLOW_OK.match(s[m.end():m.end() + 12]):
            continue
        out.append(NameHit(w, pos, base + m.end()))
    return out

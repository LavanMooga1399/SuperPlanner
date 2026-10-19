"""Normalisation and segmentation with code-point offsets (PHASE2 2.7, 2.7.1).

`Text` keeps the normalised copy (`norm`) that the grammar runs on and a map back to the submitted text, so
every span reported to the client is in Unicode code points of the original. Every regex in the intake
package runs in linear time (no nested unbounded quantifiers).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..models import SourceSpan

_REPLACE = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
            "“": '"', "”": '"', "„": '"', "″": '"',
            "–": "-", "—": "-", "‒": "-", "−": "-", "‐": "-", "‑": "-",
            " ": " ", " ": " ", " ": " ", "\t": " ", "\r": ""}

BULLET_RE = re.compile(r"^\s*([-*•·]|\d{1,3}[.)]|[a-zA-Z][.)])\s+")
_ABBREV = ("rs", "p.a", "e.g", "i.e", "etc", "approx", "vs", "no", "mr", "mrs", "ms", "dr", "st", "inc", "ltd",
           "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "p.m", "a.m")
_ENDING_ABBREV = frozenset(("jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
                            "etc"))
_SENT_END = re.compile(r"[.!?;](?=\s|$)")


@dataclass
class Text:
    original: str
    norm: str
    offsets: list[int]          # offsets[i] = original index of norm[i]; offsets[len(norm)] = len(original)

    def orig(self, i: int) -> int:
        return self.offsets[max(0, min(i, len(self.norm)))]

    def span(self, start: int, end: int) -> SourceSpan:
        """Span in original code points covering norm[start:end]."""
        a = self.orig(start)
        b = self.offsets[end - 1] + 1 if end > start else a
        b = max(a, min(b, len(self.original)))
        return SourceSpan(start=a, end=b, text=self.original[a:b][:300])


def normalise(text: str) -> Text:
    out: list[str] = []
    offs: list[int] = []
    for i, ch in enumerate(text):
        rep = _REPLACE.get(ch)
        if rep is None:
            rep = ch if ch.isascii() or ch == "₹" else unicodedata.normalize("NFKC", ch)
            rep = "".join(_REPLACE.get(c, c) for c in rep)
        for c in rep:
            out.append(c)
            offs.append(i)
    offs.append(len(text))
    return Text(original=text, norm="".join(out), offsets=offs)


@dataclass
class Segment:
    start: int                  # norm offsets
    end: int
    text: str                   # norm[start:end]
    line: int
    bullet: bool = False
    numbered: bool = False
    index_in_line: int = 0
    consumed: bool = False      # set when a pattern claimed the whole segment (no task, no name)
    tags: set[str] = field(default_factory=set)


def _is_abbrev(line: str, pos: int) -> bool:
    j = pos
    while j > 0 and (line[j - 1].isalpha() or line[j - 1] == "."):
        j -= 1
        if pos - j > 8:
            return False
    word = line[j:pos].lower()
    if word not in _ABBREV:
        return False
    if word in _ENDING_ABBREV:
        # "1 Dec. Send invites": a month (or "etc.") followed by a capitalised word ends the sentence;
        # "Dec. 5" and "Dec. 2026" keep the full stop as an abbreviation
        k = pos + 1
        while k < len(line) and line[k] == " ":
            k += 1
        if k < len(line) and line[k].isupper():
            return False
    return True


def split_sentences(line: str, base: int) -> list[tuple[int, int]]:
    """Sentence ranges (norm offsets) inside one non-bullet line."""
    out: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_END.finditer(line):
        p = m.start()
        if line[p] == "." and _is_abbrev(line, p):
            continue
        seg = line[start:p + 1]
        if seg.strip():
            out.append((base + start, base + p + 1))
        start = p + 1
    if line[start:].strip():
        out.append((base + start, base + len(line)))
    # trim whitespace
    trimmed = []
    for a, b in out:
        s = line[a - base:b - base]
        lead = len(s) - len(s.lstrip())
        trail = len(s) - len(s.rstrip())
        trimmed.append((a + lead, b - trail))
    return trimmed


def segments(t: Text) -> list[Segment]:
    """Bullet lines are one segment (marker excluded); other lines are split into sentences."""
    out: list[Segment] = []
    pos = 0
    for ln, line in enumerate(t.norm.split("\n")):
        base = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        m = BULLET_RE.match(line)
        if m:
            body_start = base + m.end()
            body = line[m.end():].rstrip()
            if body:
                end = body_start + len(body)
                # a trailing full stop is not part of the item
                if body.endswith("."):
                    end -= 1
                out.append(Segment(start=body_start, end=end, text=t.norm[body_start:end], line=ln, bullet=True,
                                   numbered=m.group(1)[0].isdigit()))
            continue
        for k, (a, b) in enumerate(split_sentences(line, base)):
            e = b - 1 if t.norm[b - 1] in ".!?;" else b
            out.append(Segment(start=a, end=e, text=t.norm[a:e], line=ln, index_in_line=k))
    return out


_WS = re.compile(r"\s+")


def clean_name(s: str, limit: int = 80) -> str:
    """Collapse leftovers of removed phrases into a readable name."""
    s = re.sub(r"\(\s*\)", " ", s)
    s = re.sub(r"\s*[,;:]\s*(?=[,;:]|$)", "", s)
    s = re.sub(r"\s+-\s*$|^\s*-\s+", "", s)
    s = _WS.sub(" ", s).strip(" ,;:-.\"'")
    s = re.sub(r"\s+([,;:])", r"\1", s)
    s = s.strip(" ,;:-")
    if len(s) > limit:
        s = s[:limit].rstrip()
    if s:
        s = s[0].upper() + s[1:]
    return s


def blank(s: str, ranges: list[tuple[int, int]], base: int = 0) -> str:
    """Replace the given norm ranges (absolute offsets) by spaces, keeping offsets stable."""
    chars = list(s)
    for a, b in ranges:
        for i in range(max(0, a - base), min(len(chars), b - base)):
            chars[i] = " "
    return "".join(chars)

"""Requirement register (M8-DESIGN 10): `docs/validation/requirements.yaml`.

The file is a YAML list of flow mappings, one requirement per line (a subset of YAML read here without a YAML
package):

    - {id: M8-RATE-05, title: "Validator mutation tests", source: "M8-DESIGN 7.2", risk: high,
       assurance: scripted, intended_use: gxp, match: ""}

Keys: id, title, source, risk (high | medium | low), assurance (scripted | unscripted | ad_hoc), intended_use
(gxp | non_gxp) and optional `match` (test-name substrings, `|`-separated, for requirements whose tests predate the
markers). CSA rule: high = directly affects product quality / patient safety or record integrity -> a scripted test
is required. Comments (`#`) and blank lines are ignored; a mapping may continue on following indented lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_PATH = REPO / "docs" / "validation" / "requirements.yaml"
RISKS = ("high", "medium", "low")
ASSURANCE = ("scripted", "unscripted", "ad_hoc")
_PAIR = re.compile(r'\s*([a-z_]+)\s*:\s*("(?:[^"\\]|\\.)*"|[^,}]*)\s*(?:,|$)')


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    source: str
    risk: str
    assurance: str
    intended_use: str
    match: tuple[str, ...] = field(default_factory=tuple)


class RegisterError(ValueError):
    pass


def _parse_map(text: str, line_no: int) -> dict[str, str]:
    body = text.strip()
    if not (body.startswith("{") and body.endswith("}")):
        raise RegisterError(f"line {line_no}: expected '- {{...}}'")
    body = body[1:-1]
    out: dict[str, str] = {}
    pos = 0
    while pos < len(body):
        m = _PAIR.match(body, pos)
        if not m or m.end() == pos:
            raise RegisterError(f"line {line_no}: cannot parse near {body[pos:pos + 30]!r}")
        k, v = m.group(1), m.group(2).strip()
        if v.startswith('"'):
            v = bytes(v[1:-1], "utf-8").decode("unicode_escape")
        out[k] = v
        pos = m.end()
    return out


def parse(text: str) -> list[Requirement]:
    items: list[tuple[int, str]] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(" #")[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if line.startswith("- "):
            items.append((n, line[2:]))
        elif items and line.startswith(" "):
            items[-1] = (items[-1][0], items[-1][1] + " " + line.strip())
        else:
            raise RegisterError(f"line {n}: expected a list item")
    reqs: list[Requirement] = []
    seen: set[str] = set()
    for n, t in items:
        d = _parse_map(t, n)
        for k in ("id", "title", "source", "risk", "assurance", "intended_use"):
            if not d.get(k):
                raise RegisterError(f"line {n}: missing {k}")
        if d["risk"] not in RISKS or d["assurance"] not in ASSURANCE or d["intended_use"] not in ("gxp", "non_gxp"):
            raise RegisterError(f"line {n}: invalid risk / assurance / intended_use")
        if d["id"] in seen:
            raise RegisterError(f"line {n}: duplicate id {d['id']}")
        seen.add(d["id"])
        reqs.append(Requirement(d["id"], d["title"], d["source"], d["risk"], d["assurance"], d["intended_use"],
                                tuple(x for x in d.get("match", "").split("|") if x)))
    return reqs


def load(path: Path | str | None = None) -> list[Requirement]:
    return parse(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))

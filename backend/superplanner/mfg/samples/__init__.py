"""Sample datasets (M1-DESIGN 10): `SAMPLES` registry, `build(sample_id) -> MfgBundle` (deterministic, canonical)
and `scale(sample_id, factor)` (tests/benchmarks: extra product variants sharing the buy-item library)."""

from __future__ import annotations

import copy
import importlib
from dataclasses import dataclass
from functools import lru_cache

from ..bundle import MfgBundle, bundle_counts, canonical_json  # noqa: F401  (canonical_json re-exported for tests)
from .common import canonical


@dataclass(frozen=True)
class SampleInfo:
    id: str
    name: str
    description: str
    module: str
    prefix: str


SAMPLES: dict[str, SampleInfo] = {}


def _register(module: str, prefix: str) -> None:
    mod = importlib.import_module(f".{module}", __name__)
    SAMPLES[mod.ID] = SampleInfo(mod.ID, mod.NAME, mod.DESCRIPTION, module, prefix)


_register("small", "SM-")
_register("medium", "MD-")
_register("kavach", "KV-")


@lru_cache(maxsize=8)
def _built(sample_id: str) -> MfgBundle:
    info = SAMPLES[sample_id]
    return importlib.import_module(f".{info.module}", __name__).build()


def build(sample_id: str) -> MfgBundle:
    """The canonical bundle of a sample (a fresh deep copy; KeyError for unknown ids)."""
    if sample_id not in SAMPLES:
        raise KeyError(sample_id)
    return copy.deepcopy(_built(sample_id))


def counts(sample_id: str) -> dict[str, int]:
    return bundle_counts(_built(sample_id))


def sample_list() -> list[dict[str, object]]:
    """`GET /samples` items: `{id, name, description, counts}`."""
    return [{"id": s.id, "name": s.name, "description": s.description, "counts": counts(s.id)}
            for s in SAMPLES.values()]


def scale(sample_id: str, factor: int) -> MfgBundle:
    """`factor` product variants: variant k >= 2 copies every make/phantom item, its BOMs and routings with the
    part-number prefix `<P><k>-` (e.g. `KV2-`); buy items, plant and resources stay shared."""
    base = build(sample_id)
    if factor <= 1:
        return base
    prefix = SAMPLES[sample_id].prefix
    made = {r["part_number"] for r in base["items"] if r["make_buy"] != "buy"}
    for k in range(2, factor + 1):
        new = f"{prefix[:-1]}{k}-"

        def ren(pn: str) -> str:
            return new + pn[len(prefix):] if pn in made and pn.startswith(prefix) else pn

        base["items"] += [dict(r, part_number=ren(r["part_number"])) for r in _rows(base, "items")
                          if r["part_number"] in made]
        for sheet, fields in (("boms", ("parent_part_number",)), ("bom_lines", ("parent_part_number",
                                                                                "child_part_number")),
                              ("routings", ("part_number",)), ("operations", ("part_number",))):
            base[sheet] += [dict(r, **{f: ren(r[f]) for f in fields}) for r in _rows(base, sheet)
                            if r[fields[0]] in made and r[fields[0]].startswith(prefix)]
    return canonical(base)


def _rows(bundle: MfgBundle, sheet: str) -> list[dict]:
    return list(bundle[sheet])

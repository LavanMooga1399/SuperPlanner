"""Override application (M8-DESIGN 4.3, pure). Overrides apply in `seq` order on top of the statistical values:

- item `abs`: the item-period value becomes `value`; item `pct`: multiplied by (1 + value / 100);
- family `pct`: every item of the family x (1 + value / 100); family `abs`: the family total of the period becomes
  `value`, split over the family's items proportionally to their current values (equal shares when all are 0).

`apply(stat, overrides, family_of)` -> (final values, per override the list of changes {item_id, period_start,
old, new}). Periods are the version's period starts within [period_from, period_to].
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable


@dataclass(frozen=True)
class Override:
    id: str
    seq: int
    item_id: str | None
    item_family: str | None
    period_from: date
    period_to: date
    mode: str
    value: float


def apply(stat: dict[tuple[str, date], float], overrides: Iterable[Override], family_of: dict[str, str | None]
          ) -> tuple[dict[tuple[str, date], float], dict[str, list[dict[str, Any]]]]:
    final = dict(stat)
    periods = sorted({p for (_i, p) in stat})
    items = sorted({i for (i, _p) in stat})
    changes: dict[str, list[dict[str, Any]]] = {}
    for o in sorted(overrides, key=lambda x: (x.seq, x.id)):
        targets = [o.item_id] if o.item_id is not None else [i for i in items if family_of.get(i) == o.item_family]
        targets = [i for i in targets if any((i, p) in final for p in periods)]
        ch: list[dict[str, Any]] = []
        for p in periods:
            if not (o.period_from <= p <= o.period_to):
                continue
            keys = [(i, p) for i in targets if (i, p) in final]
            if not keys:
                continue
            old = {k: final[k] for k in keys}
            if o.mode == "pct":
                new = {k: max(0.0, v * (1.0 + o.value / 100.0)) for k, v in old.items()}
            elif o.item_id is not None:
                new = {keys[0]: max(0.0, o.value)}
            else:
                tot = sum(old.values())
                new = {k: (o.value * v / tot if tot > 0 else o.value / len(keys)) for k, v in old.items()}
            for k in keys:
                final[k] = round(new[k], 6)
                ch.append({"item_id": k[0], "period_start": k[1], "old": round(old[k], 6), "new": final[k]})
        changes[o.id] = ch
    return final, changes

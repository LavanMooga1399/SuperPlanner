"""Independent validator of a sterilisation plan (M8-DESIGN 8, V3): per load one cycle code, pallets within the
chamber, start not before any member is ready, end = start + cycle hours, no overlap on a chamber (also with busy
loads), aeration room positions never exceeded at any time (cumulative check), aeration not before the cycle end."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def validate(loads: list[Any], chambers: list[Any], rooms: list[Any], busy_chambers: dict[str, list[tuple]],
             busy_rooms: dict[str, list[tuple]], ready: dict[str, datetime]) -> dict[str, Any]:
    viol: list[dict[str, Any]] = []
    ch = {c.id: c for c in chambers}
    rm = {r.id: r for r in rooms}
    per_chamber: dict[str, list[tuple[datetime, datetime]]] = {k: list(v) for k, v in busy_chambers.items()}
    per_room: dict[str, list[tuple[datetime, datetime, int]]] = {k: list(v) for k, v in busy_rooms.items()}
    for ix, ld in enumerate(loads):
        c = ch.get(ld.chamber_id)
        if c is None:
            viol.append({"code": "STER_V_CHAMBER", "load_ix": ix})
            continue
        pallets = sum(m.pallets for m in ld.members)
        if pallets > c.pallets:
            viol.append({"code": "STER_V_CAPACITY", "load_ix": ix, "pallets": pallets, "capacity": c.pallets})
        if c.cycle_codes is not None and ld.cycle_code not in c.cycle_codes:
            viol.append({"code": "STER_V_CYCLE", "load_ix": ix})
        if abs((ld.end - ld.start).total_seconds() - c.cycle_hours * 3600) > 1:
            viol.append({"code": "STER_V_DURATION", "load_ix": ix})
        for m in ld.members:
            if m.key in ready and ready[m.key] > ld.start + timedelta(seconds=1):
                viol.append({"code": "STER_V_READY", "load_ix": ix, "member": m.key})
        for a, b in per_chamber.get(ld.chamber_id, []):
            if a < ld.end and ld.start < b:
                viol.append({"code": "STER_V_OVERLAP", "load_ix": ix})
                break
        per_chamber.setdefault(ld.chamber_id, []).append((ld.start, ld.end))
        if ld.aeration_room_id is not None:
            if ld.aeration_room_id not in rm:
                viol.append({"code": "STER_V_ROOM", "load_ix": ix})
            else:
                per_room.setdefault(ld.aeration_room_id, []).append((ld.end, ld.aeration_end, pallets))
        if ld.aeration_end < ld.end:
            viol.append({"code": "STER_V_AERATION", "load_ix": ix})
    for rid, busy in per_room.items():
        r = rm.get(rid)
        if r is None:
            continue
        for t in sorted({a for a, _b, _n in busy}):
            used = sum(n for a, b, n in busy if a <= t < b)
            if used > r.positions:
                viol.append({"code": "STER_V_AERATION_CAPACITY", "room_id": rid, "at": t.isoformat(), "used": used})
                break
    return {"ok": not viol, "violations": viol}

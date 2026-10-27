"""Read helpers over an `OResult` for assertions."""

from __future__ import annotations

from typing import Any

from .model import OPlanned, OReq, OResult, OSup


def planned(res: OResult, item_id: str) -> list[OPlanned]:
    return [p for p in res.planned if p.item_id == item_id]


def demand_req(res: OResult, line_id: str) -> OReq:
    hit = [r for rs in res.requirements.values() for r in rs if r.kind == "demand" and r.source[1] == line_id]
    assert len(hit) == 1, (line_id, hit)
    return hit[0]


def reqs(res: OResult, item_id: str, kind: str | None = None) -> list[OReq]:
    return [r for r in res.requirements.get(item_id, []) if kind is None or r.kind == kind]


def supply(res: OResult, item_id: str, node: int) -> OSup:
    return res.supplies[item_id][node - 1]


def pegs(res: OResult, r: OReq) -> list[tuple[tuple[Any, ...], float]]:
    """[(supply ref, qty)] in peg order; reservation/balance refs are reported as ("balance", id)."""
    out = []
    for pg in r.pegs:
        s = supply(res, pg.supply_item_id, pg.supply_node)
        ref = ("balance", s.ref[1]) if s.ref[0] == "reservation" else s.ref
        out.append((ref, round(pg.qty, 6)))
    return out


def peg_kinds(res: OResult, r: OReq) -> list[tuple[str, float]]:
    return [(supply(res, pg.supply_item_id, pg.supply_node).kind, round(pg.qty, 6)) for pg in r.pegs]


def demand_proj(res: OResult, line_id: str):
    hit = [x for x in res.demand if x.key == ("demand", line_id)]
    assert len(hit) == 1
    return hit[0]


def exc(res: OResult, code: str) -> list[Any]:
    return [e for e in res.exceptions if e.code == code]

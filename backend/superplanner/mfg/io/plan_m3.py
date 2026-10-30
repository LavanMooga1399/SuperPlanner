"""Import planning of the M3 master sheets (M3-DESIGN 3.2): `operation_line_rates`, `setup_matrix`,
`operator_absences`. Create / update by natural key (no deletes, like the other master sheets). References resolve
against the final state of the file (operations / lines / operators created by the same import included)."""

from __future__ import annotations

from typing import Any

from ..bundle import SHEETS_BY_NAME
from ..model_m3 import OperationLineRateInput, OperatorAbsenceInput, SetupMatrixRowInput
from . import messages as msg


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


class M3Planner:
    def __init__(self, P: Any):
        self.P = P

    def run(self) -> None:
        if "operation_line_rates" in self.P.b:
            self.rates()
        if "setup_matrix" in self.P.b:
            self.matrix()
        if "operator_absences" in self.P.b:
            self.absences()

    # ------------------------------------------------------------ indexes of the final state
    def _routings(self) -> dict[tuple[str, str, str, int], str]:
        """(item_id, revision, code, version) -> routing id, existing and created by this import."""
        P = self.P
        out = {(r.item_id, r.revision, r.code, r.version): r.id for r in P.ds.routings.values()}
        for rid, (hdr, _ops, _st) in P.planned_routings.items():
            out[(hdr.get("item_id"), hdr.get("revision"), hdr.get("code"), hdr.get("version"))] = rid
        return out

    def _ops(self) -> dict[tuple[str, int], tuple[str, str]]:
        """(routing id, seq) -> (operation id, group id)."""
        P = self.P
        out = {(r.id, op.seq): (op.id, op.group_id) for r in P.ds.routings.values() for op in r.operations}
        for c in P.changes:
            if c.table == "operations":
                if c.action == "create":
                    out[(c.values.get("routing_id"), c.values.get("seq"))] = (c.id, c.values.get("group_id"))
                elif c.action == "delete":
                    out = {k: v for k, v in out.items() if v[0] != c.id}
                elif "group_id" in c.values:
                    out = {k: (v[0], c.values["group_id"]) if v[0] == c.id else v for k, v in out.items()}
        return out

    # ------------------------------------------------------------ operation line rates
    def rates(self) -> None:
        P = self.P
        sheet = "operation_line_rates"
        rts, ops = self._routings(), self._ops()
        existing = {(x.operation_id, x.line_id): x for x in P.ds.operation_line_rates.values()}
        seen: dict[Any, int] = {}
        for row, src in P.rows(sheet):
            if _blank(row.get("part_number")) or row.get("seq") is None or _blank(row.get("line_code")):
                for f in ("part_number", "seq", "line_code"):
                    if _blank(row.get(f)):
                        P.err(sheet, src, f, "IMP_REQUIRED", msg.required(f))
                continue
            it = P.resolve(sheet, src, "part_number", P.items, row.get("part_number"), "Part")
            ln = P.resolve(sheet, src, "line_code", P.lines, row.get("line_code"), "Line")
            if it is None or ln is None:
                continue
            rev = _s(row.get("revision")) or it.data.get("revision", "A")
            code = _s(row.get("code")) or "STD"
            ver = row.get("version")
            cands = [k for k in rts if k[:3] == (it.id, rev, code) and (ver is None or k[3] == ver)]
            rid = rts[max(cands, key=lambda k: k[3])] if cands else None
            op = ops.get((rid, row.get("seq"))) if rid else None
            if op is None:
                P.err(sheet, src, "seq", "IMP_UNKNOWN_REFERENCE",
                      f"Operation {row.get('seq')} of {_s(row.get('part_number'))} {rev}/{code}"
                      f"{'' if ver is None else '/v' + str(ver)} was not found.")
                continue
            if ln.data.get("group_id") != op[1]:
                P.err(sheet, src, "line_code", "IMP_BAD_VALUE",
                      f"Line {_s(row.get('line_code'))} is not in the stage of operation {row.get('seq')}.")
                continue
            key = (op[0], ln.id)
            if not P.dedupe(sheet, src, seen, key, f"{_s(row.get('part_number'))} op {row.get('seq')} / "
                                                   f"{_s(row.get('line_code'))}"):
                continue
            ex = existing.get(key)
            base = ({"operation_id": ex.operation_id, "line_id": ex.line_id, "setup_minutes": ex.setup_minutes,
                     "run_minutes": ex.run_minutes, "note": ex.note} if ex else {})
            d = P.merge(base, row, OperationLineRateInput, ex is None, ("setup_minutes", "run_minutes", "note"))
            d.update(operation_id=op[0], line_id=ln.id)
            inp = P.validate(sheet, src, OperationLineRateInput, d)
            if inp is None:
                continue
            new = inp.model_dump()
            k = {"part_number": _s(row.get("part_number")), "seq": row.get("seq"), "line_code": _s(row.get("line_code"))}
            if ex is None:
                P.add(sheet, "create", P.nid("olr_"), new)
                P.note(sheet, "create", k)
            else:
                ch = P.diff(base, new, ("setup_minutes", "run_minutes", "note"))
                if ch:
                    P.add(sheet, "update", ex.id, {f: new[f] for f in ch})
                P.note(sheet, "update" if ch else "unchanged", k, ch)

    # ------------------------------------------------------------ setup matrix
    def matrix(self) -> None:
        P = self.P
        sheet = "setup_matrix"
        existing = {(x.line_setup_family, x.from_family, x.to_family): x for x in P.ds.setup_matrix.values()}
        seen: dict[Any, int] = {}
        for row, src in P.rows(sheet):
            if not P.required(sheet, row, src, True):
                continue
            d = {f: row.get(f) for f in SHEETS_BY_NAME[sheet].fields if f in row}
            inp = P.validate(sheet, src, SetupMatrixRowInput, d)
            if inp is None:
                continue
            key = (inp.line_setup_family, inp.from_family, inp.to_family)
            if not P.dedupe(sheet, src, seen, key, " / ".join(key)):
                continue
            ex = existing.get(key)
            k = dict(zip(("line_setup_family", "from_family", "to_family"), key))
            if ex is None:
                P.add(sheet, "create", P.nid("stm_"), inp.model_dump())
                P.note(sheet, "create", k)
            else:
                ch = P.diff({"setup_minutes": ex.setup_minutes}, {"setup_minutes": inp.setup_minutes},
                            ("setup_minutes",))
                if ch:
                    P.add(sheet, "update", ex.id, {"setup_minutes": inp.setup_minutes})
                P.note(sheet, "update" if ch else "unchanged", k, ch)

    # ------------------------------------------------------------ operator absences
    def absences(self) -> None:
        from datetime import UTC

        from .plan import _to_aware

        P = self.P
        sheet = "operator_absences"
        codes = {x.code: x.id for x in P.ds.operators.values()}
        for c in P.changes:
            if c.table == "operators" and c.action == "create":
                codes[c.values.get("code")] = c.id
        existing = {(x.operator_id, x.start.astimezone(UTC)): x for x in P.ds.operator_absences.values()}
        seen: dict[Any, int] = {}
        for row, src in P.rows(sheet):
            if not P.required(sheet, row, src, True):
                continue
            oid = codes.get(_s(row.get("operator_code")))
            if oid is None:
                P.err(sheet, src, "operator_code", "IMP_UNKNOWN_REFERENCE",
                      f"Operator {_s(row.get('operator_code'))!r} was not found.")
                continue
            try:
                start = _to_aware(row["start"], P.tz)
                end = _to_aware(row["end"], P.tz, end=True)
            except (ValueError, TypeError):
                P.err(sheet, src, "start", "IMP_BAD_DATE", "Start / end must be dates or date-times.")
                continue
            d = {"operator_id": oid, "start": start, "end": end, "note": _s(row.get("note"))}
            if not _blank(row.get("kind")):
                d["kind"] = _s(row.get("kind"))
            inp = P.validate(sheet, src, OperatorAbsenceInput, d)
            if inp is None:
                continue
            key = (oid, inp.start.astimezone(UTC))
            if not P.dedupe(sheet, src, seen, key, f"{_s(row.get('operator_code'))} {inp.start.isoformat()}"):
                continue
            ex = existing.get(key)
            vals = {"operator_id": oid, "start_at": inp.start, "end_at": inp.end, "kind": inp.kind, "note": inp.note}
            k = {"operator_code": _s(row.get("operator_code")), "start": inp.start.isoformat()}
            if ex is None:
                P.add(sheet, "create", P.nid("oab_"), vals)
                P.note(sheet, "create", k)
            else:
                old = {"end_at": ex.end.astimezone(UTC), "kind": ex.kind, "note": ex.note}
                new = {"end_at": inp.end.astimezone(UTC), "kind": inp.kind, "note": inp.note}
                ch = P.diff(old, new, old.keys())
                if ch:
                    P.add(sheet, "update", ex.id, {f: vals[f] for f in ch})
                P.note(sheet, "update" if ch else "unchanged", k, ch)

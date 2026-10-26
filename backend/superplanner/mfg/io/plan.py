"""`plan_import(bundle, dataset, options) -> ImportPlan` (M1-DESIGN 8.1): a pure diff by natural keys.

Resolves natural keys against the dataset and against rows earlier in the bundle, runs the API's Pydantic input
models (errors become row errors), the document rules, released-document protection, the cycle check over existing
plus new edges and, for documents created as released, the `release.py` rules (in file order, against the stored
documents and each other). Nothing is written: the plan lists `Change`s in database column terms that
`api.mfg.writer.apply` executes in one transaction.

Upsert semantics: an existing key updates only the columns present in the row; a blank cell sets a nullable field
to null and leaves a non-nullable one unchanged (on create: its default). List columns replace the whole list.
Imports never delete master entities; only children (BOM lines, operations, tools, shifts, links) are deleted, and
BOM lines / operations only under `replace_children` when their sheet is part of the import.
"""

from __future__ import annotations

import types
import typing
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError

from .. import limits as L
from ..bom import find_cycles
from ..bundle import ATTR_PREFIX, SHEET_NAMES, SHEETS_BY_NAME, MfgBundle, parse_break, parse_days, parse_tool
from ..calendar import offset_tz, validate_template
from ..dataset import MfgDataset, link
from ..model import (BomInput, BomLineInput, BomLineRecord, BomRecord, CalendarExceptionInput, GroupInput,
                     GroupRecord, ItemInput, ItemRecord, LineInput, OperationInput, OperationRecord,
                     OperationToolRecord, OperatorInput, PlantInput, RoutingInput, RoutingRecord,
                     ShiftAssignmentInput, ShiftTemplateInput, SkillInput, SkillRecord, ToolPoolInput,
                     ToolPoolRecord, input_data)
from ..health import doc_label
from ..release import bom_release_issues, routing_release_issues
from . import messages as msg
from .mapping import SKIP, Source, bundle_sources

IdFactory = Callable[[str], str]
SET_FIELDS = frozenset({"skill_ids", "eligible_item_ids"})   # order carries no meaning (link tables)
DOC_HEADER_FIELDS = ("effective_from", "effective_to", "serial_from", "serial_to", "note")


def default_id_factory(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


@dataclass
class ImportOptions:
    replace_children: bool = True
    release: bool = False
    default_effective_from: date | None = None


@dataclass
class Change:
    table: str                       # writer table key (mfg_ prefix dropped)
    action: str                      # create | update | delete
    id: Any                          # row id; link tables: (parent_id, other_id)
    values: dict[str, Any] = field(default_factory=dict)   # create: all columns; update: changed columns


@dataclass
class ImportPlan:
    changes: list[Change]
    counts: dict[str, dict[str, int]]
    row_errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    changes_sample: list[dict[str, Any]]
    bump: dict[str, set[str]]        # documents whose children changed (header row_version bump)

    @property
    def error_count(self) -> int:
        return len(self.row_errors)

    @property
    def ok(self) -> bool:
        return not self.row_errors

    def has_writes(self) -> bool:
        return bool(self.changes) or any(self.bump.values())

    def preview(self, max_errors: int, max_samples: int = 50) -> dict[str, Any]:
        return {"ok": self.ok, "counts": self.counts, "error_count": self.error_count,
                "row_errors": self.row_errors[:max_errors], "warnings": self.warnings,
                "changes_sample": self.changes_sample[:max_samples]}

    def result_counts(self) -> dict[str, dict[str, int]]:
        return {s: {k: v for k, v in c.items() if k != "error"} for s, c in self.counts.items()}


# ---------------------------------------------------------------- helpers


def _nullable(model: type[BaseModel], name: str) -> bool:
    def has_none(tp: Any) -> bool:
        if tp is type(None) or tp is None:
            return True
        origin = typing.get_origin(tp)
        if origin is typing.Annotated:
            return has_none(typing.get_args(tp)[0])
        if origin in (typing.Union, types.UnionType):
            return any(has_none(a) for a in typing.get_args(tp))
        return False

    f = model.model_fields.get(name)
    return f is not None and has_none(f.annotation)


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


def _to_aware(v: Any, tz: Any, *, end: bool = False) -> datetime:
    """A cell -> aware datetime in `tz`; ValueError (-> IMP_BAD_DATE) also for values outside
    `MIN_DATE..MAX_DATE` (checked before any arithmetic that could overflow)."""
    try:
        dt = _to_aware_raw(v, tz, end=end)
    except OverflowError as exc:
        raise ValueError("date out of range") from exc
    if not (L.MIN_DATE <= dt.date() <= L.MAX_DATE):
        raise ValueError("date out of range")
    return dt


def _to_aware_raw(v: Any, tz: Any, *, end: bool = False) -> datetime:
    if isinstance(v, (date, datetime)) and not (L.MIN_DATE <= (v.date() if isinstance(v, datetime) else v)
                                                 <= L.MAX_DATE):
        raise ValueError("date out of range")
    if isinstance(v, datetime):
        return (v if v.tzinfo is not None else v.replace(tzinfo=tz)).astimezone(tz)
    if isinstance(v, date):
        d = v + timedelta(days=1) if end else v
        return datetime(d.year, d.month, d.day, tzinfo=tz)
    s = str(v).strip()
    if len(s) == 10:
        return _to_aware_raw(date.fromisoformat(s), tz, end=end)
    dt = datetime.fromisoformat(s)
    return (dt if dt.tzinfo is not None else dt.replace(tzinfo=tz)).astimezone(tz)


def _plain(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return {k: _plain(x) for k, x in v.__dict__.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


def _data(record: BaseModel) -> dict[str, Any]:
    """Input fields of a record as plain values (nested models -> dicts, `id` of lines/operations dropped)."""
    d = _plain(input_data(record))
    return d


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _err_type(e: dict[str, Any]) -> str:
    return "IMP_TOO_LONG" if e.get("type") == "string_too_long" else "IMP_BAD_VALUE"


@dataclass
class _Ent:
    """Final state of a natural-key entity (existing or created by this plan)."""
    id: str
    data: dict[str, Any]
    created: bool


# ---------------------------------------------------------------- planner


class _Planner:
    def __init__(self, bundle: MfgBundle, ds: MfgDataset, options: ImportOptions,
                 sources: dict[str, list[Source]], id_factory: IdFactory):
        self.b = {k: list(v or []) for k, v in bundle.items()}
        self.ds = ds
        self.o = options
        self.src = sources
        self.nid = id_factory
        self.changes: list[Change] = []
        self.counts: dict[str, dict[str, int]] = {}
        self.errors: list[dict[str, Any]] = []
        self.err_rows: set[tuple[str, str, int]] = set()
        self.warnings: list[dict[str, Any]] = []
        self.sample: list[dict[str, Any]] = []
        self.bump: dict[str, set[str]] = {"boms": set(), "routings": set()}
        self.tz = offset_tz(ds.plant.utc_offset)
        self.shrunk_templates: dict[str, tuple[str, Source, set[str]]] = {}   # id -> (code, source, final names)
        self.unserialized: dict[str, tuple[str, Source]] = {}     # item id -> (part number, source): serialized off
        self.rebase: tuple[Any, Any] | None = None       # (old tz, new tz) when the file changes the plant offset
        # final-state lookups by natural key
        self.items: dict[str, _Ent] = {it.part_number: _Ent(it.id, _data(it), False) for it in ds.items.values()}
        self.groups = {g.code: _Ent(g.id, _data(g), False) for g in ds.groups.values()}
        self.skills = {x.code: _Ent(x.id, _data(x), False) for x in ds.skills.values()}
        self.pools = {x.code: _Ent(x.id, _data(x), False) for x in ds.tool_pools.values()}
        self.lines = {x.code: _Ent(x.id, _data(x), False) for x in ds.lines.values()}
        self.templates = {x.code: _Ent(x.id, _data(x), False) for x in ds.shift_templates.values()}
        self.item_by_id = {e.id: pn for pn, e in self.items.items()}
        self.changed_items: set[str] = set()
        self.planned_boms: dict[str, tuple[dict[str, Any], list[dict[str, Any]], str]] = {}   # id -> (hdr, lines, status)
        self.planned_routings: dict[str, tuple[dict[str, Any], list[dict[str, Any]], str]] = {}
        self.to_release: list[tuple[str, str, Source, str]] = []      # (kind, doc id, source, label)
        self.line_src: dict[tuple[str, str], Source] = {}              # (parent item, child item) -> source
        for name in self.b:
            if name not in SHEETS_BY_NAME:
                self.warnings.append({"code": "IMP_SHEET_IGNORED", "sheet": name,
                                      "message": f"Sheet {name!r} is not an import sheet and was ignored."})

    # ------------------------------------------------------------ bookkeeping

    def rows(self, sheet: str) -> list[tuple[dict[str, Any], Source]]:
        rows = self.b.get(sheet) or []
        srcs = self.src.get(sheet) or bundle_sources({sheet: rows})[sheet]
        return [(r, s) for r, s in zip(rows, srcs) if not r.get(SKIP)]

    def count(self, sheet: str, action: str, n: int = 1) -> None:
        c = self.counts.setdefault(sheet, {"create": 0, "update": 0, "unchanged": 0, "delete": 0, "error": 0})
        c[action] += n

    def err(self, sheet: str, src: Source, f: str | None, code: str, message: str) -> None:
        self.errors.append({"sheet": src.sheet, "row": src.row, "column": src.column(f) if f else None,
                            "code": code, "message": message})
        k = (sheet, src.sheet, src.row)
        if k not in self.err_rows:
            self.err_rows.add(k)
            self.count(sheet, "error")

    def pyd_errors(self, sheet: str, src: Source, exc: ValidationError, rename: dict[str, str] | None = None,
                   ) -> None:
        for e in exc.errors()[:5]:
            loc = [x for x in e.get("loc", ()) if isinstance(x, str)]
            f = loc[0] if loc else None
            if rename and f in rename:
                f = rename[f]
            text = e.get("msg", "invalid value")
            where = f"{msg.label(f)}: " if f else ""
            self.err(sheet, src, f, _err_type(e), f"{where}{text}.")

    def note(self, sheet: str, action: str, key: dict[str, Any], fields: dict[str, Any] | None = None) -> None:
        self.count(sheet, action)
        if action != "unchanged" and len(self.sample) < 50:
            entry: dict[str, Any] = {"sheet": sheet, "key": _jsonable(key), "action": action}
            if fields:
                entry["fields"] = {k: [_jsonable(a), _jsonable(b)] for k, (a, b) in fields.items()}
            self.sample.append(entry)

    def add(self, table: str, action: str, id_: Any, values: dict[str, Any] | None = None) -> None:
        self.changes.append(Change(table, action, id_, dict(values or {})))

    @staticmethod
    def diff(old: dict[str, Any], new: dict[str, Any], names: typing.Iterable[str]) -> dict[str, tuple[Any, Any]]:
        def norm(k: str, v: Any) -> Any:
            return sorted(v) if k in SET_FIELDS and isinstance(v, list) else v

        return {k: (old.get(k), new.get(k)) for k in names if norm(k, old.get(k)) != norm(k, new.get(k))}

    def merge(self, base: dict[str, Any], row: dict[str, Any], model: type[BaseModel], creating: bool,
              fields: typing.Iterable[str], rename: dict[str, str] | None = None) -> dict[str, Any]:
        d = dict(base)
        rename = rename or {}
        for f in fields:
            if f not in row:
                continue
            target = rename.get(f, f)
            v = row[f]
            if isinstance(v, list):
                d[target] = v
            elif _blank(v):
                if _nullable(model, target):
                    d[target] = None
                elif creating:
                    d.pop(target, None)
            else:
                d[target] = v.strip() if isinstance(v, str) else v
        return d

    def required(self, sheet: str, row: dict[str, Any], src: Source, creating: bool, base: dict[str, Any] | None = None
                 ) -> bool:
        ok = True
        for c in SHEETS_BY_NAME[sheet].columns:
            if not c.required_on_create:
                continue
            if c.key and _blank(row.get(c.field)) and c.type != "list":
                self.err(sheet, src, c.field, "IMP_REQUIRED", msg.required(c.field))
                ok = False
            elif creating and not c.key and (c.field not in row or _blank(row.get(c.field))
                                             or row.get(c.field) == []):
                self.err(sheet, src, c.field, "IMP_REQUIRED", msg.required(c.field))
                ok = False
        return ok

    def validate(self, sheet: str, src: Source, model: type[BaseModel], data: dict[str, Any],
                 rename: dict[str, str] | None = None) -> BaseModel | None:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            self.pyd_errors(sheet, src, exc, rename)
            return None

    def dedupe(self, sheet: str, src: Source, seen: dict[Any, int], key: Any, shown: Any) -> bool:
        if key in seen:
            self.err(sheet, src, SHEETS_BY_NAME[sheet].key[0], "IMP_DUPLICATE_KEY", msg.duplicate_key(shown, seen[key]))
            return False
        seen[key] = src.row
        return True

    def resolve(self, sheet: str, src: Source, f: str, table: dict[str, _Ent], code: Any, what: str) -> _Ent | None:
        if _blank(code):
            return None
        e = table.get(str(code).strip())
        if e is None:
            self.err(sheet, src, f, "IMP_UNKNOWN_REFERENCE", msg.unknown_reference(what, code))
        return e

    # ------------------------------------------------------------ run

    def run(self) -> ImportPlan:
        self.plant()
        self.item_sheet()
        self.simple("skills", SkillInput, self.skills, "skills", "skl_", self.ds.skills)
        self.simple("tool_pools", ToolPoolInput, self.pools, "tool_pools", "tlp_", self.ds.tool_pools)
        self.simple("groups", GroupInput, self.groups, "groups", "wcg_", self.ds.groups)
        self.templates_sheet()
        self.line_sheet()
        self.assignment_sheet()
        self.exception_sheet()
        self.operator_sheet()
        self.shift_names_in_use()
        self.documents("boms")
        self.documents("routings")
        self.serial_documents_in_use()
        self.cycles()
        self.releases()
        for name in SHEET_NAMES:
            if name in self.b:
                self.counts.setdefault(name, {"create": 0, "update": 0, "unchanged": 0, "delete": 0, "error": 0})
        self.bump = {k: v - {c.id for c in self.changes if c.table == k and c.action != "delete"}
                     for k, v in self.bump.items()}
        return ImportPlan(self.changes, self.counts, self.errors, self.warnings, self.sample, self.bump)

    # ------------------------------------------------------------ plant

    def plant(self) -> None:
        rows = self.rows("plant")
        if not rows:
            return
        for row, src in rows[1:]:
            self.err("plant", src, None, "IMP_BAD_VALUE", "The plant sheet has at most one row.")
        row, src = rows[0]
        p = self.ds.plant
        base = _data(p)
        d = self.merge(base, row, PlantInput, False, SHEETS_BY_NAME["plant"].fields)
        inp = self.validate("plant", src, PlantInput, d)
        if inp is None:
            return
        new = inp.model_dump()
        ch = self.diff(base, new, ("name", "utc_offset", "planning_horizon_days", "currency"))
        if ch:
            self.add("plant", "update", p.id, {k: new[k] for k in ch})
            self.note("plant", "create" if p.id is None else "update", {}, ch)
            self.tz = offset_tz(new["utc_offset"])
            if "utc_offset" in ch and p.id is not None:
                self.rebase = (offset_tz(p.utc_offset), self.tz)
        else:
            self.note("plant", "unchanged", {})

    # ------------------------------------------------------------ items

    def item_sheet(self) -> None:
        seen: dict[Any, int] = {}
        spec = SHEETS_BY_NAME["items"]
        for row, src in self.rows("items"):
            pn = row.get("part_number")
            if _blank(pn):
                self.err("items", src, "part_number", "IMP_REQUIRED", msg.required("part_number"))
                continue
            pn = str(pn).strip()
            if not self.dedupe("items", src, seen, pn, f"part number {pn!r}"):
                continue
            ex = self.items.get(pn)
            creating = ex is None
            if not self.required("items", row, src, creating):
                continue
            base = dict(ex.data) if ex else {}
            d = self.merge(base, row, ItemInput, creating, spec.fields)
            attrs = dict(base.get("attributes") or {})
            for k, v in row.items():
                if k.startswith(ATTR_PREFIX):
                    name = k[len(ATTR_PREFIX):]
                    if _blank(v):
                        attrs.pop(name, None)
                    else:
                        attrs[name] = v
            d["attributes"] = attrs
            inp = self.validate("items", src, ItemInput, d)
            if inp is None:
                continue
            new = inp.model_dump()
            if creating:
                iid = self.nid("itm_")
                self.items[pn] = _Ent(iid, new, True)
                self.item_by_id[iid] = pn
                self.changed_items.add(iid)
                self.add("items", "create", iid, new)
                self.note("items", "create", {"part_number": pn})
                continue
            ch = self.diff(ex.data, new, ItemInput.model_fields)
            if ex.data.get("serialized") and not new["serialized"]:
                self.unserialized[ex.id] = (pn, src)
            if ch:
                self.add("items", "update", ex.id, {k: new[k] for k in ch})
                self.items[pn] = _Ent(ex.id, new, False)
                self.changed_items.add(ex.id)
                self.note("items", "update", {"part_number": pn}, ch)
            else:
                self.note("items", "unchanged", {"part_number": pn})

    # ------------------------------------------------------------ code-keyed sheets

    def simple(self, sheet: str, model: type[BaseModel], table: dict[str, _Ent], db_table: str, prefix: str,
               existing: dict[str, Any], extra: Callable[[dict[str, Any], Source, bool, dict[str, Any]], bool] | None
               = None, rename: dict[str, str] | None = None, columns: Callable[[dict[str, Any]], dict[str, Any]]
               | None = None) -> None:
        seen: dict[Any, int] = {}
        spec = SHEETS_BY_NAME[sheet]
        for row, src in self.rows(sheet):
            code = row.get("code")
            if _blank(code):
                self.err(sheet, src, "code", "IMP_REQUIRED", msg.required("code"))
                continue
            code = str(code).strip()
            if not self.dedupe(sheet, src, seen, code, f"code {code!r}"):
                continue
            ex = table.get(code)
            creating = ex is None
            if not self.required(sheet, row, src, creating):
                continue
            base = dict(ex.data) if ex else {}
            fields = [f for f in spec.fields if not rename or f not in rename]
            d = self.merge(base, row, model, creating, fields)
            if extra is not None and not extra(d, src, creating, row):
                continue
            inp = self.validate(sheet, src, model, d, {v: k for k, v in (rename or {}).items()})
            if inp is None:
                continue
            new = inp.model_dump()
            cols = columns(new) if columns else new
            if creating:
                eid = self.nid(prefix)
                table[code] = _Ent(eid, new, True)
                self.add(db_table, "create", eid, cols)
                self.note(sheet, "create", {"code": code})
                self.after(sheet, eid, None, new)
                continue
            ch = self.diff(ex.data, new, model.model_fields)
            table[code] = _Ent(ex.id, new, False)
            col_ch = {k: cols[k] for k in ch if k in cols}
            if col_ch:
                self.add(db_table, "update", ex.id, col_ch)
            self.after(sheet, ex.id, ex.data, new)
            self.note(sheet, "update" if ch else "unchanged", {"code": code}, ch)

    def after(self, sheet: str, eid: str, old: dict[str, Any] | None, new: dict[str, Any]) -> None:
        """Link-table changes of lines (eligible items) and operators (skills)."""
        if sheet == "lines":
            self.links("line_items", eid, (old or {}).get("eligible_item_ids") or [], new["eligible_item_ids"])
        elif sheet == "operators":
            self.links("operator_skills", eid, (old or {}).get("skill_ids") or [], new["skill_ids"])

    def links(self, table: str, parent: str, old: list[str], new: list[str]) -> None:
        o, n = set(old), set(new)
        for x in sorted(o - n):
            self.add(table, "delete", (parent, x))
        for x in sorted(n - o):
            self.add(table, "create", (parent, x))

    # ------------------------------------------------------------ lines

    def line_sheet(self) -> None:
        def extra(d: dict[str, Any], src: Source, creating: bool, row: dict[str, Any]) -> bool:
            ok = True
            if "group_code" in row and not _blank(row["group_code"]):
                g = self.resolve("lines", src, "group_code", self.groups, row["group_code"], "Stage")
                if g is None:
                    ok = False
                else:
                    d["group_id"] = g.id
            if "eligible_part_numbers" in row:
                ids = []
                for pn in row["eligible_part_numbers"] or []:
                    e = self.resolve("lines", src, "eligible_part_numbers", self.items, pn, "Part number")
                    if e is None:
                        ok = False
                    else:
                        ids.append(e.id)
                d["eligible_item_ids"] = sorted(set(ids))
            return ok

        def columns(new: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in new.items() if k != "eligible_item_ids"}

        self.simple("lines", LineInput, self.lines, "lines", "lin_", self.ds.lines, extra,
                    rename={"group_code": "group_id", "eligible_part_numbers": "eligible_item_ids"}, columns=columns)

    # ------------------------------------------------------------ shift templates + shifts

    def templates_sheet(self) -> None:
        shifts_of: dict[str, list[tuple[dict[str, Any], Source]]] = {}
        seen: dict[Any, int] = {}
        for row, src in self.rows("shifts"):
            if not self.required("shifts", row, src, True):
                continue
            tc, name = str(row["template_code"]).strip(), str(row["shift_name"]).strip()
            if not self.dedupe("shifts", src, seen, (tc, name), f"shift {tc}/{name}"):
                continue
            shifts_of.setdefault(tc, []).append((row, src))
        header_rows = {str(r.get("code") or "").strip(): (r, s) for r, s in self.rows("shift_templates")}
        for tc in shifts_of:
            if tc not in header_rows and tc not in self.templates:
                for _row, src in shifts_of[tc]:
                    self.err("shifts", src, "template_code", "IMP_UNKNOWN_REFERENCE",
                             msg.unknown_reference("Shift template", tc))
        seen = {}
        codes = [c for c in header_rows] + [c for c in shifts_of if c not in header_rows and c in self.templates]
        for code in codes:
            row, src = header_rows.get(code, ({}, shifts_of[code][0][1]))
            if code in header_rows and not code:
                self.err("shift_templates", src, "code", "IMP_REQUIRED", msg.required("code"))
                continue
            if code in header_rows and not self.dedupe("shift_templates", src, seen, code, f"code {code!r}"):
                continue
            ex = self.templates.get(code)
            creating = ex is None
            if code in header_rows and not self.required("shift_templates", row, src, creating):
                continue
            base = dict(ex.data) if ex else {}
            d = self.merge(base, row, ShiftTemplateInput, creating, ("code", "name", "description"))
            d["code"] = code
            file_shifts = shifts_of.get(code)
            shift_srcs: list[Source] = []
            if file_shifts is not None:
                parsed = []
                bad = False
                for srow, ssrc in file_shifts:
                    try:
                        parsed.append({"name": str(srow["shift_name"]).strip(), "days": parse_days(srow["days"] or []),
                                       "start": str(srow["start"]).strip(), "end": str(srow["end"]).strip(),
                                       "breaks": [parse_break(x) for x in srow.get("breaks") or []]})
                        shift_srcs.append(ssrc)
                    except (ValueError, TypeError) as exc:
                        self.err("shifts", ssrc, "days" if "day" in str(exc) else "breaks", "IMP_BAD_VALUE",
                                 f"{exc}.")
                        bad = True
                if bad:
                    continue
                d["shifts"] = parsed
            elif creating:
                self.err("shift_templates", src, "code", "IMP_REQUIRED",
                         f"Shift template {code!r} has no rows in the shifts sheet.")
                continue
            try:
                inp = ShiftTemplateInput.model_validate(d)
            except ValidationError as exc:
                for e in exc.errors()[:5]:
                    loc = list(e.get("loc", ()))
                    if loc and loc[0] == "shifts" and len(loc) > 1 and isinstance(loc[1], int) \
                            and loc[1] < len(shift_srcs):
                        f = str(loc[2]) if len(loc) > 2 else "shift_name"
                        f = {"name": "shift_name"}.get(f, f)
                        self.err("shifts", shift_srcs[loc[1]], f, _err_type(e), f"{msg.label(f)}: {e['msg']}.")
                    else:
                        f = str(loc[0]) if loc else None
                        self.err("shift_templates", src, f, _err_type(e), f"{e['msg']}.")
                continue
            problems = validate_template(inp)
            if problems:
                for p in problems[:5]:
                    loc = list(p.get("loc", ()))
                    i = next((x for x in loc if isinstance(x, int)), None)
                    if i is not None and i < len(shift_srcs):
                        self.err("shifts", shift_srcs[i], "start", "IMP_BAD_VALUE", p["msg"])
                    else:
                        self.err("shift_templates", src, "code", "IMP_BAD_VALUE", p["msg"])
                continue
            new = inp.model_dump()
            # shifts counts by name
            old_sh = {s["name"]: s for s in (ex.data["shifts"] if ex else [])}
            if file_shifts is not None:
                for s in new["shifts"]:
                    o = old_sh.get(s["name"])
                    self.count("shifts", "create" if o is None else ("unchanged" if o == s else "update"))
                for name in old_sh:
                    if name not in {s["name"] for s in new["shifts"]}:
                        self.count("shifts", "delete")
            if creating:
                tid = self.nid("sht_")
                self.templates[code] = _Ent(tid, new, True)
                self.add("shift_templates", "create", tid, new)
                if code in header_rows:
                    self.note("shift_templates", "create", {"code": code})
                continue
            ch = self.diff(ex.data, new, ShiftTemplateInput.model_fields)
            kept = {sh["name"] for sh in new["shifts"]}
            if {sh["name"] for sh in ex.data.get("shifts") or []} - kept:
                self.shrunk_templates[ex.id] = (code, src, kept)
            self.templates[code] = _Ent(ex.id, new, False)
            if ch:
                self.add("shift_templates", "update", ex.id, {k: new[k] for k in ch})
            if code in header_rows:
                self.note("shift_templates", "update" if ch else "unchanged", {"code": code},
                          {k: v for k, v in ch.items() if k != "shifts"})

    def shift_names_ok(self, sheet: str, src: Source, tpl: _Ent | None, names: list[str]) -> bool:
        if tpl is None:
            return True
        known = {s["name"] for s in tpl.data.get("shifts") or []}
        bad = [n for n in names if n not in known]
        if bad:
            self.err(sheet, src, "shift_names", "IMP_BAD_VALUE",
                     f"Shift template has no shift named {', '.join(repr(b) for b in bad)}.")
            return False
        return True

    def shift_names_in_use(self) -> None:
        """A template of the file that drops or renames a shift still named by an assignment or operator (final
        state: existing rows with the file's updates applied) -> `IMP_IN_USE` on the template row (review F2)."""
        if not self.shrunk_templates:
            return
        upd: dict[tuple[str, str], dict[str, Any]] = {}
        for c in self.changes:
            if c.action == "update" and c.table in ("shift_assignments", "operators"):
                upd.setdefault((c.table, c.id), {}).update(c.values)
        users: dict[str, list[str]] = {}
        for a in sorted(self.ds.shift_assignments.values(), key=lambda a: a.id):
            v = {"shift_template_id": a.shift_template_id, "shift_names": a.shift_names,
                 **upd.get(("shift_assignments", a.id), {})}
            t = self.shrunk_templates.get(v["shift_template_id"])
            if t is not None and any(n not in t[2] for n in v["shift_names"] or []):
                tgt = self.ds.groups.get(a.group_id or "") if a.target_type == "group" else \
                    self.ds.lines.get(a.line_id or "")
                users.setdefault(v["shift_template_id"], []).append(
                    f"assignment on {tgt.code if tgt else '?'} ({a.kind})")
        for o in sorted(self.ds.operators.values(), key=lambda o: o.code):
            v = {"shift_template_id": o.shift_template_id, "shift_names": o.shift_names,
                 **upd.get(("operators", o.id), {})}
            t = self.shrunk_templates.get(v["shift_template_id"] or "")
            if t is not None and any(n not in t[2] for n in v["shift_names"] or []):
                users.setdefault(v["shift_template_id"], []).append(f"operator {o.code}")
        for tid, who in users.items():
            code, src, _kept = self.shrunk_templates[tid]
            shown = ", ".join(who[:5]) + (f" and {len(who) - 5} more" if len(who) > 5 else "")
            self.err("shift_templates", src, "code", "IMP_IN_USE",
                     f"Shift template {code} drops or renames a shift still used by {shown}. Change those in the "
                     "same file (shift_assignments / operators sheets) or keep the shift name.")

    def serial_documents_in_use(self) -> None:
        """An item switched to not serialized while it keeps BOMs/routings (draft or released, not in the file)
        with a serial range -> `IMP_IN_USE` on the item row (review F5; documents of the file are checked by
        `documents`)."""
        for iid, (pn, src) in self.unserialized.items():
            docs = [("BOM", b) for b in self.ds.boms_by_item.get(iid, ()) if b.id not in self.planned_boms] + \
                [("routing", r) for r in self.ds.routings_by_item.get(iid, ()) if r.id not in self.planned_routings]
            used = [f"{what} {doc_label(d)}" for what, d in docs
                    if d.status != "obsolete" and d.serial_from is not None]
            if used:
                self.err("items", src, "serialized", "IMP_IN_USE",
                         f"{pn} cannot stop being serialized: {', '.join(used[:5])}"
                         f"{f' and {len(used) - 5} more' if len(used) > 5 else ''} still "
                         f"{'has' if len(used) == 1 else 'have'} a serial range.")

    # ------------------------------------------------------------ assignments

    def assignment_sheet(self) -> None:
        tcode = {e.id: c for c, e in self.templates.items()}
        gcode = {e.id: c for c, e in self.groups.items()}
        lcode = {e.id: c for c, e in self.lines.items()}
        existing: dict[tuple[Any, ...], Any] = {}
        for a in self.ds.shift_assignments.values():
            tgt = gcode.get(a.group_id) if a.target_type == "group" else lcode.get(a.line_id)
            existing[(tcode.get(a.shift_template_id), a.target_type, tgt, a.kind, a.effective_from)] = a
        seen: dict[Any, int] = {}
        spec = SHEETS_BY_NAME["shift_assignments"]
        for row, src in self.rows("shift_assignments"):
            if not self.required("shift_assignments", row, src, False):
                continue
            tpl = self.resolve("shift_assignments", src, "template_code", self.templates, row["template_code"],
                               "Shift template")
            tt = row["target_type"]
            tgt = self.resolve("shift_assignments", src, "target_code", self.groups if tt == "group" else self.lines,
                               row["target_code"], "Stage" if tt == "group" else "Line")
            if tpl is None or tgt is None:
                continue
            key = (str(row["template_code"]).strip(), tt, str(row["target_code"]).strip(), row["kind"],
                   row["effective_from"])
            if not self.dedupe("shift_assignments", src, seen, key, "assignment " + "/".join(str(k) for k in key)):
                continue
            ex = existing.get(key)
            creating = ex is None
            if not self.required("shift_assignments", row, src, creating):
                continue
            base = _data(ex) if ex else {}
            d = self.merge(base, row, ShiftAssignmentInput, creating,
                           [f for f in spec.fields if f not in ("template_code", "target_code")])
            d.update(shift_template_id=tpl.id, target_type=tt, group_id=tgt.id if tt == "group" else None,
                     line_id=tgt.id if tt == "line" else None)
            inp = self.validate("shift_assignments", src, ShiftAssignmentInput, d,
                                {"shift_template_id": "template_code", "group_id": "target_code",
                                 "line_id": "target_code"})
            if inp is None or not self.shift_names_ok("shift_assignments", src, tpl, inp.shift_names):
                continue
            new = inp.model_dump()
            k = {"template_code": key[0], "target_type": tt, "target_code": key[2], "kind": key[3],
                 "effective_from": key[4]}
            if creating:
                self.add("shift_assignments", "create", self.nid("sha_"), new)
                self.note("shift_assignments", "create", k)
                continue
            ch = self.diff(base, new, ShiftAssignmentInput.model_fields)
            if ch:
                self.add("shift_assignments", "update", ex.id, {k2: new[k2] for k2 in ch})
            self.note("shift_assignments", "update" if ch else "unchanged", k, ch)

    # ------------------------------------------------------------ calendar exceptions

    def exception_sheet(self) -> None:
        gcode = {e.id: c for c, e in self.groups.items()}
        lcode = {e.id: c for c, e in self.lines.items()}
        existing: dict[tuple[Any, ...], Any] = {}
        current = list(self.ds.calendar_exceptions.values())
        if self.rebase is not None:
            # the file changes the plant offset: existing exceptions keep their local wall-clock times (review F7),
            # so they are matched (and diffed) at their re-based instants
            old_tz, new_tz = self.rebase
            current = [x.model_copy(update={"start": x.start.astimezone(old_tz).replace(tzinfo=new_tz),
                                            "end": x.end.astimezone(old_tz).replace(tzinfo=new_tz)})
                       for x in current]
        for x in current:
            tgt = gcode.get(x.group_id) if x.scope == "group" else lcode.get(x.line_id) if x.scope == "line" else None
            existing[(x.scope, tgt, x.kind, x.start.astimezone(UTC))] = x
        seen: dict[Any, int] = {}
        self._exception_rows(existing, seen, gcode, lcode)
        if self.rebase is not None and current:
            ups = {c.id: c for c in self.changes if c.table == "calendar_exceptions" and c.action == "update"}
            for x in sorted(current, key=lambda x: x.id):
                c = ups.get(x.id)
                if c is None:
                    self.add("calendar_exceptions", "update", x.id, {})
                    c = self.changes[-1]
                c.values.setdefault("start_at", x.start.astimezone(UTC))
                c.values.setdefault("end_at", x.end.astimezone(UTC))
            self.warnings.append({"code": "IMP_EXCEPTIONS_REBASED", "sheet": "plant",
                                  "message": f"The plant UTC offset changes: {len(current)} existing calendar "
                                             "exception(s) keep their local times."})

    def _exception_rows(self, existing: dict[tuple[Any, ...], Any], seen: dict[Any, int], gcode: dict[str, str],
                        lcode: dict[str, str]) -> None:
        for row, src in self.rows("calendar_exceptions"):
            if not self.required("calendar_exceptions", row, src, False):
                continue
            scope = row["scope"]
            code = row.get("target_code")
            tgt = None
            if scope in ("group", "line"):
                if _blank(code):
                    self.err("calendar_exceptions", src, "target_code", "IMP_REQUIRED", msg.required("target_code"))
                    continue
                tgt = self.resolve("calendar_exceptions", src, "target_code",
                                   self.groups if scope == "group" else self.lines, code,
                                   "Stage" if scope == "group" else "Line")
                if tgt is None:
                    continue
            elif not _blank(code):
                self.err("calendar_exceptions", src, "target_code", "IMP_BAD_VALUE",
                         "A plant-wide exception has no target code.")
                continue
            try:
                start = _to_aware(row["start"], self.tz)
            except (ValueError, TypeError):
                self.err("calendar_exceptions", src, "start", "IMP_BAD_DATE", msg.bad_datetime(row["start"]))
                continue
            tcode = str(code).strip() if tgt is not None else None
            key = (scope, tcode, row["kind"], start.astimezone(UTC))
            if not self.dedupe("calendar_exceptions", src, seen, key, f"exception {scope}/{tcode or ''}/{start}"):
                continue
            ex = existing.get(key)
            creating = ex is None
            base = _data(ex) if ex else {}
            d = dict(base)
            d.update(scope=scope, kind=row["kind"], start=start, group_id=tgt.id if scope == "group" else None,
                     line_id=tgt.id if scope == "line" else None)
            if "end" in row:
                if _blank(row["end"]):
                    if creating:
                        self.err("calendar_exceptions", src, "end", "IMP_REQUIRED", msg.required("end"))
                        continue
                else:
                    try:
                        d["end"] = _to_aware(row["end"], self.tz, end=True)
                    except (ValueError, TypeError):
                        self.err("calendar_exceptions", src, "end", "IMP_BAD_DATE", msg.bad_datetime(row["end"]))
                        continue
            elif creating:
                self.err("calendar_exceptions", src, "end", "IMP_REQUIRED", msg.required("end"))
                continue
            if "label" in row:
                d["label"] = "" if _blank(row["label"]) else str(row["label"]).strip()
            inp = self.validate("calendar_exceptions", src, CalendarExceptionInput, d,
                                {"group_id": "target_code", "line_id": "target_code"})
            if inp is None:
                continue
            new = inp.model_dump()
            k = {"scope": scope, "target_code": tcode, "kind": row["kind"], "start": start}
            cols = {"scope": new["scope"], "group_id": new["group_id"], "line_id": new["line_id"],
                    "kind": new["kind"], "start_at": new["start"].astimezone(UTC),
                    "end_at": new["end"].astimezone(UTC), "label": new["label"]}
            if creating:
                self.add("calendar_exceptions", "create", self.nid("cex_"), cols)
                self.note("calendar_exceptions", "create", k)
                continue
            ch = self.diff(base, new, ("end", "label"))
            if ch:
                self.add("calendar_exceptions", "update", ex.id,
                         {("end_at" if f == "end" else f): cols["end_at" if f == "end" else f] for f in ch})
            self.note("calendar_exceptions", "update" if ch else "unchanged", k, ch)

    # ------------------------------------------------------------ operators

    def operator_sheet(self) -> None:
        def extra(d: dict[str, Any], src: Source, creating: bool, row: dict[str, Any]) -> bool:
            ok = True
            if "skills" in row:
                ids = []
                for c in row["skills"] or []:
                    e = self.resolve("operators", src, "skills", self.skills, c, "Skill")
                    if e is None:
                        ok = False
                    else:
                        ids.append(e.id)
                d["skill_ids"] = sorted(set(ids))
            for f, table, target, what in (("shift_template_code", self.templates, "shift_template_id",
                                            "Shift template"),
                                           ("home_group_code", self.groups, "home_group_id", "Stage")):
                if f in row:
                    if _blank(row[f]):
                        d[target] = None
                    else:
                        e = self.resolve("operators", src, f, table, row[f], what)
                        if e is None:
                            ok = False
                        else:
                            d[target] = e.id
            if ok and d.get("shift_names"):
                tpl = next((e for e in self.templates.values() if e.id == d.get("shift_template_id")), None)
                ok = self.shift_names_ok("operators", src, tpl, d["shift_names"])
            return ok

        def columns(new: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in new.items() if k != "skill_ids"}

        existing = {o.code: o for o in self.ds.operators.values()}
        table = {c: _Ent(o.id, _data(o), False) for c, o in existing.items()}
        self.simple("operators", OperatorInput, table, "operators", "emp_", self.ds.operators, extra,
                    rename={"skills": "skill_ids", "shift_template_code": "shift_template_id",
                            "home_group_code": "home_group_id"}, columns=columns)

    # ------------------------------------------------------------ BOMs and routings

    def documents(self, kind: str) -> None:
        is_bom = kind == "boms"
        head_sheet, child_sheet = ("boms", "bom_lines") if is_bom else ("routings", "operations")
        pn_field = "parent_part_number" if is_bom else "part_number"
        existing_docs = self.ds.boms if is_bom else self.ds.routings
        by_key: dict[tuple[Any, ...], Any] = {}
        by_item_rev: dict[tuple[Any, ...], list[Any]] = {}
        for d in existing_docs.values():
            k = (d.item_id, d.revision, d.version) if is_bom else (d.item_id, d.revision, d.code, d.version)
            by_key[k] = d
            by_item_rev.setdefault(k[:-1], []).append(d)
        heads: dict[tuple[Any, ...], tuple[dict[str, Any], Source]] = {}
        kids: dict[tuple[Any, ...], list[tuple[dict[str, Any], Source]]] = {}
        order: list[tuple[Any, ...]] = []

        def key_of(sheet: str, row: dict[str, Any], src: Source) -> tuple[Any, ...] | None:
            pn = row.get(pn_field)
            if _blank(pn):
                self.err(sheet, src, pn_field, "IMP_REQUIRED", msg.required(pn_field))
                return None
            e = self.resolve(sheet, src, pn_field, self.items, pn, "Part number")
            if e is None:
                return None
            rev = row.get("revision")
            rev = e.data["revision"] if _blank(rev) else str(rev).strip()
            ver = row.get("version")
            ver = "AUTO" if ver is None else ver
            if is_bom:
                return (e.id, rev, ver)
            code = row.get("code")
            return (e.id, rev, "STD" if _blank(code) else str(code).strip(), ver)

        for row, src in self.rows(head_sheet):
            k = key_of(head_sheet, row, src)
            if k is None:
                continue
            if k in heads:
                self.err(head_sheet, src, pn_field, "IMP_DUPLICATE_KEY",
                         msg.duplicate_key(self.doc_label(k), heads[k][1].row))
                continue
            heads[k] = (row, src)
            if k not in order:
                order.append(k)
        for row, src in self.rows(child_sheet):
            k = key_of(child_sheet, row, src)
            if k is None:
                continue
            kids.setdefault(k, []).append((row, src))
            if k not in order:
                order.append(k)
        child_present = child_sheet in self.b
        resolved: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        for k in order:
            if k[-1] != "AUTO":
                resolved[k] = k
                continue
            docs = by_item_rev.get(k[:-1], [])
            drafts = [d.version for d in docs if d.status == "draft"]
            if drafts:
                resolved[k] = k[:-1] + (max(drafts),)
            elif not docs:
                resolved[k] = k[:-1] + (1,)
            else:
                top = max(docs, key=lambda d: d.version)
                trial = self.plan_doc(kind, k[:-1] + (top.version,), heads.get(k), kids.get(k, []), top,
                                      child_present, dry=True)
                resolved[k] = k[:-1] + (top.version if not trial else max(d.version for d in docs) + 1,)
        done: set[tuple[Any, ...]] = set()
        for k in order:
            rk = resolved[k]
            if rk in done:
                src = (heads.get(k) or kids[k][0])[1]
                self.err(head_sheet, src, "version", "IMP_DUPLICATE_KEY", msg.duplicate_key(self.doc_label(rk), None))
                continue
            done.add(rk)
            self.plan_doc(kind, rk, heads.get(k), kids.get(k, []), by_key.get(rk), child_present, dry=False)

    def doc_label(self, k: tuple[Any, ...]) -> str:
        pn = self.item_by_id.get(k[0], k[0])
        if len(k) == 3:
            return f"BOM {pn} rev {k[1]} v{k[2]}"
        return f"routing {pn} rev {k[1]} {k[2]} v{k[3]}"

    def plan_doc(self, kind: str, k: tuple[Any, ...], head: tuple[dict[str, Any], Source] | None,
                 kid_rows: list[tuple[dict[str, Any], Source]], existing: Any, child_present: bool, *, dry: bool
                 ) -> bool:
        """Plan one BOM/routing document. `dry=True`: only answer whether it would change (nothing recorded)."""
        is_bom = kind == "boms"
        head_sheet, child_sheet = ("boms", "bom_lines") if is_bom else ("routings", "operations")
        saved = (len(self.changes), len(self.errors), dict((s, dict(c)) for s, c in self.counts.items()),
                 len(self.sample), set(self.err_rows))
        hrow, hsrc = head if head else ({}, kid_rows[0][1])
        item_id = k[0]
        pn = self.item_by_id.get(item_id, item_id)
        item = self.items[pn].data
        label = self.doc_label(k)
        creating = existing is None
        ok = True
        if is_bom and item["make_buy"] == "buy":
            self.err(head_sheet, hsrc, "parent_part_number", "IMP_BAD_VALUE",
                     f"{pn} is a buy item and cannot have a BOM (MFG_ITEM_NOT_MAKE).")
            ok = False
        if not is_bom and item["make_buy"] != "make":
            self.err(head_sheet, hsrc, "part_number", "IMP_BAD_VALUE",
                     f"{pn} is not a make item and cannot have a routing (MFG_ITEM_NOT_MAKE).")
            ok = False
        # header
        hdr_fields = DOC_HEADER_FIELDS + (() if is_bom else ("priority",))
        base = {f: getattr(existing, f) for f in hdr_fields} if existing else {}
        model = BomInput if is_bom else RoutingInput
        hdr = self.merge(base, hrow, model, creating, hdr_fields)
        status = "draft"
        if creating:
            st = hrow.get("status")
            status = st if not _blank(st) else ("released" if self.o.release else "draft")
            if hdr.get("effective_from") is None and self.o.default_effective_from is not None:
                hdr["effective_from"] = self.o.default_effective_from
        else:
            status = existing.status
        if hdr.get("serial_from") is not None and not item["serialized"]:
            self.err(head_sheet, hsrc, "serial_from", "IMP_BAD_VALUE",
                     f"{pn} is not serialized, so the document cannot have a serial range (MFG_SERIAL_NOT_ALLOWED).")
            ok = False
        ident = {"item_id": item_id, "revision": k[1], "version": k[-1]}
        if not is_bom:
            ident["code"] = k[2]
        try:
            hv = model.model_validate({**ident, **hdr})
            hdr = {f: getattr(hv, f) for f in hdr_fields}
        except ValidationError as exc:
            self.pyd_errors(head_sheet, hsrc, exc)
            ok = False
        # children
        if is_bom:
            finals, deletes, child_ok, kid_changes = self.plan_lines(k, item_id, existing, kid_rows, child_present)
        else:
            finals, deletes, child_ok, kid_changes = self.plan_ops(k, existing, kid_rows, child_present)
        ok = ok and child_ok
        hdr_changes = self.diff(base, hdr, hdr_fields) if existing else {}
        changed = creating or bool(hdr_changes) or any(c[0] != "unchanged" for c in kid_changes)
        if dry:
            self._restore(saved)
            return changed
        if existing is not None and existing.status != "draft" and changed:
            self.err(head_sheet, hsrc, None, "IMP_RELEASED_READONLY",
                     msg.released_readonly("BOM" if is_bom else "Routing", label))
            ok = False
        if not ok:
            self._drop_since(saved)
            return changed
        if status not in ("draft", "released", "obsolete"):
            status = "draft"
        doc_id = existing.id if existing else self.nid("bom_" if is_bom else "rtg_")
        key = {("parent_part_number" if is_bom else "part_number"): pn, "revision": k[1], "version": k[-1]}
        if not is_bom:
            key["code"] = k[2]
        table = "boms" if is_bom else "routings"
        if creating:
            vals = {**ident, **hdr, "status": "draft" if status == "released" else status}
            self.add(table, "create", doc_id, vals)
            self.note(head_sheet, "create", key)
            if status == "released":
                self.to_release.append((kind, doc_id, hsrc, label))
        elif head is not None or hdr_changes:
            if hdr_changes:
                self.add(table, "update", doc_id, {f: hdr[f] for f in hdr_changes})
            self.note(head_sheet, "update" if hdr_changes else "unchanged", key, hdr_changes)
        child_table = "bom_lines" if is_bom else "operations"
        for action, cid, values, ckey, cfields in kid_changes:
            if action == "create":
                values = {("bom_id" if is_bom else "routing_id"): doc_id, **values}
            if action != "unchanged":
                self.add(child_table, action, cid, values)
            self.note(child_sheet, action, {**key, **ckey}, cfields)
            if not is_bom and action in ("create", "update"):
                self.tool_changes(cid, values.get("__tools__"))
        for c in self.changes:
            c.values.pop("__tools__", None)
        if kid_changes and any(a != "unchanged" for a, *_ in kid_changes):
            self.bump[table].add(doc_id)
        final = (ident | hdr, finals, status)
        (self.planned_boms if is_bom else self.planned_routings)[doc_id] = final
        if is_bom:
            for ln, src in finals:
                if src is not None:
                    self.line_src.setdefault((item_id, ln["child_item_id"]), src)
        return changed

    def _restore(self, saved: tuple[Any, ...]) -> None:
        n_ch, n_err, counts, n_sample, err_rows = saved
        del self.changes[n_ch:]
        del self.errors[n_err:]
        self.counts = counts
        del self.sample[n_sample:]
        self.err_rows = err_rows

    def _drop_since(self, saved: tuple[Any, ...]) -> None:
        """Keep the errors of a failed document, drop its changes/samples."""
        n_ch, _n_err, _counts, n_sample, _err_rows = saved
        del self.changes[n_ch:]
        del self.sample[n_sample:]

    def plan_lines(self, k: tuple[Any, ...], item_id: str, existing: BomRecord | None,
                   rows: list[tuple[dict[str, Any], Source]], child_present: bool
                   ) -> tuple[list[tuple[dict[str, Any], Source | None]], list[str], bool, list[tuple[Any, ...]]]:
        old: dict[tuple[str, str], BomLineRecord] = {}
        for ln in (existing.lines if existing else []):
            old[(ln.find_number, ln.child_item_id)] = ln
        fields = [f for f in SHEETS_BY_NAME["bom_lines"].fields
                  if f not in ("parent_part_number", "revision", "version", "find_number", "child_part_number")]
        ok = True
        seen: dict[tuple[str, str], int] = {}
        alt_seen: dict[tuple[str, str], int] = {}
        final: dict[tuple[str, str], tuple[dict[str, Any], Source | None]] = {}
        changes: list[tuple[Any, ...]] = []
        for i, (row, src) in enumerate(rows):
            cpn = row.get("child_part_number")
            if _blank(cpn):
                self.err("bom_lines", src, "child_part_number", "IMP_REQUIRED", msg.required("child_part_number"))
                ok = False
                continue
            child = self.resolve("bom_lines", src, "child_part_number", self.items, cpn, "Part number")
            if child is None:
                ok = False
                continue
            fn = row.get("find_number")
            fn = str((i + 1) * 10) if _blank(fn) else str(fn).strip()
            lk = (fn, child.id)
            if lk in seen:
                self.err("bom_lines", src, "find_number", "IMP_DUPLICATE_KEY",
                         msg.duplicate_key(f"find number {fn} / {cpn}", seen[lk]))
                ok = False
                continue
            seen[lk] = src.row
            if child.id == item_id:
                self.err("bom_lines", src, "child_part_number", "IMP_BOM_CYCLE",
                         msg.cycle(f"{cpn} -> {cpn}"))
                ok = False
                continue
            o = old.get(lk)
            creating = o is None
            if creating and _blank(row.get("qty_per")):
                self.err("bom_lines", src, "qty_per", "IMP_REQUIRED", msg.required("qty_per"))
                ok = False
                continue
            base = _data(o) if o else {}
            base.pop("id", None)
            d = self.merge(base, row, BomLineInput, creating, fields)
            d.update(find_number=fn, child_item_id=child.id)
            if d.get("uom") is None:
                d["uom"] = o.uom if o is not None else child.data["uom"]
            inp = self.validate("bom_lines", src, BomLineInput, d, {"child_item_id": "child_part_number"})
            if inp is None:
                ok = False
                continue
            new = inp.model_dump()
            new.pop("id", None)
            if new.get("alt_group") is not None:
                ak = (new["alt_group"], child.id)
                if ak in alt_seen:
                    self.err("bom_lines", src, "alt_group", "IMP_BAD_VALUE",
                             f"Alternate group {new['alt_group']} lists {cpn} twice (also row {alt_seen[ak]}).")
                    ok = False
                    continue
                alt_seen[ak] = src.row
            final[lk] = (new, src)
            ckey = {"find_number": fn, "child_part_number": str(cpn).strip()}
            if creating:
                changes.append(("create", self.nid("bml_"), new, ckey, None))
            else:
                oldd = _data(o)
                ch = self.diff(oldd, new, new.keys())
                changes.append(("update" if ch else "unchanged", o.id, {f: new[f] for f in ch}, ckey, ch))
        deletes: list[str] = []
        replace = self.o.replace_children and child_present
        for lk, o in old.items():
            if lk in final:
                continue
            if replace:
                deletes.append(o.id)
                changes.append(("delete", o.id, {}, {"find_number": o.find_number,
                                                     "child_part_number": self.item_by_id.get(o.child_item_id, "?")},
                                None))
            else:
                d = _data(o)
                d.pop("id", None)
                final[lk] = (d, None)
        return list(final.values()), deletes, ok, changes

    def plan_ops(self, k: tuple[Any, ...], existing: RoutingRecord | None, rows: list[tuple[dict[str, Any], Source]],
                 child_present: bool) -> tuple[list[tuple[dict[str, Any], Source | None]], list[str], bool,
                                               list[tuple[Any, ...]]]:
        old: dict[int, OperationRecord] = {op.seq: op for op in (existing.operations if existing else [])}
        fields = [f for f in SHEETS_BY_NAME["operations"].fields
                  if f not in ("part_number", "revision", "code", "version", "seq", "group_code", "skill_code",
                               "tools")]
        ok = True
        seen: dict[int, int] = {}
        final: dict[int, tuple[dict[str, Any], Source | None]] = {}
        changes: list[tuple[Any, ...]] = []
        for row, src in rows:
            seq = row.get("seq")
            if seq is None:
                self.err("operations", src, "seq", "IMP_REQUIRED", msg.required("seq"))
                ok = False
                continue
            if seq in seen:
                self.err("operations", src, "seq", "IMP_DUPLICATE_KEY",
                         msg.duplicate_key(f"operation {seq}", seen[seq]))
                ok = False
                continue
            seen[seq] = src.row
            o = old.get(seq)
            creating = o is None
            if creating and not self.required("operations", row, src, True):
                ok = False
                continue
            base = _data(o) if o else {}
            base.pop("id", None)
            d = self.merge(base, row, OperationInput, creating, fields)
            d["seq"] = seq
            row_ok = True
            if "group_code" in row and not _blank(row["group_code"]):
                g = self.resolve("operations", src, "group_code", self.groups, row["group_code"], "Stage")
                if g is None:
                    row_ok = False
                else:
                    d["group_id"] = g.id
            if "skill_code" in row:
                if _blank(row["skill_code"]):
                    d["skill_id"] = None
                else:
                    s = self.resolve("operations", src, "skill_code", self.skills, row["skill_code"], "Skill")
                    if s is None:
                        row_ok = False
                    else:
                        d["skill_id"] = s.id
            if "tools" in row:
                tools = []
                for t in row["tools"] or []:
                    try:
                        code, q = parse_tool(t)
                    except ValueError:
                        self.err("operations", src, "tools", "IMP_BAD_VALUE",
                                 f"Tool {t!r} is not CODE or CODE:QUANTITY.")
                        row_ok = False
                        continue
                    p = self.resolve("operations", src, "tools", self.pools, code, "Tool pool")
                    if p is None:
                        row_ok = False
                    else:
                        tools.append({"tool_pool_id": p.id, "qty": q})
                d["tools"] = tools
            if not row_ok:
                ok = False
                continue
            inp = self.validate("operations", src, OperationInput, d,
                                {"group_id": "group_code", "skill_id": "skill_code", "tool_pool_id": "tools"})
            if inp is None:
                ok = False
                continue
            new = inp.model_dump()
            new.pop("id", None)
            final[seq] = (new, src)
            ckey = {"seq": seq}
            cols = {f: v for f, v in new.items() if f != "tools"}
            if creating:
                changes.append(("create", self.nid("opr_"), {**cols, "__tools__": (None, new["tools"])}, ckey, None))
            else:
                oldd = _data(o)
                oldd.pop("id", None)
                ch = self.diff(oldd, new, new.keys())
                values = {f: new[f] for f in ch if f != "tools"}
                if "tools" in ch:
                    values["__tools__"] = (o, new["tools"])
                changes.append(("update" if ch else "unchanged", o.id, values, ckey, ch))
        replace = self.o.replace_children and child_present
        deletes: list[str] = []
        for seq, o in old.items():
            if seq in final:
                continue
            if replace:
                deletes.append(o.id)
                changes.append(("delete", o.id, {}, {"seq": seq}, None))
            else:
                d = _data(o)
                d.pop("id", None)
                final[seq] = (d, None)
        return list(final.values()), deletes, ok, changes

    def tool_changes(self, op_id: str, spec: tuple[Any, list[dict[str, Any]]] | None) -> None:
        if spec is None:
            return
        old_op, tools = spec
        old = {t.tool_pool_id: t for t in (old_op.tools if old_op is not None else [])}
        new = {t["tool_pool_id"]: t["qty"] for t in tools}
        for pid, t in old.items():
            if pid not in new or new[pid] != t.qty:
                self.add("operation_tools", "delete", (op_id, pid), {"operation_id": op_id, "tool_pool_id": pid})
        for pid, q in new.items():
            if pid not in old or old[pid].qty != q:
                self.add("operation_tools", "create", self.nid("otl_"),
                         {"operation_id": op_id, "tool_pool_id": pid, "qty": q})

    # ------------------------------------------------------------ cycles

    def cycles(self) -> None:
        edges: set[tuple[str, str]] = set()
        for b in self.ds.boms.values():
            if b.id in self.planned_boms or b.status == "obsolete":
                continue
            for ln in b.lines:
                edges.add((b.item_id, ln.child_item_id))
        for hdr, finals, status in self.planned_boms.values():
            if status == "obsolete":
                continue
            for ln, _src in finals:
                edges.add((hdr["item_id"], ln["child_item_id"]))
        if not self.line_src:
            return
        for cyc in find_cycles(sorted(edges), key=lambda i: self.item_by_id.get(i, i)):
            path = " -> ".join(self.item_by_id.get(i, i) for i in cyc)
            for a, b in zip(cyc, cyc[1:]):
                src = self.line_src.get((a, b))
                if src is not None:
                    self.err("bom_lines", src, "child_part_number", "IMP_BOM_CYCLE", msg.cycle(path))
                    break

    # ------------------------------------------------------------ releases (documents created as released)

    def releases(self) -> None:
        if not self.to_release:
            return
        planned = self.planned_dataset()
        for kind, doc_id, src, label in self.to_release:
            if kind == "boms":
                issues, _ = bom_release_issues(planned, doc_id, None, False)
            else:
                issues, _ = routing_release_issues(planned, doc_id, None, False)
            if issues:
                sheet = "boms" if kind == "boms" else "routings"
                self.err(sheet, src, None, "IMP_RELEASE_BLOCKED",
                         msg.release_blocked("BOM" if kind == "boms" else "Routing", label,
                                             [f"{i.code}: {i.message}" for i in issues[:3]]))
                continue
            docs = planned.boms if kind == "boms" else planned.routings
            docs[doc_id].status = "released"
            planned.invalidate()
            for c in self.changes:
                if c.table == kind and c.id == doc_id and c.action == "create":
                    c.values["status"] = "released"

    def planned_dataset(self) -> MfgDataset:
        ds = self.ds
        stamp = {"row_version": 1, "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                 "updated_at": datetime(2026, 1, 1, tzinfo=UTC)}
        out = MfgDataset(plant=ds.plant)
        for pn, e in self.items.items():
            if e.id in self.changed_items or e.id not in ds.items:
                out.items[e.id] = ItemRecord.model_construct(**e.data, id=e.id, **stamp, has_bom=False,
                                                             has_routing=False, used_in_count=0)
            else:
                out.items[e.id] = ds.items[e.id].model_copy()
        for table, target, cls, extra in ((self.groups, out.groups, GroupRecord, {"line_count": 0}),
                                          (self.skills, out.skills, SkillRecord,
                                           {"operator_count": 0, "operation_count": 0}),
                                          (self.pools, out.tool_pools, ToolPoolRecord, {"operation_count": 0})):
            for e in table.values():
                target[e.id] = cls.model_construct(**e.data, id=e.id, **stamp, **extra)
        out.lines = dict(ds.lines)
        for b in ds.boms.values():
            if b.id not in self.planned_boms:
                out.boms[b.id] = b.model_copy(update={"lines": [ln.model_copy() for ln in b.lines]})
        for bid, (hdr, finals, status) in self.planned_boms.items():
            lines = [BomLineRecord.model_construct(**{**ln, "id": ln.get("id") or f"bml_{i:032x}"})
                     for i, (ln, _s) in enumerate(finals)]
            out.boms[bid] = BomRecord.model_construct(**hdr, id=bid, status="draft" if status == "released"
                                                      and any(bid == d for _k, d, _s, _l in self.to_release)
                                                      else status, lines=lines, **stamp)
        for r in ds.routings.values():
            if r.id not in self.planned_routings:
                out.routings[r.id] = r.model_copy(update={"operations": [o.model_copy() for o in r.operations]})
        for rid, (hdr, finals, status) in self.planned_routings.items():
            ops = []
            for i, (op, _s) in enumerate(finals):
                od = dict(op)
                od["tools"] = [OperationToolRecord.model_construct(**t) for t in od.get("tools") or []]
                ops.append(OperationRecord.model_construct(**{**od, "id": f"opr_{i:032x}"}))
            out.routings[rid] = RoutingRecord.model_construct(**hdr, id=rid, status="draft" if status == "released"
                                                              and any(rid == d for _k, d, _s, _l in self.to_release)
                                                              else status, operations=ops, **stamp)
        return link(out)


def plan_import(bundle: MfgBundle, ds: MfgDataset, options: ImportOptions | None = None, *,
                sources: dict[str, list[Source]] | None = None, id_factory: IdFactory = default_id_factory
                ) -> ImportPlan:
    """Pure diff of `bundle` against `ds` (see the module docstring). Unknown sheets produce a warning."""
    return _Planner(bundle, ds, options or ImportOptions(), sources or {}, id_factory).run()

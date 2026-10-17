"""Table rows -> draft items for both domains (PHASE2 2.13)."""

from __future__ import annotations

import re

from ..messages import note_text
from ..models import (CellRef, DraftAmount, DraftDebt, DraftDuration, DraftExpense, DraftGoal, DraftHolding,
                      DraftIncome, DraftResource, DraftTask, ExtractContext, FinanceDraft, IntakeError, IntakeNote,
                      Provenance, ScheduleDraft, TableApply)
from ..money.extract import (DEBT_KINDS, EXPENSE_CATS, GOAL_KINDS, HOLDING_CLASS, INCOME_RE, DEBT_RE, GOAL_RE)
from ..schedule.extract import MILESTONE_RE, detect_kind
from ..text.dates import parse_date_text, parse_month_text
from ..text.durations import parse_duration_text
from ..text.names import resolve, slug
from ..text.numbers import frequency_anywhere, parse_money_text, parse_percent_text
from .mapping import fields_of, norm_header
from .parse import parse_rows

PRIORITY_WORDS = {"high": 8, "medium": 5, "med": 5, "low": 3, "urgent": 9, "critical": 10}
FIN_PRIORITY = {"must": "must", "high": "must", "essential": "must", "should": "should", "medium": "should",
                "nice": "nice", "low": "nice", "optional": "nice"}
ROW_KINDS = {"income": "income", "expense": "expense", "goal": "goal", "debt": "debt", "loan": "debt",
             "holding": "holding", "investment": "holding", "savings": "holding", "asset": "holding",
             "spending": "expense", "cost": "expense", "salary": "income"}
_YES = {"yes", "y", "true", "1", "essential", "need", "must"}
_NO = {"no", "n", "false", "0", "optional", "want", "nice"}
_UNIT_HEADERS = {"hours": "hours", "hrs": "hours", "days": "days", "weeks": "weeks", "minutes": "minutes",
                 "mins": "minutes"}


def _validate_mapping(req: TableApply, ncol: int, domain: str) -> dict[str, int]:
    fields = fields_of(domain)  # type: ignore[arg-type]
    out: dict[str, int] = {}
    for m in req.mapping:
        if m.column >= ncol:
            raise IntakeError("BAD_MAPPING", f"Column {m.column + 1} does not exist.", {"column": m.column})
        if m.field is None:
            continue
        if m.field not in fields:
            raise IntakeError("BAD_MAPPING", f"Unknown field {m.field!r}.", {"field": m.field})
        if m.field in out:
            raise IntakeError("BAD_MAPPING", f"The field {m.field!r} is mapped to more than one column.",
                              {"field": m.field})
        out[m.field] = m.column
    if "name" not in out:
        raise IntakeError("BAD_MAPPING", "Choose the column that holds the names.", {"field": "name"})
    return out


def _rows(req: TableApply, max_chars: int) -> tuple[list[str] | None, list[list[str]]]:
    rows = parse_rows(req.text, req.delimiter, max_chars=max_chars)
    header = rows[0] if req.has_header else None
    data = rows[1:] if req.has_header else rows
    ncol = max(len(r) for r in rows)
    return header, [r + [""] * (ncol - len(r)) for r in data]


def _row_note(n: int, text: str) -> IntakeNote:
    return IntakeNote(code="TABLE_ROW", severity="warning", message=note_text("TABLE_ROW", n=n, text=text))


def _prov(row: int, col: int, conf: float = 0.95) -> Provenance:
    return Provenance(source="table", confidence=conf, cell=CellRef(row=row, column=col))


def _next_row_index(keys: set[str]) -> int:
    nums = [int(k[3:]) for k in keys if re.fullmatch(r"row\d+", k)]
    return max(nums) + 1 if nums else 0


def apply_schedule_rows(req: TableApply, ctx: ExtractContext, base: ScheduleDraft | None, *,
                        max_chars: int) -> tuple[ScheduleDraft, list[IntakeNote]]:
    header, data = _rows(req, max_chars)
    ncol = len(data[0]) if data else (len(header) if header else 0)
    fmap = _validate_mapping(req, ncol, "schedule")
    if not data:
        raise IntakeError("TABLE_EMPTY", "The table has no data rows.")
    draft = base.model_copy(deep=True) if base is not None else ScheduleDraft(
        kind=ctx.kind or detect_kind(" ".join(r[fmap["name"]] for r in data[:200]), None), name="Imported plan")
    notes: list[IntakeNote] = []
    unit = req.options.duration_unit
    if header is not None and "duration" in fmap:
        unit = _UNIT_HEADERS.get(norm_header(header[fmap["duration"]]), unit)
    start = _next_row_index({t.key for t in draft.tasks})
    res_by_name = {r.name.lower(): r.key for r in draft.resources}
    created: list[tuple[int, int, DraftTask, list[str]]] = []      # (row, key index, task, predecessor refs)
    ids: dict[str, str] = {}
    for i, row in enumerate(data):
        n = i + 1
        cell = lambda f: row[fmap[f]].strip() if f in fmap else ""  # noqa: E731
        name = cell("name")
        if not name:
            notes.append(_row_note(n, "no name, so the row was skipped."))
            continue
        key = f"row{start + i}"
        if len(created) + len(draft.tasks) >= 500:
            notes.append(_row_note(n, "the draft already has 500 items, so the row was skipped."))
            continue
        prov = draft.provenance
        prov[f"/tasks/{key}/name"] = _prov(i, fmap["name"])
        task = DraftTask(key=key, name=name[:200])
        dur_cell = cell("duration")
        if dur_cell:
            if dur_cell.strip().lower() in ("0", "milestone", "-"):
                task.milestone = True
            else:
                d = parse_duration_text(dur_cell, unit)
                if d is None:
                    notes.append(_row_note(n, f"the duration \"{dur_cell[:40]}\" could not be read."))
                else:
                    task.duration = DraftDuration(optimistic=min(d.optimistic, 10000), likely=min(d.likely, 10000),
                                                  pessimistic=min(d.pessimistic, 10000), unit=d.unit)  # type: ignore
                    prov[f"/tasks/{key}/duration"] = _prov(i, fmap["duration"])
        three = [cell(f) for f in ("optimistic", "likely", "pessimistic")]
        if any(three):
            try:
                vals = [float(x) for x in three if x]
                o = float(three[0]) if three[0] else min(vals)
                p = float(three[2]) if three[2] else max(vals)
                lk = float(three[1]) if three[1] else (o + p) / 2
                o, lk, p = sorted((o, lk, p))
                task.duration = DraftDuration(optimistic=o, likely=lk, pessimistic=p, unit=unit)
                col = fmap.get("likely", fmap.get("optimistic", fmap.get("pessimistic")))
                prov[f"/tasks/{key}/duration"] = _prov(i, col)  # type: ignore[arg-type]
            except ValueError:
                notes.append(_row_note(n, "the three-point estimate could not be read."))
        if task.duration is None and not task.milestone and MILESTONE_RE.search(name) and not dur_cell:
            task.milestone = True
            prov[f"/tasks/{key}/milestone"] = Provenance(source="derived", confidence=0.7,
                                                        note="No duration and the name looks like a milestone")
        for fld in ("deadline", "earliest_start"):
            v = cell(fld)
            if v:
                d = parse_date_text(v, ctx.today, ctx.locale)
                if d is None:
                    notes.append(_row_note(n, f"the date \"{v[:40]}\" could not be read."))
                else:
                    setattr(task, fld, d)
                    prov[f"/tasks/{key}/{fld}"] = _prov(i, fmap[fld])
        pr = cell("priority")
        if pr:
            low = pr.lower()
            val = PRIORITY_WORDS.get(low)
            if val is None and re.fullmatch(r"\d{1,2}", low) and 1 <= int(low) <= 10:
                val = int(low)
            if val is None:
                notes.append(_row_note(n, f"the priority \"{pr[:40]}\" could not be read."))
            else:
                task.priority = val
        if cell("group"):
            task.group = cell("group")[:200]
        if cell("notes"):
            task.notes = cell("notes")[:2000]
        rcell = cell("resources")
        if rcell and not task.milestone:
            kind = "person"
            if header is not None and "resources" in fmap and norm_header(header[fmap["resources"]]) == "machine":
                kind = "machine"
            for nm in [x.strip() for x in re.split(r"[,;/&]|\band\b", rcell) if x.strip()][:20]:
                rk = res_by_name.get(nm.lower())
                if rk is None:
                    rk = "r_" + slug(nm)
                    k = 2
                    base_k = rk
                    while any(r.key == rk for r in draft.resources):
                        rk = f"{base_k[:28]}_{k}"
                        k += 1
                    draft.resources.append(DraftResource(key=rk, name=nm[:200], kind=kind))  # type: ignore[arg-type]
                    res_by_name[nm.lower()] = rk
                if rk not in task.resources:
                    task.resources.append(rk)
            prov[f"/tasks/{key}/resources"] = _prov(i, fmap["resources"])
        if task.milestone:
            task.duration = None
            task.resources = []
        if cell("id"):
            ids[cell("id").lower()] = key
        refs = [x.strip() for x in re.split(r"[,;/]", cell("predecessors")) if x.strip()]
        created.append((i, start + i, task, refs))
    # predecessors: by id, then name, then row number
    names = [(t.key, t.name) for _, _, t, _ in created] + [(t.key, t.name) for t in draft.tasks]
    row_key = {i + 1: t.key for i, _, t, _ in created}
    mode = req.options.predecessor_ref
    for i, _, task, refs in created:
        for ref in refs[:50]:
            target = None
            low = ref.lower()
            if mode in ("auto", "id"):
                target = ids.get(low)
            if target is None and mode in ("auto", "name"):
                exact = [k for k, nm in names if nm.lower() == low and k != task.key]
                target = exact[0] if exact else resolve(ref, names, exclude=task.key).key
            if target is None and mode in ("auto", "row") and re.fullmatch(r"\d{1,4}", ref):
                target = row_key.get(int(ref))
            if target is None or target == task.key:
                notes.append(_row_note(i + 1, f"\"{ref[:40]}\" does not match another row, so that link was left out."))
                continue
            if target not in task.after:
                task.after.append(target)
        if task.after and "predecessors" in fmap:
            draft.provenance[f"/tasks/{task.key}/after"] = _prov(i, fmap["predecessors"])
    draft.tasks.extend(t for _, _, t, _ in created)
    return ScheduleDraft.model_validate(draft.model_dump()), notes


def _infer_kind(name: str) -> str | None:
    if DEBT_RE.search(name):
        return "debt"
    if INCOME_RE.search(name):
        return "income"
    for rx, _, _ in HOLDING_CLASS:
        if rx.search(name):
            return "holding"
    if GOAL_RE.search(name) or any(rx.search(name) for rx, k in GOAL_KINDS if k != "education"):
        return "goal"
    return None


def apply_finance_rows(req: TableApply, ctx: ExtractContext, base: FinanceDraft | None, *,
                       max_chars: int) -> tuple[FinanceDraft, list[IntakeNote]]:
    header, data = _rows(req, max_chars)
    ncol = len(data[0]) if data else (len(header) if header else 0)
    fmap = _validate_mapping(req, ncol, "finance")
    if not data:
        raise IntakeError("TABLE_EMPTY", "The table has no data rows.")
    draft = base.model_copy(deep=True) if base is not None else FinanceDraft(
        start_month=f"{ctx.today.year:04d}-{ctx.today.month:02d}")
    if base is None:
        draft.profile.currency = ctx.currency
        draft.profile.locale = ctx.locale
    notes: list[IntakeNote] = []
    prov = draft.provenance
    for i, row in enumerate(data):
        n = i + 1
        cell = lambda f: row[fmap[f]].strip() if f in fmap else ""  # noqa: E731
        name = cell("name")
        if not name:
            notes.append(_row_note(n, "no name, so the row was skipped."))
            continue
        kind_cell = cell("row_kind").lower()
        kind, kconf = None, 0.95
        if kind_cell:
            kind = ROW_KINDS.get(kind_cell.rstrip("s")) or ROW_KINDS.get(kind_cell)
        if kind is None:
            kind = _infer_kind(name)
            kconf = 0.6
        if kind is None:
            kind = req.options.default_row_kind
            kconf = 0.6
        amt_cell = cell("amount")
        amount = None
        if amt_cell:
            r = parse_money_text(amt_cell)
            if r is None:
                notes.append(_row_note(n, f"the amount \"{amt_cell[:40]}\" could not be read."))
            else:
                amount = DraftAmount(low=r[0], high=r[1])
        freq_cell = cell("frequency")
        freq = frequency_anywhere(freq_cell) if freq_cell else None
        if freq_cell and freq is None:
            low = freq_cell.lower()
            freq = {"month": "monthly", "year": "yearly", "quarter": "quarterly", "one-time": "once"}.get(low)
            if freq is None:
                notes.append(_row_note(n, f"the frequency \"{freq_cell[:40]}\" could not be read."))
        if freq is None and amt_cell:
            freq = frequency_anywhere(amt_cell)
        freq = freq or req.options.amount_frequency
        coll = {"income": "incomes", "expense": "expenses", "goal": "goals", "debt": "debts", "holding": "holdings"}[kind]
        prefix = {"income": "i", "expense": "e", "goal": "g", "debt": "d", "holding": "h"}[kind]
        items = getattr(draft, coll)
        limit = {"incomes": 20, "expenses": 100, "goals": 12, "debts": 20, "holdings": 50}[coll]
        if len(items) >= limit:
            notes.append(_row_note(n, f"the plan already has the most {coll} allowed, so the row was skipped."))
            continue
        keys = {x.key for x in items}
        k = len(items) + 1
        while f"{prefix}{k}" in keys:
            k += 1
        key = f"{prefix}{k}"
        base_path = f"/{coll}/{key}"
        prov[f"{base_path}/name"] = _prov(i, fmap["name"])
        if "row_kind" in fmap or kconf < 0.95:
            prov[f"{base_path}/kind"] = Provenance(source="table", confidence=kconf,
                                                   cell=CellRef(row=i, column=fmap.get("row_kind", fmap["name"])))
        if amount is not None:
            prov[f"{base_path}/{'target' if kind == 'goal' else 'amount' if kind != 'debt' else 'balance'}"] = \
                _prov(i, fmap["amount"])
        if kind == "income":
            items.append(DraftIncome(key=key, name=name[:200], amount=amount, frequency=freq))  # type: ignore
        elif kind == "expense":
            ess_cell = cell("essential").lower()
            essential = True if ess_cell in _YES else False if ess_cell in _NO else None
            cat_cell = cell("category")
            cat, ess_default, infl = "other", None, None
            for rx, cc, ess, inf in EXPENSE_CATS:
                if rx.search(cat_cell or name) or rx.search(name):
                    cat, ess_default, infl = cc, ess, inf
                    break
            items.append(DraftExpense(key=key, name=name[:200], category=(cat_cell or cat)[:64], amount=amount,
                                      frequency=freq, essential=essential if essential is not None else ess_default,
                                      inflation_pct=infl))  # type: ignore[arg-type]
        elif kind == "goal":
            gk = "other"
            for rx, kk in GOAL_KINDS:
                if rx.search(name):
                    gk = kk
                    break
            month = None
            if cell("date"):
                month = parse_month_text(cell("date"), ctx.today, ctx.locale)
                if month is None:
                    notes.append(_row_note(n, f"the date \"{cell('date')[:40]}\" could not be read."))
                else:
                    prov[f"{base_path}/target_month"] = _prov(i, fmap["date"])
            pr = FIN_PRIORITY.get(cell("priority").lower()) if cell("priority") else None
            items.append(DraftGoal(key=key, name=name[:200], kind=gk, target=amount, target_month=month,  # type: ignore
                                   priority=pr, inflation_pct=9.0 if gk == "education" else None))  # type: ignore
        elif kind == "debt":
            dk = "other"
            for rx, kk, _ in DEBT_KINDS:
                if rx.search(name):
                    dk = kk
                    break
            rate = parse_percent_text(cell("interest_rate")) if cell("interest_rate") else None
            if rate is not None and not 0 <= rate <= 60:
                rate = None
            emi = parse_money_text(cell("emi")) if cell("emi") else None
            bal = parse_money_text(cell("balance")) if cell("balance") else None
            balance = DraftAmount(low=bal[0], high=bal[1]) if bal else amount
            items.append(DraftDebt(key=key, name=name[:200], kind=dk, balance=balance,  # type: ignore[arg-type]
                                   interest_rate_pct=rate, emi=DraftAmount(low=emi[0], high=emi[1]) if emi else None))
        else:
            cls = None
            src = cell("asset_class") or name
            for rx, cid, _ in HOLDING_CLASS:
                if rx.search(src):
                    cls = cid
                    break
            items.append(DraftHolding(key=key, name=name[:200], asset_class_id=cls, amount=amount))
    return FinanceDraft.model_validate(draft.model_dump()), notes

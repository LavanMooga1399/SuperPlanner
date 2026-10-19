"""Table import: parse, mapping, apply (PHASE2 2.13; plan P2-8)."""

from __future__ import annotations

import pytest

from intake_helpers import CTX, FIN_CTX, TABLE_TEXT
from superplanner import intake
from superplanner.intake.models import ColumnMapping, TableApply, TableOptions


def suggested(p):
    return [c.suggested_field for c in p.columns]


def apply_req(text, p, **kw) -> TableApply:
    return TableApply(text=text, delimiter=p.delimiter, has_header=p.has_header,
                      mapping=[ColumnMapping(column=c.index, field=c.suggested_field) for c in p.columns], **kw)


def test_example_parse_exact():
    p = intake.parse_table(TABLE_TEXT, "schedule")
    assert p.model_dump() == {
        "delimiter": "\t", "has_header": True, "row_count": 3,
        "columns": [
            {"index": 0, "header": "Task", "samples": ["Requirements", "Design", "Build"], "suggested_field": "name",
             "confidence": 0.95},
            {"index": 1, "header": "Duration", "samples": ["2-3 d", "1 w", "2 w"], "suggested_field": "duration",
             "confidence": 0.95},
            {"index": 2, "header": "After", "samples": ["", "Requirements", "Design"],
             "suggested_field": "predecessors", "confidence": 0.9},
            {"index": 3, "header": "Owner", "samples": ["Priya", "Priya", "Ravi"], "suggested_field": "resources",
             "confidence": 0.9},
            {"index": 4, "header": "Due", "samples": ["", "", "15/12/2026"], "suggested_field": "deadline",
             "confidence": 0.9}],
        "preview": [["Requirements", "2-3 d", "", "Priya", ""], ["Design", "1 w", "Requirements", "Priya", ""],
                    ["Build", "2 w", "Design", "Ravi", "15/12/2026"]],
        "warnings": []}


def test_example_apply():
    p = intake.parse_table(TABLE_TEXT, "schedule")
    r = intake.apply_schedule_table(apply_req(TABLE_TEXT, p), CTX, None)
    t = {x.key: x for x in r.draft.tasks}
    assert list(t) == ["row0", "row1", "row2"]
    assert (t["row0"].duration.optimistic, t["row0"].duration.pessimistic, t["row0"].duration.unit) == (2, 3, "days")
    assert t["row1"].after == ["row0"] and t["row2"].after == ["row1"]
    assert t["row2"].deadline.isoformat() == "2026-12-15"
    assert [x.name for x in r.draft.resources] == ["Priya", "Ravi"]
    assert t["row0"].resources == ["r_priya"] and t["row2"].resources == ["r_ravi"]
    prov = r.draft.provenance["/tasks/row0/duration"]
    assert prov.source == "table" and prov.cell.row == 0 and prov.cell.column == 1 and prov.confidence == 0.95
    assert r.row_notes == [] and r.ready
    b = intake.build_schedule(r.draft, CTX)
    assert b.ready and b.problem.metadata["intake"]["source"] == "table"


@pytest.mark.parametrize("text,delim,header", [
    ("name,duration\n\"Design, phase 1\",2 days\nBuild,3 days", ",", True),
    ("Write docs;2 days\nReview;3 h\nShip;1 d", ";", False),
    ("task|hours\nCut|2\nWeld|3", "|", True),
])
def test_delimiter_and_header_detection(text, delim, header):
    p = intake.parse_table(text, "schedule")
    assert (p.delimiter, p.has_header) == (delim, header)
    assert "name" in suggested(p) and "duration" in suggested(p)


def test_quoted_csv_cell_and_hours_header():
    text = "name,duration\n\"Design, phase 1\",2 days\nBuild,3 days"
    p = intake.parse_table(text, "schedule")
    assert p.preview[0][0] == "Design, phase 1"
    p = intake.parse_table("task|hours\nCut|2\nWeld|3", "schedule")
    r = intake.apply_schedule_table(apply_req("task|hours\nCut|2\nWeld|3", p), CTX, None)
    assert r.draft.tasks[0].duration.unit == "hours" and r.draft.tasks[0].duration.likely == 2


def test_content_based_suggestions_without_header():
    p = intake.parse_table("Write docs;2 days\nReview;3 h\nShip;1 d", "schedule")
    assert suggested(p) == ["name", "duration"]


def test_three_point_columns_and_bare_numbers():
    text = "Task\tMin\tLikely\tMax\nA\t1\t2\t4\nB\t2\t2\t2"
    p = intake.parse_table(text, "schedule")
    assert suggested(p) == ["name", "optimistic", "likely", "pessimistic"]
    r = intake.apply_schedule_table(apply_req(text, p, options=TableOptions(duration_unit="hours")), CTX, None)
    a = r.draft.tasks[0].duration
    assert (a.optimistic, a.likely, a.pessimistic, a.unit) == (1, 2, 4, "hours")


def test_predecessors_by_id_and_row_number():
    text = "ID\tTask\tDuration\tDepends on\nA1\tPlan\t1 d\t\nB2\tBuild\t2 d\tA1\nC3\tTest\t1 d\t2"
    p = intake.parse_table(text, "schedule")
    assert suggested(p) == ["id", "name", "duration", "predecessors"]
    r = intake.apply_schedule_table(apply_req(text, p), CTX, None)
    t = {x.name: x for x in r.draft.tasks}
    assert t["Build"].after == ["row0"] and t["Test"].after == ["row1"]


def test_row_notes_and_skipped_rows():
    text = "Task\tDuration\tDue\nGood\t1 d\t\n\t2 d\t\nOdd\tbanana\tnot a date"
    p = intake.parse_table(text, "schedule")
    r = intake.apply_schedule_table(apply_req(text, p), CTX, None)
    assert [t.name for t in r.draft.tasks] == ["Good", "Odd"]
    msgs = [n.message for n in r.row_notes]
    assert all(n.code == "TABLE_ROW" for n in r.row_notes)
    assert any(m.startswith("Row 2:") for m in msgs) and sum(m.startswith("Row 3:") for m in msgs) == 2
    assert r.draft.tasks[1].duration is None
    assert any(q.code == "SCHED_TASK_DURATION" for q in r.questions)


def test_base_draft_keys_continue():
    p = intake.parse_table(TABLE_TEXT, "schedule")
    first = intake.apply_schedule_table(apply_req(TABLE_TEXT, p), CTX, None)
    again = intake.apply_schedule_table(apply_req(TABLE_TEXT, p), CTX, first.draft)
    keys = [t.key for t in again.draft.tasks]
    assert keys[:3] == ["row0", "row1", "row2"] and len(keys) == 6 and len(set(keys)) == 6
    assert again.draft.tasks[4].after == [keys[3]]
    assert len(again.draft.resources) == 2


@pytest.mark.parametrize("mapping,detail", [
    ([ColumnMapping(column=9, field="name")], {"column": 9}),
    ([ColumnMapping(column=0, field="name"), ColumnMapping(column=1, field="name")], {"field": "name"}),
    ([ColumnMapping(column=1, field="duration")], {"field": "name"}),
])
def test_bad_mapping(mapping, detail):
    with pytest.raises(intake.IntakeError) as e:
        intake.apply_schedule_table(TableApply(text=TABLE_TEXT, delimiter="\t", has_header=True, mapping=mapping),
                                    CTX, None)
    assert e.value.code == "BAD_MAPPING" and e.value.details == detail


def test_limits():
    with pytest.raises(intake.IntakeError) as e:
        intake.parse_table("   \n", "schedule")
    assert e.value.code == "TABLE_EMPTY"
    with pytest.raises(intake.IntakeError) as e:
        intake.parse_table("a\tb\n" * 2002, "schedule")
    assert e.value.code == "TABLE_TOO_LARGE" and e.value.details == {"max_rows": 2000}
    with pytest.raises(intake.IntakeError) as e:
        intake.parse_table("\t".join(["x"] * 31), "schedule")
    assert e.value.code == "TABLE_TOO_LARGE" and e.value.details == {"max_columns": 30}
    with pytest.raises(intake.IntakeError) as e:
        intake.parse_table("x" * 101, "schedule", max_chars=100)
    assert e.value.code == "TABLE_TOO_LARGE" and e.value.details == {"max_chars": 100}


def test_ragged_rows_warning():
    p = intake.parse_table("Task\tDuration\nA\t1 d\nB\t2 d\textra", "schedule")
    assert p.warnings


FIN_CSV = ('name,amount,type,frequency\n"Salary, main",1.2 lakh,income,monthly\nRent,25000,expense,\n'
           'Car,8 lakh,goal,\nFD,3L,holding,\nHome loan,40L,loan,\n,500,expense,\nGym,abc,,')


def test_finance_table_row_kinds():
    p = intake.parse_table(FIN_CSV, "finance")
    assert (p.delimiter, p.has_header) == (",", True)
    assert suggested(p) == ["name", "amount", "row_kind", "frequency"]
    r = intake.apply_finance_table(apply_req(FIN_CSV, p), FIN_CTX, None)
    d = r.draft
    assert [(i.name, i.amount.low) for i in d.incomes] == [("Salary, main", 120000)]
    assert [(e.name, e.category, e.essential) for e in d.expenses] == [("Rent", "living", True),
                                                                       ("Gym", "other", None)]
    assert [(g.name, g.kind, g.target.low) for g in d.goals] == [("Car", "vehicle", 800000)]
    assert [(h.name, h.asset_class_id) for h in d.holdings] == [("FD", "fixed_deposit")]
    assert [(x.name, x.kind, x.balance.low) for x in d.debts] == [("Home loan", "home", 4000000)]
    assert [n.message for n in r.row_notes] == ["Row 6: no name, so the row was skipped.",
                                                'Row 7: the amount "abc" could not be read.']
    assert [i.key for i in d.incomes] == ["row0"] and [e.key for e in d.expenses] == ["row1", "row6"]
    assert d.provenance["/incomes/row0/amount"].source == "table"
    assert d.provenance["/incomes/row0/amount"].cell.model_dump() == {"row": 0, "column": 1}


def test_finance_row_kind_inferred_from_name():
    text = "Item\tAmount\nSalary\t90000\nGroceries\t12000\nCar loan EMI\t8000\nSave for a house\t20 lakh"
    p = intake.parse_table(text, "finance")
    r = intake.apply_finance_table(apply_req(text, p), FIN_CTX, None)
    d = r.draft
    assert [i.name for i in d.incomes] == ["Salary"]
    assert [e.name for e in d.expenses] == ["Groceries"]
    (debt,) = d.debts
    assert debt.emi.low == 8000 and debt.balance is None            # "EMI" in the name
    assert any(q.code == "FIN_DEBT_BALANCE" for q in r.questions)
    assert [g.kind for g in d.goals] == ["home"]
    assert d.provenance["/incomes/row0/kind"].confidence == 0.6     # row kind inferred from the name
    base = intake.apply_finance_table(apply_req(text, p), FIN_CTX, d)
    assert [i.key for i in base.draft.incomes] == ["row0", "row4"]

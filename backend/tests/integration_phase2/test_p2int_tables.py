"""CSV / paste import edge cases end to end (PHASE2 2.13; plan P2-8, P3b-6 backend side).

parse -> apply (suggested or changed mapping) -> questions -> build -> create -> solve/run, with the
independent schedule checker on the solved schedule.
"""

from __future__ import annotations

import pytest

from p2_helpers import API, CTX_JSON, FIN, FIN_CTX_JSON, IN, solve_and_check, wait_fin_run


def parse(c, dom, text, **kw):
    r = c.post(f"{IN}/{dom}/table/parse", json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def suggested(p):
    return [{"column": x["index"], "field": x["suggested_field"]} for x in p["columns"]]


def apply(c, dom, text, p, mapping=None, ctx=None, status=200, **extra):
    body = {"text": text, "delimiter": p["delimiter"], "has_header": p["has_header"],
            "mapping": suggested(p) if mapping is None else mapping,
            "context": ctx or (CTX_JSON if dom == "schedule" else FIN_CTX_JSON), **extra}
    r = c.post(f"{IN}/{dom}/table/apply", json=body)
    assert r.status_code == status, r.text
    return r.json()


def finish_schedule(c, body):
    """Accept every suggestion, build, then create + solve + independent check."""
    draft, qs = body["draft"], body["questions"]
    for _ in range(5):
        if not qs:
            break
        r = c.post(f"{IN}/schedule/answer", json={"draft": draft, "context": CTX_JSON, "answers": [
            {"question_id": q["id"], "use_default": True} if q.get("default") is not None else
            {"question_id": q["id"], "value": {"text": "1 day"}} for q in qs]})
        assert r.status_code == 200, r.text
        draft, qs = r.json()["draft"], r.json()["questions"]
    b = c.post(f"{IN}/schedule/build", json={"draft": draft, "context": CTX_JSON}).json()
    assert b["ready"], b
    assert b["problem"]["metadata"]["intake"]["source"] == "table"
    return b, solve_and_check(c, b["problem"], strategy="auto")


SPEC_TSV = ("Task\tDuration\tAfter\tOwner\tDue\nRequirements\t2-3 d\t\tPriya\t\nDesign\t1 w\tRequirements\tPriya\t\n"
            "Build\t2 w\tDesign\tRavi\t15/12/2026")


def test_spec_tsv_parse_apply_build_solve(client):
    p = parse(client, "schedule", SPEC_TSV)
    assert p["delimiter"] == "\t" and p["has_header"] and p["row_count"] == 3
    assert [c["suggested_field"] for c in p["columns"]] == ["name", "duration", "predecessors", "resources", "deadline"]
    body = apply(client, "schedule", SPEC_TSV, p)
    tasks = {t["key"]: t for t in body["draft"]["tasks"]}
    assert list(tasks) == ["row0", "row1", "row2"]
    assert tasks["row1"]["after"] == ["row0"] and tasks["row2"]["after"] == ["row1"]
    assert tasks["row2"]["deadline"] == "2026-12-15"
    b, (rec, run, sch) = finish_schedule(client, body)
    assert b["duration_summary"]["tasks_with_range"] == 1


def test_changed_mapping_ignore_column(client):
    p = parse(client, "schedule", SPEC_TSV)
    m = suggested(p)
    m[3]["field"] = None                      # ignore Owner
    body = apply(client, "schedule", SPEC_TSV, p, mapping=m)
    assert all(t["resources"] == [] for t in body["draft"]["tasks"])
    assert body["draft"]["resources"] == []
    finish_schedule(client, body)


def test_csv_with_bom_crlf_and_quoted_commas(client):
    text = '﻿Task,Duration,Predecessors\r\n"Design, phase 1",2 days,\r\nBuild,"3-5 days","Design, phase 1"\r\n'
    p = parse(client, "schedule", text)
    assert p["delimiter"] == "," and p["row_count"] == 2
    assert p["columns"][0]["suggested_field"] == "name"
    body = apply(client, "schedule", text, p)
    t = body["draft"]["tasks"]
    assert t[0]["name"] == "Design, phase 1"
    assert t[1]["after"] == ["row0"]
    assert (t[1]["duration"]["optimistic"], t[1]["duration"]["pessimistic"]) == (3, 5)
    finish_schedule(client, body)


def test_escaped_quotes_and_unicode_names(client):
    text = 'Task,Duration\n"He said ""go""",1 d\nडिज़ाइन समीक्षा,2 d\n'
    body = apply(client, "schedule", text, parse(client, "schedule", text))
    assert [t["name"] for t in body["draft"]["tasks"]] == ['He said "go"', "डिज़ाइन समीक्षा"]


@pytest.mark.parametrize("text,delim", [
    ("Task;Duration;Owner\nPlan;1 d;Asha\nDo;2 d;Asha\n", ";"),
    ("Task|Hours|After\nCut|3|\nWeld|2|Cut\n", "|"),
    ("Task\tDuration\t\nA\t1 d\t\nB\t2 d\t\n", "\t"),          # Excel paste with a trailing tab
    ("\n\nTask,Duration\n\nA,1 d\n\n\nB,2 d\n\n", ","),       # blank lines around and between rows
])
def test_delimiters_and_blank_lines(client, text, delim):
    p = parse(client, "schedule", text)
    assert p["delimiter"] == delim and p["row_count"] == 2
    body = apply(client, "schedule", text, p)
    assert len(body["draft"]["tasks"]) == 2
    assert all(t["duration"] is not None for t in body["draft"]["tasks"])


def test_hours_header_overrides_unit_and_pipe_predecessor(client):
    text = "Task|Hours|After\nCut|3|\nWeld|2|Cut\n"
    body = apply(client, "schedule", text, parse(client, "schedule", text), options={"duration_unit": "days"})
    t = body["draft"]["tasks"]
    assert t[0]["duration"]["unit"] == "hours" and t[0]["duration"]["likely"] == 3
    assert t[1]["after"] == ["row0"]


def test_headerless_content_suggestions(client):
    text = "Prepare slides\t2 days\t15/12/2026\nRehearse talk\t3 hours\t16/12/2026\n"
    p = parse(client, "schedule", text)
    assert p["has_header"] is False
    assert [c["suggested_field"] for c in p["columns"]] == ["name", "duration", "deadline"]
    body = apply(client, "schedule", text, p)
    assert [t["deadline"] for t in body["draft"]["tasks"]] == ["2026-12-15", "2026-12-16"]


def test_ids_row_numbers_unknown_refs_skipped_rows_priority_groups(client):
    text = ("ID,Task,Duration,Depends on,Priority,Phase\nA1,Survey,2 d,,high,Prep\nA2,Design,3 d,A1,medium,Prep\n"
            "A3,Build,5 d,\"A2; 1\",low,Exec\nA4,Test,2 d,Ghost,9,Exec\nA5,,1 d,A4,,\nA6,Test,1 d,A3,,Exec\n")
    body = apply(client, "schedule", text, parse(client, "schedule", text))
    t = {x["key"]: x for x in body["draft"]["tasks"]}
    assert "row4" not in t                                   # nameless row skipped
    assert t["row1"]["after"] == ["row0"] and set(t["row2"]["after"]) == {"row0", "row1"}
    assert t["row3"]["after"] == [] and t["row5"]["after"] == ["row2"]
    assert [t[k]["priority"] for k in ("row0", "row1", "row2", "row3")] == [8, 5, 3, 9]
    assert t["row0"]["group"] == "Prep"
    notes = [n["message"] for n in body["row_notes"]]
    assert any(m.startswith("Row 5:") for m in notes) and any("Ghost" in m for m in notes)
    assert all(n["code"] == "TABLE_ROW" for n in body["row_notes"])
    finish_schedule(client, body)


def test_three_point_columns_and_bad_cells(client):
    text = "Task,Optimistic,Most likely,Pessimistic,Due\nA,1,2,4,31/12/2026\nB,1,2,3,not a date\n"
    body = apply(client, "schedule", text, parse(client, "schedule", text), options={"duration_unit": "hours"})
    a, b = body["draft"]["tasks"]
    assert (a["duration"]["optimistic"], a["duration"]["likely"], a["duration"]["pessimistic"]) == (1, 2, 4)
    assert a["duration"]["unit"] == "hours" and a["deadline"] == "2026-12-31"
    assert b["deadline"] is None
    assert any("not a date" in n["message"] for n in body["row_notes"])
    built, _ = finish_schedule(client, body)
    est = next(x for x in built["problem"]["tasks"] if x["name"].startswith("A"))["duration_estimate"]
    assert est == {"optimistic_minutes": 60, "likely_minutes": 120, "pessimistic_minutes": 240}


def test_base_draft_append_continues_keys(client):
    p = parse(client, "schedule", SPEC_TSV)
    first = apply(client, "schedule", SPEC_TSV, p)
    second = apply(client, "schedule", SPEC_TSV, p, base=first["draft"])
    assert [t["key"] for t in second["draft"]["tasks"]] == ["row0", "row1", "row2", "row3", "row4", "row5"]


@pytest.mark.parametrize("text,code,detail", [
    ("   \n  ", "TABLE_EMPTY", None),
    ("Task,Duration\n" + "".join(f"T{i},1 d\n" for i in range(2001)), "TABLE_TOO_LARGE", "max_rows"),
    (",".join(f"c{i}" for i in range(31)) + "\n" + ",".join("x" for _ in range(31)) + "\n", "TABLE_TOO_LARGE",
     "max_columns"),
])
def test_parse_limits(client, text, code, detail):
    r = client.post(f"{IN}/schedule/table/parse", json={"text": text})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == code
    if detail:
        assert detail in err["details"]


def test_table_text_over_one_million_chars(client):
    r = client.post(f"{IN}/finance/table/parse", json={"text": "a" * 1_000_001})
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("TABLE_TOO_LARGE", "VALIDATION_ERROR")


def test_header_only_table_apply_is_table_empty(client):
    text = "Task,Duration\n"
    p = parse(client, "schedule", text)
    assert p["row_count"] == 0
    err = apply(client, "schedule", text, p, status=422)["error"]
    assert err["code"] == "TABLE_EMPTY"


@pytest.mark.parametrize("mapping", [
    [{"column": 0, "field": "name"}, {"column": 1, "field": "name"}],
    [{"column": 1, "field": "duration"}],
    [{"column": 0, "field": "name"}, {"column": 9, "field": "duration"}],
    [{"column": 0, "field": "name"}, {"column": 1, "field": "no_such_field"}],
])
def test_bad_mappings(client, mapping):
    p = parse(client, "schedule", SPEC_TSV)
    r = client.post(f"{IN}/schedule/table/apply", json={"text": SPEC_TSV, "delimiter": "\t", "has_header": True,
                                                        "mapping": mapping, "context": CTX_JSON})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] in ("BAD_MAPPING", "VALIDATION_ERROR")


FIN_CSV = ("Type,Item,Amount,Frequency,Essential,Date,Asset,Rate,EMI\n"
           "income,Salary,\"1,20,000\",monthly,,,,,\n"
           "expense,Rent,25000,monthly,yes,,,,\n"
           "expense,Netflix,649,monthly,no,,,,\n"
           "goal,House down payment,15 lakh,,,2030-06,,,\n"
           "loan,Car loan,3L,,,,,9%,10000\n"
           "investment,Mutual funds,8 lakh,,,,equity,,\n"
           "savings,Fixed deposit,\"₹5,00,000\",,,,fixed deposit,,\n"
           ",School fees,18000,quarterly,yes,,,,\n")


def test_finance_csv_rows_kinds_and_plan_runs(client):
    p = parse(client, "finance", FIN_CSV)
    assert p["row_count"] == 8 and not p["warnings"]
    body = apply(client, "finance", FIN_CSV, p)
    d = body["draft"]
    assert [(i["name"], i["amount"]["low"]) for i in d["incomes"]] == [("Salary", 120000)]
    ex = {e["name"]: e for e in d["expenses"]}
    assert ex["Rent"]["essential"] is True and ex["Netflix"]["essential"] is False
    assert ex["School fees"]["frequency"] == "quarterly"           # row kind inferred from the name
    assert d["debts"][0]["balance"]["low"] == 300000 and d["debts"][0]["emi"]["low"] == 10000
    assert d["debts"][0]["interest_rate_pct"] == 9
    h = {x["name"]: x for x in d["holdings"]}
    assert h["Mutual funds"]["asset_class_id"] == "equity_index"
    assert h["Fixed deposit"]["asset_class_id"] == "fixed_deposit" and h["Fixed deposit"]["amount"]["low"] == 500000
    g = d["goals"][0]
    assert g["target"]["low"] == 1500000 and g["target_month"] == "2030-06"
    keys = [x["key"] for coll in ("incomes", "expenses", "debts", "holdings", "goals") for x in d[coll]]
    assert sorted(keys) == sorted(f"row{i}" for i in range(8))
    # answer the rest with defaults (age is the only required question here) and run the plan
    draft, qs = d, body["questions"]
    for _ in range(5):
        if not qs:
            break
        ans = [{"question_id": q["id"], "use_default": True} if q.get("default") is not None
               else {"question_id": q["id"], "value": 35} for q in qs]
        r = client.post(f"{IN}/finance/answer", json={"draft": draft, "answers": ans, "context": FIN_CTX_JSON})
        assert r.status_code == 200, r.text
        draft, qs = r.json()["draft"], r.json()["questions"]
    b = client.post(f"{IN}/finance/build", json={"draft": draft, "context": FIN_CTX_JSON}).json()
    assert b["ready"], b
    r = client.post(f"{FIN}/plans", json=b["plan"])
    assert r.status_code == 201, r.text
    run = client.post(f"{FIN}/plans/{r.json()['id']}/runs", json={"seed": 0, "simulation": {"n_paths": 300}})
    done = wait_fin_run(client, run.json()["run_id"])
    assert done["status"] == "completed" and done["feasibility"] == "feasible"


def test_table_import_writes_nothing_to_the_db(client, db_url):
    import sqlalchemy as sa
    eng = sa.create_engine(db_url)

    def counts():
        with eng.connect() as c:
            return {n: c.execute(sa.text(f'SELECT COUNT(*) FROM "{n}"')).scalar_one()
                    for n in sa.inspect(eng).get_table_names()}
    before = counts()
    p = parse(client, "finance", FIN_CSV)
    apply(client, "finance", FIN_CSV, p)
    p = parse(client, "schedule", SPEC_TSV)
    body = apply(client, "schedule", SPEC_TSV, p)
    client.post(f"{IN}/schedule/build", json={"draft": body["draft"], "context": CTX_JSON})
    assert counts() == before
    eng.dispose()
    assert API

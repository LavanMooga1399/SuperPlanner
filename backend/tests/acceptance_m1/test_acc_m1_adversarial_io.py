"""WP-D adversarial: hostile import files and request bodies against the real API (M1-DESIGN 8.3, R4). Every case
must answer a 4xx envelope (never 500, never hang), stage no control characters or non-finite numbers, and leave
the user's data readable."""

from __future__ import annotations

import io
import json
import time
import zipfile

import pytest

from accm1_files import (BILLION_LAUGHS_DTD, CT, HEADER_ROW, SHEET_HEAD, WB, WB_RELS, XXE_DTD, istr, items_rows,
                         lie_about_size, num, sheet, xlsx, zip_of)
from accm1_helpers import Api

WS_OPEN = SHEET_HEAD[SHEET_HEAD.index("<worksheet"):]
WB_OPEN = WB[WB.index("<workbook"):]
GOOD = sheet(HEADER_ROW + items_rows(("A-1", "buy", num("C@", "5"))))
SST_CT = CT.replace("</Types>", '<Override PartName="/xl/sharedStrings.xml" ContentType="application/'
                                'vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
SST_RELS = WB_RELS.replace("</Relationships>", '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/'
                                               'officeDocument/2006/relationships/sharedStrings" '
                                               'Target="sharedStrings.xml"/></Relationships>')


def _sst(*strings: str, dtd: str = "") -> str:
    return ('<?xml version="1.0"?>' + dtd + '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")


def _with_sst(rows_xml: str, sst: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", SST_CT)
        z.writestr("_rels/.rels", xlsx(GOOD) and zipfile.ZipFile(io.BytesIO(xlsx(GOOD))).read("_rels/.rels"))
        z.writestr("xl/workbook.xml", WB)
        z.writestr("xl/_rels/workbook.xml.rels", SST_RELS)
        z.writestr("xl/worksheets/sheet1.xml", sheet(rows_xml))
        z.writestr("xl/sharedStrings.xml", sst)
    return buf.getvalue()


REFUSED = {
    "billion laughs in a worksheet": (xlsx(sheet(HEADER_ROW + items_rows(("&lol9;", "buy", num("C@", "5"))),
                                                 head='<?xml version="1.0"?>' + BILLION_LAUGHS_DTD + WS_OPEN)),
                                      "MFG_IMPORT_FILE_INVALID"),
    "billion laughs in workbook.xml": (xlsx(GOOD, workbook='<?xml version="1.0"?>' + BILLION_LAUGHS_DTD +
                                            WB_OPEN.replace('name="items"', 'name="&lol9;"')),
                                       "MFG_IMPORT_FILE_INVALID"),
    "billion laughs in [Content_Types].xml": (xlsx(GOOD, content_types='<?xml version="1.0"?>' + BILLION_LAUGHS_DTD
                                                   + CT[CT.index("<Types"):]), "MFG_IMPORT_FILE_INVALID"),
    "billion laughs in sharedStrings.xml": (_with_sst(HEADER_ROW + '<row r="2"><c r="A2" t="s"><v>0</v></c></row>',
                                                      _sst("&lol9;", dtd=BILLION_LAUGHS_DTD)),
                                            "MFG_IMPORT_FILE_INVALID"),
    "external entity (XXE) in a worksheet": (xlsx(sheet(HEADER_ROW + items_rows(("&xxe;", "buy", num("C@", "5"))),
                                                        head='<?xml version="1.0"?>' + XXE_DTD + WS_OPEN)),
                                             "MFG_IMPORT_FILE_INVALID"),
    "external entity (XXE) in workbook.xml": (xlsx(GOOD, workbook='<?xml version="1.0"?>' + XXE_DTD +
                                                   WB_OPEN.replace('name="items"', 'name="&xxe;"')),
                                              "MFG_IMPORT_FILE_INVALID"),
    "cell in row 1,048,576": (xlsx(sheet(HEADER_ROW + f'<row r="1048576">{istr("A1048576", "X")}</row>')),
                              "MFG_IMPORT_TOO_LARGE"),
    "cell in column XFD": (xlsx(sheet(HEADER_ROW + f'<row r="2">{istr("XFD2", "X")}</row>')), "MFG_IMPORT_TOO_LARGE"),
    "row number 99,999,999,999": (xlsx(sheet(HEADER_ROW + f'<row r="99999999999">{istr("A99999999999", "X")}</row>')),
                                  "MFG_IMPORT_TOO_LARGE"),
    "negative row number": (xlsx(sheet(HEADER_ROW + f'<row r="-5">{istr("A-5", "X")}</row>')),
                            "MFG_IMPORT_FILE_INVALID"),
    "bad cell reference": (xlsx(sheet(HEADER_ROW + f'<row r="2">{istr("ZZZZZZ2", "X")}</row>')),
                           "MFG_IMPORT_FILE_INVALID"),
    "<v>NaN</v>": (xlsx(sheet(HEADER_ROW + items_rows(("N", "buy", num("C@", "NaN"))))), "MFG_IMPORT_FILE_INVALID"),
    "<v>inf</v>": (xlsx(sheet(HEADER_ROW + items_rows(("N", "buy", num("C@", "inf"))))), "MFG_IMPORT_FILE_INVALID"),
    "<v>0x10</v>": (xlsx(sheet(HEADER_ROW + items_rows(("N", "buy", num("C@", "0x10"))))), "MFG_IMPORT_FILE_INVALID"),
    "raw control character in XML": (xlsx(sheet(HEADER_ROW + items_rows(("C\x01", "buy", num("C@", "5"))))),
                                     "MFG_IMPORT_FILE_INVALID"),
    "zip bomb (60 MiB of zeros, ratio ~1000)": (zip_of({"items.csv": b"part_number,make_buy\n" + b"0" * (60 << 20)}),
                                                "MFG_IMPORT_TOO_LARGE"),
    "xlsx bomb (30 MiB worksheet comment)": (xlsx(SHEET_HEAD + "<!--" + "a" * (30 << 20) + "-->" + "</sheetData>"
                                                  "</worksheet>"), "MFG_IMPORT_TOO_LARGE"),
    "declared size smaller than the real data": (lie_about_size(zip_of({"items.csv": b"part_number,make_buy\n" +
                                                                        b"A,buy\n" * 200_000}), "items.csv", 100),
                                                 "MFG_IMPORT_FILE_INVALID"),
    "250 zip members": (zip_of({f"s{i}.csv": b"a,b\n1,2\n" for i in range(250)}), "MFG_IMPORT_TOO_LARGE"),
    "zip path traversal": (zip_of({"../../etc/items.csv": b"part_number,make_buy\nA,buy\n"}),
                           "MFG_IMPORT_FILE_INVALID"),
    "absolute zip path": (zip_of({"/etc/items.csv": b"part_number,make_buy\nA,buy\n"}), "MFG_IMPORT_FILE_INVALID"),
    "old .xls (OLE)": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600, "MFG_IMPORT_FILE_INVALID"),
    "empty body": (b"", "MFG_IMPORT_FILE_INVALID"),
    "truncated xlsx": (xlsx(GOOD)[:200], "MFG_IMPORT_FILE_INVALID"),
    "csv cell over 4,000 chars": (b"part_number,make_buy\n" + b"A" * 5000 + b",buy\n", "MFG_IMPORT_TOO_LARGE"),
    "csv with 150 columns": ((",".join(f"c{i}" for i in range(150)) + "\n" + ",".join("1" * 150) + "\n").encode(),
                             "MFG_IMPORT_TOO_LARGE"),
    "csv with 60,001 rows": (b"part_number,make_buy\n" + b"".join(b"P%d,buy\n" % i for i in range(60_001)),
                             "MFG_IMPORT_TOO_LARGE"),
}


@pytest.mark.parametrize("case", list(REFUSED))
def test_hostile_file_is_refused_cleanly(api: Api, case: str):
    data, code = REFUSED[case]
    t = time.monotonic()
    r = api.raw("POST", "/imports", params={"filename": "f.xlsx" if data[:2] == b"PK" else "f.csv",
                                            "sheet": "items"},
                content=data, headers={"content-type": "application/octet-stream"})
    assert time.monotonic() - t < 10
    assert r.status_code == 422, (case, r.status_code, r.text[:300])
    assert r.json()["error"]["code"] == code, (case, r.text[:300])
    assert "passwd" not in r.text and "root:" not in r.text
    assert api.get("/summary")["counts"]["items"] == 0


def test_oversize_and_wrong_content_type_uploads(api: Api):
    big = b"a,b\n" + b"1,2\n" * 1_400_000                                  # > 5 MiB
    r = api.raw("POST", "/imports", params={"filename": "big.csv"}, content=big,
                headers={"content-type": "application/octet-stream"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    def chunks():
        for _ in range(700):
            yield b"x" * 10_000

    r = api.raw("POST", "/imports", params={"filename": "c.csv"}, content=chunks(),
                headers={"content-type": "application/octet-stream"})
    assert r.status_code == 413, r.text[:200]
    r = api.raw("POST", "/imports", params={"filename": "j.xlsx"}, content=xlsx(GOOD),
                headers={"content-type": "application/json"})
    assert r.status_code == 422
    r = api.raw("POST", "/imports", params={"filename": "x" * 201}, content=b"a,b\n1,2\n",
                headers={"content-type": "application/octet-stream"})
    assert r.status_code == 422


def _preview(api: Api, data: bytes, name: str, sheet_name: str | None = "items") -> tuple[dict, dict]:
    rec = api.upload(data, name, sheet_name)
    staged = json.dumps(rec["sheets"], allow_nan=False)             # raises on a staged NaN/inf float
    assert "\\u0000" not in staged
    rec, preview = api.wizard(data, name, sheet=sheet_name)
    return rec, preview


@pytest.mark.parametrize("value,code", [("1E999", "IMP_BAD_NUMBER"), ("-1E999", "IMP_BAD_NUMBER"),
                                        ("1e308", "IMP_BAD_VALUE")])
def test_non_finite_and_huge_numbers_are_row_errors(api: Api, value: str, code: str):
    _, pv = _preview(api, xlsx(sheet(HEADER_ROW + items_rows(("N-1", "buy", num("C@", value))))), "n.xlsx")
    assert [(e["row"], e["column"], e["code"]) for e in pv["row_errors"]] == [(2, "lead_time_days", code)]


def test_csv_numbers_nan_inf_are_row_errors(api: Api):
    data = b"part_number,make_buy,lead_time_days,min_order_qty\nQ1,buy,5,1E999\nQ2,buy,5,NaN\nQ3,buy,5,inf\n"
    _, pv = _preview(api, data, "n.csv")
    assert sorted((e["row"], e["code"]) for e in pv["row_errors"]) == [(2, "IMP_BAD_NUMBER"), (3, "IMP_BAD_NUMBER"),
                                                                       (4, "IMP_BAD_NUMBER")]


def test_formulas_use_the_cached_value_or_are_row_errors(api: Api):
    rows = ('<row r="2">' + istr("A2", "F-1") + istr("B2", "buy") + '<c r="C2"><f>1+1</f></c></row>'
            '<row r="3">' + istr("A3", "F-2") + istr("B3", "buy") + '<c r="C3"><f>1+1</f><v>2</v></c></row>'
            '<row r="4"><c r="A4" t="str"><f>A1</f><v>=cmd|x</v></c>' + istr("B4", "buy") + num("C4", "3") + '</row>')
    rec, pv = _preview(api, xlsx(sheet(HEADER_ROW + rows)), "f.xlsx")
    assert [(e["row"], e["code"]) for e in pv["row_errors"]] == [(2, "IMP_FORMULA_NO_VALUE")]
    assert pv["counts"]["items"]["create"] == 2


def test_control_characters_never_reach_staging(api: Api):
    data = b"part_number,make_buy,lead_time_days\nA\x00B,buy,5\nC\x07D,buy,5\nE\tF,buy,5\n"
    rec, pv = _preview(api, data, "c.csv")
    assert {(e["row"], e["code"]) for e in pv["row_errors"]} >= {(2, "IMP_CONTROL_CHAR"), (3, "IMP_CONTROL_CHAR")}
    for s in rec["sheets"]:
        for row in s["sample_rows"]:
            assert not any(isinstance(v, str) and any(ord(ch) < 32 and ch not in "\t\r\n" for ch in v) for v in row)
    # Excel's _xHHHH_ escapes in shared strings (what Excel writes for a control character)
    x = _with_sst(HEADER_ROW + '<row r="2"><c r="A2" t="s"><v>0</v></c>' + istr("B2", "buy") + num("C2", "5") +
                  '</row>', _sst("X_x0000_Y"))
    rec, pv = _preview(api, x, "x.xlsx")
    assert "\\u0000" not in json.dumps(rec)


def test_export_neutralises_formula_injection(api: Api):
    api.post("/items", {"part_number": "INJ-1", "make_buy": "buy", "lead_time_days": 1,
                        "description": '=HYPERLINK("http://evil.example","x")'})
    api.post("/items", {"part_number": "+INJ-2", "make_buy": "buy", "lead_time_days": 1, "description": "@SUM(1)"})
    data = api.call("GET", "/export", 200, params={"format": "xlsx"}).content
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data))           # not read-only: data_type is visible
    ws = wb["items"]
    cells = [c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value[:1] in "=+-@"]
    assert cells and all(c.data_type == "s" for c in cells), [(c.coordinate, c.data_type) for c in cells]
    z = api.call("GET", "/export", 200, params={"format": "zip"}).content
    text = zipfile.ZipFile(io.BytesIO(z)).read("items.csv").decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "'+INJ-2" in text and "'@SUM" in text
    for line in text.splitlines():
        for cell in line.split(","):
            assert cell.lstrip('"')[:1] not in ("=", "+", "@"), line


NON_FINITE = ["NaN", "Infinity", "-Infinity", "1e999"]


@pytest.mark.parametrize("value", NON_FINITE)
@pytest.mark.xfail(strict=True, reason="DEFECT: non-finite float in `attributes` -> 500 and (SQLite) a poisoned "
                                       "row that makes GET /items, /items/{id}, /health, /plant answer 500")
def test_non_finite_attribute_values_are_rejected_and_never_stored(api: Api, value: str):
    body = '{"part_number":"J1","make_buy":"buy","lead_time_days":1,"attributes":{"x":%s}}' % value
    r = api.raw("POST", "/items", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 422, (r.status_code, r.text[:200])
    for path in ("/items", "/health", "/summary"):
        assert api.raw("GET", path).status_code == 200, path


@pytest.mark.xfail(strict=True, reason="DEFECT: non-finite float in plant `attributes` -> 500 and (SQLite) "
                                       "GET /plant answers 500 afterwards")
def test_non_finite_plant_attribute_is_rejected(api: Api):
    plant = api.get("/plant")
    body = json.dumps({"name": "P", "utc_offset": "+05:30", "planning_horizon_days": 90, "currency": "",
                       "attributes": {"a": 0}}).replace('"a": 0', '"a": NaN')
    r = api.raw("PUT", "/plant", content=body, headers={"content-type": "application/json",
                                                        "If-Match": f'"{plant["row_version"]}"'})
    assert r.status_code == 422, (r.status_code, r.text[:200])
    assert api.raw("GET", "/plant").status_code == 200


def test_bounded_floats_reject_nan_and_infinity(api: Api):
    for field in ("min_order_qty", "safety_stock", "order_multiple"):
        for v in ("NaN", "Infinity"):
            body = '{"part_number":"B1","make_buy":"buy","lead_time_days":1,"%s":%s}' % (field, v)
            r = api.raw("POST", "/items", content=body, headers={"content-type": "application/json"})
            assert r.status_code == 422, (field, v, r.status_code)
    for q in ("nan", "inf", "-1", "0"):
        assert api.raw("GET", "/routings/rtg_x/time-preview", params={"qty": q}).status_code in (404, 422)

"""Trace matrix (M8-DESIGN 10): requirement x test, merged with JUnit results.

- Backend: AST scan of `backend/tests/**/test_*.py` for `@pytest.mark.req("ID", ...)` on test functions (and
  module / class `pytestmark`), plus the register's `match` name substrings.
- Frontend: regex scan of `frontend/e2e/**/*.spec.ts` for `@req:ID` in test titles.
- JUnit XML files (`--junit`): last result per test (`passed` / `failed` / `skipped`).

`build(...)` -> rows `{id, title, source, risk, assurance, intended_use, tests, last_result, gap}`; `write(...)`
writes `trace-matrix.csv`, `trace-matrix.html` and `trace-matrix.json`; a high-risk requirement without a test
makes the result `ok = False` (exit 1 of `manage.py trace-matrix`).
"""

from __future__ import annotations

import ast
import csv
import html
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .register import REPO, Requirement, load

E2E_RE = re.compile(r"""test(?:\.only|\.skip)?\(\s*(['"`])(?P<title>.*?)\1""")
REQ_TAG = re.compile(r"@req:([A-Z0-9][A-Z0-9-]*)")


def _req_ids(dec: ast.expr) -> list[str]:
    """IDs of a `pytest.mark.req(...)` decorator / mark expression."""
    if isinstance(dec, ast.Call):
        f = dec.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name == "req":
            return [a.value for a in dec.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    if isinstance(dec, (ast.List, ast.Tuple)):
        return [x for e in dec.elts for x in _req_ids(e)]
    return []


def scan_python(root: Path) -> dict[str, list[str]]:
    """test node id -> requirement ids (marker) for every test function; ids without markers map to []."""
    out: dict[str, list[str]] = {}
    for path in sorted(root.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root.parent).as_posix()
        module_ids: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in node.targets):
                module_ids += _req_ids(node.value)

        def visit(body: list[ast.stmt], prefix: str, inherited: list[str]) -> None:
            for n in body:
                if isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
                    cls = list(inherited) + [x for d in n.decorator_list for x in _req_ids(d)]
                    for st in n.body:
                        if isinstance(st, ast.Assign) and any(getattr(t, "id", "") == "pytestmark"
                                                              for t in st.targets):
                            cls += _req_ids(st.value)
                    visit(n.body, f"{prefix}{n.name}::", cls)
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                    ids = list(inherited) + [x for d in n.decorator_list for x in _req_ids(d)]
                    out[f"{rel}::{prefix}{n.name}"] = sorted(set(ids))
        visit(tree.body, "", module_ids)
    return out


def scan_e2e(root: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*.spec.ts")):
        rel = path.relative_to(root.parent).as_posix()
        for m in E2E_RE.finditer(path.read_text(encoding="utf-8")):
            title = m.group("title")
            ids = REQ_TAG.findall(title)
            out[f"{rel}::{title}"] = sorted(set(ids))
    return out


def junit_results(files: Iterable[Path | str]) -> dict[str, str]:
    """`classname::name`-ish keys -> result; matched against test ids by function name and file stem."""
    out: dict[str, str] = {}
    for f in files:
        try:
            tree = ET.parse(str(f))
        except (ET.ParseError, OSError):
            continue
        for tc in tree.iter("testcase"):
            name = tc.get("name", "")
            cls = tc.get("classname", "")
            res = "passed"
            if tc.find("failure") is not None or tc.find("error") is not None:
                res = "failed"
            elif tc.find("skipped") is not None:
                res = "skipped"
            out[f"{cls}::{name}"] = res
    return out


def _result_of(test_id: str, results: dict[str, str]) -> str | None:
    if not results:
        return None
    path, _, name = test_id.partition("::")
    stem = path.rsplit("/", 1)[-1].removesuffix(".py").removesuffix(".spec.ts")
    base = name.split("::")[-1].split("[")[0]
    for k, v in results.items():
        cls, _, n = k.partition("::")
        if (n == base or n.split("[")[0] == base) and (stem in cls or cls.endswith(stem) or not cls):
            return v
    return None


def build(reqs: list[Requirement] | None = None, *, tests_root: Path | None = None, e2e_root: Path | None = None,
          junit: Iterable[Path | str] = ()) -> dict[str, Any]:
    reqs = reqs if reqs is not None else load()
    py = scan_python(tests_root or REPO / "backend" / "tests")
    e2e = scan_e2e(e2e_root or REPO / "frontend" / "e2e")
    results = junit_results(junit)
    by_req: dict[str, set[str]] = {r.id: set() for r in reqs}
    for tid, ids in {**py, **e2e}.items():
        for i in ids:
            if i in by_req:
                by_req[i].add(tid)
    for r in reqs:
        for sub in r.match:
            by_req[r.id] |= {tid for tid in py if sub in tid.split("::")[-1]}
    rows = []
    unknown = sorted({i for ids in {**py, **e2e}.values() for i in ids} - set(by_req))
    for r in reqs:
        tests = sorted(by_req[r.id])
        res = [x for x in (_result_of(t, results) for t in tests) if x]
        last = "failed" if "failed" in res else ("passed" if "passed" in res else ("skipped" if res else None))
        rows.append({"id": r.id, "title": r.title, "source": r.source, "risk": r.risk, "assurance": r.assurance,
                     "intended_use": r.intended_use, "tests": tests, "last_result": last, "gap": not tests})
    gaps = [{"id": x["id"], "title": x["title"], "risk": x["risk"]} for x in rows if x["gap"]]
    high = sum(1 for g in gaps if g["risk"] == "high")
    return {"generated_at": datetime.now(UTC).isoformat(), "requirements": len(rows),
            "covered": sum(1 for x in rows if not x["gap"]), "gaps": gaps, "high_risk_gaps": high,
            "unknown_ids": unknown, "rows": rows, "ok": high == 0}


def to_csv(m: dict[str, Any]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "title", "source", "risk", "assurance", "intended_use", "tests", "last_result", "gap"])
    for r in m["rows"]:
        w.writerow([r["id"], r["title"], r["source"], r["risk"], r["assurance"], r["intended_use"],
                    " | ".join(r["tests"]), r["last_result"] or "", "yes" if r["gap"] else ""])
    return buf.getvalue().encode("utf-8")


def to_html(m: dict[str, Any]) -> bytes:
    e = html.escape
    rows = "".join(
        f"<tr class=\"{'gap' if r['gap'] else ''}\"><td>{e(r['id'])}</td><td>{e(r['title'])}</td>"
        f"<td>{e(r['source'])}</td><td>{e(r['risk'])}</td><td>{e(r['assurance'])}</td>"
        f"<td>{'<br>'.join(e(t) for t in r['tests']) or '<b>no test</b>'}</td><td>{e(r['last_result'] or '-')}</td>"
        "</tr>" for r in m["rows"])
    doc = (f"<!doctype html><html><head><meta charset=\"utf-8\"><title>Trace matrix</title><style>"
           "body{font-family:sans-serif}td,th{border:1px solid #ccc;padding:4px;vertical-align:top}"
           "table{border-collapse:collapse}tr.gap{background:#fde8e8}</style></head><body>"
           f"<h1>Trace matrix</h1><p>Generated {e(m['generated_at'])}: {m['requirements']} requirements, "
           f"{m['covered']} covered, {len(m['gaps'])} gaps ({m['high_risk_gaps']} high risk).</p>"
           "<table><tr><th>ID</th><th>Title</th><th>Source</th><th>Risk</th><th>Assurance</th><th>Tests</th>"
           f"<th>Last result</th></tr>{rows}</table></body></html>")
    return doc.encode("utf-8")


def write(m: dict[str, Any], out_dir: Path | str) -> list[Path]:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    paths = [d / "trace-matrix.csv", d / "trace-matrix.html", d / "trace-matrix.json"]
    paths[0].write_bytes(to_csv(m))
    paths[1].write_bytes(to_html(m))
    paths[2].write_text(json.dumps(m, indent=1), encoding="utf-8")
    return paths

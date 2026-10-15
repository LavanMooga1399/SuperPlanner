"""A.2 dependency rules and A.7.6 public API (acceptance criteria 1.2, 1.3)."""

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "superplanner"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            mods.add(base)
            if node.module is None:
                mods.update("." * node.level + a.name for a in node.names)
    return mods


def test_engine_imports_no_web_db_api_or_templates():
    for f in (PKG / "engine").rglob("*.py"):
        for m in _imports(f):
            assert not m.startswith(("fastapi", "sqlalchemy", "starlette", "uvicorn")), (f, m)
            assert "superplanner.api" not in m and "superplanner.templates" not in m, (f, m)
            assert not m.startswith(("..api", "..templates", "...api", "...templates")), (f, m)


def test_validator_is_independent():
    allowed = {".model", ".compiled", ".timeutil", ".objectives", "__future__", "bisect", "typing", "pydantic"}
    mods = _imports(PKG / "engine" / "validator.py")
    assert mods <= allowed, mods - allowed
    for forbidden in ("decoder", "graph", "solvers"):
        assert not any(forbidden in m for m in mods)


def test_templates_import_only_engine_model():
    for f in (PKG / "templates").glob("*.py"):
        for m in _imports(f):
            if m.startswith("superplanner"):
                assert m == "superplanner.engine.model", (f, m)
            assert "api" not in m.split(".")


def test_public_api_exact_names():
    from superplanner.engine import (CompileError, Placement, Problem, __version__, analyze, explain_schedule,
                                     optimize, preflight, validate_schedule)
    import superplanner

    assert __version__ == "0.1.0" == superplanner.__version__
    assert callable(preflight) and callable(analyze) and callable(optimize)
    assert callable(validate_schedule) and callable(explain_schedule)
    assert issubclass(CompileError, Exception) and Problem and Placement


def test_validate_and_explain_raise_compile_error():
    import pytest

    from engine_helpers import problem, task
    from superplanner.engine import CompileError, explain_schedule, validate_schedule

    p = problem([task("A", 10, ["GHOST"])], [])
    with pytest.raises(CompileError) as ei:
        validate_schedule(p, [])
    assert ei.value.issues[0].code == "UNKNOWN_RESOURCE"
    with pytest.raises(CompileError):
        explain_schedule(p, [])

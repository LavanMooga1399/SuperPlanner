"""F.2 dependency rules and the F.2.1 public API (acceptance 1.2, 1.3)."""

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "superplanner" / "finance"


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


def test_finance_never_imports_web_db_or_api():
    files = list(PKG.rglob("*.py"))
    assert len(files) >= 20
    for f in files:
        for m in _imports(f):
            assert not m.startswith(("fastapi", "starlette", "sqlalchemy", "uvicorn")), (f, m)
            assert "superplanner.api" not in m and not m.startswith(("..api", "...api")), (f, m)


def test_only_bridge_imports_engine_model():
    for f in PKG.rglob("*.py"):
        for m in _imports(f):
            if "superplanner.engine" in m or m.startswith(("..engine", "...engine")):
                assert f.name == "bridge.py", (f, m)
                assert m == "superplanner.engine.model", (f, m)


def test_validator_imports_only_allowed_modules():
    allowed = {".model", ".defaults", ".timegrid", ".cashflow", ".returns", "__future__", "collections",
               "dataclasses", "typing", "pydantic", "numpy", "math", "."}
    mods = _imports(PKG / "validator.py")
    assert mods <= allowed, mods - allowed
    for forbidden in ("optimizer", "simulate", "advisor", "pipeline"):
        assert not any(forbidden in m for m in mods)


def test_public_api_exact():
    import superplanner.finance as f

    names = ['default_plan', 'default_assumptions', 'preflight', 'project_cashflow', 'summarize_cashflow', 'run_plan',
             'validate_result', 'apply_what_if', 'compare_results', 'contributions_csv', 'to_planner_problem',
             'TEMPLATES', 'get_template', 'DISCLAIMER', 'DISCLAIMER_VERSION', 'FinancePreflightError',
             'FinanceCancelled', 'FinancePlan', 'FinanceResult']
    for n in names:
        assert getattr(f, n) is not None
        assert n in f.__all__
    assert f.__version__ == "fin-0.1.0"
    assert f.DISCLAIMER_VERSION == "fin-disclaimer-1"
    assert issubclass(f.FinancePreflightError, Exception) and issubclass(f.FinanceCancelled, Exception)
    for n in f.__all__:
        assert hasattr(f, n), n


def test_default_plan_and_assumptions():
    import superplanner.finance as f

    p = f.default_plan(start_month="2026-11")
    assert p.name == "My financial plan" and p.start_month == "2026-11"
    a = f.default_assumptions()
    assert [c.id for c in a.asset_classes] == ["cash", "fixed_deposit", "short_debt", "govt_long", "equity_index",
                                               "gold"]
    assert a.risky_cap_by_tolerance_pct == [20, 40, 60, 75, 90]
    assert f.preflight(p).ok

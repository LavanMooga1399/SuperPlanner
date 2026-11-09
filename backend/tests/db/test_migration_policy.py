"""M6-DESIGN 4.2 item 6 (T-H3): expand / contract migration policy.

Every revision from 0008 on declares `policy = "expand"` or `"contract"` (module attribute, also stated in its
docstring). An `expand` revision's `upgrade()` may only add (tables, nullable columns or columns with a server
default, indexes, constraints on new tables, job kinds); drops, renames, type changes and NOT NULL without a
default are contract operations and fail this test. 0001-0007 shipped before the policy (additive by their own
docstrings) and are not re-checked."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[2] / "superplanner" / "migrations" / "versions"
LEGACY = {"0001_initial", "0002_phase2b", "0003_mfg", "0004_mfg_m2", "0005_mfg_m3", "0006_mfg_m4", "0007_m5"}
CONTRACT_OPS = {"drop_table", "drop_column", "rename_table", "drop_constraint", "drop_index", "drop_table_comment",
                "drop_column_comment"}
CONTRACT_SQL = ("DROP ", "RENAME ", " TYPE ", "SET NOT NULL", "TRUNCATE ")


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "op":
        return f.attr
    return None


def _kw(node: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in node.keywords if k.arg == name), None)


def violations(source: str) -> tuple[str | None, list[str]]:
    """(declared policy, contract operations found in upgrade() of an expand revision)."""
    tree = ast.parse(source)
    policy = None
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "policy" for t in n.targets):
            policy = ast.literal_eval(n.value)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if policy != "expand" or "upgrade" not in funcs:
        return policy, []
    found: list[str] = []
    seen: set[str] = set()

    def visit_fn(fn: ast.FunctionDef) -> None:
        if fn.name in seen:
            return
        seen.add(fn.name)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in funcs:      # helpers called by upgrade()
                visit_fn(funcs[node.func.id])
            name = _call_name(node)
            if name is None:
                continue
            if name in CONTRACT_OPS:
                found.append(name)
            elif name == "alter_column":
                if _kw(node, "type_") is not None or _kw(node, "new_column_name") is not None:
                    found.append("alter_column (type / rename)")
                nn = _kw(node, "nullable")
                if isinstance(nn, ast.Constant) and nn.value is False:
                    found.append("alter_column (NOT NULL)")
            elif name == "add_column":
                col = node.args[1] if len(node.args) > 1 else None
                if isinstance(col, ast.Call):
                    nn, sd = _kw(col, "nullable"), _kw(col, "server_default")
                    if isinstance(nn, ast.Constant) and nn.value is False and sd is None:
                        found.append("add_column (NOT NULL without default)")
            elif name == "execute" and node.args and isinstance(node.args[0], ast.Constant) and \
                    isinstance(node.args[0].value, str):
                sql = " " + node.args[0].value.upper()
                found.extend(f"execute ({k.strip()})" for k in CONTRACT_SQL if k in sql)

    visit_fn(funcs["upgrade"])
    return policy, found


def _revisions() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if not p.name.startswith("__"))


@pytest.mark.parametrize("path", _revisions(), ids=lambda p: p.stem)
def test_revision_follows_the_policy(path: Path):
    if path.stem in LEGACY:
        return
    src = path.read_text(encoding="utf-8")
    policy, bad = violations(src)
    assert policy in ("expand", "contract"), f"{path.stem}: declare policy = 'expand' | 'contract'"
    assert f"Policy: {policy}" in ast.get_docstring(ast.parse(src)), f"{path.stem}: state the policy in the docstring"
    assert bad == [], f"{path.stem} is 'expand' but contains contract operations: {bad}"


def test_0008_is_expand():
    policy, bad = violations((VERSIONS / "0008_m6.py").read_text(encoding="utf-8"))
    assert policy == "expand" and bad == []


def test_expand_with_drop_column_fails():
    """T-H3."""
    src = '''"""x. Policy: expand"""
from alembic import op
import sqlalchemy as sa
policy = "expand"

def _helper():
    op.drop_column("mfg_items", "family")

def upgrade():
    op.add_column("t", sa.Column("a", sa.Integer(), nullable=True))
    op.add_column("t", sa.Column("b", sa.Integer(), nullable=False))
    op.alter_column("t", "c", type_=sa.Text())
    op.execute("ALTER TABLE t RENAME COLUMN x TO y")
    _helper()

def downgrade():
    op.drop_column("t", "a")
'''
    policy, bad = violations(src)
    assert policy == "expand"
    assert bad == ["add_column (NOT NULL without default)", "alter_column (type / rename)", "execute (RENAME)",
                   "drop_column"]
    assert violations(src.replace('policy = "expand"', 'policy = "contract"'))[1] == []

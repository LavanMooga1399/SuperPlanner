"""Import boundary and message compliance of `superplanner.intake` (PHASE2 2.2, 2.7; plan P2-10)."""

from __future__ import annotations

import ast
from pathlib import Path

from intake_helpers import load_finance_helpers
from superplanner.finance.advisor.messages import FORBIDDEN_WORDS, contains_forbidden
from superplanner.intake import messages
from superplanner.intake.ai import prompts

PKG = Path(__file__).resolve().parents[2] / "superplanner" / "intake"


def _imports(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add("." * node.level + (node.module or ""))
    return mods


def test_intake_never_imports_web_db_or_api():
    files = list(PKG.rglob("*.py"))
    assert len(files) >= 25
    for f in files:
        for m in _imports(f):
            assert not m.startswith(("fastapi", "starlette", "sqlalchemy", "uvicorn")), (f, m)
            assert "superplanner.api" not in m and not m.startswith(("..api", "...api")), (f, m)
            if m.startswith("anthropic"):
                assert f.relative_to(PKG).as_posix() == "ai/client.py", (f, m)


def test_anthropic_imported_lazily_only():
    tree = ast.parse((PKG / "ai" / "client.py").read_text())
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any(isinstance(n, ast.Import) and any(a.name == "anthropic" for a in n.names) for n in top)
    assert not any(isinstance(n, ast.ImportFrom) and (n.module or "").startswith("anthropic") for n in top)


def _catalog_texts() -> list[str]:
    out = [messages.PRIVACY_NOTICE, *messages.FALLBACK_PREFIX.values(), *messages.NOTES.values(),
           *messages.PROMPTS.values(), *prompts.all_texts()]
    return [t for t in out if isinstance(t, str)]


def test_messages_and_prompts_pass_denylist_and_forbidden_words():
    fh = load_finance_helpers()
    for text in _catalog_texts():
        assert fh.denylist_hits(text) == [], text
        assert contains_forbidden(text) == [], text
    for f in (PKG / "messages.py", PKG / "ai" / "prompts.py"):
        src = f.read_text()
        assert fh.denylist_hits(src) == [], f
        low = src.lower()
        for w in FORBIDDEN_WORDS:
            assert f" {w} " not in low, (f, w)

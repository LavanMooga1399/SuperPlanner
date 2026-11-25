"""Validation kit service (M8-DESIGN 10, 11 V1-V4): trace matrix (the latest file written by `manage.py
trace-matrix --out` under `ARCHIVE_DIR/validation`, else a live scan of the repository without test results) and
configuration baselines (stored in `val_baselines`, canonical JSON + sha256, diff by path)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from ....validation import baseline as B
from ....validation import trace as T
from ...context import AppContext
from ...db.models import new_id, utcnow
from .. import repo
from ..db_models_m8 import ValBaselineRow
from . import m8_examples
from .common import audit, read_tx, write_tx
from .m8common import page


def _matrix(ctx: AppContext) -> dict[str, Any]:
    d = getattr(ctx.settings, "archive_dir", None)
    if d:
        p = Path(d) / "validation" / "trace-matrix.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    try:
        return T.build()
    except FileNotFoundError:          # deployed without the repository (no register): empty matrix
        return {"generated_at": None, "requirements": 0, "covered": 0, "gaps": [], "high_risk_gaps": 0, "rows": [],
                "ok": True}


def trace_matrix(ctx: AppContext, fmt: str) -> Any:
    m = _matrix(ctx)
    if fmt == "csv":
        return T.to_csv(m), "trace-matrix.csv", "text/csv"
    if fmt == "html":
        return T.to_html(m), "trace-matrix.html", "text/html"
    return {"generated_at": m["generated_at"], "requirements": m["requirements"], "covered": m["covered"],
            "gaps": m["gaps"], "high_risk_gaps": m["high_risk_gaps"],
            "rows": [{k: r[k] for k in ("id", "title", "risk", "tests", "last_result")} for r in m["rows"]],
            "csv_url": "/api/v1/mfg/validation/trace-matrix?format=csv"}


def _record(r: ValBaselineRow, full: bool = False) -> dict[str, Any]:
    return {"id": r.id, "label": r.label, "sha256": r.sha256, "created_by": r.created_by, "created_at": r.created_at,
            "content": r.content if full else None}


def list_baselines(ctx: AppContext, limit: int, offset: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        n = int(s.execute(select(func.count()).select_from(ValBaselineRow)).scalar() or 0)
        rows = s.execute(select(ValBaselineRow).order_by(ValBaselineRow.created_at.desc(), ValBaselineRow.id.desc())
                         .limit(limit).offset(offset)).scalars()
        return page([_record(r) for r in rows], n, limit, offset)


def create_in(s: Any, label: str, actor: str) -> ValBaselineRow:
    content = B.collect(s)
    r = ValBaselineRow(id=new_id("vbl_"), label=label, created_by=actor, created_at=utcnow(),
                       sha256=B.digest(content), content=json.loads(B.canonical(content)))
    s.add(r)
    s.flush()
    audit(s, "baseline", r.id, "create", {"label": label, "sha256": r.sha256})
    return r


def create_baseline(ctx: AppContext, a: Any, body: Any) -> dict[str, Any]:
    with write_tx(ctx, lock=False) as (s, _):
        return _record(create_in(s, body.label, a.user_id), True)


def get_baseline(ctx: AppContext, baseline_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return _record(repo.get_row(s, ValBaselineRow, baseline_id, what="Baseline"), True)


def diff_baselines(ctx: AppContext, a_id: str, b_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        a = repo.get_row(s, ValBaselineRow, a_id, what="Baseline")
        b = repo.get_row(s, ValBaselineRow, b_id, what="Baseline")
        ch = B.diff(a.content, b.content)
        return {"a": a.id, "b": b.id, "a_sha256": a.sha256, "b_sha256": b.sha256, "same": a.sha256 == b.sha256,
                "changes": ch[:2000]}


__getattr__ = m8_examples.module_getattr(__name__)

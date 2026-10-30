"""APS runs (M3-DESIGN 10, 11 #179-199). **S0 stub**: every endpoint answers with the frozen contract examples
(`mfg/aps/fixtures/example_run.json`) so the UI can be built against the real routes; replaced in S3."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ...context import AppContext
from ...db import utcnow
from ...errors import ApiError

FIXTURE = Path(__file__).resolve().parents[3] / "mfg" / "aps" / "fixtures" / "example_run.json"


@lru_cache(maxsize=1)
def _fx() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def fx(key: str) -> Any:
    return copy.deepcopy(_fx()[key])


def create_run(ctx: AppContext, body: Any, idem: str | None) -> tuple[dict[str, Any], bool]:
    return fx("post_runs_response_202"), False


def list_runs(ctx: AppContext, **kw: Any) -> dict[str, Any]:
    return fx("runs_page")


def published_run(ctx: AppContext) -> dict[str, Any]:
    return fx("run")


def get_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    return fx("run")


def update_run(ctx: AppContext, run_id: str, body: Any, if_match: str | None) -> dict[str, Any]:
    return fx("run")


def delete_run(ctx: AppContext, run_id: str, if_match: str | None) -> None:
    return None


def cancel_run(ctx: AppContext, run_id: str) -> dict[str, Any]:
    return fx("run_running")


def publish_run(ctx: AppContext, run_id: str, if_match: str | None) -> dict[str, Any]:
    r = fx("run")
    r["is_published"] = True
    return r


def create_edits(ctx: AppContext, run_id: str, body: Any) -> dict[str, Any]:
    return fx("edits_response_201")


def gantt(ctx: AppContext, run_id: str, **kw: Any) -> dict[str, Any]:
    return fx("gantt")


def operations(ctx: AppContext, run_id: str, **kw: Any) -> dict[str, Any]:
    return fx("operations_page")


def operation(ctx: AppContext, run_id: str, op_no: int) -> dict[str, Any]:
    return fx("operation_detail")


def orders(ctx: AppContext, run_id: str, **kw: Any) -> dict[str, Any]:
    return fx("orders_page")


def demand(ctx: AppContext, run_id: str, **kw: Any) -> dict[str, Any]:
    return fx("demand")


def load(ctx: AppContext, run_id: str, **kw: Any) -> dict[str, Any]:
    return fx("load")


def dispatch(ctx: AppContext, run_id: str, **kw: Any) -> dict[str, Any]:
    return fx("dispatch")


def overtime(ctx: AppContext, run_id: str, **kw: Any) -> dict[str, Any]:
    return fx("overtime")


def exceptions(ctx: AppContext, run_id: str, **kw: Any) -> dict[str, Any]:
    return fx("exceptions_page")


def bottlenecks(ctx: AppContext, run_id: str) -> dict[str, Any]:
    return fx("bottlenecks")


def compare(ctx: AppContext, run_id: str, with_id: str) -> dict[str, Any]:
    return fx("compare")


def export(ctx: AppContext, run_id: str, fmt: str) -> tuple[bytes, str, str]:
    raise ApiError(409, "APS_RUN_NOT_COMPLETED", "Export is available from S3.", {})


def run_job(ctx: Any, run_id: str, lease: Any) -> None:  # pragma: no cover - S3
    raise ApiError(500, "INTERNAL", "APS runs are not executable before S3.", {})


def recover_interrupted_runs(ctx: Any) -> int:
    """Inline mode: every queued/running APS run -> failed (+ its job), as the other run kinds."""
    from ....jobs import common as job_common
    from ....jobs.types import RESTART_ERROR
    from ...db.ownership import system_scope
    from ..db_models_m3 import MfgApsRunRow

    with system_scope(), ctx.write_guard(), ctx.db.write() as s:
        runs = list(s.scalars(select(MfgApsRunRow).where(MfgApsRunRow.status.in_(("queued", "running")))).all())
        now = utcnow()
        for run in runs:
            run.status = "failed"
            run.error = {"code": "APS_RESTARTED", "message": RESTART_ERROR}
            run.finished_at = now
        job_common.mark_jobs_failed(s, "aps_run", [r.id for r in runs], RESTART_ERROR)
        return len(runs)

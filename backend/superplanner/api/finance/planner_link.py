"""Send a finance result to the scheduler as a regular plan (FINANCE.md 16.1, 18.2).

Order matters: the result is read in a read session, the problem is built with `finance.to_planner_problem`,
then `problem_service.create_problem` runs its own write transaction (never inside a finance write session),
and the `finance_result.sent_to_planner` audit row is written in a second transaction afterwards.
"""

from __future__ import annotations

from typing import Any

from superplanner import finance

from ..context import AppContext
from ..errors import ApiError
from ..services import problem_service
from .run_service import load_result
from .schemas import SendToPlannerRequest


def send_to_planner(ctx: AppContext, result_id: str, req: SendToPlannerRequest) -> dict[str, Any]:
    summary, result, plan = load_result(ctx, result_id)   # 404 if unknown
    if result.feasibility != "feasible":
        raise ApiError(422, "NOT_FEASIBLE",
                       f"Only a feasible plan can be sent to the planner (this result is {result.feasibility}).",
                       {"feasibility": result.feasibility})
    name = req.name or f"{plan.name} - money calendar"
    try:
        problem, skipped = finance.to_planner_problem(
            plan, result, name=name, months=req.months, utc_offset=req.utc_offset,
            review_every_months=req.review_every_months, include_rebalances=req.include_rebalances)
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", f"The request is not valid: {exc}",
                       {"errors": [{"loc": ["body"], "msg": str(exc), "type": "value_error"}]})
    metadata = dict(problem.metadata)
    metadata["finance_plan_id"] = summary["plan_id"]
    metadata["finance_result_id"] = result_id
    problem = problem.model_copy(update={"metadata": metadata})
    rec = problem_service.create_problem(ctx, problem)
    with ctx.db.write() as s:
        problem_service.audit(s, "finance_result", result_id, "finance_result.sent_to_planner",
                              {"problem_id": rec["id"]})
    return {"problem_id": rec["id"], "record": rec, "task_count": len(problem.tasks), "skipped": skipped,
            "url": f"/plans/{rec['id']}/tasks"}

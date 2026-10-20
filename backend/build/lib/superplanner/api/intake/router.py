"""`/api/v1/intake` endpoints (PHASE2 2.15). Stateless: sync handlers (threadpool), no DB access, 200 on success.

User text, table cells and AI prompts/responses are never logged here or in `superplanner.intake`.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from superplanner import intake
from superplanner.intake import (FinanceBuildResult, FinanceIntakeResponse, ScheduleBuildResult,
                                 ScheduleIntakeResponse, TableParseRequest, TableParseResult)

from ..errors import ApiError
from . import service
from .schemas import (DescribeRequest, FinanceAnswerRequest, FinanceBuildRequest, FinanceTableApplyRequest,
                      ScheduleAnswerRequest, ScheduleBuildRequest, ScheduleTableApplyRequest)


class IntakeRoute(APIRoute):
    """Maps the size limits of `text` to the documented codes: TEXT_TOO_LONG / TABLE_TOO_LARGE."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        original = super().get_route_handler()
        is_table = "/table/" in self.path

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                for e in exc.errors():
                    loc = list(e.get("loc") or [])
                    if e.get("type") == "string_too_long" and loc == ["body", "text"]:
                        limit = (e.get("ctx") or {}).get("max_length")
                        if is_table:
                            raise ApiError(422, "TABLE_TOO_LARGE", f"The table is longer than {limit} characters.",
                                           {"max_chars": limit}) from None
                        raise ApiError(422, "TEXT_TOO_LONG", f"The text is longer than {limit} characters.",
                                       {"max_chars": limit}) from None
                raise
        return handler


router = APIRouter(prefix="/intake", tags=["intake"], route_class=IntakeRoute)


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except intake.IntakeError as exc:
        raise service.api_error(exc) from None


@router.get("/capabilities")
def capabilities(request: Request) -> dict:
    return service.capabilities(request)


# ---------------------------------------------------------------- schedule

@router.post("/schedule/describe")
def schedule_describe(req: DescribeRequest, request: Request) -> ScheduleIntakeResponse:
    s = service.settings_of(request)
    return _call(intake.describe_schedule, req.text, req.context, ai=service.ai_options(request, req.use_ai),
                 max_chars=s.intake_max_text_chars)


@router.post("/schedule/answer")
def schedule_answer(req: ScheduleAnswerRequest, request: Request) -> ScheduleIntakeResponse:
    return _call(intake.answer_schedule, req.draft, req.answers, req.context,
                 ai_available=service.ai_state(request)[0])


@router.post("/schedule/build")
def schedule_build(req: ScheduleBuildRequest) -> ScheduleBuildResult:
    return _call(intake.build_schedule, req.draft, req.context)


@router.post("/schedule/table/parse")
def schedule_table_parse(req: TableParseRequest, request: Request) -> TableParseResult:
    s = service.settings_of(request)
    return _call(intake.parse_table, req.text, "schedule", delimiter=req.delimiter, has_header=req.has_header,
                 max_chars=s.intake_max_table_chars)


@router.post("/schedule/table/apply")
def schedule_table_apply(req: ScheduleTableApplyRequest, request: Request) -> ScheduleIntakeResponse:
    s = service.settings_of(request)
    return _call(intake.apply_schedule_table, req, req.context, req.base, max_chars=s.intake_max_table_chars,
                 ai_available=service.ai_state(request)[0])


# ---------------------------------------------------------------- finance

@router.post("/finance/describe")
def finance_describe(req: DescribeRequest, request: Request) -> FinanceIntakeResponse:
    s = service.settings_of(request)
    return _call(intake.describe_finance, req.text, req.context, ai=service.ai_options(request, req.use_ai),
                 max_chars=s.intake_max_text_chars)


@router.post("/finance/answer")
def finance_answer(req: FinanceAnswerRequest, request: Request) -> FinanceIntakeResponse:
    return _call(intake.answer_finance, req.draft, req.answers, req.context,
                 ai_available=service.ai_state(request)[0])


@router.post("/finance/build")
def finance_build(req: FinanceBuildRequest) -> FinanceBuildResult:
    return _call(intake.build_finance, req.draft, req.context)


@router.post("/finance/table/parse")
def finance_table_parse(req: TableParseRequest, request: Request) -> TableParseResult:
    s = service.settings_of(request)
    return _call(intake.parse_table, req.text, "finance", delimiter=req.delimiter, has_header=req.has_header,
                 max_chars=s.intake_max_table_chars)


@router.post("/finance/table/apply")
def finance_table_apply(req: FinanceTableApplyRequest, request: Request) -> FinanceIntakeResponse:
    s = service.settings_of(request)
    return _call(intake.apply_finance_table, req, req.context, req.base, max_chars=s.intake_max_table_chars,
                 ai_available=service.ai_state(request)[0])

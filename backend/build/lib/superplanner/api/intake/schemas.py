"""Intake request models (PHASE2 2.15). Responses are the intake response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from superplanner.intake import (Answer, ExtractContext, FinanceDraft, MAX_TABLE_CHARS, ScheduleDraft, TableApply)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DescribeRequest(_Strict):
    text: str = Field(max_length=20000)
    context: ExtractContext
    use_ai: bool = False


class ScheduleAnswerRequest(_Strict):
    draft: ScheduleDraft
    answers: list[Answer] = Field(max_length=500)
    context: ExtractContext


class FinanceAnswerRequest(_Strict):
    draft: FinanceDraft
    answers: list[Answer] = Field(max_length=500)
    context: ExtractContext


class ScheduleBuildRequest(_Strict):
    draft: ScheduleDraft
    context: ExtractContext


class FinanceBuildRequest(_Strict):
    draft: FinanceDraft
    context: ExtractContext


class ScheduleTableApplyRequest(TableApply):
    context: ExtractContext
    base: ScheduleDraft | None = None


class FinanceTableApplyRequest(TableApply):
    context: ExtractContext
    base: FinanceDraft | None = None


__all__ = ["DescribeRequest", "ScheduleAnswerRequest", "FinanceAnswerRequest", "ScheduleBuildRequest",
           "FinanceBuildRequest", "ScheduleTableApplyRequest", "FinanceTableApplyRequest", "MAX_TABLE_CHARS"]

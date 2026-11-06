"""M6 assistant contract (M6-DESIGN 1.1-1.5, 1.7; frozen at S0)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from ..mfg.model import EntityId, MfgModel

MAX_TEXT = 4000
TurnStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
DraftKind = Literal["expedite_po_schedule", "release_planned_orders", "open_overtime", "schedule_edit", "create_pr",
                    "raise_priority", "whatif_run"]
QuickKind = Literal["why_late", "limits", "changes"]
ContextType = Literal["demand_line", "demand_order", "work_order", "item", "purchase_order", "line", "aps_run",
                      "mrp_run", "eco", "supplier", "page"]
#: P2 2.10 codes plus the assistant's own
AiCode = Literal["AI_DISABLED", "AI_SDK_MISSING", "AI_NO_CREDENTIALS", "AI_PLANT_OPTED_OUT", "AI_FORBIDDEN",
                 "AI_BUSY", "AI_BUDGET_EXCEEDED", "AI_RATE_LIMITED", "AI_AUTH_FAILED", "AI_API_ERROR",
                 "AI_CONNECTION_ERROR", "AI_UNEXPECTED", "AI_REFUSED", "AI_TRUNCATED", "AI_ROUND_LIMIT",
                 "AI_TURN_LOST", "AI_CANCELLED"]
PRIVACY_NOTICE = ("The assistant sends your question and the planning records it looks up (part numbers, quantities, "
                  "dates, order numbers - no prices unless you ask about cost, no personal data) to Anthropic, an AI "
                  "provider, to answer. Answers may be wrong; check the linked records. Nothing is sent when you use "
                  "the built-in explanations.")


class BudgetLeft(MfgModel):
    user: int
    plant: int


class AssistantPlantSettings(MfgModel):
    assistant_enabled: bool = True
    assistant_allow_whatif: bool = True


class AssistantStatus(MfgModel):
    available: bool
    code: str | None = None                 # AiCode when unavailable
    message: str = ""
    privacy_notice: str = PRIVACY_NOTICE
    budget_left: BudgetLeft
    plant: AssistantPlantSettings
    model: str = "claude-opus-5-5"
    max_text_chars: int = MAX_TEXT
    max_tool_rounds: int = 8
    quick_kinds: list[QuickKind] = Field(default_factory=lambda: ["why_late", "limits", "changes"])


class ConversationInput(MfgModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    allow_whatif: bool = False


class TurnContext(MfgModel):
    type: ContextType
    id: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class TurnInput(MfgModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT)]
    context: TurnContext | None = None
    allow_whatif: bool = False


class TurnAccepted(MfgModel):
    turn_id: str
    conversation_id: str
    status: TurnStatus


class TurnStep(MfgModel):
    at: datetime
    kind: Literal["thinking", "tool", "answer", "note"]
    name: str | None = None                 # tool name
    summary: str = ""                       # "tool: demand_status (DO-KV-003/10)"
    ok: bool = True


class Citation(MfgModel):
    ref: Annotated[str, StringConstraints(pattern=r"^[RQ][0-9]{1,4}$")]
    type: str
    id: str
    label: str
    link: str


class IfMatchOf(MfgModel):
    type: str
    id: str
    row_version: int


class DraftCard(MfgModel):
    draft_id: str
    kind: DraftKind
    summary: str
    method: Literal["POST", "PUT"]
    path: str                               # /api/v1/... (exact request)
    body: dict[str, Any]
    if_match_of: IfMatchOf | None = None
    required_permission: str
    allowed: bool                           # the asking user holds `required_permission` (UI disables Apply)
    applied_at: datetime | None = None
    applied_status: Literal["succeeded", "failed"] | None = None
    response_ref: str | None = None


class TurnError(MfgModel):
    code: str
    message: str


class Tokens(MfgModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0


class TurnRecord(MfgModel):
    id: str
    conversation_id: str
    status: TurnStatus
    user_text: str
    context: TurnContext | None = None
    allow_whatif: bool = False
    steps: list[TurnStep] = Field(default_factory=list)
    answer: str | None = None               # markdown subset; markers [R7] resolved through `citations`
    citations: list[Citation] = Field(default_factory=list)
    drafts: list[DraftCard] = Field(default_factory=list)
    error: TurnError | None = None
    model: str | None = None
    fallback_code: str | None = None
    tokens: Tokens = Field(default_factory=Tokens)
    rounds: int = 0
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ConversationRecord(MfgModel):
    id: str
    title: str
    allow_whatif: bool
    created_at: datetime
    updated_at: datetime
    turns: int = 0


class ConversationDetail(ConversationRecord):
    history: list[TurnRecord] = Field(default_factory=list)   # oldest first


class DraftApplied(MfgModel):
    status: Literal["succeeded", "failed"]
    response_ref: Annotated[str, StringConstraints(max_length=200)] | None = None


class QuickItem(MfgModel):
    text: str
    refs: list[str] = Field(default_factory=list)          # citation refs (Q1, Q2, ...)


class QuickSection(MfgModel):
    title: str
    items: list[QuickItem] = Field(default_factory=list)


class QuickExplanation(MfgModel):
    kind: QuickKind
    title: str
    subject: dict[str, Any] | None = None   # {type, id, label}
    sections: list[QuickSection] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)       # the existing endpoints the answer came from
    empty_message: str = ""


__all__ = ["AssistantPlantSettings", "AssistantStatus", "BudgetLeft", "Citation", "ConversationDetail",
           "ConversationInput", "ConversationRecord", "DraftApplied", "DraftCard", "EntityId", "IfMatchOf",
           "PRIVACY_NOTICE", "QuickExplanation", "QuickItem", "QuickSection", "Tokens", "TurnAccepted", "TurnContext",
           "TurnError", "TurnInput", "TurnRecord", "TurnStep"]

"""`/api/v1/mfg/bulk/...` bulk actions (docs/UX-STANDARD.md "Backend support"; service `services/bulk.py`).

One route per action, each with exactly the permission of the single-record call. Paths live under `/bulk/` so
they never collide with `/{collection}/{id}/{action}`. Body `{"items": [{"id", "row_version"}], ...params}`
(1-200 distinct ids); response 200 with one result per item (also when every item failed).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints, field_validator

from ..context import AppContext, get_ctx
from .router_m2 import P, _idem, _idem_key, _ok
from .schemas_m2 import _Strict
from .services import bulk

router = APIRouter(prefix="/mfg/bulk", tags=["mfg-bulk"])


class BulkRef(_Strict):
    #: plain string like a path id: a malformed / unknown / foreign id is that record's 404, not a 422 of the batch
    id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    row_version: Annotated[int, Field(ge=0, le=2**31 - 1)]


class BulkRequest(_Strict):
    items: Annotated[list[BulkRef], Field(min_length=1, max_length=bulk.MAX_BULK)]

    @field_validator("items")
    @classmethod
    def _distinct(cls, v: list[BulkRef]) -> list[BulkRef]:
        if len({x.id for x in v}) != len(v):
            raise ValueError("each id may appear only once")
        return v


class BulkReleaseRequest(BulkRequest):
    reserve: bool = False
    #: M4-DESIGN 4.1: applied to every WO of the batch that has a first-operation shortage
    override_reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class BulkRejectRequest(BulkRequest):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _respond(action: str, body: BulkRequest, key: str | None, ctx: AppContext) -> JSONResponse:
    out, replay = bulk.run(ctx, action, body.model_dump(mode="json"), _idem(key))
    return _ok(out, 200, headers={"Idempotent-Replay": "true"} if replay else None)


def _route(action: str, model: type[BulkRequest]) -> Any:
    def handler(body: model, idempotency_key: str | None = _idem_key(),  # type: ignore[valid-type]
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
        return _respond(action, body, idempotency_key, ctx)
    handler.__annotations__["body"] = model      # resolved per action (this module uses string annotations)
    return handler


for _action, _perm in bulk.ACTIONS.items():
    _model = BulkReleaseRequest if _action == "work-orders/release" else \
        BulkRejectRequest if _action == "purchase-requests/reject" else BulkRequest
    router.add_api_route(f"/{_action}", _route(_action, _model), methods=["POST"], dependencies=P(_perm),
                         name="bulk_" + _action.replace("-", "_").replace("/", "_"))

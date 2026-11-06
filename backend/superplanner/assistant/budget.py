"""Daily token budgets (M6-DESIGN 1.1, 1.6): `assistant_usage` rows per (day, user, plant); the user's budget
spans all plants, the plant's all users. Day = UTC date."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..api.db import new_id
from ..api.mfg.db_models_m6 import AssistantUsageRow


def today() -> date:
    return datetime.now(UTC).date()


def left(s: Session, settings: Any, user_id: str, owner_id: str, day: date | None = None) -> tuple[int, int]:
    d = day or today()
    U = AssistantUsageRow
    used_user = int(s.execute(select(func.coalesce(func.sum(U.tokens), 0)).where(U.day == d, U.user_id == user_id))
                    .scalar() or 0)
    used_plant = int(s.execute(select(func.coalesce(func.sum(U.tokens), 0)).where(U.day == d, U.owner_id == owner_id))
                     .scalar() or 0)
    return (max(0, int(settings.assistant_daily_tokens_per_user) - used_user),
            max(0, int(settings.assistant_daily_tokens_per_plant) - used_plant))


def add(s: Session, user_id: str, owner_id: str, tokens: int, day: date | None = None) -> None:
    d = day or today()
    stmt = pg_insert(AssistantUsageRow).values(id=new_id("asu_"), day=d, user_id=user_id, owner_id=owner_id,
                                               tokens=int(tokens), calls=1)
    stmt = stmt.on_conflict_do_update(constraint="uq_assistant_usage_key", set_={
        "tokens": AssistantUsageRow.tokens + int(tokens), "calls": AssistantUsageRow.calls + 1})
    s.execute(stmt)


#: a turn is refused before the model is called when less than this is left (1 round with the cached prompt)
MIN_TURN_TOKENS = 4000

"""Row-lock helpers (PHASE2B 2.12).

Lock strength (review R4): plan/problem and run rows are locked `FOR NO KEY UPDATE` (`key_share=True`), which does
not conflict with the implicit `FOR KEY SHARE` that inserting a child row (event, schedule, result) takes on its
parent. Plain `FOR UPDATE` is used only by deletes. Lock order: plan/problem -> run -> job.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def lock_row(s: Session, model: Any, row_id: str) -> bool:
    """`SELECT id ... FOR NO KEY UPDATE`; False if the row does not exist (or is not visible to the owner)."""
    return s.execute(select(model.id).where(model.id == row_id).with_for_update(key_share=True)).first() is not None


def lock_parent_key_share(s: Session, model: Any, row_id: str) -> bool:
    """`SELECT id ... FOR KEY SHARE` on a parent before locking a child run row (worker final transactions)."""
    return s.execute(select(model.id).where(model.id == row_id)
                     .with_for_update(read=True, key_share=True)).first() is not None


def get_locked(s: Session, model: Any, row_id: str, *, for_delete: bool = False) -> Any:
    """`Session.get` with a row lock: FOR NO KEY UPDATE, or plain FOR UPDATE when the row will be deleted."""
    lock: Any = True if for_delete else {"key_share": True}
    return s.get(model, row_id, with_for_update=lock)


def is_unique_violation(exc: IntegrityError, index_name: str, _columns: str = "") -> bool:
    """True if `exc` comes from the given unique index/constraint (PostgreSQL names it in the error).
    `_columns` is ignored (kept for existing call sites)."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    if diag is not None and getattr(diag, "constraint_name", None) == index_name:
        return True
    return index_name in str(orig if orig is not None else exc)

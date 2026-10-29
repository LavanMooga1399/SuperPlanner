"""Central ownership enforcement at the ORM layer (PHASE2B 4.7).

Every owned table mixes in `OwnedMixin` (`owner_id` FK users.id). `install(db, single_user)` registers two
session events on the Database's session factories:

1. `do_orm_execute`: every ORM SELECT/UPDATE/DELETE that touches an owned entity gets
   `with_loader_criteria(OwnedMixin, owner_id == <current user>)`. `SYSTEM` scope -> unfiltered. Unbound inside an
   HTTP request -> `OwnershipViolation` (fail closed, 500). Unbound outside a request (tests, CLI, worker threads,
   which do not inherit request context vars) -> system.
2. `before_flush`: new owned rows without `owner_id` get the bound user; unbound/system -> `usr_local` in
   single_user mode, else `OwnershipViolation` (workers always set `owner_id` explicitly).

Raw SQL (`text()`, `engine.connect()`) is never filtered; services do not use it (B 3.5.6).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Table, event
from sqlalchemy.sql import visitors
from sqlalchemy.orm import Mapped, ORMExecuteState, Session, mapped_column, with_loader_criteria

if TYPE_CHECKING:  # pragma: no cover
    from .session import Database

log = logging.getLogger(__name__)

LOCAL_USER_ID = "usr_local"


class _System:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "SYSTEM"


SYSTEM: Any = _System()

_owner: ContextVar[Any] = ContextVar("sp_owner", default=None)          # None = unbound
_in_request: ContextVar[bool] = ContextVar("sp_in_request", default=False)


class OwnershipViolation(RuntimeError):
    """A query on an owned table ran inside an HTTP request without a bound user (or an insert had no owner)."""


class OwnedMixin:
    """Root tables owned by one user. Children reached only through an owned parent carry no owner_id.

    The FK is named by the metadata naming convention (`fk_<table>_owner_id_users`, as in migration 0002)."""

    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def current_owner() -> Any:
    """The bound user id, `SYSTEM`, or None (unbound)."""
    return _owner.get()


def in_request() -> bool:
    return _in_request.get()


def bind_owner(user_id: str) -> None:
    """Bind a user for the rest of the current context (used by `require_user`; the var lives for the request).
    Clears the actor binding (M2-DESIGN 10.1): the actor is re-bound by the mfg workspace dependency."""
    _owner.set(user_id)
    _actor.set(None)


_actor: ContextVar[str | None] = ContextVar("sp_actor", default=None)


def bind_actor(user_id: str | None) -> None:
    """M2-DESIGN 10.1: the real user acting in a (possibly foreign) workspace; audit `actor_id` uses it."""
    _actor.set(user_id)


def current_actor() -> str | None:
    return _actor.get()


@contextmanager
def owner_scope(user_id: str) -> Iterator[None]:
    token = _owner.set(user_id)
    try:
        yield
    finally:
        _owner.reset(token)


@contextmanager
def system_scope() -> Iterator[None]:
    """Workers, reaper, recovery, migrations, CLI, lazy app start: unfiltered access."""
    token = _owner.set(SYSTEM)
    try:
        yield
    finally:
        _owner.reset(token)


@contextmanager
def request_scope() -> Iterator[None]:
    """Mark the current context as an HTTP request (OwnershipScopeMiddleware; tests)."""
    token = _in_request.set(True)
    try:
        yield
    finally:
        _in_request.reset(token)


def _owned_tables() -> frozenset[str]:
    global _OWNED_TABLES
    if _OWNED_TABLES is None:
        names = set()
        stack = list(OwnedMixin.__subclasses__())
        while stack:
            cls = stack.pop()
            stack.extend(cls.__subclasses__())
            table = getattr(cls, "__table__", None)
            if table is not None:
                names.add(table.name)
        _OWNED_TABLES = frozenset(names)
    return _OWNED_TABLES


_OWNED_TABLES: frozenset[str] | None = None


def _touches_owned(state: ORMExecuteState) -> bool:
    """True if any owned table appears anywhere in the statement (incl. `select(func.count()).select_from(M)`,
    whose `all_mappers` is empty, and subqueries)."""
    try:
        if any(issubclass(m.class_, OwnedMixin) for m in state.all_mappers):
            return True
    except Exception:  # pragma: no cover - fall through to the structural scan
        pass
    owned = _owned_tables()
    for element in visitors.iterate(state.statement):
        if isinstance(element, Table) and element.name in owned:
            return True
    return False


def _on_execute(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.is_column_load or state.is_relationship_load:
        return  # the parent load was already filtered
    owner = _owner.get()
    if owner is SYSTEM:
        return
    if owner is None:
        if _in_request.get() and _touches_owned(state):
            log.error("OwnershipViolation: unbound query on an owned table inside a request: %s",
                      str(state.statement).replace("\n", " ")[:500])
            raise OwnershipViolation("query on an owned table without a bound user")
        return  # outside a request (tests, CLI, worker threads): system
    # A bound user: always add the criteria (a no-op for statements without owned entities).
    state.statement = state.statement.options(
        with_loader_criteria(OwnedMixin, lambda cls: cls.owner_id == owner, include_aliases=True))


def _make_before_flush(single_user: bool):
    def _before_flush(session: Session, _ctx: Any, _instances: Any) -> None:
        for obj in session.new:
            if not isinstance(obj, OwnedMixin) or getattr(obj, "owner_id", None):
                continue
            owner = _owner.get()
            if isinstance(owner, str):
                obj.owner_id = owner
            elif single_user:
                obj.owner_id = LOCAL_USER_ID
            else:
                log.error("OwnershipViolation: insert of %s without owner_id", type(obj).__name__)
                raise OwnershipViolation(f"insert of {type(obj).__name__} without an owner")
    return _before_flush


def install(db: "Database", single_user: bool) -> None:
    """Register the ownership hooks on the Database's session factories (idempotent per Database)."""
    if getattr(db, "_ownership_installed", False):
        return
    before_flush = _make_before_flush(single_user)
    for factory in db.session_factories:
        event.listen(factory, "do_orm_execute", _on_execute)
        event.listen(factory, "before_flush", before_flush)
    db._ownership_installed = True  # type: ignore[attr-defined]


class OwnershipScopeMiddleware:
    """Pure ASGI: marks every HTTP request so unbound owned-table queries fail closed."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _in_request.set(True)
        try:
            await self.app(scope, receive, send)
        finally:
            _in_request.reset(token)

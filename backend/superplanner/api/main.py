"""FastAPI app factory (A.14, PHASE2B 4.4/4.7): `create_app(settings)` plus module-level `app` for uvicorn.

Creating an app has no side effects; the schema check (or AUTO_MIGRATE upgrade), startup recovery and the job
backend start in the lifespan (or lazily on the first request, e.g. for a `TestClient` used without `with`).
The module-level `app` (what uvicorn imports) is built lazily on first attribute access and checks configuration
and schema before uvicorn starts serving: a missing/invalid DATABASE_URL or weak production setting exits 2, a
database not at `migrate.HEAD` (or unreachable) exits 3, each with one clear line on stderr.

Operations (Q5, PHASE2B 5.2-5.4): `RequestContextMiddleware` is the outermost layer (request id on every
response incl. 413/CORS, access line, HTTP metrics); `/metrics` at the root (unless METRICS_ENABLED=false);
`configure_logging` replaces `logging.basicConfig` and only acts if logging is not configured yet.

Wiring (complete since Q1): every data router is included with `Depends(require_user)`, which
binds the request's owner for the ORM ownership filter; `health` and `auth` routers without it. The
`OwnershipScopeMiddleware` marks HTTP requests so unbound owned-table queries fail closed. CORS allows
credentials only in accounts mode and exposes the 2b headers.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from superplanner import engine
from superplanner.obs.logging import configure_logging
from superplanner.obs.request_context import RequestContextMiddleware

from .auth import body_gate
from .auth import passwords
from .auth import router as auth_router
from .auth.deps import require_user
from .config import ConfigError, Settings
from .context import AppContext
from .db.ownership import OwnershipScopeMiddleware
from .errors import install_handlers
from .finance import router as finance_router
from .intake import router as intake_router
from .intake import service as intake_service
from .limits import BodySizeLimitMiddleware
from .mfg import router as mfg_router
from .mfg import router_m2 as mfg_router_m2
from .mfg import router_m3 as mfg_router_m3
from .routes import health, metrics, problems, schedules, solver_runs, templates

API_PREFIX = "/api/v1"
EXPOSE_HEADERS = ["ETag", "Location", "Content-Disposition", "X-Request-ID", "Idempotent-Replayed", "Retry-After"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings, "api")
    ctx = AppContext(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(ctx.start)
        try:
            yield
        finally:
            await run_in_threadpool(ctx.stop)

    app = FastAPI(title="SuperPlanner API", version=engine.__version__, lifespan=lifespan)
    app.state.ctx = ctx
    app.state.settings = settings
    # Inner to outer: ownership marker, body limits, CORS (so a 413 still carries the CORS headers), request
    # context (outermost: every response carries X-Request-ID and is logged/measured once).
    app.add_middleware(OwnershipScopeMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins or []),
                       allow_credentials=settings.cors_allow_credentials, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=EXPOSE_HEADERS)
    app.add_middleware(RequestContextMiddleware)
    install_handlers(app)
    passwords.configure_hash_slots(settings.hash_concurrency, settings.auth_hash_wait_seconds)   # per process
    if settings.auth_mode == "accounts":
        passwords.warm_dummy_hash(settings.password_hash_profile)   # no cold-start burst of unbounded hashes
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth_router.router, prefix=API_PREFIX)   # auth routes resolve the session themselves
    protected = (templates.router, problems.router, solver_runs.router, schedules.router, finance_router.router,
                 intake_router.router, mfg_router.router, mfg_router_m2.router,
                 mfg_router_m3.router)
    for r in protected:
        app.include_router(r, prefix=API_PREFIX, dependencies=[Depends(require_user)])
    body_gate.install(app, protected)   # 401/403 before 422 also for unparseable JSON bodies
    if settings.metrics_enabled:
        app.include_router(metrics.router)   # root, outside /api/v1 (B 5.4)
    intake_service.install(app, settings)   # per-app AI concurrency slots (PHASE2 2.10)
    return app


def _module_app() -> FastAPI:
    try:
        settings = Settings()
    except ConfigError as exc:   # uvicorn imports this module: exit 2 with one clear line (PHASE2B 5.1)
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    _preflight_schema(settings)
    return create_app(settings)


def _preflight_schema(settings: Settings) -> None:
    """Refuse to serve before uvicorn starts if the schema is not at head (AUTO_MIGRATE: upgrade first)."""
    import sqlalchemy as sa

    from superplanner import migrate

    from .db import Database
    from .db.ownership import system_scope

    db = Database.from_settings(settings, service="api")
    try:
        with system_scope():
            migrate.ensure_schema(db, settings)
    except migrate.SchemaError as exc:
        print(f"schema error: {exc}", file=sys.stderr)
        raise SystemExit(3) from None
    except sa.exc.OperationalError as exc:
        print(f"cannot reach the database: {str(exc.orig or exc).splitlines()[0]}", file=sys.stderr)
        raise SystemExit(3) from None
    finally:
        db.dispose()


_APP: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """`superplanner.api.main:app` for uvicorn, built on first access (importing this module has no side effects,
    so tests can import `create_app` without DATABASE_URL)."""
    global _APP
    if name != "app":
        raise AttributeError(name)
    if _APP is None:
        _APP = _module_app()
    return _APP

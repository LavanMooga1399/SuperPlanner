"""FastAPI app factory (A.14): `create_app(settings)` plus module-level `app` for uvicorn.

Creating an app has no side effects; tables, startup recovery and the run executor start in the
lifespan (or lazily on the first request, e.g. for a `TestClient` used without `with`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from superplanner import engine

from .config import Settings
from .context import AppContext
from .errors import install_handlers
from .finance import router as finance_router
from .limits import BodySizeLimitMiddleware
from .routes import health, problems, schedules, solver_runs, templates

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
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
    # Added before CORS so CORS stays the outer layer and a 413 still carries the CORS headers.
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["ETag", "Location",
                                                                                 "Content-Disposition"])
    install_handlers(app)
    for r in (health.router, templates.router, problems.router, solver_runs.router, schedules.router,
              finance_router.router):
        app.include_router(r, prefix=API_PREFIX)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()

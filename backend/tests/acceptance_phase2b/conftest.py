"""Q6 acceptance suite (PLAN-PHASE2B 7): end-to-end scenarios with real API/worker processes.

SQLite run: the single_user/inline scenarios (and the in-process authorization sweep).
PostgreSQL run (SP_TEST_DB=postgres): queue/accounts scenarios with worker subprocesses, chaos and restarts.
"""

from __future__ import annotations

import sys
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parents[1]), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

warnings.filterwarnings("ignore", message=".*httpx2.*")

from acc_helpers import Db, Proc, load_int_helpers  # noqa: E402

# Import at collection time: `superplanner.api.main` builds its module-level app from the environment, and the root
# conftest's Postgres env (JOB_BACKEND=queue without DATABASE_URL) would make that import exit 2 inside a test.
load_int_helpers()


@pytest.fixture
def db_url(db_url_factory) -> str:
    return db_url_factory("acc")


@pytest.fixture
def db(db_url: str) -> Iterator[Db]:
    d = Db(db_url)
    yield d
    d.dispose()


@pytest.fixture
def procs(request: pytest.FixtureRequest) -> Iterator[list[Proc]]:
    """Every process appended here is killed at teardown (and its log tail shown on failure)."""
    started: list[Proc] = []
    yield started
    failed = getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed
    for p in started:
        try:
            p.stop(timeout=10)
        except Exception:  # pragma: no cover
            pass
        if failed:
            sys.stderr.write(f"\n----- {p.name} log tail -----\n{p.log_text()[-4000:]}\n")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)

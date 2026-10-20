"""`scripts/pg_dev_cluster.sh` (PHASE2B 3.6; Q1-13): init/start/url/stop as root in a scratch dir, idempotent,
and `postgres` never runs as uid 0."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pg_dev_cluster.sh"
PG_BIN = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin"))

pytestmark = [
    pytest.mark.postgres_only,
    pytest.mark.skipif(os.name == "nt" or not (PG_BIN / "initdb").exists() or shutil.which("bash") is None,
                       reason="needs bash and the PostgreSQL server binaries"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(*args: str) -> str:
    p = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout.strip()


def test_cluster_lifecycle():
    base = Path(tempfile.mkdtemp(prefix="sp-pgtest-"))
    data, port = base / "pgdata", str(_free_port())
    try:
        assert "cluster created" in _run("init", str(data), port)
        assert "already running" in _run("init", str(data), port)       # idempotent
        assert "already running" in _run("start", str(data), port)
        url = _run("url", str(data), port)
        assert url == f"postgresql+psycopg://sp_test:sp_test@127.0.0.1:{port}/postgres"
        pid = int((data / "postmaster.pid").read_text().split()[0])
        assert os.stat(f"/proc/{pid}").st_uid != 0                       # never runs as root
        eng = sa.create_engine(url)
        try:
            with eng.connect() as c:
                assert c.execute(sa.text("SELECT rolcreatedb FROM pg_roles WHERE rolname = 'sp_test'")).scalar()
                assert c.execute(sa.text("SHOW listen_addresses")).scalar() == "127.0.0.1"
                assert c.execute(sa.text("SELECT datcollate FROM pg_database WHERE datname = 'postgres'")
                                 ).scalar() == "C"
        finally:
            eng.dispose()
        assert "stopped" in _run("stop", str(data))
        assert "not running" in _run("stop", str(data))                    # idempotent
        assert "started" in _run("start", str(data), port)
        assert "stopped" in _run("stop", str(data))
    finally:
        subprocess.run(["bash", str(SCRIPT), "stop", str(data)], capture_output=True, timeout=60)
        shutil.rmtree(base, ignore_errors=True)

"""Fix round: packaged wheel data files (common_passwords.txt) and the hardened backend image."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from ops_helpers import BACKEND, REPO

PKG = BACKEND / "superplanner"


def _pyproject() -> dict:
    return tomllib.loads((BACKEND / "pyproject.toml").read_text())


def _data_files() -> list[Path]:
    return sorted(p for p in PKG.rglob("*")
                  if p.is_file() and p.suffix not in {".py", ".pyc"} and "__pycache__" not in p.parts)


# ---------------------------------------------------------------- package data

def test_every_package_data_file_is_declared():
    """Every non-Python file inside the package is listed in [tool.setuptools.package-data] (so wheels carry it)."""
    declared: dict[str, list[str]] = _pyproject()["tool"]["setuptools"]["package-data"]
    files = _data_files()
    assert any(p.name == "common_passwords.txt" for p in files)
    missing = []
    for p in files:
        rel = p.relative_to(BACKEND)
        pkg = ".".join(rel.parent.parts)
        patterns = declared.get(pkg, []) + declared.get("*", [])
        if not any(fnmatch.fnmatch(p.name, pat) for pat in patterns):
            missing.append(str(rel))
    assert not missing, f"not in package-data: {missing}"


def _build_wheel(out: Path) -> Path:
    """Build from a copy of the sources, so setuptools' build/ and egg-info output never touches the checkout."""
    src = out.parent / "src"
    src.mkdir()
    shutil.copy2(BACKEND / "pyproject.toml", src / "pyproject.toml")
    shutil.copytree(PKG, src / "superplanner", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    p = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(out), str(src)],
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        pytest.skip(f"cannot build the wheel here (needs setuptools from the index): {p.stderr[-300:]}")
    wheels = list(out.glob("superplanner-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


@pytest.mark.slow
def test_wheel_contains_data_and_sign_up_works_from_it(tmp_path):
    """A non-editable install (the unpacked wheel, outside the source tree) accepts a sign-up (was 500)."""
    whl = _build_wheel(tmp_path / "out")
    names = zipfile.ZipFile(whl).namelist()
    assert "superplanner/api/auth/common_passwords.txt" in names
    assert "superplanner/migrations/script.py.mako" in names
    site = tmp_path / "site"
    zipfile.ZipFile(whl).extractall(site)
    script = (
        "import superplanner, sys\n"
        "assert superplanner.__file__.startswith(sys.argv[1]), superplanner.__file__\n"
        "from fastapi.testclient import TestClient\n"
        "from superplanner.api.config import Settings\n"
        "from superplanner.api.main import create_app\n"
        "app = create_app(Settings(database_url='sqlite:///' + sys.argv[2], auth_mode='accounts',\n"
        "                          password_hash_profile='fast', cookie_secure=False))\n"
        "with TestClient(app) as c:\n"
        "    r = c.post('/api/v1/auth/sign-up', json={'email': 'ana@example.com',\n"
        "               'password': 'correct horse battery staple'})\n"
        "    print(r.status_code, r.text[:200])\n"
        "    assert r.status_code == 201 and r.json()['authenticated'] is True\n"
    )
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("JOB_", "WORKER_", "AUTH_", "SP_", "PASSWORD_", "CORS_", "DATABASE_"))}
    env["PYTHONPATH"] = str(site)
    p = subprocess.run([sys.executable, "-c", script, str(site), str(tmp_path / "w.db")],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, (p.stdout, p.stderr[-2000:])


# ---------------------------------------------------------------- image hardening

def _req_pins(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)==(\S+)$", line)
        if m:
            out[re.sub(r"\[.*\]", "", m.group(1)).lower()] = m.group(2)
    return out


def test_runtime_requirements_exclude_test_packages_and_keep_pins():
    runtime = _req_pins(BACKEND / "requirements-runtime.txt")
    full = _req_pins(BACKEND / "requirements.txt")
    assert "pytest" not in runtime and "httpx" not in runtime
    assert {"pytest", "httpx"} <= set(full)
    # every runtime pin is also in requirements.txt with the same version
    assert all(full.get(k) == v for k, v in runtime.items()), (runtime, full)
    # runtime == pyproject [project].dependencies
    deps = {}
    for d in _pyproject()["project"]["dependencies"]:
        name, ver = d.split("==")
        deps[re.sub(r"\[.*\]", "", name).lower()] = ver
    assert runtime == deps


def test_backend_image_code_is_not_writable_by_runtime_user():
    text = (BACKEND / "Dockerfile").read_text()
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    assert "chown" not in code, "the runtime user must not own /app"
    assert "requirements-runtime.txt" in code
    assert not re.search(r"pip install[^\n]*-r requirements\.txt", code)
    assert "USER 10001" in code
    assert "requirements-runtime.txt" not in (BACKEND / ".dockerignore").read_text()


def test_compose_backend_services_hardened():
    import yaml

    text = (REPO / "docker-compose.yml").read_text()
    text = re.sub(r"\$\{([A-Z_]+):-([^}]*)\}", r"\2", text)
    text = re.sub(r"\$\{([A-Z_]+):\?[^}]*\}", "x", text)
    s = yaml.safe_load(text)["services"]
    for name in ("migrate", "api", "worker"):
        svc = s[name]
        assert svc.get("read_only") is True, name
        assert svc.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in svc.get("security_opt", []), name
        assert any(str(t).startswith("/tmp") for t in svc.get("tmpfs", [])), name


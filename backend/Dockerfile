# syntax=docker/dockerfile:1
# SuperPlanner backend images (PHASE2B 5.5). Build from the repo root via docker-compose.yml, or:
#   docker build -f backend/Dockerfile --target api    -t superplanner-api    backend
#   docker build -f backend/Dockerfile --target worker -t superplanner-worker backend
# Both targets run as the non-root user "sp" (uid 10001). SP_ENV=production and LOG_FORMAT=json are image defaults.
# /app stays owned by root (read-only for uid 10001): nothing at runtime writes under /app, so a file-write bug in
# the API cannot change the application code. Only runtime dependencies are installed (no pytest/httpx extras).

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SP_ENV=production \
    LOG_FORMAT=json
WORKDIR /app
COPY requirements-runtime.txt ./
RUN pip install -r requirements-runtime.txt \
 && groupadd --gid 10001 sp \
 && useradd --uid 10001 --gid sp --no-create-home --home-dir /app --shell /usr/sbin/nologin sp
COPY alembic.ini pyproject.toml ./
COPY superplanner/ ./superplanner/
RUN python -m compileall -q superplanner
USER 10001:10001

# ---------------------------------------------------------------- API
FROM base AS api
# Only the fixed internal subnet of docker-compose.yml (the nginx container) may set X-Forwarded-For (R10).
ENV FORWARDED_ALLOW_IPS=127.0.0.1 HOST=0.0.0.0 PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=4)"]
# sh -c so FORWARDED_ALLOW_IPS/PORT are expanded at start; exec keeps uvicorn as PID 1 (receives SIGTERM).
CMD ["sh", "-c", "exec uvicorn superplanner.api.main:app --host \"$HOST\" --port \"$PORT\" --proxy-headers --forwarded-allow-ips=\"$FORWARDED_ALLOW_IPS\" --no-access-log"]

# ---------------------------------------------------------------- worker
FROM base AS worker
ENV WORKER_METRICS_PORT=9101
EXPOSE 9101
# The worker's metrics endpoint doubles as its liveness probe (PHASE2B 5.2).
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/metrics' % os.environ.get('WORKER_METRICS_PORT', '9101'), timeout=4)"]
STOPSIGNAL SIGTERM
CMD ["python", "-m", "superplanner.worker"]

"""API settings (ARCHITECTURE 13, 14, 16; PHASE2B 5.1). Read from the environment; tests pass explicit values.

PostgreSQL only (ARCHITECTURE "Implementation notes: PostgreSQL-only"): `DATABASE_URL` is required and must be a
`postgresql+psycopg://` URL (`postgres://` / `postgresql://` are normalised). `APP_ENV` (legacy alias `SP_ENV`)
defaults to `production`; `development` must be set explicitly and is the only environment that allows
`AUTH_MODE=single_user`, permissive CORS, plain-http cookies or a missing metrics token.

Fields whose default depends on another setting (`APP_ENV`) default to `None` and are resolved in `__post_init__`;
explicit constructor values always win. Invalid combinations raise `ConfigError` (the API / worker / CLI entry points
print one line and exit with code 2).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATABASE_URL_EXAMPLE = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME"
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)
APP_ENVS = ("development", "production")
SP_ENVS = APP_ENVS   # legacy name
JOB_BACKENDS = ("inline", "queue")
AUTH_MODES = ("single_user", "accounts")
PASSWORD_HASH_PROFILES = ("default", "fast")
LOG_FORMATS = ("text", "json")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
JOB_KINDS = ("solver_run", "finance_run", "aps_run")


class ConfigError(ValueError):
    """Invalid configuration. Entry points print the message and exit with code 2."""


def normalize_database_url(url: str) -> str:
    """`postgres://` and `postgresql://` -> `postgresql+psycopg://` (psycopg 3); everything else unchanged."""
    u = (url or "").strip()
    for prefix in ("postgres://", "postgresql://"):
        if u.startswith(prefix):
            return "postgresql+psycopg://" + u[len(prefix):]
    return u


def is_postgres_url(url: str) -> bool:
    return normalize_database_url(url).startswith("postgresql+psycopg://")


def validate_database_url(url: str | None, name: str = "DATABASE_URL") -> str:
    """The normalised URL, or ConfigError with one line naming the variable and the expected form."""
    if not url or not url.strip():
        raise ConfigError(f"{name} is required (PostgreSQL only), e.g. {name}={DATABASE_URL_EXAMPLE}")
    u = normalize_database_url(url)
    if not is_postgres_url(u):
        scheme = u.split(":", 1)[0] if ":" in u else u[:20]
        raise ConfigError(f"{name} must be a PostgreSQL URL ({DATABASE_URL_EXAMPLE}); got scheme {scheme!r}.")
    return u


def resolve_migration_url(explicit: str | None = None) -> str:
    """URL for schema changes: explicit (`--url`), else MIGRATION_DATABASE_URL, else DATABASE_URL (validated)."""
    if explicit:
        return validate_database_url(explicit, "--url")
    if _env("MIGRATION_DATABASE_URL"):
        return validate_database_url(_env("MIGRATION_DATABASE_URL"), "MIGRATION_DATABASE_URL")
    return validate_database_url(_env("DATABASE_URL"), "DATABASE_URL")


# Placeholder / well-known values refused as secrets outside development (DB passwords, METRICS_TOKEN).
WEAK_SECRETS = frozenset({"", "postgres", "password", "passw0rd", "secret", "changeme", "change-me", "change_me",
                          "superplanner", "sp_test", "sp_dev", "admin", "test", "example", "default", "123456",
                          "12345678", "letmein", "qwerty"})
MIN_DB_PASSWORD_CHARS = 12
MIN_METRICS_TOKEN_CHARS = 24


def _is_weak(secret: str | None, minimum: int) -> bool:
    if secret is None:
        return True
    low = secret.strip().lower()
    return (len(low) < minimum or low in WEAK_SECRETS or ("change" in low and "me" in low)
            or len(set(low)) < 4)


def _db_password(url: str) -> str | None:
    from sqlalchemy.engine import make_url

    try:
        return make_url(url).password  # type: ignore[return-value]
    except Exception:
        return None


# ---------------------------------------------------------------- env helpers

def _env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v is not None and v.strip() != "" else None


def _env_origins() -> list[str] | None:
    raw = os.environ.get("CORS_ORIGINS")
    if raw is None:
        return None   # resolved per APP_ENV in __post_init__
    return [o.strip() for o in raw.split(",") if o.strip()]


def _env_max_body() -> int:
    try:
        return max(1024, int(os.environ.get("MAX_BODY_BYTES", str(5 * 1024 * 1024))))
    except ValueError:
        return 5 * 1024 * 1024


def _env_workers() -> int:
    try:
        return max(1, int(os.environ.get("RUN_WORKERS", "2")))
    except ValueError:
        return 2


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return v if v > 0 else default


def _env_bool_opt(name: str) -> bool | None:
    raw = _env(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false (got {raw!r}).")


def _int(name: str, default: int, minimum: int = 0) -> Callable[[], int]:
    def f() -> int:
        raw = _env(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except ValueError:
            raise ConfigError(f"{name} must be an integer (got {raw!r}).") from None
        if v < minimum:
            raise ConfigError(f"{name} must be >= {minimum} (got {v}).")
        return v
    return f


def _float(name: str, default: float) -> Callable[[], float]:
    def f() -> float:
        raw = _env(name)
        if raw is None:
            return default
        try:
            v = float(raw)
        except ValueError:
            raise ConfigError(f"{name} must be a number (got {raw!r}).") from None
        if v <= 0:
            raise ConfigError(f"{name} must be > 0 (got {v}).")
        return v
    return f


def _str(name: str, default: str | None = None) -> Callable[[], str | None]:
    return lambda: _env(name) or default


def _bool(name: str, default: bool) -> Callable[[], bool]:
    def f() -> bool:
        v = _env_bool_opt(name)
        return default if v is None else v
    return f


def _opt_bool(name: str) -> Callable[[], bool | None]:
    return lambda: _env_bool_opt(name)


def _lower(name: str) -> Callable[[], str | None]:
    return lambda: (_env(name) or "").lower() or None


def _app_env() -> str | None:
    app, legacy = _env("APP_ENV"), _env("SP_ENV")
    if app and legacy and app.lower() != legacy.lower():
        raise ConfigError(f"APP_ENV={app!r} and its legacy alias SP_ENV={legacy!r} disagree; set only APP_ENV.")
    return (app or legacy or "").lower() or None


def _auto_migrate() -> bool | None:
    v = _env_bool_opt("AUTO_MIGRATE")
    return _env_bool_opt("DB_AUTO_MIGRATE") if v is None else v


def _worker_embedded() -> int | str | None:
    raw = _env("WORKER_EMBEDDED")
    if raw is None:
        return None
    if raw.lower() == "auto":
        return "auto"
    try:
        v = int(raw)
    except ValueError:
        raise ConfigError(f"WORKER_EMBEDDED must be 'auto' or an integer (got {raw!r}).") from None
    if v < 0:
        raise ConfigError(f"WORKER_EMBEDDED must be >= 0 (got {v}).")
    return v


def _worker_kinds() -> list[str]:
    raw = _env("WORKER_KINDS")
    if raw is None:
        return list(JOB_KINDS)
    return [k.strip() for k in raw.split(",") if k.strip()]


# ---------------------------------------------------------------- settings

@dataclass
class Settings:
    # --- existing (Phase 1/2/2a)
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL") or "")
    cors_origins: list[str] | None = field(default_factory=_env_origins)
    run_workers: int = field(default_factory=_env_workers)
    max_body_bytes: int = field(default_factory=_env_max_body)   # 413 PAYLOAD_TOO_LARGE above this
    sse_poll_seconds: float = 0.5
    sse_keepalive_seconds: float = 15.0
    progress_min_interval_seconds: float = 0.5   # max 2 progress events per second per run
    # Intake (PHASE2 2.12). AI assist is off unless INTAKE_AI_ENABLED is set and credentials resolve.
    intake_ai_enabled: bool = field(default_factory=lambda: _env_flag("INTAKE_AI_ENABLED"))
    intake_ai_timeout_seconds: float = field(default_factory=lambda: _env_float("INTAKE_AI_TIMEOUT_SECONDS", 60.0))
    intake_ai_max_retries: int = 2
    intake_ai_max_concurrent: int = 2
    intake_max_text_chars: int = 20000
    intake_max_table_chars: int = 1_000_000
    intake_ai_client_factory: Callable[[], Any] | None = None   # tests only: returns a fake SDK client

    # --- environment and database (PostgreSQL only)
    # APP_ENV (legacy alias SP_ENV); None -> production. Constructor name kept as `sp_env` for compatibility.
    sp_env: str | None = field(default_factory=_app_env)
    # Owner role URL for schema changes (AUTO_MIGRATE, `superplanner.migrate`); None -> DATABASE_URL.
    migration_database_url: str | None = field(default_factory=_str("MIGRATION_DATABASE_URL"))
    db_pool_size: int = field(default_factory=_int("DB_POOL_SIZE", 10, 1))
    db_max_overflow: int = field(default_factory=_int("DB_MAX_OVERFLOW", 10, 0))
    db_pool_timeout_seconds: float = field(default_factory=_float("DB_POOL_TIMEOUT_SECONDS", 30.0))
    db_pool_recycle_seconds: int = field(default_factory=_int("DB_POOL_RECYCLE_SECONDS", 1800, 0))
    db_pool_pre_ping: bool = field(default_factory=_bool("DB_POOL_PRE_PING", True))
    db_statement_timeout_ms: int = field(default_factory=_int("DB_STATEMENT_TIMEOUT_MS", 30000, 0))
    db_lock_timeout_ms: int = field(default_factory=_int("DB_LOCK_TIMEOUT_MS", 10000, 0))
    db_connect_timeout_seconds: int = field(default_factory=_int("DB_CONNECT_TIMEOUT_SECONDS", 10, 1))
    # AUTO_MIGRATE (legacy alias DB_AUTO_MIGRATE): upgrade the schema at startup. Default false everywhere.
    db_auto_migrate: bool | None = field(default_factory=_auto_migrate)

    # --- Phase 2b: jobs and workers (B 2.2-2.9)
    job_backend: str | None = field(default_factory=_lower("JOB_BACKEND"))
    worker_embedded: int | str | None = field(default_factory=_worker_embedded)
    worker_concurrency: int = field(default_factory=_int("WORKER_CONCURRENCY", 2, 1))
    worker_kinds: list[str] = field(default_factory=_worker_kinds)
    worker_id: str | None = field(default_factory=_str("WORKER_ID"))
    worker_metrics_port: int = field(default_factory=_int("WORKER_METRICS_PORT", 9101, 0))
    worker_poll_seconds: float = field(default_factory=_float("WORKER_POLL_SECONDS", 1.0))
    worker_shutdown_grace_seconds: float = field(default_factory=_float("WORKER_SHUTDOWN_GRACE_SECONDS", 30.0))
    job_lease_seconds: float = field(default_factory=_float("JOB_LEASE_SECONDS", 30.0))
    job_heartbeat_seconds: float = field(default_factory=_float("JOB_HEARTBEAT_SECONDS", 10.0))
    job_cancel_poll_seconds: float = field(default_factory=_float("JOB_CANCEL_POLL_SECONDS", 1.0))
    job_reaper_seconds: float = field(default_factory=_float("JOB_REAPER_SECONDS", 15.0))
    job_max_attempts: int = field(default_factory=_int("JOB_MAX_ATTEMPTS", 3, 1))
    job_backoff_base_seconds: float = field(default_factory=_float("JOB_BACKOFF_BASE_SECONDS", 5.0))
    job_backoff_max_seconds: float = field(default_factory=_float("JOB_BACKOFF_MAX_SECONDS", 300.0))
    job_retention_days: int = field(default_factory=_int("JOB_RETENTION_DAYS", 30, 1))
    idempotency_ttl_hours: int = field(default_factory=_int("IDEMPOTENCY_TTL_HOURS", 24, 1))

    # --- Phase 2b: accounts (B 4.1-4.6)
    auth_mode: str | None = field(default_factory=_lower("AUTH_MODE"))   # None -> accounts (every environment)
    signup_enabled: bool = field(default_factory=_bool("SIGNUP_ENABLED", True))
    session_max_age_days: int = field(default_factory=_int("SESSION_MAX_AGE_DAYS", 30, 1))
    session_idle_days: int = field(default_factory=_int("SESSION_IDLE_DAYS", 7, 1))
    cookie_secure: bool | None = field(default_factory=_opt_bool("COOKIE_SECURE"))
    public_base_url: str | None = field(default_factory=_str("PUBLIC_BASE_URL"))
    password_hash_profile: str = field(default_factory=lambda: (_env("PASSWORD_HASH_PROFILE") or "default").lower())
    auth_rate_limit_enabled: bool = field(default_factory=_bool("AUTH_RATE_LIMIT_ENABLED", True))
    auth_signin_limit_per_ip: int = field(default_factory=_int("AUTH_SIGNIN_LIMIT_PER_IP", 30, 1))
    auth_signin_limit_per_email: int = field(default_factory=_int("AUTH_SIGNIN_LIMIT_PER_EMAIL", 10, 1))
    auth_signup_limit_per_ip: int = field(default_factory=_int("AUTH_SIGNUP_LIMIT_PER_IP", 5, 1))
    auth_change_password_limit_per_user: int = field(
        default_factory=_int("AUTH_CHANGE_PASSWORD_LIMIT_PER_USER", 10, 1))
    # Process-wide argon2 slots (0 = max(1, cpu_count // 2)); a request waits at most AUTH_HASH_WAIT_SECONDS, then 429.
    auth_hash_concurrency: int = field(default_factory=_int("AUTH_HASH_CONCURRENCY", 0, 0))
    auth_hash_wait_seconds: float = field(default_factory=_float("AUTH_HASH_WAIT_SECONDS", 1.0))
    # Inline job backend only (no worker maintenance): how often the API prunes sessions / rate-limit buckets.
    auth_prune_interval_seconds: float = field(default_factory=_float("AUTH_PRUNE_INTERVAL_SECONDS", 600.0))
    trusted_proxy_cidrs: str | None = field(default_factory=_str("TRUSTED_PROXY_CIDRS"))
    forwarded_allow_ips: str = field(default_factory=lambda: _env("FORWARDED_ALLOW_IPS") or "127.0.0.1")

    # --- Phase 2b: operations (B 5.2-5.4)
    log_level: str = field(default_factory=lambda: (_env("LOG_LEVEL") or "INFO").upper())
    log_format: str | None = field(default_factory=_lower("LOG_FORMAT"))
    metrics_enabled: bool = field(default_factory=_bool("METRICS_ENABLED", True))
    metrics_token: str | None = field(default_factory=_str("METRICS_TOKEN"))
    host: str = field(default_factory=lambda: _env("HOST") or "127.0.0.1")
    port: int = field(default_factory=_int("PORT", 8000, 1))

    # warnings collected by validation (logged once by the app / worker)
    warnings: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.sp_env = (self.sp_env or "production").lower()
        if self.sp_env not in APP_ENVS:
            raise ConfigError(f"APP_ENV must be one of {', '.join(APP_ENVS)} (got {self.sp_env!r}).")
        prod = self.is_production

        # database (PostgreSQL only)
        self.database_url = validate_database_url(self.database_url, "DATABASE_URL")
        if self.migration_database_url:
            self.migration_database_url = validate_database_url(self.migration_database_url,
                                                                "MIGRATION_DATABASE_URL")
        if self.db_auto_migrate is None:
            self.db_auto_migrate = False
        if prod:
            for name, url in (("DATABASE_URL", self.database_url),
                              ("MIGRATION_DATABASE_URL", self.migration_database_url)):
                pw = _db_password(url) if url else None
                if pw is not None and _is_weak(pw, MIN_DB_PASSWORD_CHARS):
                    raise ConfigError(f"{name} has a weak or placeholder password (need >= "
                                      f"{MIN_DB_PASSWORD_CHARS} characters, not a default); refused outside "
                                      "APP_ENV=development.")

        # jobs
        if self.job_backend is None:
            self.job_backend = "queue"
        self.job_backend = self.job_backend.lower()
        if self.job_backend not in JOB_BACKENDS:
            raise ConfigError(f"JOB_BACKEND must be one of {', '.join(JOB_BACKENDS)} (got {self.job_backend!r}).")
        if self.job_backend == "inline":
            if prod:
                raise ConfigError("JOB_BACKEND=inline is only allowed with APP_ENV=development "
                                  "(inline startup recovery would fail the runs of other API instances).")
            self.warnings.append("JOB_BACKEND=inline: run only ONE API process on this database "
                                 "(inline startup recovery fails every queued/running run).")
        if self.worker_embedded is None:
            self.worker_embedded = 0 if prod else "auto"
        bad_kinds = [k for k in self.worker_kinds if k not in JOB_KINDS]
        if bad_kinds or not self.worker_kinds:
            raise ConfigError(f"WORKER_KINDS must be a comma list of {', '.join(JOB_KINDS)} "
                              f"(got {','.join(self.worker_kinds)!r}).")

        # accounts (secure default everywhere; single_user is a development convenience only)
        if self.auth_mode is None:
            self.auth_mode = "accounts"
        self.auth_mode = self.auth_mode.lower()
        if self.auth_mode not in AUTH_MODES:
            raise ConfigError(f"AUTH_MODE must be one of {', '.join(AUTH_MODES)} (got {self.auth_mode!r}).")
        if prod and self.auth_mode == "single_user":
            raise ConfigError("AUTH_MODE=single_user is only allowed with APP_ENV=development.")
        self.password_hash_profile = (self.password_hash_profile or "default").lower()
        if self.password_hash_profile not in PASSWORD_HASH_PROFILES:
            raise ConfigError(f"PASSWORD_HASH_PROFILE must be one of {', '.join(PASSWORD_HASH_PROFILES)} "
                              f"(got {self.password_hash_profile!r}).")
        if prod and self.password_hash_profile == "fast":
            raise ConfigError("PASSWORD_HASH_PROFILE=fast is for tests only and is refused outside APP_ENV=development.")
        if self.cookie_secure is None:
            self.cookie_secure = prod
        if prod and not self.cookie_secure:
            raise ConfigError("COOKIE_SECURE=false is only allowed with APP_ENV=development "
                              "(session cookies must not travel over plain http).")
        if self.public_base_url is None and not prod:
            self.public_base_url = "http://127.0.0.1:5173"
        if prod and not self.public_base_url:
            raise ConfigError("PUBLIC_BASE_URL is required outside APP_ENV=development "
                              "(e.g. PUBLIC_BASE_URL=https://planner.example.com).")
        if self.public_base_url:
            self.public_base_url = self.public_base_url.rstrip("/")
            if prod and not self.public_base_url.lower().startswith("https://"):
                raise ConfigError(f"PUBLIC_BASE_URL must be https:// outside APP_ENV=development "
                                  f"(got {self.public_base_url!r}).")

        # CORS (R10: production default is empty = same-origin deployment)
        if self.cors_origins is None:
            self.cors_origins = [] if prod else list(DEFAULT_CORS_ORIGINS)
        self.cors_origins = list(self.cors_origins)
        if "*" in self.cors_origins and self.cors_allow_credentials:
            raise ConfigError("CORS_ORIGINS must list explicit origins (no '*') when AUTH_MODE=accounts, "
                              "because credentials are allowed.")
        if prod:
            for o in self.cors_origins:
                parts = urlsplit(o)
                if o in ("*", "null") or "*" in o or parts.scheme != "https" or not parts.netloc or \
                        parts.path not in ("", "/") or parts.query:
                    raise ConfigError(f"CORS_ORIGINS entry {o!r} is too permissive: outside APP_ENV=development "
                                      "only explicit https://host[:port] origins are allowed (or leave it empty "
                                      "for a same-origin deployment).")

        # secrets
        if prod and self.metrics_enabled and _is_weak(self.metrics_token, MIN_METRICS_TOKEN_CHARS):
            raise ConfigError(f"METRICS_TOKEN must be set to a random value of >= {MIN_METRICS_TOKEN_CHARS} "
                              "characters outside APP_ENV=development (or set METRICS_ENABLED=false).")

        # operations
        if self.log_format is None:
            self.log_format = "json" if prod else "text"
        self.log_format = self.log_format.lower()
        if self.log_format not in LOG_FORMATS:
            raise ConfigError(f"LOG_FORMAT must be one of {', '.join(LOG_FORMATS)} (got {self.log_format!r}).")
        self.log_level = (self.log_level or "INFO").upper()
        if self.log_level not in LOG_LEVELS:
            raise ConfigError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)} (got {self.log_level!r}).")

    # ---------------------------------------------------------------- derived

    @property
    def app_env(self) -> str:
        return str(self.sp_env)

    @property
    def is_production(self) -> bool:
        """True for every environment except `development` (secure defaults apply)."""
        return self.sp_env != "development"

    @property
    def is_development(self) -> bool:
        return self.sp_env == "development"

    @property
    def is_postgres(self) -> bool:   # always true; kept for callers written before PostgreSQL-only
        return True

    @property
    def schema_url(self) -> str:
        """URL used for schema changes (owner role): MIGRATION_DATABASE_URL, else DATABASE_URL."""
        return self.migration_database_url or self.database_url

    @property
    def single_user(self) -> bool:
        return self.auth_mode == "single_user"

    @property
    def cors_allow_credentials(self) -> bool:
        return self.auth_mode == "accounts"

    @property
    def hash_concurrency(self) -> int:
        """Effective number of argon2 hash slots per process (`AUTH_HASH_CONCURRENCY`, 0 = auto)."""
        if self.auth_hash_concurrency and self.auth_hash_concurrency > 0:
            return int(self.auth_hash_concurrency)
        from .auth.passwords import default_hash_concurrency

        return default_hash_concurrency()

    @property
    def embedded_workers(self) -> int:
        """Number of embedded worker threads in queue mode (`auto` = RUN_WORKERS)."""
        if self.worker_embedded == "auto":
            return self.run_workers
        return int(self.worker_embedded or 0)

    def log_warnings(self) -> None:
        for w in self.warnings:
            log.warning("config: %s", w)

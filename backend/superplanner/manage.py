"""Admin CLI (PHASE2B 4.9): `python -m superplanner.manage <command>`.

    create-user --email E [--name N] --password-stdin     prints the new user id
    set-password --email E --password-stdin               also revokes the user's sessions
    disable-user --email E / enable-user --email E        disable also revokes the user's sessions
    reassign-owner --from usr_local --to-email E [--dry-run]
                                                          moves every owned row (one transaction); prints counts
    list-users
    prune                                                 expired sessions, stale rate-limit buckets, terminal
                                                          jobs older than JOB_RETENTION_DAYS, stale worker rows
    load-sample [--sample kavach] [--email E] [--replace]
                                                          load a manufacturing sample dataset (default kavach) for
                                                          the user E (default: the local user); same path and audit
                                                          event as POST /api/v1/mfg/samples/{id}/load

    trace-backfill [--owner ID]                           M5: rebuild genealogy edges from the ledger and serials
                                                          (idempotent; every plant by default)
    audit-verify [--owner ID]                             M5: check the audit hash chains; exit 1 on a broken link
    archive --before YYYY-MM-DD [--classes a,b] [--owner ID] [--purge]
                                                          M5: export to ARCHIVE_DIR (JSONL.gz + manifest); --purge
                                                          deletes only the purgeable classes afterwards
    convert-plant --from-user EMAIL --org SLUG --code C [--name N] [--dry-run]
                                                          M5: move a personal plant into an organisation

Uses `DATABASE_URL` (or `--url`) and runs in system scope. Like the API it refuses to run unless the schema is at
head (`migrate.ensure_schema`; AUTO_MIGRATE=true upgrades first). Exit codes: 0 ok, 1 command error (unknown user, weak password, email
taken), 2 configuration error, 3 schema error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TextIO

import sqlalchemy as sa
from sqlalchemy import func, select, update

from . import migrate
from .api.auth import passwords
from .api.auth import sessions as sess
from .api.auth.maintenance import prune_auth_tables
from .api.auth.models import UserRow
from .api.auth.schemas import EMAIL_RE, MAX_EMAIL, normalize_email
from .api.config import ConfigError, Settings
from .api.db import Database, load_all_models, new_id
from .api.db.ownership import system_scope


class CommandError(RuntimeError):
    """A user-facing failure (exit code 1)."""


def owned_tables() -> list[sa.Table]:
    """Every table with an `owner_id` column (problems, solver_runs, schedules, finance_plans, finance_runs,
    finance_results, jobs)."""
    md = load_all_models()
    return [t for t in md.sorted_tables if "owner_id" in t.c]


def _read_password(stdin: TextIO) -> str:
    line = stdin.readline()
    pw = line.rstrip("\r\n")
    if not pw:
        raise CommandError("no password on stdin (use --password-stdin and pipe one line)")
    return pw


def _email(raw: str) -> str:
    email = normalize_email(raw)
    if len(email) > MAX_EMAIL or not EMAIL_RE.match(email):
        raise CommandError(f"not a valid email address: {raw!r}")
    return email


def _user_by_email(s: Any, email: str) -> UserRow:
    u = s.scalar(select(UserRow).where(UserRow.email == _email(email)))
    if u is None:
        raise CommandError(f"no user with email {_email(email)!r}")
    return u


def _checked_hash(password: str, email: str | None, settings: Settings) -> str:
    reasons = passwords.policy_reasons(password, email)
    if reasons:
        raise CommandError(f"weak password: {', '.join(reasons)}")
    return passwords.hash_password(password, settings.password_hash_profile)


def cmd_create_user(db: Database, settings: Settings, args: argparse.Namespace, out: TextIO, stdin: TextIO) -> None:
    email = _email(args.email)
    pw_hash = _checked_hash(_read_password(stdin), email, settings)
    now = datetime.now(UTC)
    with db.write() as s:
        if s.scalar(select(UserRow.id).where(UserRow.email == email)) is not None:
            raise CommandError(f"a user with email {email!r} already exists")
        uid = new_id("usr_")
        s.add(UserRow(id=uid, email=email, display_name=(args.name or None), password_hash=pw_hash,
                      is_local=False, disabled=False, created_at=now, updated_at=now, password_changed_at=now))
    print(uid, file=out)


def cmd_set_password(db: Database, settings: Settings, args: argparse.Namespace, out: TextIO,
                     stdin: TextIO) -> None:
    email = _email(args.email)
    pw_hash = _checked_hash(_read_password(stdin), email, settings)
    now = datetime.now(UTC)
    with db.write() as s:
        u = _user_by_email(s, email)
        if u.is_local:
            raise CommandError("the local user cannot have a password")
        u.password_hash, u.password_changed_at, u.updated_at = pw_hash, now, now
        n = sess.revoke_all(s, u.id, now=now)
    print(f"password set for {email}; {n} session(s) revoked", file=out)


def _set_disabled(db: Database, args: argparse.Namespace, out: TextIO, disabled: bool) -> None:
    now = datetime.now(UTC)
    with db.write() as s:
        u = _user_by_email(s, args.email)
        u.disabled, u.updated_at = disabled, now
        n = sess.revoke_all(s, u.id, now=now) if disabled else 0
        email = u.email
    print(f"{'disabled' if disabled else 'enabled'} {email}" + (f"; {n} session(s) revoked" if disabled else ""),
          file=out)


def cmd_reassign_owner(db: Database, args: argparse.Namespace, out: TextIO) -> None:
    with db.write() as s:
        src = s.get(UserRow, args.from_user)
        if src is None:
            raise CommandError(f"no user with id {args.from_user!r}")
        dst = _user_by_email(s, args.to_email)
        if dst.id == src.id:
            raise CommandError("source and target are the same user")
        src_id, dst_id, dst_email = src.id, dst.id, dst.email
        # M1-DESIGN 14.1: per-owner unique keys of the mfg tables would clash mid-command; refuse up front.
        mfg_rows = {t.name: n for t in owned_tables() if t.name.startswith("mfg_")
                    for n in [int(s.scalar(select(func.count()).select_from(t).where(t.c.owner_id == dst.id)) or 0)]
                    if n}
        if mfg_rows:
            listed = ", ".join(f"{k}: {v}" for k, v in mfg_rows.items())
            raise CommandError(f"the target user already has manufacturing data ({listed}); reset it in the app "
                               "first")
        counts: dict[str, int] = {}
        for t in owned_tables():
            if t.name == "audit_events":       # append-only; the chain hash covers owner_id (M5-DESIGN 7)
                continue
            if args.dry_run:
                counts[t.name] = int(s.scalar(select(func.count()).select_from(t)
                                              .where(t.c.owner_id == src.id)) or 0)
            else:
                res = s.execute(update(t).where(t.c.owner_id == src.id).values(owner_id=dst.id))
                counts[t.name] = int(res.rowcount or 0)
        if args.dry_run:
            s.rollback()
    verb = "would move" if args.dry_run else "moved"
    print(f"{verb} rows from {src_id} to {dst_id} ({dst_email}):", file=out)
    for name, n in counts.items():
        print(f"  {name}: {n}", file=out)


def cmd_list_users(db: Database, out: TextIO) -> None:
    with db.read() as s:
        rows = s.execute(select(UserRow.id, UserRow.email, UserRow.display_name, UserRow.is_local,
                                UserRow.disabled, UserRow.created_at, UserRow.last_login_at)
                         .order_by(UserRow.created_at, UserRow.id)).all()
    print("id\temail\tname\tlocal\tdisabled\tcreated_at\tlast_login_at", file=out)
    for r in rows:
        print("\t".join(["" if v is None else str(v) for v in
                         (r.id, r.email, r.display_name, r.is_local, r.disabled, sess.aware(r.created_at),
                          sess.aware(r.last_login_at))]), file=out)


def prune_jobs(s: Any, now: datetime, retention_days: int) -> dict[str, int]:
    """Jobs part of `prune` (Q5, B 2.9 retention; ORM statements in system scope): terminal jobs
    finished more than `retention_days` ago, and `job_workers` rows without a heartbeat for a day."""
    from datetime import timedelta

    from sqlalchemy import delete

    from .api.db import JobRow, JobWorkerRow

    jobs = s.execute(delete(JobRow).where(JobRow.status.in_(("succeeded", "failed", "cancelled")),
                                          JobRow.finished_at < now - timedelta(days=int(retention_days)))
                     .execution_options(synchronize_session=False))
    workers = s.execute(delete(JobWorkerRow).where(JobWorkerRow.heartbeat_at < now - timedelta(days=1))
                        .execution_options(synchronize_session=False))
    return {"jobs": int(jobs.rowcount or 0), "job_workers": int(workers.rowcount or 0)}


def cmd_prune(db: Database, out: TextIO, settings: Settings | None = None) -> None:
    now = datetime.now(UTC)
    retention = settings.job_retention_days if settings is not None else 30
    with db.write() as s:
        counts = prune_auth_tables(s, now)
        counts.update(prune_jobs(s, now, retention))
    for name, n in counts.items():
        print(f"{name}: {n} deleted", file=out)


class _CliContext:
    """The subset of `AppContext` the mfg services use (`settings`, `db`, `write_guard`)."""

    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db

    def write_guard(self) -> Any:
        import contextlib

        return contextlib.nullcontext()


def cmd_load_sample(db: Database, settings: Settings, args: argparse.Namespace, out: TextIO) -> None:
    from .api.db.ownership import install as install_ownership
    from .api.db.ownership import owner_scope
    from .api.errors import ApiError
    from .api.mfg.services import samples
    from .mfg.samples import SAMPLES

    if args.sample not in SAMPLES:
        raise CommandError(f"unknown sample {args.sample!r} (choose from {', '.join(sorted(SAMPLES))})")
    with db.read() as s:
        if args.email:
            uid = _user_by_email(s, args.email).id
        else:
            u = s.get(UserRow, "usr_local")
            if u is None:   # pragma: no cover - ensure_schema creates it
                raise CommandError("the local user does not exist")
            uid = u.id
    install_ownership(db, single_user=uid == "usr_local")
    try:
        with owner_scope(uid):
            res = samples.load(_CliContext(settings, db), args.sample, bool(args.replace))
    except ApiError as exc:
        raise CommandError(f"{exc.message} (use --replace to replace the existing manufacturing data)"
                           if exc.code == "MFG_IMPORT_HAS_ERRORS" else exc.message) from None
    counts = res["result"]["counts"]
    total = sum(sum(v for k, v in c.items() if k in ("create", "update")) for c in counts.values()
                if isinstance(c, dict))
    print(f"loaded sample {args.sample} for {uid}: {total} row(s) created/updated; "
          f"health {'ok' if res['health']['ok'] else 'has findings'}", file=out)


def _owners(s: Any, owner: str | None) -> list[str]:
    from .api.mfg.db_models import MfgPlantRow

    if owner:
        return [owner]
    return sorted(set(s.execute(select(MfgPlantRow.owner_id)).scalars()))


def cmd_trace_backfill(db: Database, args: argparse.Namespace, out: TextIO) -> None:
    from .api.mfg.services.trace import backfill

    with db.write() as s:
        r = backfill(s, args.owner)
    print(f"trace backfill: {r['postings']} posting(s), {r['serials']} serial(s), {r['edges_added']} edge(s) added "
          f"in {r['duration_ms']} ms", file=out)


def cmd_audit_verify(db: Database, args: argparse.Namespace, out: TextIO) -> None:
    from .api.audit_chain import verify
    from .api.db.models import AuditEventRow

    bad = []
    with db.read() as s:
        owners = [args.owner] if args.owner else [None] + sorted(
            {o for o in s.execute(select(AuditEventRow.owner_id).distinct()).scalars() if o})
        for o in owners:
            r = verify(s, o)
            label = o or "(platform)"
            if r["ok"]:
                print(f"{label}: ok, {r['checked']} row(s)", file=out)
            else:
                print(f"{label}: BROKEN at audit row {r['first_broken_id']} after {r['checked']} good row(s)", file=out)
                bad.append(label)
    if bad:
        raise CommandError(f"audit chain broken for {', '.join(bad)}")


def cmd_archive(db: Database, settings: Settings, args: argparse.Namespace, out: TextIO) -> None:
    from .api.mfg.services import maintenance as M

    before = datetime.combine(datetime.strptime(args.before, "%Y-%m-%d").date(), datetime.min.time(), UTC)
    classes = [c.strip() for c in (args.classes or ",".join(M.CLASSES)).split(",") if c.strip()]
    bad = [c for c in classes if c not in M.CLASSES]
    if bad:
        raise CommandError(f"unknown class(es) {', '.join(bad)} (choose from {', '.join(M.CLASSES)})")
    if not settings.archive_dir and not args.purge:
        raise CommandError("ARCHIVE_DIR is not set")
    with db.write() as s:
        for o in _owners(s, args.owner):
            m = M.archive(s, o, before, classes, settings.archive_dir, purge=bool(args.purge))
            for c, info in m["classes"].items():
                print(f"{o} {c}: {info['rows']} archived in {len(info['files'])} file(s), {info['purged']} purged",
                      file=out)


def cmd_convert_plant(db: Database, args: argparse.Namespace, out: TextIO) -> None:
    from .api.errors import ApiError
    from .orgs.service import convert_plant

    with db.read() as s:
        uid = _user_by_email(s, args.from_user).id
    try:
        r = convert_plant(db, uid, args.org, args.code, args.name, dry_run=bool(args.dry_run))
    except ApiError as e:
        raise CommandError(e.message) from None
    moved = sum(r["rows"].values())
    print(f"{'would move' if args.dry_run else 'moved'} {moved} row(s) of {args.from_user} to plant {args.code} "
          f"({r['plant_owner_id']}); {args.from_user} is plant_admin", file=out)
    for k, v in sorted(r["rows"].items()):
        if v:
            print(f"  {k}: {v}", file=out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m superplanner.manage", description="SuperPlanner admin commands")
    p.add_argument("--url", help="database URL (default: DATABASE_URL)")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("--email", required=True)
    c.add_argument("--name")
    c.add_argument("--password-stdin", action="store_true", required=True)
    c = sub.add_parser("set-password")
    c.add_argument("--email", required=True)
    c.add_argument("--password-stdin", action="store_true", required=True)
    for name in ("disable-user", "enable-user"):
        sub.add_parser(name).add_argument("--email", required=True)
    c = sub.add_parser("reassign-owner")
    c.add_argument("--from", dest="from_user", default="usr_local")
    c.add_argument("--to-email", required=True)
    c.add_argument("--dry-run", action="store_true")
    sub.add_parser("list-users")
    sub.add_parser("prune")
    c = sub.add_parser("load-sample")
    c.add_argument("--sample", default="kavach")
    c.add_argument("--email", help="owner of the data (default: the local user, AUTH_MODE=single_user)")
    c.add_argument("--replace", action="store_true", help="delete this user's manufacturing data first")
    c = sub.add_parser("trace-backfill")
    c.add_argument("--owner", help="plant owner id (default: every plant)")
    c = sub.add_parser("audit-verify")
    c.add_argument("--owner", help="workspace owner id (default: every chain)")
    c = sub.add_parser("archive")
    c.add_argument("--before", required=True, help="YYYY-MM-DD (rows created before this date)")
    c.add_argument("--classes", help="comma list (default: every class)")
    c.add_argument("--owner", help="plant owner id (default: every plant)")
    c.add_argument("--purge", action="store_true", help="delete the purgeable classes after archiving")
    c = sub.add_parser("convert-plant")
    c.add_argument("--from-user", required=True, help="email of the person whose plant moves")
    c.add_argument("--org", required=True, help="organisation slug")
    c.add_argument("--code", required=True, help="plant code in the organisation")
    c.add_argument("--name")
    c.add_argument("--dry-run", action="store_true")
    return p


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None, err: TextIO | None = None,
         stdin: TextIO | None = None) -> int:
    out, err, stdin = out or sys.stdout, err or sys.stderr, stdin or sys.stdin
    args = build_parser().parse_args(argv)
    try:
        settings = Settings(database_url=args.url) if args.url else Settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=err)
        return 2
    db = Database.from_settings(settings, service="manage")
    try:
        with system_scope():
            migrate.ensure_schema(db, settings)
            cmd = args.command
            if cmd == "create-user":
                cmd_create_user(db, settings, args, out, stdin)
            elif cmd == "set-password":
                cmd_set_password(db, settings, args, out, stdin)
            elif cmd in ("disable-user", "enable-user"):
                _set_disabled(db, args, out, cmd == "disable-user")
            elif cmd == "reassign-owner":
                cmd_reassign_owner(db, args, out)
            elif cmd == "list-users":
                cmd_list_users(db, out)
            elif cmd == "load-sample":
                cmd_load_sample(db, settings, args, out)
            elif cmd == "trace-backfill":
                cmd_trace_backfill(db, args, out)
            elif cmd == "audit-verify":
                cmd_audit_verify(db, args, out)
            elif cmd == "archive":
                cmd_archive(db, settings, args, out)
            elif cmd == "convert-plant":
                cmd_convert_plant(db, args, out)
            else:
                cmd_prune(db, out, settings)
        return 0
    except CommandError as exc:
        print(f"error: {exc}", file=err)
        return 1
    except migrate.SchemaError as exc:
        print(f"schema error: {exc}", file=err)
        return 3
    finally:
        db.dispose()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

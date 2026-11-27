"""Electronic signatures (M7-DESIGN 4.1-4.3, 4.6): enrolment, credential checks, lockout, policies, preview, signing,
manifestation, verification, OIDC step-up, clock skew.

Signing a signable action happens in two phases:
1. `authenticate(ctx, a, record_type, action, signature)` - before the action's write transaction (no plant lock
   held during argon2): Part 11 mode and policy decide whether a signature counts; the person must be enrolled,
   not revoked, not locked; user name and credentials are verified (password, TOTP with replay refusal, SSO step-up
   token of this session, or the ESIG_LOCAL_CREDENTIALS signing password). A failure is recorded in its own
   transaction under the user's row lock (three in 15 minutes lock signing for 30 minutes, audit `esig.lockout`,
   plant notification) and answered 422 `ESIG_AUTH_FAILED` / 423 `ESIG_LOCKED`.
2. `sign(s, a, auth, record_type, record_id, action, signature, ...)` - inside the action's transaction: policy
   step (meaning, role, distinct signer, author), content hash (409 `ESIG_CONTENT_CHANGED`), clock skew (503),
   then the signature row (database clock, content snapshot, HMAC) and the `esig.signed` audit event. The outcome
   says whether this was the last step (the action runs) or the 202 pending answer.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import weakref
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ....esig import content as C
from ....esig import policy as POL
from ....esig.model import ACK_TEXT, ACK_VERSION, MEANING_LABELS, PolicyUpdate, SignatureInput
from ...context import AppContext
from ...db.models import new_id, utcnow
from ...db.ownership import current_owner, system_scope
from ...errors import ApiError
from ..db_models_m7 import EsigPolicyRow, EsigSignatureRow, EsigStepupRow
from . import m7_examples
from .common import check_version, jsonable, read_tx, write_tx

FAIL_WINDOW = timedelta(minutes=15)
LOCK_FOR = timedelta(minutes=30)
MAX_FAILURES = 3
STEPUP_MINUTES = 5
SKEW_TTL_SECONDS = 300.0
#: tests: added to the measured app/DB skew (T-S7)
SKEW_INJECT_MS: float = 0.0
_SKEW: dict[int, tuple[float, float]] = {}


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def db_now(s: Session) -> datetime:
    """The database clock (4.6: signature, decision and result times)."""
    return _aware(s.execute(text("SELECT clock_timestamp()")).scalar())  # type: ignore[return-value]


def load_registry() -> None:
    """Import the modules that register content loaders (lazy: they import this module)."""
    from . import eco_m7, part11, qa_capa, qa_complaints, qa_equipment, qa_field_actions, qa_holds, qa_inspection, \
        qa_ncr  # noqa: F401
    C.register("esig_policy", _policy_loader)


# ---------------------------------------------------------------- clock (4.6)

def measure_skew(ctx: AppContext, force: bool = False) -> tuple[float, datetime, datetime]:
    """(skew_ms, app_utc, db_utc); re-measured at most every 5 minutes (per database)."""
    key = id(ctx.db)
    cached = _SKEW.get(key)
    mono = time.monotonic()
    if cached is not None and not force and mono - cached[1] < SKEW_TTL_SECONDS:
        now = datetime.now(UTC)
        return cached[0] + SKEW_INJECT_MS, now, now + timedelta(milliseconds=cached[0])
    with ctx.db.read() as s:
        t0 = time.time()
        dbt = _aware(s.execute(text("SELECT clock_timestamp()")).scalar())
        t1 = time.time()
    app = datetime.fromtimestamp((t0 + t1) / 2, UTC)
    skew = (dbt - app).total_seconds() * 1000.0 if dbt else 0.0
    _SKEW[key] = (skew, mono)
    return skew + SKEW_INJECT_MS, app, dbt or app


def time_info(ctx: AppContext) -> dict[str, Any]:
    skew, app, dbt = measure_skew(ctx, force=True)
    mx = float(ctx.settings.esig_max_clock_skew_ms)
    return {"app_utc": app, "db_utc": dbt, "skew_ms": round(skew, 3), "max_skew_ms": mx, "ok": abs(skew) <= mx}


def _check_clock(ctx_settings: Any, skew_ms: float) -> None:
    mx = float(ctx_settings.esig_max_clock_skew_ms)
    if abs(skew_ms) > mx:
        raise ApiError(503, "ESIG_CLOCK_SKEW", "Signing is unavailable: the server clocks disagree. Ask your "
                       "administrator to check time synchronisation.", {"skew_ms": round(skew_ms, 1),
                                                                         "max_skew_ms": mx})


# ---------------------------------------------------------------- MAC (0.1)

def _mac_keys(ctx_or_settings: Any) -> list[bytes]:
    st = getattr(ctx_or_settings, "settings", ctx_or_settings)
    return [hashlib.sha256(b"superplanner-esig|" + k.encode()).digest() for k in (st.secrets_keys or []) if k]


def _mac_message(r: EsigSignatureRow) -> bytes:
    doc = {"id": r.id, "owner_id": r.owner_id, "record_type": r.record_type, "record_id": r.record_id,
           "record_version": r.record_version, "action": r.action, "step": r.step, "meaning": r.meaning,
           "signer_id": r.signer_id, "signer_legal_name": r.signer_legal_name, "signer_username": r.signer_username,
           "signed_at": _aware(r.signed_at), "auth_method": r.auth_method, "policy_id": r.policy_id,
           "policy_version": r.policy_version, "content_hash": r.content_hash, "comment": r.comment,
           "audit_event_id": r.audit_event_id, "client_ip": r.client_ip, "session_ref": r.session_ref}
    return C.canonical(doc).encode("utf-8")


def compute_mac(keys: list[bytes], r: EsigSignatureRow) -> str:
    msg = _mac_message(r)
    if not keys:
        return "sha256:" + hashlib.sha256(msg).hexdigest()
    return "k1:" + hmac.new(keys[0], msg, hashlib.sha256).hexdigest()


def mac_ok(keys: list[bytes], r: EsigSignatureRow) -> bool:
    msg = _mac_message(r)
    if r.mac.startswith("k1:"):
        return any(hmac.compare_digest(r.mac, "k1:" + hmac.new(k, msg, hashlib.sha256).hexdigest()) for k in keys)
    if keys:                       # review m1: with keys configured an unkeyed MAC is not accepted (forgeable)
        return False
    return hmac.compare_digest(r.mac, "sha256:" + hashlib.sha256(msg).hexdigest())


# ---------------------------------------------------------------- policies (4.3)

def _final_release_role(s: Session) -> str:
    from .qa_common import settings_of

    return settings_of(s).final_release_role


def policy_record(r: EsigPolicyRow | POL.Policy, sigs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"id": r.id or "", "record_type": r.record_type, "action": r.action, "steps": r.steps, "auth": r.auth,
            "distinct_signers": r.distinct_signers, "exclude_author": r.exclude_author, "version": r.version,
            "fixed": (r.record_type, r.action) in POL.FIXED, "row_version": getattr(r, "row_version", 0) or 0,
            "updated_at": getattr(r, "updated_at", None) or datetime(2026, 1, 1, tzinfo=UTC),
            "signatures": sigs or []}


def expected_policy_keys(s: Session) -> list[tuple[str, str]]:
    """Default policy keys of the bound workspace (network-only policies in the network workspace, M9 6.6)."""
    from ..db_models import MfgPlantRow

    net = s.execute(select(MfgPlantRow.kind).limit(1)).scalar() == "network"
    return [k for k in POL.DEFAULTS if net or k not in POL.NETWORK_ONLY]


def seed_policies(s: Session) -> dict[tuple[str, str], EsigPolicyRow]:
    """Insert the missing default policies of the bound plant (4.3); returns all rows by key."""
    rows = {(r.record_type, r.action): r for r in s.execute(select(EsigPolicyRow)).scalars()}
    missing = [k for k in expected_policy_keys(s) if k not in rows]
    if missing:
        frr = _final_release_role(s)
        now = utcnow()
        for k in missing:
            d = POL.default(*k, final_release_role=frr)
            assert d is not None
            r = EsigPolicyRow(id=new_id("esp_"), record_type=k[0], action=k[1], steps=d.steps, auth=d.auth,
                              distinct_signers=d.distinct_signers, exclude_author=d.exclude_author, version=1,
                              row_version=1, created_at=now, updated_at=now)
            s.add(r)
            rows[k] = r
        s.flush()
    return rows


def effective_policy(s: Session, record_type: str, action: str) -> POL.Policy | None:
    r = s.execute(select(EsigPolicyRow).where(EsigPolicyRow.record_type == record_type,
                                              EsigPolicyRow.action == action)).scalars().first()
    if r is not None:
        return POL.Policy(r.id, r.record_type, r.action, list(r.steps), r.auth, r.distinct_signers,
                          r.exclude_author, r.version)
    return POL.default(record_type, action, _final_release_role(s))


def list_policies(ctx: AppContext, a: Any) -> dict[str, Any]:
    with read_tx(ctx) as s:
        n = int(s.execute(select(func.count()).select_from(EsigPolicyRow)).scalar() or 0)
        expected = len(expected_policy_keys(s))
    if n < expected:
        with write_tx(ctx) as (s, _plant):
            seed_policies(s)
            from .common import audit

            audit(s, "esig_policy", None, "create", {"seeded": True})
    with read_tx(ctx) as s:
        rows = list(s.execute(select(EsigPolicyRow).order_by(EsigPolicyRow.record_type, EsigPolicyRow.action))
                    .scalars())
        return {"items": [policy_record(r) for r in rows], "total": len(rows), "limit": len(rows), "offset": 0}


def _policy_loader(s: Session, record_id: str, lock: bool) -> C.Loaded:
    """`esig_policy` records are addressed as `<record_type>.<action>`."""
    rt, _, action = record_id.partition(".")
    rows = seed_policies(s)
    r = rows.get((rt, action))
    if r is None:
        raise ApiError(404, "NOT_FOUND", "Signature policy not found.", {"id": record_id})
    content = {"record_type": r.record_type, "action": r.action, "steps": r.steps, "auth": r.auth,
               "distinct_signers": r.distinct_signers, "exclude_author": r.exclude_author, "version": r.version}
    return C.Loaded(r, content, r.row_version, None, [("Policy", f"{rt}.{action}"), ("Version", str(r.version))])


def update_policy(ctx: AppContext, a: Any, record_type: str, action: str, body: PolicyUpdate,
                  if_match: str | None) -> dict[str, Any]:
    steps = [st.model_dump() for st in body.steps]
    why = POL.validate(record_type, action, steps, body.auth)
    if why is not None:
        raise ApiError(422, "ESIG_POLICY_INVALID", why, {"record_type": record_type, "action": action})
    rid = f"{record_type}.{action}"
    auth = authenticate(ctx, a, "esig_policy", "update", body.signature)
    from ...audit_diff import audit_regulated

    with write_tx(ctx) as (s, _plant):
        load_registry()
        rows = seed_policies(s)
        r = rows[(record_type, action)]
        check_version(r, if_match)
        before = policy_record(r)
        after_doc = {"steps": steps, "auth": body.auth, "distinct_signers": body.distinct_signers,
                     "exclude_author": body.exclude_author}
        loaded = _policy_loader(s, rid, True)
        out = sign(s, a, auth, "esig_policy", rid, "update", body.signature, loaded=loaded, params=after_doc)
        if out.pending is not None:
            return out.pending
        r.steps, r.auth = steps, body.auth
        r.distinct_signers, r.exclude_author = body.distinct_signers, body.exclude_author
        r.version += 1
        r.row_version += 1
        r.updated_at = utcnow()
        s.flush()
        audit_regulated(s, "esig_policy", r.id, "update", before=before, after=policy_record(r),
                        reason=_reason(body.signature), record_version=r.row_version,
                        signature_id=out.signature_ids[-1] if out.signature_ids else None)
        return policy_record(r, manifests(s, "esig_policy", rid))


def _reason(sig: SignatureInput | None) -> str | None:
    return sig.comment.strip() or None if sig is not None and sig.comment else None


# ---------------------------------------------------------------- enrolment and status (4.1)

def _user(s: Session, user_id: str, lock: bool = False) -> Any:
    from ...auth.models import UserRow

    q = select(UserRow).where(UserRow.id == user_id)
    if lock:
        q = q.with_for_update()
    return s.execute(q).scalars().first()


def _is_sso(s: Session, user_id: str) -> bool:
    from ..db_models_m5 import UserIdentityRow

    return s.execute(select(UserIdentityRow.id).where(UserIdentityRow.user_id == user_id).limit(1)).first() is not None


def _methods(ctx: AppContext, s: Session, u: Any) -> tuple[list[str], bool, bool, bool]:
    """(methods, totp_enabled, sso_user, local_credentials)."""
    from ....identity.service import totp_enabled

    tot = totp_enabled(s, u.id)
    sso = _is_sso(s, u.id) and not u.password_hash
    local = bool(sso and ctx.settings.esig_local_credentials and u.esig_password_hash)
    out: list[str] = []
    if u.password_hash or local:
        out.append("password")
        if tot:
            out.append("password_totp")
    if sso and ctx.settings.oidc_issuer:
        out += ["sso", "sso_mfa"]
    return out, tot, sso, local


def _status_of(ctx: AppContext, s: Session, u: Any) -> dict[str, Any]:
    methods, tot, sso, local = _methods(ctx, s, u)
    locked = _aware(u.esig_locked_until)
    if locked is not None and locked <= datetime.now(UTC):
        locked = None
    enrolled = u.esig_enrolled_at is not None and u.esig_revoked_at is None
    return {"user_id": u.id, "username": u.email or u.id, "enrolled": enrolled, "legal_name": u.legal_name,
            "enrolled_at": _aware(u.esig_enrolled_at), "ack_version": u.esig_ack_version,
            "revoked_at": _aware(u.esig_revoked_at), "locked_until": locked, "methods": methods,
            "totp_enabled": tot, "sso_user": sso, "local_credentials": local,
            "can_sign": enrolled and locked is None and u.kind == "person" and bool(methods),
            "acknowledgement": {"version": ACK_VERSION, **ACK_TEXT}}


def status(ctx: AppContext, p: Any) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        u = _user(s, p.user_id)
        if u is None:
            raise ApiError(404, "NOT_FOUND", "User not found.", {})
        return _status_of(ctx, s, u)


def _not_allowed(why: str) -> ApiError:
    return ApiError(403, "ESIG_NOT_ALLOWED", why, {})


def enroll(ctx: AppContext, p: Any, body: Any, request: Any) -> dict[str, Any]:
    """4.1: legal name + acknowledgement, confirmed with the password (or an SSO step-up token)."""
    from ...auth.passwords import hash_password, verify_password

    if getattr(p, "scopes", None) is not None or getattr(p, "is_local", False):
        raise _not_allowed("API tokens and the local single-user account cannot enrol for electronic signatures.")
    session_ref = hashlib.sha256(p.session_id.encode()).hexdigest() if p.session_id else None
    with system_scope(), ctx.db.read() as s:
        u = _user(s, p.user_id)
        if u is None or u.kind != "person" or u.disabled:
            raise _not_allowed("Only people can enrol for electronic signatures.")
        sso = _is_sso(s, u.id) and not u.password_hash
        pw_hash = u.password_hash
        if u.esig_revoked_at is not None:            # review M2: only an admin reinstates a revoked signer
            raise ApiError(403, "ESIG_REVOKED", "Your signing rights were revoked; ask an organisation admin to "
                           "reinstate them.", {})
        locked = _aware(u.esig_locked_until)
        if locked is not None and locked > datetime.now(UTC):
            raise ApiError(423, "ESIG_LOCKED", "Signing is locked after repeated failures.", {"until": jsonable(locked)})
        fresh = False
        if sso and p.session_id:                     # review m13: a sign-in within the last 10 minutes
            from ...auth.models import UserSessionRow

            created = s.execute(select(UserSessionRow.created_at).where(UserSessionRow.id == p.session_id)).scalar()
            fresh = created is not None and _aware(created) > datetime.now(UTC) - timedelta(minutes=10)
    ok = False
    if body.password is not None and pw_hash:
        ok = verify_password(pw_hash, body.password, ctx.settings.password_hash_profile)
    elif body.stepup_token is not None and sso:
        ok = _consume_stepup(ctx, p.user_id, session_ref, body.stepup_token, need_mfa=False) is not None
    elif sso and ctx.settings.esig_local_credentials and body.signing_password is not None:
        # review m13: IdP without step-up - a fresh SSO sign-in plus the person's TOTP code enrol the signing
        # password (local credentials)
        if not fresh:
            raise ApiError(422, "ESIG_REAUTH_REQUIRED", "Sign in again with your company account, then enrol within "
                           "10 minutes.", {})
        ok = bool(body.totp_code) and _check_totp(ctx, p.user_id, body.totp_code)
    if not ok:                                       # review m12: enrolment failures count toward the lockout
        _record_failure(ctx, p.user_id)
    if sso and ctx.settings.esig_local_credentials and body.signing_password is None and not ctx.settings.oidc_issuer:
        raise ApiError(422, "VALIDATION_ERROR", "Set a signing password.", {"errors": [
            {"loc": ["body", "signing_password"], "msg": "required", "type": "value_error"}]})
    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        u = _user(s, p.user_id, lock=True)
        u.legal_name = body.legal_name
        u.esig_enrolled_at = now
        u.esig_ack_version = ACK_VERSION
        u.esig_revoked_at = None
        u.esig_failed = None
        if body.signing_password is not None and sso and ctx.settings.esig_local_credentials:
            u.esig_password_hash = hash_password(body.signing_password, ctx.settings.password_hash_profile)
        u.updated_at = now
        from ...services.problem_service import audit_row

        audit_row(s, "user", u.id, "esig.enrolled", {"legal_name": body.legal_name, "ack_version": ACK_VERSION})
        s.flush()
        return _status_of(ctx, s, u)


def revoke(ctx: AppContext, p: Any, org_id: str, member_id: str, reinstate: bool = False) -> dict[str, Any]:
    """P4: an organisation admin revokes a member's signing enrolment."""
    from ..db_models_m5 import OrgMemberRow

    with system_scope(), ctx.db.write() as s:
        me = s.execute(select(OrgMemberRow).where(OrgMemberRow.org_id == org_id, OrgMemberRow.user_id == p.user_id,
                                                  OrgMemberRow.accepted_at.is_not(None))).scalars().first()
        if me is None:
            raise ApiError(404, "NOT_FOUND", "Organisation not found.", {"id": org_id})
        if me.org_role != "org_admin":
            raise ApiError(403, "MFG_FORBIDDEN", "Only organisation admins can do this.", {"permission": "org_admin"})
        m = s.execute(select(OrgMemberRow).where(OrgMemberRow.org_id == org_id, OrgMemberRow.id == member_id)
                      ).scalars().first()
        if m is None or m.user_id is None:
            raise ApiError(404, "NOT_FOUND", "Member not found.", {"id": member_id})
        u = _user(s, m.user_id, lock=True)
        if reinstate:
            u.esig_revoked_at = None
        else:
            u.esig_revoked_at = utcnow()
        from ...services.problem_service import audit_row

        audit_row(s, "user", u.id, "esig.reinstated" if reinstate else "esig.revoked", {"org_id": org_id,
                                                                                         "by": p.user_id})
        s.flush()
        return _status_of(ctx, s, u)


# ---------------------------------------------------------------- OIDC step-up (4.2 (3))

def stepup_start(ctx: AppContext, p: Any) -> tuple[str, str]:
    from ....identity import service as ids

    if not p.session_id:
        raise _not_allowed("Sign in with your company account first.")
    session_ref = hashlib.sha256(p.session_id.encode()).hexdigest()
    return ids.oidc_login(ctx, f"stepup:{p.user_id}:{session_ref}", stepup=True)


def issue_stepup(ctx: AppContext, user_id: str, session_ref: str, claims: dict[str, Any], started_at: datetime
                 ) -> str:
    """Called by the OIDC callback of a step-up: fresh `auth_time` -> a single-use 5-minute token."""
    at = claims.get("auth_time")
    if not isinstance(at, (int, float)):
        raise ApiError(401, "AUTH_SSO_FAILED", "The provider did not confirm a fresh sign-in (auth_time).", {})
    auth_time = datetime.fromtimestamp(float(at), UTC)
    if auth_time < started_at - timedelta(seconds=60):
        raise ApiError(401, "AUTH_SSO_FAILED", "The provider did not re-authenticate you (stale auth_time).", {})
    amr = claims.get("amr") if isinstance(claims.get("amr"), list) else []
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        s.query(EsigStepupRow).filter(EsigStepupRow.expires_at < now - timedelta(hours=1)).delete(
            synchronize_session=False)
        s.add(EsigStepupRow(token_hash=hashlib.sha256(raw.encode()).hexdigest(), user_id=user_id,
                            session_ref=session_ref, amr=[str(x)[:32] for x in amr][:10], auth_time=auth_time,
                            expires_at=now + timedelta(minutes=STEPUP_MINUTES), used_at=None))
    return raw


def _consume_stepup(ctx: AppContext, user_id: str, session_ref: str | None, raw: str, *, need_mfa: bool
                    ) -> list[str] | None:
    """The token's amr when valid for this user and session (marked used), else None."""
    h = hashlib.sha256(raw.encode()).hexdigest()
    now = utcnow()
    with system_scope(), ctx.db.write() as s:
        r = s.get(EsigStepupRow, h, with_for_update=True)
        if r is None or r.used_at is not None or _aware(r.expires_at) < now or r.user_id != user_id or \
                session_ref is None or not hmac.compare_digest(r.session_ref, session_ref):
            return None
        amr = list(r.amr or [])
        if need_mfa and not set(amr) & set(ctx.settings.esig_mfa_amr):
            raise ApiError(422, "ESIG_MFA_UNAVAILABLE", "This step needs multi-factor authentication; your company "
                           "sign-in did not use it.", {"amr": amr})
        r.used_at = now
        return amr


# ---------------------------------------------------------------- authentication (phase 1)

@dataclass(frozen=True)
class Auth:
    user_id: str
    method: str
    legal_name: str
    username: str


def _part11_and_policy(ctx: AppContext, record_type: str, action: str) -> tuple[bool, POL.Policy | None]:
    from ..db_models import MfgPlantRow

    with read_tx(ctx) as s:
        on = bool(s.execute(select(MfgPlantRow.part11_mode).limit(1)).scalar() or False)
        if not on and (record_type, action) not in POL.ALWAYS:
            return False, None
        return True, effective_policy(s, record_type, action)


def authenticate(ctx: AppContext, a: Any, record_type: str, action: str, sig: SignatureInput | None
                 ) -> Auth | None:
    if sig is None:
        return None
    on, pol = _part11_and_policy(ctx, record_type, action)
    if not on or pol is None or not pol.steps:
        return None
    if not ctx.settings.esig_enabled:
        raise ApiError(503, "ESIG_DISABLED", "Electronic signatures are switched off on this server.", {})
    if a.p.scopes is not None:
        raise _not_allowed("API tokens cannot sign.")
    from ...auth.passwords import verify_dummy, verify_password

    with system_scope(), ctx.db.read() as s:
        u = _user(s, a.user_id)
        if u is None or u.kind != "person" or u.disabled or u.is_local:
            raise _not_allowed("Only people with an account can sign.")
        if u.esig_enrolled_at is None or u.esig_revoked_at is not None:
            raise ApiError(403, "ESIG_NOT_ENROLLED", "Enrol for electronic signatures first (account menu).",
                           {"revoked": u.esig_revoked_at is not None})
        locked = _aware(u.esig_locked_until)
        if locked is not None and locked > datetime.now(UTC):
            raise ApiError(423, "ESIG_LOCKED", "Signing is locked after repeated failures.", {"until": jsonable(locked)})
        sso = _is_sso(s, u.id) and not u.password_hash
        pw_hash = u.password_hash or (u.esig_password_hash if sso and ctx.settings.esig_local_credentials else None)
        legal, username, uid = u.legal_name or "", u.email or u.id, u.id
        from ....identity.service import totp_row

        tr = totp_row(s, uid)
        has_totp = tr is not None and tr.enabled_at is not None
    need_mfa = pol.auth == "password_totp"
    name_ok = hmac.compare_digest(sig.username.strip().lower(), (username or "").lower())
    profile = ctx.settings.password_hash_profile
    method = None
    if sig.stepup_token is not None and sso:
        amr = _consume_stepup(ctx, uid, a.session_ref, sig.stepup_token, need_mfa=need_mfa) if name_ok else None
        if amr is not None:
            method = "sso_mfa" if set(amr) & set(ctx.settings.esig_mfa_amr) else "sso"
    elif sig.password is not None and pw_hash:
        if need_mfa and not has_totp:
            raise ApiError(422, "ESIG_MFA_UNAVAILABLE", "This step needs a verification code: set up two-step "
                           "sign-in in your account first.", {})
        ok = verify_password(pw_hash, sig.password, profile) and name_ok
        if ok and need_mfa:
            ok = sig.totp_code is not None and _check_totp(ctx, uid, sig.totp_code)
        if ok:
            method = "password_totp" if need_mfa else "password"
    else:
        if sig.password is not None:
            verify_dummy(sig.password, profile)          # same cost as a real check
        if need_mfa and sso and sig.stepup_token is None and not ctx.settings.esig_local_credentials:
            raise ApiError(422, "ESIG_MFA_UNAVAILABLE", "Re-authenticate with your company account.", {})
    if method is None:
        _record_failure(ctx, uid)
    _clear_failures(ctx, uid)
    return Auth(uid, method, legal, username)


def _check_totp(ctx: AppContext, user_id: str, code: str) -> bool:
    from ....identity import service as ids

    with system_scope(), ctx.db.write() as s:
        r = s.execute(select(ids.UserTotpRow).where(ids.UserTotpRow.user_id == user_id).with_for_update()
                      ).scalars().first()
        if r is None or r.enabled_at is None:
            return False
        return ids._check_code(ctx, s, r, code)


def _record_failure(ctx: AppContext, user_id: str) -> None:
    """Count a failed signing attempt under the user's row lock (T-S1); raises 422 or 423."""
    owner = current_owner()
    with system_scope(), ctx.db.write() as s:
        u = _user(s, user_id, lock=True)
        now = db_now(s)
        already = _aware(u.esig_locked_until)
        if already is not None and already > now:      # a concurrent attempt locked it meanwhile: no new count
            raise ApiError(423, "ESIG_LOCKED", "Signing is locked after repeated failures.",
                           {"until": jsonable(already)})
        recent = [t for t in (u.esig_failed or []) if datetime.fromisoformat(t) > now - FAIL_WINDOW]
        recent.append(now.isoformat())
        if len(recent) >= MAX_FAILURES:
            u.esig_locked_until = now + LOCK_FOR
            u.esig_failed = []
            _lockout_effects(s, owner, u, now)
            locked_until = u.esig_locked_until
        else:
            u.esig_failed = recent
            locked_until = None
    if locked_until is not None:
        raise ApiError(423, "ESIG_LOCKED", "Signing is locked for 30 minutes after three failed attempts.",
                       {"until": jsonable(locked_until)})
    raise ApiError(422, "ESIG_AUTH_FAILED", "The user name or the credentials are not correct.",
                   {"remaining": MAX_FAILURES - len(recent)})


def _lockout_effects(s: Session, owner: Any, u: Any, now: datetime) -> None:
    from ...db.models import AuditEventRow
    from ...audit_chain import link
    from ..db_models_m4 import MfgNotificationRow

    plant = owner if isinstance(owner, str) else None
    row = AuditEventRow(entity_type="user", entity_id=u.id, action="esig.lockout",
                        details={"until": (now + LOCK_FOR).isoformat(), "username": u.email}, actor_id=u.id,
                        owner_id=plant, created_at=datetime.now(UTC))
    link(s, row)
    s.add(row)
    if plant is not None:
        s.add(MfgNotificationRow(id=new_id("ntf_"), owner_id=plant, kind="esig_lockout", severity="warning",
                                 title=f"Signing locked for {u.legal_name or u.email}",
                                 body="Three failed signature attempts in 15 minutes; signing is locked for 30 "
                                      "minutes. Plant admins and QA approvers: check whether this was the person.",
                                 link="/mfg/account", trigger_id=None, created_at=now))


def _clear_failures(ctx: AppContext, user_id: str) -> None:
    with system_scope(), ctx.db.write() as s:
        u = _user(s, user_id, lock=True)
        if u.esig_failed:
            u.esig_failed = None


# ---------------------------------------------------------------- signing (phase 2)

@dataclass
class Outcome:
    final: bool
    pending: dict[str, Any] | None = None
    signature_ids: list[str] = field(default_factory=list)


def _valid_sigs(s: Session, record_type: str, record_id: str, action: str | None = None,
                version: int | None = None) -> list[EsigSignatureRow]:
    q = select(EsigSignatureRow).where(EsigSignatureRow.record_type == record_type,
                                       EsigSignatureRow.record_id == record_id, EsigSignatureRow.status == "valid")
    if action is not None:
        q = q.where(EsigSignatureRow.action == action)
    if version is not None:
        q = q.where(EsigSignatureRow.record_version == version)
    return list(s.execute(q.order_by(EsigSignatureRow.signed_at, EsigSignatureRow.id)).scalars())


def _loader(record_type: str) -> C.Loader:
    load_registry()
    ld = C.REGISTRY.get(record_type)
    if ld is None:
        raise ApiError(404, "NOT_FOUND", f"Unknown record type {record_type!r}.", {"record_type": record_type})
    return ld


def load(s: Session, record_type: str, record_id: str, lock: bool = False) -> C.Loaded:
    return _loader(record_type)(s, record_id, lock)


def _required_error(s: Session, a: Any, record_type: str, record_id: str, action: str, decision: str | None,
                    loaded: C.Loaded, pol: POL.Policy) -> ApiError:
    prev = _preview_in(s, a, record_type, record_id, action, decision, loaded, pol, True)
    return ApiError(422, "ESIG_REQUIRED", "This action needs an electronic signature.", {"preview": jsonable(prev)})


def sign(s: Session, a: Any, auth: Auth | None, record_type: str, record_id: str, action: str,
         sig: SignatureInput | None, *, decision: str | None = None, loaded: C.Loaded | None = None,
         stored_content: dict[str, Any] | None = None, store_record_id: str | None = None,
         store_version: int | None = None, ctx_settings: Any = None, params: dict[str, Any] | None = None
         ) -> Outcome:
    """Phase 2 inside the action's transaction (see module doc). `params`: the action's parameters (decision,
    new policy, verification result ...) - stored in the signed snapshot (`_params`) and identical for every step
    of a multi-step flow (review M9)."""
    from ...audit_diff import part11_on

    always = (record_type, action) in POL.ALWAYS
    if not (part11_on(s) or always):
        return Outcome(True)
    seed_policies(s)
    pol = effective_policy(s, record_type, action)
    if pol is None or not pol.steps:
        return Outcome(True)
    if loaded is None:
        loaded = load(s, record_type, record_id)
    if sig is None or auth is None:
        raise _required_error(s, a, record_type, record_id, action, decision, loaded, pol)
    if auth.user_id != a.user_id:                                      # pragma: no cover - programming error
        raise ApiError(403, "ESIG_ROLE", "The signer is not the session user.", {})
    earlier = _valid_sigs(s, record_type, record_id, action, loaded.version)
    stale = [e for e in earlier if (e.policy_id, e.policy_version) != (pol.id, pol.version)]
    for e in stale:                    # review m2: steps signed under another policy version start over
        e.status = "superseded"
        e.updated_at = utcnow()
    earlier = [e for e in earlier if e not in stale]
    p_plain = C.plain(params) if params is not None else None
    for e in earlier:                  # review M9: every step signs the same parameters
        if (e.content or {}).get("_params") != p_plain:
            raise ApiError(409, "ESIG_PARAMS_CHANGED", "Earlier steps were signed for different parameters of this "
                           "action; sign the same decision or start over.", {"step": e.step})
    idx = len(earlier)
    if idx >= len(pol.steps):
        return Outcome(True)
    step = pol.steps[idx]
    meanings = POL.expected_meanings(action, step, decision)
    if sig.meaning not in meanings:
        raise ApiError(422, "ESIG_MEANING", f"This step is signed with the meaning {', '.join(meanings)}.",
                       {"expected": meanings, "step": idx + 1})
    block = POL.step_block(pol, idx, a.p.roles, a.user_id, [e.signer_id for e in earlier], loaded.author_id)
    if block == "ESIG_ROLE":
        raise ApiError(403, "ESIG_ROLE", "Your roles do not allow you to sign this step.",
                       {"roles": step["roles"], "step": idx + 1})
    if block == "ESIG_SAME_SIGNER":
        raise ApiError(409, "ESIG_SAME_SIGNER", "Another person must sign this step.", {"step": idx + 1})
    if block == "ESIG_AUTHOR":
        raise ApiError(409, "ESIG_AUTHOR", "The author of this record cannot sign this step.", {"step": idx + 1})
    if pol.auth == "password_totp" and auth.method not in ("password_totp", "sso_mfa"):
        raise ApiError(422, "ESIG_MFA_UNAVAILABLE", "This step needs a verification code.", {})
    current = C.content_hash(loaded.content)
    if not hmac.compare_digest(sig.content_hash, current):
        raise ApiError(409, "ESIG_CONTENT_CHANGED", "The record changed since you opened the signature dialog. "
                       "Review it again.", {"current_hash": current})
    if stored_content is None and params is not None:
        stored_content = {**loaded.content, "_params": params}
    snapshot = C.plain(stored_content if stored_content is not None else loaded.content)
    if not C.size_ok(snapshot):
        raise ApiError(422, "ESIG_CONTENT_TOO_LARGE", "The record is too large to be signed.",
                       {"max_bytes": C.MAX_CONTENT_BYTES})
    settings = ctx_settings or _settings(s)
    if not _mac_keys(settings):    # review m1: Part 11 signatures are always keyed
        raise ApiError(503, "ESIG_SECRETS_REQUIRED", "Signing needs SECRETS_KEY on the server.", {})
    skew = _skew_for(s, settings)
    _check_clock(settings, skew)
    sid = new_id("esg_")
    rec_id = store_record_id or record_id
    rec_ver = store_version if store_version is not None else loaded.version
    from ...services.problem_service import audit_row

    ev = audit_row(s, f"esig_{record_type}"[:32], rec_id, "esig.signed",
                   {"action": action, "step": idx + 1, "meaning": sig.meaning, "content_hash": current,
                    "auth_method": auth.method}, reason=sig.comment.strip() or None, record_version=rec_ver,
                   signature_id=sid)
    now = db_now(s)
    row = EsigSignatureRow(
        id=sid, record_type=record_type, record_id=rec_id, record_version=rec_ver, action=action, step=idx + 1,
        meaning=sig.meaning, signer_id=a.user_id, signer_legal_name=auth.legal_name[:200],
        signer_username=auth.username[:254], signed_at=now, auth_method=auth.method, policy_id=pol.id,
        policy_version=pol.version, content_hash=C.content_hash(snapshot) if stored_content is not None else current,
        content=snapshot, comment=sig.comment, status="valid", audit_event_id=int(ev.id), mac="",
        client_ip=(a.client_ip or "")[:64] or None, session_ref=a.session_ref, row_version=1, created_at=now,
        updated_at=now)
    row.owner_id = current_owner()
    from ...audit_diff import bind_reason, current_reason

    if current_reason() is None and sig.comment.strip():      # review m4: the comment is the action's reason
        bind_reason(sig.comment.strip())
    row.mac = compute_mac(_mac_keys(settings), row)
    s.add(row)
    s.flush()
    if idx + 1 < len(pol.steps):
        nxt = _next_step(pol, idx + 1, a, [e.signer_id for e in earlier] + [a.user_id], loaded.author_id, decision)
        return Outcome(False, {"status": "pending_signatures", "record_type": record_type, "record_id": record_id,
                               "signatures": manifests(s, record_type, rec_id, current_hash=current),
                               "next_step": nxt}, [e.id for e in earlier] + [sid])
    return Outcome(True, None, [e.id for e in earlier] + [sid])


_SETTINGS: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()


def bind_settings(settings: Any, engine: Any) -> None:
    """The settings of one engine's app (keys, skew limit) for signing inside services (`Database.from_settings`)."""
    _SETTINGS[engine] = settings


def _settings(s: Session | None = None) -> Any:
    if s is not None:
        try:
            found = _SETTINGS.get(s.get_bind())
        except TypeError:          # pragma: no cover
            found = None
        if found is not None:
            return found
    from ...config import Settings

    return Settings()


def _skew_for(s: Session, settings: Any) -> float:
    t0 = time.time()
    dbt = db_now(s)
    t1 = time.time()
    app = datetime.fromtimestamp((t0 + t1) / 2, UTC)
    return (dbt - app).total_seconds() * 1000.0 + SKEW_INJECT_MS


def supersede_pending(s: Session, record_type: str, record_id: str, version: int) -> int:
    """4.2: editing a record with pending step signatures marks them superseded (the flow restarts)."""
    n = 0
    from ...services.problem_service import audit_row

    for r in _valid_sigs(s, record_type, record_id, None, version):
        r.status = "superseded"
        r.updated_at = utcnow()
        audit_row(s, f"esig_{record_type}"[:32], record_id, "esig.superseded", {"signature_id": r.id,
                                                                               "action": r.action})
        n += 1
    return n


def locked_error(what: str) -> ApiError:
    return ApiError(409, "ESIG_RECORD_LOCKED", f"{what} is signed and locked; it cannot be changed.", {})


# ---------------------------------------------------------------- manifestation (11.50)

def _local(s: Session, at: datetime) -> str:
    from ....mfg.tz import plant_tz
    from .m2util import plant

    tz = plant_tz(plant(s))
    loc = _aware(at).astimezone(tz)
    off = loc.strftime("%z")
    off = f"{off[:3]}:{off[3:]}" if off else "+00:00"
    return f"{loc.strftime('%Y-%m-%d %H:%M:%S')} {loc.tzname() or ''} (UTC{off})".replace("  ", " ")


def _matches(r: EsigSignatureRow, current_hash: str | None, current_content: dict[str, Any] | None) -> bool:
    """Does the signed snapshot still describe the record? Snapshots with action parameters (`_params`, M9) are
    compared with the current content plus those parameters; policy updates with the policy now in force."""
    if current_hash is None:
        return True
    c = r.content if isinstance(r.content, dict) else {}
    if "_params" in c and current_content is not None:
        if r.record_type == "esig_policy":                 # review m9: the update applied = the content now
            after = c["_params"] or {}
            return all(C.plain(current_content).get(k) == v for k, v in after.items())
        return C.content_hash({**current_content, "_params": c["_params"]}) == r.content_hash
    return r.content_hash == current_hash


def manifest(s: Session, r: EsigSignatureRow, current_hash: str | None, lang: str = "en",
             current_content: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": r.id, "meaning": r.meaning, "meaning_label": MEANING_LABELS.get(lang, MEANING_LABELS["en"])
            .get(r.meaning, r.meaning), "signer_legal_name": r.signer_legal_name,
            "signer_username": r.signer_username, "signed_at": _aware(r.signed_at),
            "signed_at_local": _local(s, r.signed_at), "auth_method": r.auth_method, "action": r.action,
            "step": r.step, "status": r.status, "record_version": r.record_version, "comment": r.comment,
            "content_matches_current": _matches(r, current_hash, current_content)}


def manifests(s: Session, record_type: str, record_id: str, *, current_hash: str | None = None,
              include_superseded: bool = True) -> list[dict[str, Any]]:
    q = select(EsigSignatureRow).where(EsigSignatureRow.record_type == record_type,
                                       EsigSignatureRow.record_id == record_id)
    if not include_superseded:
        q = q.where(EsigSignatureRow.status == "valid")
    rows = list(s.execute(q.order_by(EsigSignatureRow.signed_at, EsigSignatureRow.id)).scalars())
    content = None
    needs = current_hash is None or any(isinstance(r.content, dict) and "_params" in r.content for r in rows)
    if rows and needs and record_type in C.REGISTRY and record_type != "calibration":
        try:
            content = load(s, record_type, record_id).content
            current_hash = current_hash or C.content_hash(content)
        except ApiError:
            pass
    return [manifest(s, r, current_hash, current_content=content) for r in rows]


def record_manifests(s: Session, record_type: str, record_id: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    return manifests(s, record_type, record_id, current_hash=C.content_hash(content))


# ---------------------------------------------------------------- preview (E3)

def _next_step(pol: POL.Policy, idx: int, a: Any, earlier: list[str], author_id: str | None,
               decision: str | None) -> dict[str, Any] | None:
    if idx >= len(pol.steps):
        return None
    st = pol.steps[idx]
    block = POL.step_block(pol, idx, a.p.roles, a.user_id, earlier, author_id)
    return {"step": idx + 1, "meanings": POL.expected_meanings(pol.action, st, decision), "roles": st["roles"],
            "auth": pol.auth, "can_sign": block is None, "blocked_reason": block}


def _preview_in(s: Session, a: Any, record_type: str, record_id: str, action: str, decision: str | None,
                loaded: C.Loaded, pol: POL.Policy | None, on: bool) -> dict[str, Any]:
    from ...audit_diff import part11_on

    h = C.content_hash(loaded.content)
    earlier = _valid_sigs(s, record_type, record_id, action, loaded.version) if pol else []
    nxt = _next_step(pol, len(earlier), a, [e.signer_id for e in earlier], loaded.author_id, decision) \
        if pol and pol.steps else None
    with system_scope():
        u = _user(s, a.user_id)
    signer = {"legal_name": getattr(u, "legal_name", None), "username": getattr(u, "email", None) or a.user_id,
              "enrolled": bool(u is not None and u.esig_enrolled_at is not None and u.esig_revoked_at is None),
              "locked_until": _aware(getattr(u, "esig_locked_until", None)), "methods": []}
    if nxt is not None and not signer["enrolled"] and nxt["can_sign"]:
        nxt["can_sign"], nxt["blocked_reason"] = False, "ESIG_NOT_ENROLLED"
    return {"record_type": record_type, "record_id": record_id, "action": action, "record_version": loaded.version,
            "content_hash": h, "content": C.plain(loaded.content),
            "summary": [{"label": k, "value": v} for k, v in loaded.summary],
            "required": bool(on and pol is not None and pol.steps), "part11_mode": part11_on(s),
            "policy": policy_record(pol) if pol is not None else None, "next_step": nxt,
            "signatures": manifests(s, record_type, record_id, current_hash=h), "signer": signer,
            "legal_statement": ACK_TEXT["en"]}


#: preview action -> the policy action (inspection lots pick by scope)
def policy_action(s: Session, record_type: str, action: str, loaded: C.Loaded) -> str:
    if record_type == "inspection_lot" and action in ("decide", "decide_final"):
        return "decide_final" if getattr(loaded.row, "scope", None) == "final" else "decide"
    return action


def preview(ctx: AppContext, a: Any, record_type: str, record_id: str, action: str, decision: str | None
            ) -> dict[str, Any]:
    from ...audit_diff import part11_on

    with read_tx(ctx) as s:
        loaded = load(s, record_type, record_id)
        pa = policy_action(s, record_type, action, loaded)
        if (record_type, pa) not in POL.DEFAULTS:
            raise ApiError(404, "NOT_FOUND", f"{record_type}.{action} is not a signable action.", {})
        on = part11_on(s) or (record_type, pa) in POL.ALWAYS
        pol = effective_policy(s, record_type, pa)
        out = _preview_in(s, a, record_type, record_id, pa, decision, loaded, pol, on)
    st = status(ctx, a.p) if a.p.scopes is None else None
    if st is not None:
        out["signer"]["methods"] = st["methods"]
    return out


# ---------------------------------------------------------------- lists and verification (E4, E5)

def list_signatures(ctx: AppContext, record_type: str | None, record_id: str | None, signer_id: str | None,
                    from_: date | None, to: date | None, limit: int, offset: int) -> dict[str, Any]:
    conds = []
    if record_type:
        conds.append(EsigSignatureRow.record_type == record_type)
    if record_id:
        conds.append(EsigSignatureRow.record_id == record_id)
    if signer_id:
        conds.append(EsigSignatureRow.signer_id == signer_id)
    if from_:
        conds.append(EsigSignatureRow.signed_at >= datetime.combine(from_, datetime.min.time(), UTC))
    if to:
        conds.append(EsigSignatureRow.signed_at < datetime.combine(to + timedelta(days=1), datetime.min.time(), UTC))
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(EsigSignatureRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(EsigSignatureRow).where(*conds).order_by(EsigSignatureRow.signed_at.desc(),
                                                                              EsigSignatureRow.id)
                              .limit(limit).offset(offset)).scalars())
        items = [{**manifest(s, r, None), "record_type": r.record_type, "record_id": r.record_id,
                  "content_hash": r.content_hash} for r in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}


def _chain_link_ok(s: Session, ctx: AppContext, event_id: int | None) -> bool:
    from ...audit_chain import _hash, _keys
    from ...db.models import AuditEventRow

    if event_id is None:
        return False
    ev = s.get(AuditEventRow, event_id)
    if ev is None or not ev.chain_hash:
        return False
    cond = AuditEventRow.owner_id == ev.owner_id if ev.owner_id else AuditEventRow.owner_id.is_(None)
    prev = s.execute(select(AuditEventRow.chain_hash).where(cond, AuditEventRow.id < ev.id,
                                                            AuditEventRow.chain_hash.is_not(None))
                     .order_by(AuditEventRow.id.desc()).limit(1)).scalar()
    keys = _keys(s)
    if ev.chain_hash.startswith("k1:"):
        return any(hmac.compare_digest(ev.chain_hash, _hash(prev, ev, k)) for k in keys)
    return ev.chain_hash == _hash(prev, ev)


def verify(ctx: AppContext, signature_id: str) -> dict[str, Any]:
    from .. import repo

    with read_tx(ctx) as s:
        r = repo.get_row(s, EsigSignatureRow, signature_id, what="Signature")
        mac = mac_ok(_mac_keys(ctx), r)
        stored = C.content_hash(r.content)
        content_ok = stored == r.content_hash
        current_hash = None
        current_version = None
        matches = False
        try:
            if r.record_type == "calibration":
                from .qa_equipment import calibration_content

                cur = calibration_content(s, r.record_id)
                current_hash, current_version = C.content_hash(C.plain(cur[0])), cur[1]
                matches = current_hash == r.content_hash
            else:
                ld = load(s, r.record_type, r.record_id)
                current_hash, current_version = C.content_hash(ld.content), ld.version
                matches = _matches(r, current_hash, ld.content)
        except ApiError:
            pass
        with system_scope():
            chain = _chain_link_ok(s, ctx, r.audit_event_id)
        return {"signature_id": r.id, "mac_ok": mac, "chain_ok": chain, "content_hash_ok": content_ok,
                "content_matches_current": matches, "record_version_signed": r.record_version,
                "record_version_current": current_version, "current_hash": current_hash}


__getattr__ = m7_examples.module_getattr(__name__)

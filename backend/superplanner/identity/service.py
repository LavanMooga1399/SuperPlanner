"""Identity services (M5-DESIGN 3.1-3.3): OIDC login / callback, TOTP setup / enable / disable / login step,
pending logins, API tokens. Users, sessions and identities are platform tables (system scope).

Security notes (I4): OIDC `state` is stored hashed, the PKCE verifier encrypted with a key derived from the raw
state (never stored), both single use within 10 minutes; TOTP secrets are Fernet-encrypted;
recovery codes are argon2-hashed; pending-login and API tokens are stored as sha256; nothing secret is logged.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select

from ..api.auth import passwords
from ..api.auth import sessions as sess
from ..api.auth.models import UserRow
from ..api.context import AppContext
from ..api.db.models import new_id
from ..api.db.ownership import system_scope
from ..api.errors import ApiError
from ..api.mfg.db_models_m5 import (ApiTokenRow, OidcStateRow, OrgMemberRow, OrgRow, PendingLoginRow,
                                    UserIdentityRow, UserTotpRow)
from . import crypto, oidc, totp
from . import tokens as tok

log = logging.getLogger(__name__)
STATE_MINUTES = 10
PENDING_MINUTES = 5
PENDING_ATTEMPTS = 5


def _h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=UTC)


def sso_enabled(ctx: AppContext) -> bool:
    st = ctx.settings
    return bool(st.oidc_issuer and st.oidc_client_id and st.oidc_client_secret) and not st.single_user


def _domain(email: str | None) -> str:
    return (email or "").rsplit("@", 1)[-1].lower() if email and "@" in email else ""


def sso_required_for(ctx: AppContext, email: str | None) -> bool:
    return sso_enabled(ctx) and _domain(email) in {d.lower() for d in ctx.settings.oidc_required_domains}


def config(ctx: AppContext) -> dict[str, Any]:
    st = ctx.settings
    return {"mode": "single_user" if st.single_user else "accounts", "sso_enabled": sso_enabled(ctx),
            "sso_label": st.oidc_label if sso_enabled(ctx) else "",
            "sso_required_domains": list(st.oidc_required_domains) if sso_enabled(ctx) else [],
            "password_login": not st.single_user}


# ---------------------------------------------------------------- OIDC (3.1)

def _fetch(ctx: AppContext) -> oidc.Fetch:
    return ctx.settings.oidc_http or oidc.http_fetch


def _redirect_uri(ctx: AppContext) -> str:
    st = ctx.settings
    if st.oidc_redirect_url:
        return st.oidc_redirect_url
    base = (st.public_base_url or "http://127.0.0.1:8000").rstrip("/")
    return base + "/api/v1/auth/oidc/callback"


def _state_fernet(state: str) -> Any:
    """The PKCE verifier is encrypted with a key derived from the raw state, which is never stored (only its hash):
    the database alone cannot reveal it."""
    import base64

    from cryptography.fernet import Fernet

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"sp-pkce:" + state.encode()).digest()))


def safe_next(nxt: str | None) -> str:
    """Only same-origin relative paths (open-redirect guard)."""
    if not nxt or not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or urlparse(nxt).netloc:
        return "/"
    return nxt[:500]


def oidc_login(ctx: AppContext, nxt: str | None) -> str:
    if not sso_enabled(ctx):
        raise ApiError(404, "NOT_FOUND", "Single sign-on is not configured.", {})
    st = ctx.settings
    try:
        doc = oidc.discovery(st.oidc_issuer, _fetch(ctx))
    except oidc.OidcError as e:
        raise ApiError(502, e.code, e.message, {}) from None
    state, nonce = oidc.new_state(), oidc.new_state()
    verifier, challenge = oidc.pkce_pair()
    stored = _state_fernet(state).encrypt(verifier.encode()).decode()
    now = _now()
    with system_scope(), ctx.db.write() as s:
        s.query(OidcStateRow).filter(OidcStateRow.expires_at < now).delete(synchronize_session=False)
        s.add(OidcStateRow(state_hash=_h(state), nonce=nonce, verifier_enc=stored, next_url=safe_next(nxt),
                           expires_at=now + timedelta(minutes=STATE_MINUTES)))
    return oidc.authorize_url(doc, st.oidc_client_id, _redirect_uri(ctx), st.oidc_scopes, state, nonce, challenge)


def _take_state(ctx: AppContext, state: str) -> OidcStateRow:
    now = _now()
    with system_scope(), ctx.db.write() as s:
        row = s.get(OidcStateRow, _h(state), with_for_update=True)
        if row is None:
            raise ApiError(400, "AUTH_SSO_STATE", "This sign-in link is not valid any more; start again.", {})
        s.delete(row)                                   # single use
        s.flush()
        s.expunge(row)
    if _aware(row.expires_at) < now:
        raise ApiError(400, "AUTH_SSO_STATE", "This sign-in link has expired; start again.", {})
    return row


def oidc_callback(ctx: AppContext, request: Any, code: str | None, state: str | None, error: str | None
                  ) -> tuple[sess.SessionView, str, str]:
    """-> (session view, cookie token, next url)."""
    if not sso_enabled(ctx):
        raise ApiError(404, "NOT_FOUND", "Single sign-on is not configured.", {})
    if not state or len(state) > 200:
        raise ApiError(400, "AUTH_SSO_STATE", "The sign-in response has no valid state.", {})
    row = _take_state(ctx, state)
    if error or not code:
        raise ApiError(401, "AUTH_SSO_FAILED", "The provider did not sign you in.", {"error": (error or "")[:100]})
    st = ctx.settings
    verifier = _state_fernet(state).decrypt(row.verifier_enc.encode()).decode()
    fetch = _fetch(ctx)
    try:
        doc = oidc.discovery(st.oidc_issuer, fetch)
        tokens = oidc.exchange(doc, fetch, code=code[:2000], verifier=verifier, redirect_uri=_redirect_uri(ctx),
                               client_id=st.oidc_client_id, client_secret=st.oidc_client_secret)
        claims = oidc.validate_id_token(tokens["id_token"], doc, fetch, issuer=st.oidc_issuer,
                                        client_id=st.oidc_client_id, nonce=row.nonce)
    except oidc.OidcError as e:
        log.info("auth.sso_failed code=%s", e.code)
        raise ApiError(401 if e.code == "AUTH_SSO_FAILED" else 502, e.code, e.message, {}) from None
    user = _link_or_create(ctx, claims)
    now = _now()
    with system_scope(), ctx.db.write() as s:
        u = s.get(UserRow, user)
        if u is None or u.disabled:
            raise ApiError(403, "AUTH_SSO_NOT_ALLOWED", "This account is disabled.", {})
        u.last_login_at = now
        old = sess.lookup(s, sess.read_cookie(request, st), st, now)
        if old is not None:
            sess.revoke(s, old[0].id, now)
        srow, token = sess.create_session(s, u, st, request, now)
        srow.expires_at = min(_aware(srow.expires_at), now + timedelta(hours=st.sso_session_hours))
        s.flush()
        v = sess.view(srow, u)
    return v, token, row.next_url


def _link_or_create(ctx: AppContext, claims: dict[str, Any]) -> str:
    st = ctx.settings
    iss, sub = str(claims["iss"]), str(claims["sub"])[:255]
    email = str(claims.get("email") or "").strip().lower() or None
    verified = claims.get("email_verified") is True
    now = _now()
    with system_scope(), ctx.db.write() as s:
        ident = s.execute(select(UserIdentityRow).where(UserIdentityRow.issuer == iss, UserIdentityRow.sub == sub)
                          ).scalars().first()
        if ident is not None:
            ident.last_login_at = now
            return ident.user_id
        user = None
        if email and verified:
            user = s.execute(select(UserRow).where(UserRow.email == email)).scalars().first()
            if user is not None and (user.is_local or user.kind != "person"):
                user = None
        if user is None:
            allowed = {d.lower() for d in st.oidc_allowed_domains}
            if not (email and verified and _domain(email) in allowed):
                raise ApiError(403, "AUTH_SSO_NOT_ALLOWED", "Your organisation has not enabled sign-in for this "
                               "account.", {})
            user = UserRow(id=new_id("usr_"), email=email, display_name=str(claims.get("name") or "")[:100] or None,
                           password_hash=None, is_local=False, disabled=False, created_at=now, updated_at=now,
                           kind="person")
            s.add(user)
            s.flush()
            if st.oidc_org_slug:
                org = s.execute(select(OrgRow).where(OrgRow.slug == st.oidc_org_slug)).scalars().first()
                if org is not None:
                    s.add(OrgMemberRow(id=new_id("orm_"), org_id=org.id, user_id=user.id, org_role="org_member",
                                       created_at=now, row_version=1))
        s.add(UserIdentityRow(id=new_id("uid_"), issuer=iss, sub=sub, user_id=user.id, email=email, created_at=now,
                              last_login_at=now))
        return user.id


# ---------------------------------------------------------------- TOTP (3.2)

def totp_row(s: Any, user_id: str) -> UserTotpRow | None:
    return s.get(UserTotpRow, user_id)


def totp_enabled(s: Any, user_id: str) -> bool:
    r = totp_row(s, user_id)
    return r is not None and r.enabled_at is not None


def org_requires_2fa(s: Any, user_id: str) -> bool:
    return s.execute(select(func.count()).select_from(OrgMemberRow).join(OrgRow, OrgRow.id == OrgMemberRow.org_id)
                     .where(OrgMemberRow.user_id == user_id, OrgRow.require_2fa.is_(True))).scalar() > 0


def totp_status(ctx: AppContext, user_id: str) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        r = totp_row(s, user_id)
        return {"enabled": bool(r and r.enabled_at), "enabled_at": _aware(r.enabled_at) if r else None,
                "recovery_codes_left": len(r.recovery_hashes or []) if r and r.enabled_at else 0,
                "required_by_org": org_requires_2fa(s, user_id)}


def totp_setup(ctx: AppContext, user_id: str) -> dict[str, Any]:
    keys = ctx.settings.secrets_keys
    secret = totp.new_secret()
    enc = crypto.encrypt(keys, secret)
    now = _now()
    with system_scope(), ctx.db.write() as s:
        u = s.get(UserRow, user_id)
        r = totp_row(s, user_id)
        if r is not None and r.enabled_at is not None:
            raise ApiError(409, "AUTH_2FA_ENABLED", "Two-step sign-in is already on; turn it off first.", {})
        if r is None:
            s.add(UserTotpRow(user_id=user_id, secret_enc=enc, enabled_at=None, last_step=None, recovery_hashes=[],
                              created_at=now))
        else:
            r.secret_enc, r.last_step = enc, None
    return {"secret": secret, "otpauth_uri": totp.otpauth_uri(secret, (u.email if u else None) or user_id)}


def _check_code(ctx: AppContext, s: Any, r: UserTotpRow, code: str, unix: float | None = None) -> bool:
    secret = crypto.decrypt(ctx.settings.secrets_keys, r.secret_enc)
    step = totp.verify(secret, code, unix if unix is not None else _now().timestamp(), r.last_step)
    if step is None:
        return False
    r.last_step = step                         # replay of the same (or an older) step is refused
    return True


def _new_recovery(ctx: AppContext) -> tuple[list[str], list[str]]:
    codes = totp.recovery_codes()
    profile = ctx.settings.password_hash_profile
    return codes, [passwords.hash_password(c, profile) for c in codes]


def totp_enable(ctx: AppContext, user_id: str, code: str) -> dict[str, Any]:
    codes, hashes = _new_recovery(ctx)
    with system_scope(), ctx.db.write() as s:
        r = s.get(UserTotpRow, user_id, with_for_update=True)
        if r is None:
            raise ApiError(409, "AUTH_2FA_NOT_SET_UP", "Start the setup first.", {})
        if r.enabled_at is not None:
            raise ApiError(409, "AUTH_2FA_ENABLED", "Two-step sign-in is already on.", {})
        if not _check_code(ctx, s, r, code):
            raise ApiError(422, "AUTH_TOTP_INVALID", "That code is not valid.", {"loc": ["body", "code"]})
        r.enabled_at, r.recovery_hashes = _now(), hashes
    log.info("auth.totp_enabled user_id=%s", user_id)
    return {"recovery_codes": codes}


def totp_disable(ctx: AppContext, user_id: str, code: str) -> None:
    with system_scope(), ctx.db.write() as s:
        r = s.get(UserTotpRow, user_id, with_for_update=True)
        if r is None or r.enabled_at is None:
            raise ApiError(409, "AUTH_2FA_NOT_SET_UP", "Two-step sign-in is off.", {})
        if org_requires_2fa(s, user_id):
            raise ApiError(409, "AUTH_2FA_REQUIRED", "Your organisation requires two-step sign-in.", {})
        if not _check_code(ctx, s, r, code):
            raise ApiError(422, "AUTH_TOTP_INVALID", "That code is not valid.", {"loc": ["body", "code"]})
        s.delete(r)


def totp_new_recovery(ctx: AppContext, user_id: str, code: str) -> dict[str, Any]:
    codes, hashes = _new_recovery(ctx)
    with system_scope(), ctx.db.write() as s:
        r = s.get(UserTotpRow, user_id, with_for_update=True)
        if r is None or r.enabled_at is None:
            raise ApiError(409, "AUTH_2FA_NOT_SET_UP", "Two-step sign-in is off.", {})
        if not _check_code(ctx, s, r, code):
            raise ApiError(422, "AUTH_TOTP_INVALID", "That code is not valid.", {"loc": ["body", "code"]})
        r.recovery_hashes = hashes
    return {"recovery_codes": codes}


def new_pending(ctx: AppContext, s: Any, user_id: str) -> str:
    t = secrets.token_urlsafe(32)
    now = _now()
    s.query(PendingLoginRow).filter(PendingLoginRow.expires_at < now).delete(synchronize_session=False)
    s.add(PendingLoginRow(token_hash=_h(t), user_id=user_id, expires_at=now + timedelta(minutes=PENDING_MINUTES),
                          attempts=0))
    return t


def pending_user(ctx: AppContext, token: str | None) -> str:
    if not token or len(token) > 100:
        raise ApiError(401, "AUTH_REQUIRED", "Please sign in to continue.", {})
    with system_scope(), ctx.db.read() as s:
        r = s.get(PendingLoginRow, _h(token))
        if r is None or _aware(r.expires_at) < _now():
            raise ApiError(401, "AUTH_REQUIRED", "The sign-in has expired; sign in again.", {})
        return r.user_id


def login_totp(ctx: AppContext, request: Any, pending: str, code: str | None, recovery: str | None
               ) -> tuple[sess.SessionView, str]:
    if not (code or recovery):
        raise ApiError(422, "AUTH_TOTP_INVALID", "Give the code from your app or a recovery code.", {})
    now = _now()
    profile = ctx.settings.password_hash_profile
    ok = False
    with system_scope(), ctx.db.write() as s:
        p = s.get(PendingLoginRow, _h(pending), with_for_update=True)
        if p is None or _aware(p.expires_at) < now or p.attempts >= PENDING_ATTEMPTS:
            raise ApiError(401, "AUTH_REQUIRED", "The sign-in has expired; sign in again.", {})
        p.attempts += 1
        r = s.get(UserTotpRow, p.user_id, with_for_update=True)
        if r is not None and r.enabled_at is not None:
            if code:
                ok = _check_code(ctx, s, r, code)
            else:
                left = list(r.recovery_hashes or [])
                for i, hsh in enumerate(left):
                    if passwords.verify_password(hsh, recovery.strip().lower(), profile):
                        del left[i]
                        r.recovery_hashes = left
                        ok = True
                        break
        user_id = p.user_id
        if ok:
            s.delete(p)
    if not ok:
        raise ApiError(422, "AUTH_TOTP_INVALID", "That code is not valid.", {})
    with system_scope(), ctx.db.write() as s:
        u = s.get(UserRow, user_id)
        if u is None or u.disabled:
            raise ApiError(401, "AUTH_REQUIRED", "Please sign in to continue.", {})
        u.last_login_at = now
        row, token = sess.create_session(s, u, ctx.settings, request, now)
        return sess.view(row, u), token


# ---------------------------------------------------------------- API tokens (3.3)

def token_record(r: ApiTokenRow) -> dict[str, Any]:
    return {"id": r.id, "kind": r.kind, "name": r.name, "prefix": r.prefix, "scopes": list(r.scopes),
            "workspace_owner_id": r.workspace_owner_id, "expires_at": _aware(r.expires_at),
            "last_used_at": _aware(r.last_used_at), "last_used_ip": r.last_used_ip, "created_at": _aware(r.created_at),
            "revoked_at": _aware(r.revoked_at)}


def _admin_plants(s: Any, user_id: str) -> set[str]:
    """Plant workspaces where `user_id` is an active `plant_admin` (and not disabled)."""
    from ..api.mfg.db_models_m2 import MfgPlantMemberRow

    u = s.get(UserRow, user_id)
    if u is None or u.disabled:
        return set()
    return {o for o, roles in s.execute(select(MfgPlantMemberRow.owner_id, MfgPlantMemberRow.roles).where(
        MfgPlantMemberRow.user_id == user_id, MfgPlantMemberRow.active.is_(True))).all()
        if "plant_admin" in (roles or [])}


def list_tokens(ctx: AppContext, user_id: str) -> dict[str, Any]:
    """Own personal tokens and the plant tokens of every plant the caller administers (15.WP-S M2)."""
    with system_scope(), ctx.db.read() as s:
        plants = _admin_plants(s, user_id)
        cond = (ApiTokenRow.created_by == user_id) | (ApiTokenRow.user_id == user_id)
        if plants:
            cond = cond | ((ApiTokenRow.kind == "plant") & ApiTokenRow.workspace_owner_id.in_(sorted(plants)))
        rows = list(s.execute(select(ApiTokenRow).where(cond).order_by(ApiTokenRow.created_at.desc())).scalars())
        return {"items": [token_record(r) for r in rows]}


def valid_scopes() -> set[str]:
    from ..api.mfg.access import PERMISSIONS

    return set(PERMISSIONS) | {"integration.read", "integration.write"}


def create_token(ctx: AppContext, user_id: str, inp: Any) -> dict[str, Any]:
    bad = [x for x in inp.scopes if x not in valid_scopes()]
    if bad:
        raise ApiError(422, "VALIDATION_ERROR", f"Unknown scope {bad[0]!r}.",
                       {"errors": [{"loc": ["body", "scopes"], "msg": f"unknown scope {bad[0]!r}",
                                    "type": "value_error"}]})
    ws = inp.workspace_owner_id or user_id
    holder = user_id
    from ..api.mfg.access import _membership

    if inp.kind == "plant":
        roles = _membership(ctx, ws, user_id) if ws != user_id else None
        with system_scope(), ctx.db.read() as s:
            wu = s.get(UserRow, ws)
            is_plant = wu is not None and wu.kind == "plant"
        if ws == user_id or not roles or "plant_admin" not in roles or not is_plant:
            raise ApiError(403, "MFG_FORBIDDEN", "Plant tokens are created by a plant admin of that plant.",
                           {"permission": "plant_admin"})
        holder = ws                                   # the plant principal
    elif ws != user_id and not _membership(ctx, ws, user_id):
        raise ApiError(404, "NOT_FOUND", "Workspace not found.", {"id": ws})
    raw = tok.new_token()
    now = _now()
    with system_scope(), ctx.db.write() as s:
        r = ApiTokenRow(id=new_id("tok_"), kind=inp.kind, user_id=holder, name=inp.name, token_hash=tok.token_hash(raw),
                        prefix=tok.display_prefix(raw), scopes=sorted(set(inp.scopes)), workspace_owner_id=ws,
                        expires_at=now + timedelta(days=inp.expires_days), last_used_at=None, last_used_ip=None,
                        created_by=user_id, created_at=now, revoked_at=None)
        s.add(r)
        s.flush()
        out = token_record(r)
    log.info("auth.token_created id=%s kind=%s", out["id"], inp.kind)
    return {**out, "token": raw}


def revoke_token(ctx: AppContext, user_id: str, token_id: str) -> None:
    with system_scope(), ctx.db.write() as s:
        r = s.get(ApiTokenRow, token_id) if len(token_id) <= 64 else None
        if r is None or (user_id not in (r.created_by, r.user_id) and not (
                r.kind == "plant" and r.workspace_owner_id in _admin_plants(s, user_id))):
            raise ApiError(404, "NOT_FOUND", "Token not found.", {"id": token_id[:64]})
        if r.revoked_at is None:
            r.revoked_at = _now()


def resolve_bearer(ctx: AppContext, raw: str, ip: str | None) -> ApiTokenRow:
    """The token row for a bearer value (401 `AUTH_TOKEN_INVALID` / `AUTH_TOKEN_EXPIRED`)."""
    if not tok.looks_like(raw):
        raise ApiError(401, "AUTH_TOKEN_INVALID", "The API token is not valid.", {})
    h = tok.token_hash(raw)
    now = _now()
    with system_scope(), ctx.db.read() as s:
        r = s.execute(select(ApiTokenRow).where(ApiTokenRow.token_hash == h)).scalars().first()
        u = s.get(UserRow, r.user_id) if r is not None else None
        if r is None or r.revoked_at is not None or u is None or u.disabled:
            raise ApiError(401, "AUTH_TOKEN_INVALID", "The API token is not valid.", {})
        if r.kind == "plant" and r.workspace_owner_id not in _admin_plants(s, r.created_by):
            # the creator lost plant_admin or was disabled: the plant token stops working (15.WP-S M2)
            raise ApiError(401, "AUTH_TOKEN_INVALID", "The API token is not valid.", {})
        if _aware(r.expires_at) <= now:
            raise ApiError(401, "AUTH_TOKEN_EXPIRED", "The API token has expired.", {})
        s.expunge(r)
    if r.last_used_at is None or now - _aware(r.last_used_at) > timedelta(minutes=1):
        with system_scope(), ctx.db.write() as s:
            x = s.get(ApiTokenRow, r.id)
            if x is not None:
                x.last_used_at, x.last_used_ip = now, (ip or "")[:64] or None
    return r


__all__ = ["config", "create_token", "list_tokens", "login_totp", "oidc_callback", "oidc_login", "resolve_bearer",
           "revoke_token", "safe_next", "sso_required_for", "totp_disable", "totp_enable", "totp_new_recovery",
           "totp_setup", "totp_status"]

"""Push subscription endpoints (M6-DESIGN 2, 5 M1-M3; session users only)."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..api.db import new_id, utcnow
from ..api.errors import ApiError, not_found
from ..api.mfg.db_models_m6 import PushSubscriptionRow
from ..api.schemas import as_utc
from .model import PushSubscriptionInput
from .vapid import b64u_decode, public_key

MAX_SUBSCRIPTIONS_PER_USER = 20
#: M6 review M3: the public push services of the browsers (exact host or a subdomain of a `.`-prefixed entry)
PUSH_HOSTS: tuple[str, ...] = ("fcm.googleapis.com", ".push.services.mozilla.com", ".notify.windows.com",
                               "web.push.apple.com", ".push.apple.com")


def host_allowed(host: str, settings: Any) -> bool:
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    for e in PUSH_HOSTS:
        if (e.startswith(".") and h.endswith(e) and len(h) > len(e)) or h == e:
            return True
    return h in (getattr(settings, "webpush_extra_hosts", None) or []) and not settings.is_production


def endpoint_allowed(endpoint: str, settings: Any) -> bool:
    u = urlsplit(endpoint)
    return u.scheme == "https" and not u.username and not u.password and (u.port in (None, 443)) and \
        host_allowed(u.hostname or "", settings)


def disabled() -> ApiError:
    return ApiError(422, "PUSH_DISABLED", "Push notifications are not set up on this server.", {})


def vapid_public_key(ctx: Any) -> dict[str, Any]:
    s = ctx.settings
    if not s.push_enabled:
        return {"enabled": False, "public_key": None, "topics": ["critical_alerts", "approvals", "digest_ready"]}
    return {"enabled": True, "public_key": public_key(s.webpush_vapid_private_key),
            "topics": ["critical_alerts", "approvals", "digest_ready"]}


def _enc(ctx: Any, value: str) -> str:
    keys = list(ctx.settings.secrets_keys or [])
    if not keys:
        return "raw:" + value
    from ..identity.crypto import encrypt

    return "enc:" + encrypt(keys, value)


def dec(ctx_or_settings: Any, value: str) -> str:
    if value.startswith("raw:"):
        return value[4:]
    settings = getattr(ctx_or_settings, "settings", ctx_or_settings)
    from ..identity.crypto import decrypt

    return decrypt(list(settings.secrets_keys or []), value[4:] if value.startswith("enc:") else value)


def record(r: PushSubscriptionRow) -> dict[str, Any]:
    # M6 review M3: no delivery details (scanning oracle) - only whether the device is active
    return {"id": r.id, "endpoint_host": urlsplit(r.endpoint).hostname or "", "topics": list(r.topics or []),
            "user_agent": r.user_agent, "created_at": as_utc(r.created_at), "active": int(r.failures or 0) == 0}


def list_subscriptions(ctx: Any, user_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        rows = list(s.execute(select(PushSubscriptionRow).where(PushSubscriptionRow.user_id == user_id)
                              .order_by(PushSubscriptionRow.created_at)).scalars())
        return {"items": [record(r) for r in rows]}


def subscribe(ctx: Any, user_id: str, body: PushSubscriptionInput, user_agent: str) -> dict[str, Any]:
    if not ctx.settings.push_enabled:
        raise disabled()
    try:
        p256 = b64u_decode(body.keys.p256dh)
        auth = b64u_decode(body.keys.auth)
    except Exception:  # noqa: BLE001
        p256, auth = b"", b""
    host = urlsplit(body.endpoint).hostname or ""
    if not endpoint_allowed(body.endpoint, ctx.settings):
        raise ApiError(422, "PUSH_SUBSCRIPTION_INVALID", "The push endpoint is not a known browser push service.",
                       {"loc": ["body", "endpoint"]})
    if len(p256) != 65 or p256[0] != 4 or len(auth) != 16 or not host or "." not in host:
        raise ApiError(422, "PUSH_SUBSCRIPTION_INVALID", "The push subscription keys or endpoint are not valid.",
                       {"loc": ["body", "keys"]})
    try:
        from cryptography.hazmat.primitives.asymmetric import ec

        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256)
    except Exception:  # noqa: BLE001
        raise ApiError(422, "PUSH_SUBSCRIPTION_INVALID", "The push subscription key is not a P-256 point.",
                       {"loc": ["body", "keys", "p256dh"]}) from None
    eh = hashlib.sha256(body.endpoint.encode()).hexdigest()
    now = utcnow()
    from ..api.auth.models import UserRow

    with ctx.write_guard(), ctx.db.write() as s:
        # review m5: serialise this user's subscribes (count + upsert) and move a device that another account
        # registered to this account (one browser = one owner; never two accounts on one device)
        s.execute(select(UserRow.id).where(UserRow.id == user_id).with_for_update())
        s.execute(delete(PushSubscriptionRow).where(PushSubscriptionRow.endpoint_hash == eh,
                                                    PushSubscriptionRow.user_id != user_id))
        n = len(list(s.execute(select(PushSubscriptionRow.id).where(PushSubscriptionRow.user_id == user_id))))
        stmt = pg_insert(PushSubscriptionRow).values(
            id=new_id("psb_"), user_id=user_id, endpoint=body.endpoint, endpoint_hash=eh,
            p256dh_enc=_enc(ctx, body.keys.p256dh), auth_enc=_enc(ctx, body.keys.auth), topics=list(body.topics),
            user_agent=(user_agent or "")[:300], created_at=now, last_success_at=None, failures=0)
        stmt = stmt.on_conflict_do_update(constraint="uq_push_subscriptions_endpoint", set_={
            "p256dh_enc": stmt.excluded.p256dh_enc, "auth_enc": stmt.excluded.auth_enc,
            "topics": stmt.excluded.topics, "user_agent": stmt.excluded.user_agent, "failures": 0})
        existing = s.execute(select(PushSubscriptionRow.id).where(PushSubscriptionRow.user_id == user_id,
                                                                  PushSubscriptionRow.endpoint_hash == eh)).first()
        if existing is None and n >= MAX_SUBSCRIPTIONS_PER_USER:
            raise ApiError(409, "PUSH_TOO_MANY", f"At most {MAX_SUBSCRIPTIONS_PER_USER} devices per person.", {})
        s.execute(stmt)
        row = s.execute(select(PushSubscriptionRow).where(PushSubscriptionRow.user_id == user_id,
                                                          PushSubscriptionRow.endpoint_hash == eh)
                        .execution_options(populate_existing=True)).scalars().one()
        return record(row)


def unsubscribe(ctx: Any, user_id: str, subscription_id: str) -> None:
    with ctx.write_guard(), ctx.db.write() as s:
        row = s.execute(select(PushSubscriptionRow).where(PushSubscriptionRow.id == subscription_id,
                                                          PushSubscriptionRow.user_id == user_id)).scalars().first()
        if row is None:
            raise not_found("Push subscription", subscription_id)
        s.delete(row)

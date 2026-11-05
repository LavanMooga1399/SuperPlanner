"""Transactional outbox, pull cursor and signed webhooks (M5-DESIGN 4.6, I2, I4).

- `emit(s, type, data)` writes an `int_outbox` row in the caller's business transaction when integration is
  enabled for the bound plant (one cached settings read per session; a rolled-back transaction leaves no event).
- `events(after, limit, types)` -> ordered events + `next_after`; a cursor older than the retained window is 410
  `INT_CURSOR_EXPIRED` (outbox rows are purged after 90 days, 7).
- Webhooks: `SP-Event-Id`, `SP-Signature: t=<unix>,v1=<hex hmac-sha256(secret, t + "." + body)>`; FIFO per endpoint
  (a failing event blocks later ones); backoff 30 s doubling to 1 h, `dead` after 24 h; https only and no private
  targets unless `INTEGRATION_ALLOW_PRIVATE_TARGETS` (SSRF guard, resolved addresses checked).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api.db import new_id
from ..api.errors import ApiError
from .contract import SCHEMA

BACKOFF_FIRST = 30
BACKOFF_MAX = 3600
DEAD_AFTER = timedelta(hours=24)
DELIVERY_TIMEOUT = 10.0
MAX_PULL = 1000

Poster = Callable[[str, bytes, dict[str, str]], tuple[int, str]]


def _settings(s: Session) -> Any:
    from ..api.mfg.db_models_m5 import IntSettingsRow

    key = "sp_int_settings"
    if key not in s.info:
        s.info[key] = s.execute(select(IntSettingsRow)).scalars().first()
    return s.info[key]


def enabled(s: Session) -> bool:
    st = _settings(s)
    return bool(st is not None and st.enabled)


def emit(s: Session, type_: str, data: dict[str, Any], entity_ref: str | None = None) -> None:
    """Write one outbound event in the business transaction (no-op while integration is off)."""
    if not enabled(s):
        return
    from ..api.mfg.db_models_m5 import IntOutboxRow
    from ..api.mfg.services.common import jsonable
    from ..api.mfg.services.m2util import actor_id

    s.add(IntOutboxRow(id=new_id("evt_"), type=type_, entity_ref=(entity_ref or "")[:64] or None,
                       data=jsonable(data), actor_id=actor_id(), occurred_at=datetime.now(UTC)))


def event_view(r: Any, plant: dict[str, Any]) -> dict[str, Any]:
    return {"schema": SCHEMA, "id": int(r.seq), "type": r.type, "occurred_at": r.occurred_at, "plant": plant,
            "actor": r.actor_id, "data": r.data}


def events(s: Session, after: int, limit: int, types: list[str] | None, plant: dict[str, Any]) -> dict[str, Any]:
    from ..api.mfg.db_models_m5 import IntOutboxRow

    purged = int(((_settings(s).sor or {}) if _settings(s) is not None else {}).get("_purged_through", 0) or 0)
    if 0 < after < purged:                     # set by retention (7) when delivered events are purged
        raise ApiError(410, "INT_CURSOR_EXPIRED", "Events after this cursor are no longer kept; resynchronise from "
                       "a snapshot.", {"oldest": purged + 1})
    q = select(IntOutboxRow).where(IntOutboxRow.seq > after)
    if types:
        q = q.where(IntOutboxRow.type.in_(types))
    rows = list(s.execute(q.order_by(IntOutboxRow.seq).limit(min(limit, MAX_PULL))).scalars())
    return {"items": [event_view(r, plant) for r in rows], "next_after": int(rows[-1].seq) if rows else after}


# ---------------------------------------------------------------- webhooks

def sign(secret: str, body: bytes, t: int) -> str:
    mac = hmac.new(secret.encode(), str(t).encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify_signature(secret: str, body: bytes, header: str, tolerance: int = 300, now: int | None = None) -> bool:
    """Receiver side (documented for ERP middleware): constant-time compare and a timestamp window."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((now if now is not None else int(time.time())) - t) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, body, t).split("v1=", 1)[1], parts.get("v1", ""))


def check_url(url: str, allow_private: bool) -> None:
    """422 `INT_URL_NOT_ALLOWED`: https only, and every resolved address public unless private targets are
    allowed."""
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise ApiError(422, "INT_URL_NOT_ALLOWED", "Webhook URLs must be https without credentials.",
                       {"loc": ["body", "url"]})
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ApiError(422, "INT_URL_NOT_ALLOWED", "The webhook host cannot be resolved.",
                       {"loc": ["body", "url"]}) from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or \
                ip.is_unspecified or (ip.version == 6 and ip.ipv4_mapped is not None and
                                      (ip.ipv4_mapped.is_private or ip.ipv4_mapped.is_loopback)):
            raise ApiError(422, "INT_URL_NOT_ALLOWED", "Webhook URLs must not point to private or local addresses "
                           "(set INTEGRATION_ALLOW_PRIVATE_TARGETS for ERP middleware on the LAN).",
                           {"loc": ["body", "url"], "address": str(ip)})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are not followed (a 3xx to an internal host would bypass the SSRF guard); a 3xx is a failure."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def http_post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json",
                                                                        **headers})
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(
        context=ssl.create_default_context()))
    try:
        with opener.open(req, timeout=DELIVERY_TIMEOUT) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP {e.code}"
    except Exception as e:                 # network errors are retried
        return 0, e.__class__.__name__


def backoff(attempts: int) -> int:
    return min(BACKOFF_MAX, BACKOFF_FIRST * (2 ** max(0, attempts - 1)))


def deliver_endpoint(s: Session, endpoint: Any, secret: str, plant: dict[str, Any], post: Poster,
                     now: datetime | None = None, max_events: int = 500,
                     allow_private: bool | None = None) -> dict[str, int]:
    """Deliver due events of one endpoint in seq order (caller holds the endpoint row lock). Stops at the first
    failure (FIFO). Returns counts. With `allow_private` given, the URL is re-checked right before posting (the
    host may resolve differently than when the endpoint was saved); a refused URL is a failed attempt, no
    request is sent."""
    from ..api.mfg.db_models_m5 import IntDeliveryRow, IntOutboxRow

    now = now or datetime.now(UTC)
    out = {"delivered": 0, "failed": 0, "dead": 0}
    q = select(IntOutboxRow).where(IntOutboxRow.seq > endpoint.cursor).order_by(IntOutboxRow.seq).limit(max_events)
    if endpoint.event_types:
        q = q.where(IntOutboxRow.type.in_(list(endpoint.event_types)))
    for ev in s.execute(q).scalars():
        d = s.execute(select(IntDeliveryRow).where(IntDeliveryRow.endpoint_id == endpoint.id,
                                                   IntDeliveryRow.event_seq == ev.seq)).scalars().first()
        if d is None:
            d = IntDeliveryRow(id=new_id("dlv_"), endpoint_id=endpoint.id, event_seq=int(ev.seq), status="pending",
                               attempts=0, next_attempt_at=now, last_error=None, last_status_code=None,
                               delivered_at=None, created_at=now)
            s.add(d)
            s.flush()
        if d.status == "dead":
            out["dead"] += 1
            break                                   # FIFO: a dead event blocks until retried
        if d.next_attempt_at is not None and _aware(d.next_attempt_at) > now:
            break
        body = json.dumps(_json(event_view(ev, plant)), separators=(",", ":"), sort_keys=True).encode()
        t = int(now.timestamp())
        try:
            if allow_private is not None:
                check_url(endpoint.url, allow_private)
            code, err = post(endpoint.url, body, {"SP-Event-Id": str(ev.seq),
                                                  "SP-Signature": sign(secret, body, t)})
        except ApiError as e:
            code, err = 0, f"{e.code}: {e.message}"
        d.attempts += 1
        d.last_status_code = code or None
        if 200 <= code < 300:
            d.status, d.delivered_at, d.next_attempt_at, d.last_error = "delivered", now, None, None
            endpoint.cursor = int(ev.seq)
            out["delivered"] += 1
            continue
        d.last_error = (err or f"HTTP {code}")[:500]
        if now - _aware(d.created_at) >= DEAD_AFTER:
            d.status, d.next_attempt_at = "dead", None
            out["dead"] += 1
        else:
            d.next_attempt_at = now + timedelta(seconds=backoff(d.attempts))
            out["failed"] += 1
        break
    s.flush()
    return out


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _json(v: Any) -> Any:
    from ..api.mfg.services.common import jsonable

    return jsonable(v)


def run_delivery_job(ctx: Any, run_id: str, lease: Any) -> None:  # pragma: no cover - scheduled delivery (S2)
    from ..api.mfg.services.integration import deliver_all_job

    deliver_all_job(ctx, run_id, lease)


__all__ = ["backoff", "check_url", "deliver_endpoint", "emit", "enabled", "events", "sign", "verify_signature"]

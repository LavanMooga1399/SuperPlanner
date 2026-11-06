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
import http.client
import socket
import ssl
import time
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


_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


def _embedded_v4(ip: Any) -> list[Any]:
    """IPv4 addresses carried inside an IPv6 one: v4-mapped, NAT64 (64:ff9b::/96), 6to4 (2002::/16), Teredo."""
    if ip.version != 6:
        return []
    out = []
    if ip.ipv4_mapped is not None:
        out.append(ip.ipv4_mapped)
    if ip in _NAT64:
        out.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip.sixtofour is not None:
        out.append(ip.sixtofour)
    if ip.teredo is not None:
        out.extend(ip.teredo)
    return out


def _bad_ip(ip: Any) -> bool:
    """Anything that is not a global unicast address (blocks private, loopback, link-local, CGNAT 100.64/10,
    documentation, benchmarking, multicast, reserved), also when embedded in IPv6 (15.WP-S minor 2)."""
    if ip.version == 6 and ip in _NAT64_LOCAL:
        return True
    if not ip.is_global or ip.is_multicast:
        return True
    return any(_bad_ip(x) for x in _embedded_v4(ip))


def resolve_checked(url: str, allow_private: bool) -> tuple[str, int, list[str]]:
    """(host, port, addresses) of an https URL; 422 `INT_URL_NOT_ALLOWED` unless https without credentials and,
    unless private targets are allowed, every resolved address public."""
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise ApiError(422, "INT_URL_NOT_ALLOWED", "Webhook URLs must be https without credentials.",
                       {"loc": ["body", "url"]})
    port = u.port or 443
    try:
        infos = socket.getaddrinfo(u.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ApiError(422, "INT_URL_NOT_ALLOWED", "The webhook host cannot be resolved.",
                       {"loc": ["body", "url"]}) from None
    addrs: list[str] = []
    for info in infos:
        a = info[4][0].split("%")[0]
        ip = ipaddress.ip_address(a)
        if not allow_private and _bad_ip(ip):
            raise ApiError(422, "INT_URL_NOT_ALLOWED", "Webhook URLs must not point to private or local addresses "
                           "(set INTEGRATION_ALLOW_PRIVATE_TARGETS for ERP middleware on the LAN).",
                           {"loc": ["body", "url"], "address": str(ip)})
        if a not in addrs:
            addrs.append(a)
    if not addrs:
        raise ApiError(422, "INT_URL_NOT_ALLOWED", "The webhook host cannot be resolved.", {"loc": ["body", "url"]})
    return u.hostname, port, addrs


def check_url(url: str, allow_private: bool) -> None:
    """422 `INT_URL_NOT_ALLOWED`: https only, and every resolved address public unless private targets are
    allowed."""
    resolve_checked(url, allow_private)


class ProxyError(OSError):
    """The HTTPS proxy refused or failed the CONNECT (a failed delivery attempt)."""


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connects to exactly the address that passed the SSRF check (no second DNS lookup: closes the rebinding
    window), while TLS still uses the URL's host name for SNI and certificate verification. With a proxy, the
    tunnel is `CONNECT <checked ip>:<port>` (`connect_by = "ip"`, default) so the proxy cannot resolve the name to
    another address; `connect_by = "host"` sends the host name instead (for proxies that only tunnel to names -
    then the proxy resolves it; the SSRF check of the target still ran)."""

    def __init__(self, host: str, ip: str, port: int, timeout: float, context: ssl.SSLContext,
                 proxy: dict[str, Any] | None = None):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._pinned_ip = ip
        self._proxy = proxy

    def _socket_to(self, ip: str, port: int) -> socket.socket:
        a = ipaddress.ip_address(ip)                      # a literal: no resolver involved at all
        sock = socket.socket(socket.AF_INET6 if a.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((str(a), port))
        except OSError:
            sock.close()
            raise
        return sock

    def connect(self) -> None:
        if self._proxy is None:
            sock = self._socket_to(self._pinned_ip, self.port)
        else:
            px = self._proxy
            sock = socket.create_connection((px["host"], px["port"]), self.timeout)   # the proxy's own name
            target = self._pinned_ip if px.get("connect_by", "ip") == "ip" else self.host
            hp = f"[{target}]:{self.port}" if ":" in target else f"{target}:{self.port}"
            req = f"CONNECT {hp} HTTP/1.1\r\nHost: {hp}\r\n"
            if px.get("auth"):
                req += f"Proxy-Authorization: Basic {px['auth']}\r\n"
            sock.sendall((req + "\r\n").encode("ascii"))
            resp = b""
            while b"\r\n\r\n" not in resp and len(resp) < 16384:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
            line = resp.split(b"\r\n", 1)[0].decode("latin-1", "replace")
            parts = line.split(" ", 2)
            if len(parts) < 2 or not parts[1].isdigit() or not 200 <= int(parts[1]) < 300:
                sock.close()
                raise ProxyError(f"proxy CONNECT refused: {line[:100]}")
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def proxy_config(url: str | None, connect_by: str = "ip") -> dict[str, Any] | None:
    """`http://[user:pass@]host:port` -> proxy dict, or None (direct)."""
    if not url or url.strip().lower() in ("direct", "none", "off"):
        return None
    import base64
    from urllib.parse import unquote

    u = urlparse(url if "://" in url else f"http://{url}")
    if u.scheme != "http" or not u.hostname:
        raise ValueError("the webhook proxy must be an http:// proxy URL (CONNECT tunnels the TLS connection)")
    auth = base64.b64encode(f"{unquote(u.username)}:{unquote(u.password or '')}".encode()).decode() \
        if u.username else None
    return {"host": u.hostname, "port": u.port or 3128, "auth": auth, "connect_by": connect_by}


def _bypass(host: str) -> bool:
    from urllib.request import proxy_bypass_environment

    try:
        return bool(proxy_bypass_environment(host))
    except Exception:                                  # pragma: no cover - malformed NO_PROXY
        return False


def pinned_post(url: str, body: bytes, headers: dict[str, str], *, allow_private: bool,
                context: ssl.SSLContext | None = None, proxy: dict[str, Any] | None = None) -> tuple[int, str]:
    """POST to the validated address (directly, or through `proxy` by CONNECT); redirects are never followed (a
    3xx is a failed attempt). Hosts matched by NO_PROXY go direct."""
    host, port, addrs = resolve_checked(url, allow_private)
    if proxy is not None and _bypass(host):
        proxy = None
    u = urlparse(url)
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    ctx = context or ssl.create_default_context()
    last = ""
    for ip in addrs[:3]:
        conn = _PinnedHTTPSConnection(host, ip, port, DELIVERY_TIMEOUT, ctx, proxy)
        try:
            conn.request("POST", path, body=body, headers={"Content-Type": "application/json", "Host": host if
                                                           port == 443 else f"{host}:{port}", **headers})
            r = conn.getresponse()
            r.read(65536)
            return r.status, "" if 200 <= r.status < 300 else f"HTTP {r.status}"
        except ssl.SSLError as e:
            return 0, f"SSLError: {e.reason or e}"[:200]
        except ProxyError as e:
            return 0, str(e)[:200]
        except OSError as e:
            last = e.__class__.__name__
        finally:
            conn.close()
    return 0, last or "connection failed"


def http_post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, str]:
    """Default poster (private targets refused); see `pinned_post`."""
    return pinned_post(url, body, headers, allow_private=False)


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
    # un-parked events behind the cursor are sent first (once; a failure parks them again)
    for d in list(s.execute(select(IntDeliveryRow).where(IntDeliveryRow.endpoint_id == endpoint.id,
                                                         IntDeliveryRow.status == "retry")
                            .order_by(IntDeliveryRow.event_seq)).scalars()):
        ev = s.execute(select(IntOutboxRow).where(IntOutboxRow.seq == d.event_seq)).scalars().first()
        if ev is None:
            d.status = "parked"
            continue
        body = json.dumps(_json(event_view(ev, plant)), separators=(",", ":"), sort_keys=True).encode()
        try:
            if allow_private is not None:
                check_url(endpoint.url, allow_private)
            code, err = post(endpoint.url, body, {"SP-Event-Id": str(ev.seq),
                                                  "SP-Signature": sign(secret, body, int(now.timestamp()))})
        except ApiError as e:
            code, err = 0, f"{e.code}: {e.message}"
        d.attempts += 1
        d.last_status_code = code or None
        if 200 <= code < 300:
            d.status, d.delivered_at, d.last_error = "delivered", now, None
            out["delivered"] += 1
        else:
            d.status, d.last_error = "parked", (err or f"HTTP {code}")[:500]
            out["failed"] += 1
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

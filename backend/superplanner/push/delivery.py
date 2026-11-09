"""Web Push delivery (M6-DESIGN 2): job kind `push_delivery` (one per plant, M5 scheduler pattern) and
`send_to_user` (digest_ready).

Per plant run: everything new since the previous run's cursor - M4 notifications that are critical or `line_down`
(topic `critical_alerts`, recipients with `floor_view`), submitted PRs (`approvals`, `pr_approve`), submitted ECOs
(`eco_approve`), completed replan proposals (`schedule_publish`) - is sent to the subscriptions of the plant's people
with that topic and permission. Payload: title, short body, link path only (`PushPayload`), encrypted per RFC 8291
(`aes128gcm`), VAPID (RFC 8292) authorisation, `TTL: 86400`, `Urgency: high` for critical alerts. A push service
answering 404 / 410 deletes the subscription; other failures count up (deleted after 20). Egress uses the standard
proxy environment (HTTPS_PROXY / NO_PROXY, DEPLOY 13); the webhook address guard does not apply (push services are
public hosts)."""

from __future__ import annotations

import json
import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from ..api.db import utcnow
from ..api.mfg.db_models_m6 import PushSubscriptionRow
from ..api.schemas import as_utc
from . import ece, vapid

log = logging.getLogger("superplanner.push")
TTL_SECONDS = 86400
MAX_FAILURES = 20
FANOUT_THREADS = 16
TIMEOUT_SECONDS = 10.0


def _post(settings: Any, url: str, headers: dict[str, str], body: bytes) -> int:
    """M6 review M3: allow-listed push hosts only, through the M5 pinned connection (resolved and checked address,
    TLS to the host name, proxy per DEPLOY 13, redirects never followed); failures are not reported in detail."""
    from .service import endpoint_allowed

    if not endpoint_allowed(url, settings):
        return 410                                       # not a push service (any more): drop the subscription
    if settings.push_post is not None:
        return int(settings.push_post(url, headers, body, TIMEOUT_SECONDS))
    from ..integration.outbox import pinned_post, proxy_config

    extra = urllib.parse.urlsplit(url).hostname in (settings.webpush_extra_hosts or [])   # development stub only
    try:
        status, _err = pinned_post(url, body, headers, allow_private=bool(extra and not settings.is_production),
                                   proxy=proxy_config(settings.webhook_proxy, settings.webhook_proxy_connect))
        return int(status)
    except Exception as exc:  # noqa: BLE001 - refused address / network failure = a failed attempt
        log.info("push post failed: %s", type(exc).__name__)
        return 0


def _one(ctx: Any, sub: dict[str, Any], payload: bytes, urgency: str) -> tuple[str, int]:
    from .service import dec

    s = ctx.settings
    try:
        p256 = vapid.b64u_decode(dec(s, sub["p256dh_enc"]))
        auth = vapid.b64u_decode(dec(s, sub["auth_enc"]))
        body = ece.encrypt(payload, p256, auth)
    except Exception as exc:  # noqa: BLE001
        log.info("push subscription %s unusable: %s", sub["id"], type(exc).__name__)
        return sub["id"], 410
    headers = {"Authorization": vapid.authorization(s.webpush_vapid_private_key, s.webpush_subject, sub["endpoint"]),
               "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
               "TTL": str(TTL_SECONDS), "Urgency": urgency}
    return sub["id"], _post(s, sub["endpoint"], headers, body)


def deliver(ctx: Any, subs: list[dict[str, Any]], message: dict[str, Any], urgency: str = "normal") -> dict[str, int]:
    """Send one payload to many subscriptions (thread pool); apply 2xx / 404 / 410 / failure bookkeeping."""
    from ..api.db.ownership import system_scope
    from .model import PushPayload

    if not subs or not ctx.settings.push_enabled:
        return {"sent": 0, "gone": 0, "failed": 0}
    payload = json.dumps(PushPayload.model_validate(message).model_dump(exclude_none=True)).encode()
    with ThreadPoolExecutor(max_workers=min(FANOUT_THREADS, len(subs))) as ex:
        results = list(ex.map(lambda x: _one(ctx, x, payload, urgency), subs))
    ok = [i for i, st in results if 200 <= st < 300]
    gone = [i for i, st in results if st in (404, 410)]
    bad = [i for i, st in results if not (200 <= st < 300) and st not in (404, 410)]
    with system_scope(), ctx.write_guard(), ctx.db.write() as s:
        if ok:
            s.execute(update(PushSubscriptionRow).where(PushSubscriptionRow.id.in_(ok))
                      .values(last_success_at=utcnow(), failures=0))
        if gone:
            s.execute(delete(PushSubscriptionRow).where(PushSubscriptionRow.id.in_(gone)))
        if bad:
            s.execute(update(PushSubscriptionRow).where(PushSubscriptionRow.id.in_(bad))
                      .values(failures=PushSubscriptionRow.failures + 1))
            s.execute(delete(PushSubscriptionRow).where(PushSubscriptionRow.id.in_(bad),
                                                        PushSubscriptionRow.failures >= MAX_FAILURES))
    return {"sent": len(ok), "gone": len(gone), "failed": len(bad)}


def _subs(s: Any, user_ids: list[str], topic: str) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    rows = s.execute(select(PushSubscriptionRow).where(PushSubscriptionRow.user_id.in_(user_ids))).scalars()
    return [{"id": r.id, "user_id": r.user_id, "endpoint": r.endpoint, "p256dh_enc": r.p256dh_enc,
             "auth_enc": r.auth_enc} for r in rows if topic in (r.topics or [])]


def send_to_user(ctx: Any, user_id: str, topic: str, title: str, body: str, link: str) -> int:
    from ..api.db.ownership import system_scope

    if not ctx.settings.push_enabled:
        return 0
    with system_scope(), ctx.db.read() as s:
        subs = _subs(s, [user_id], topic)
    return deliver(ctx, subs, {"title": title[:120], "body": body[:240], "link": link[:300], "topic": topic})["sent"]


# ---------------------------------------------------------------- per plant (job kind push_delivery)

def plant_people(s: Any, owner_id: str) -> dict[str, frozenset[str]]:
    """user id -> permissions in the plant (owner principal + active members)."""
    from ..api.auth.models import UserRow
    from ..api.mfg.access import ROLE_PERMISSIONS, permissions_of
    from ..api.mfg.db_models_m2 import MfgPlantMemberRow

    out: dict[str, frozenset[str]] = {owner_id: ROLE_PERMISSIONS["owner"]}
    for uid, roles in s.execute(select(MfgPlantMemberRow.user_id, MfgPlantMemberRow.roles).join(
            UserRow, UserRow.id == MfgPlantMemberRow.user_id).where(
            MfgPlantMemberRow.owner_id == owner_id, MfgPlantMemberRow.active.is_(True),
            UserRow.disabled.is_(False))).all():
        out[uid] = permissions_of(list(roles or []))
    return out


def last_cursor(s: Any, owner_id: str) -> datetime | None:
    from ..api.mfg.db_models_m5 import MaintenanceRunRow

    r = s.execute(select(MaintenanceRunRow.results).where(
        MaintenanceRunRow.kind == "push_delivery", MaintenanceRunRow.owner_scope_id == owner_id,
        MaintenanceRunRow.status == "completed").order_by(MaintenanceRunRow.created_at.desc()).limit(1)).first()
    cur = ((r[0] or {}) if r else {}).get("cursor")
    return datetime.fromisoformat(cur) if cur else None


def _events(s: Any, owner_id: str, since: datetime) -> list[tuple[datetime, str, str, dict[str, Any], str]]:
    """[(at, topic, permission, payload, urgency)] new since `since` in the plant."""
    from ..api.mfg.db_models_m2 import MfgPurchaseDocRow
    from ..api.mfg.db_models_m3 import MfgApsRunRow
    from ..api.mfg.db_models_m4 import MfgNotificationRow
    from ..api.mfg.db_models_m5 import MfgChangeRequestRow

    out = []
    N = MfgNotificationRow
    for n in s.execute(select(N).where(N.owner_id == owner_id, N.created_at > since).order_by(N.created_at)
                       .limit(200)).scalars():
        if n.severity == "critical" or n.kind in ("line_down", "LINE_DOWN"):
            link = n.link if (n.link or "").startswith("/") else "/m/alerts"
            out.append((as_utc(n.created_at), "critical_alerts", "floor_view",
                        {"title": n.title[:120], "body": "Critical alert", "link": link[:300],
                         "topic": "critical_alerts", "tag": n.id}, "high"))
    D = MfgPurchaseDocRow
    for d in s.execute(select(D).where(D.owner_id == owner_id, D.doc_type == "pr", D.status == "submitted",
                                       D.submitted_at > since).limit(100)).scalars():
        out.append((as_utc(d.submitted_at), "approvals", "pr_approve",
                    {"title": f"{d.number} waits for approval", "body": "Purchase request", "link": "/m/approvals",
                     "topic": "approvals", "tag": d.id}, "normal"))
    C = MfgChangeRequestRow
    for c in s.execute(select(C).where(C.owner_id == owner_id, C.status == "submitted", C.updated_at > since)
                       .limit(100)).scalars():
        out.append((as_utc(c.updated_at), "approvals", "eco_approve",
                    {"title": f"{c.number} waits for approval", "body": "Engineering change", "link": "/m/approvals",
                     "topic": "approvals", "tag": c.id}, "normal"))
    R = MfgApsRunRow
    for r in s.execute(select(R).where(R.owner_id == owner_id, R.status == "completed", R.kind == "live",
                                       R.is_published.is_(False), R.finished_at > since).limit(20)).scalars():
        if (r.extras or {}).get("replan"):
            out.append((as_utc(r.finished_at), "approvals", "schedule_publish",
                        {"title": f"Replan proposal {r.run_no} is ready", "body": "Compare and publish",
                         "link": "/m/approvals", "topic": "approvals", "tag": r.id}, "normal"))
    return sorted(out, key=lambda x: x[0])


def latest_event_at(s: Any, owner_id: str) -> datetime | None:
    from ..api.mfg.db_models_m2 import MfgPurchaseDocRow
    from ..api.mfg.db_models_m3 import MfgApsRunRow
    from ..api.mfg.db_models_m4 import MfgNotificationRow
    from ..api.mfg.db_models_m5 import MfgChangeRequestRow

    vals = [s.execute(select(func.max(MfgNotificationRow.created_at)).where(
                MfgNotificationRow.owner_id == owner_id)).scalar(),
            s.execute(select(func.max(MfgPurchaseDocRow.submitted_at)).where(
                MfgPurchaseDocRow.owner_id == owner_id, MfgPurchaseDocRow.status == "submitted")).scalar(),
            s.execute(select(func.max(MfgChangeRequestRow.updated_at)).where(
                MfgChangeRequestRow.owner_id == owner_id, MfgChangeRequestRow.status == "submitted")).scalar(),
            s.execute(select(func.max(MfgApsRunRow.finished_at)).where(
                MfgApsRunRow.owner_id == owner_id, MfgApsRunRow.is_published.is_(False))).scalar()]
    vals = [as_utc(v) for v in vals if v is not None]
    return max(vals) if vals else None


def has_subscribers(s: Any, owner_id: str) -> bool:
    people = list(plant_people(s, owner_id))
    return s.execute(select(PushSubscriptionRow.id).where(PushSubscriptionRow.user_id.in_(people)).limit(1)
                     ).first() is not None


def is_due(s: Any, ctx: Any, owner_id: str, now: datetime) -> bool:
    if not ctx.settings.push_enabled or not has_subscribers(s, owner_id):
        return False
    latest = latest_event_at(s, owner_id)
    cur = last_cursor(s, owner_id) or now - timedelta(hours=1)
    return latest is not None and latest > cur


def run_plant(ctx: Any, owner_id: str, now: datetime | None = None) -> dict[str, Any]:
    from ..api.db.ownership import system_scope

    now = now or datetime.now(UTC)
    with system_scope(), ctx.db.read() as s:
        since = last_cursor(s, owner_id) or now - timedelta(hours=1)
        events = _events(s, owner_id, since)
        people = plant_people(s, owner_id)
        subs_by_topic = {t: _subs(s, list(people), t) for t in ("critical_alerts", "approvals")}
    sent = gone = failed = 0
    cursor = since
    for at, topic, perm, payload, urgency in events:
        subs = [x for x in subs_by_topic[topic] if perm in people.get(x["user_id"], frozenset())]
        r = deliver(ctx, subs, payload, urgency)
        sent, gone, failed = sent + r["sent"], gone + r["gone"], failed + r["failed"]
        cursor = max(cursor, at)
    return {"cursor": cursor.isoformat(), "events": len(events), "sent": sent, "gone": gone, "failed": failed}


def run_job(ctx: Any, run_id: str, lease: Any) -> None:
    from ..integration.jobs import run_duty

    run_duty(ctx, run_id, lease, lambda info: run_plant(ctx, info["owner"]))

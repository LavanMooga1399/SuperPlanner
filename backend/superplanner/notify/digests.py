"""Digest subscriptions and the `digest_send` duty (M6-DESIGN 3.3, 5 D4-D6).

A digest = the plant or organisation dashboard computed in the recipient's permission scope at send time (their
plant roles / org membership), as an HTML mail with the tiles and the top 10 exceptions / alerts (links built from
PUBLIC_BASE_URL) plus a CSV of the tiles. Without SMTP digest subscriptions are refused (422 DIGEST_NO_SMTP); the
push topic `digest_ready` still announces a fresh dashboard."""

from __future__ import annotations

import csv
import html
import io
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..api.db import new_id, utcnow
from ..api.errors import ApiError, not_found
from ..api.mfg.db_models_m6 import DigestSubscriptionRow
from ..api.schemas import as_utc
from ..mfg.model_m6 import DigestInput

log = logging.getLogger("superplanner.notify")
MAX_DIGESTS_PER_USER = 20


def no_smtp() -> ApiError:
    return ApiError(422, "DIGEST_NO_SMTP", "E-mail digests need an SMTP server; ask your administrator.", {})


def _scope_label(s: Any, scope: str, scope_id: str, user_id: str) -> tuple[str, str] | None:
    """(label, time zone) if `user_id` may see the scope, else None."""
    from ..api.db.ownership import system_scope
    from ..api.mfg.db_models import MfgPlantRow
    from ..api.mfg.db_models_m2 import MfgPlantMemberRow
    from ..api.mfg.db_models_m5 import OrgMemberRow, OrgRow

    with system_scope():
        if scope == "plant":
            if scope_id != user_id:
                m = s.execute(select(MfgPlantMemberRow.roles).where(
                    MfgPlantMemberRow.owner_id == scope_id, MfgPlantMemberRow.user_id == user_id,
                    MfgPlantMemberRow.active.is_(True))).first()
                if m is None or not m[0]:
                    return None
            p = s.execute(select(MfgPlantRow.name, MfgPlantRow.time_zone).where(MfgPlantRow.owner_id == scope_id)
                          ).first()
            return ((p[0] if p else "Plant"), (p[1] if p and p[1] else "UTC"))
        org = s.get(OrgRow, scope_id)
        if org is None:
            return None
        mem = s.execute(select(OrgMemberRow.id).where(OrgMemberRow.org_id == org.id, OrgMemberRow.user_id == user_id,
                                                      OrgMemberRow.accepted_at.is_not(None))).first()
        if mem is None:
            return None
        return org.name, "UTC"


def record(r: DigestSubscriptionRow, label: str = "") -> dict[str, Any]:
    return {"id": r.id, "scope": r.scope, "scope_id": r.scope_id, "scope_label": label, "frequency": r.frequency,
            "local_time": r.local_time, "weekday": r.weekday, "time_zone": r.time_zone,
            "created_at": as_utc(r.created_at), "last_sent_at": as_utc(r.last_sent_at)}


def list_digests(ctx: Any, user_id: str) -> dict[str, Any]:
    with ctx.db.read() as s:
        rows = list(s.execute(select(DigestSubscriptionRow).where(DigestSubscriptionRow.user_id == user_id)
                              .order_by(DigestSubscriptionRow.created_at)).scalars())
        out = []
        for r in rows:
            lab = _scope_label(s, r.scope, r.scope_id, user_id)
            out.append(record(r, lab[0] if lab else ""))
        return {"items": out, "smtp_enabled": ctx.settings.smtp_enabled}


def create_digest(ctx: Any, user_id: str, body: DigestInput) -> dict[str, Any]:
    if not ctx.settings.smtp_enabled:
        raise no_smtp()
    with ctx.write_guard(), ctx.db.write() as s:
        lab = _scope_label(s, body.scope, body.scope_id, user_id)
        if lab is None:
            raise not_found("Plant" if body.scope == "plant" else "Organisation", body.scope_id)
        n = len(list(s.execute(select(DigestSubscriptionRow.id).where(DigestSubscriptionRow.user_id == user_id))))
        if n >= MAX_DIGESTS_PER_USER:
            raise ApiError(409, "DIGEST_TOO_MANY", f"At most {MAX_DIGESTS_PER_USER} digests per person.", {})
        r = DigestSubscriptionRow(id=new_id("dgs_"), user_id=user_id, scope=body.scope, scope_id=body.scope_id,
                                  frequency=body.frequency, local_time=body.local_time,
                                  weekday=(body.weekday if body.weekday is not None else 0)
                                  if body.frequency == "weekly" else None,
                                  time_zone=lab[1], created_at=utcnow(), last_sent_at=None)
        s.add(r)
        s.flush()
        return record(r, lab[0])


def delete_digest(ctx: Any, user_id: str, digest_id: str) -> None:
    with ctx.write_guard(), ctx.db.write() as s:
        r = s.execute(select(DigestSubscriptionRow).where(DigestSubscriptionRow.id == digest_id,
                                                          DigestSubscriptionRow.user_id == user_id)).scalars().first()
        if r is None:
            raise not_found("Digest", digest_id)
        s.delete(r)


# ---------------------------------------------------------------- sending (job kind digest_send)

def due(r: DigestSubscriptionRow, now: datetime) -> bool:
    """The local send time of today (weekly: of this week's weekday) has passed and nothing was sent since."""
    try:
        tz = ZoneInfo(r.time_zone or "UTC")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz)
    hh, mm = (int(x) for x in r.local_time.split(":"))
    slot = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if r.frequency == "weekly":
        slot = slot - timedelta(days=(local.weekday() - int(r.weekday or 0)) % 7)
    if slot > local:
        slot -= timedelta(days=7 if r.frequency == "weekly" else 1)
    last = as_utc(r.last_sent_at)
    created = as_utc(r.created_at)
    slot_utc = slot.astimezone(UTC)
    return (last is None or last < slot_utc) and (created is None or created <= slot_utc)


def tiles_csv(tiles: dict[str, Any], plant_label: str = "") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["plant", "tile", "value", "unit", "status", "note"])
    for name, t in tiles.items():
        w.writerow([plant_label, name, "" if t.get("value") is None else t.get("value"), t.get("unit", ""),
                    t.get("status", ""), t.get("note", "")])
    return buf.getvalue().encode("utf-8")


def _fmt(t: dict[str, Any]) -> str:
    v = t.get("value")
    if v is None:
        return "n/a"
    if t.get("unit") == "%":
        return f"{100 * float(v):.1f}%"
    return f"{v:,.0f}" if isinstance(v, (int, float)) and abs(v) >= 100 else f"{v}"


def render(settings: Any, title: str, sections: list[tuple[str, dict[str, Any]]], alerts: list[dict[str, Any]]
           ) -> tuple[str, str]:
    base = (settings.public_base_url or "").rstrip("/")
    lines = [title, ""]
    parts = [f"<h2>{html.escape(title)}</h2>"]
    for label, tiles in sections:
        if label:
            lines.append(label)
            parts.append(f"<h3>{html.escape(label)}</h3>")
        parts.append("<table border='1' cellpadding='4' cellspacing='0'><tr><th>Tile</th><th>Value</th>"
                     "<th>Status</th></tr>")
        for name, t in tiles.items():
            lines.append(f"  {name}: {_fmt(t)} ({t.get('status')})")
            parts.append(f"<tr><td>{html.escape(name)}</td><td>{html.escape(_fmt(t))}</td>"
                         f"<td>{html.escape(str(t.get('status')))}</td></tr>")
        parts.append("</table>")
    if alerts:
        lines += ["", "Top exceptions and alerts:"]
        parts.append("<h3>Top exceptions and alerts</h3><ul>")
        for a in alerts[:10]:
            url = f"{base}{a.get('link') or '/m'}"
            lines.append(f"  - {a['text']} {url}")
            parts.append(f"<li><a href=\"{html.escape(url, quote=True)}\">{html.escape(a['text'])}</a></li>")
        parts.append("</ul>")
    return "\n".join(lines), "".join(parts)


def run_job(ctx: Any, run_id: str, lease: Any) -> None:
    from ..integration.jobs import run_duty

    run_duty(ctx, run_id, lease, lambda info: send_due(ctx))


def send_due(ctx: Any, now: datetime | None = None) -> dict[str, Any]:
    """Send every due digest (each computed in its recipient's scope). -> counts."""
    from ..api.auth.models import UserRow
    from ..api.db.ownership import owner_scope, system_scope

    now = now or datetime.now(UTC)
    sent = failed = 0
    with system_scope(), ctx.db.read() as s:
        subs = [r for r in s.execute(select(DigestSubscriptionRow)).scalars() if due(r, now)]
        emails = {u.id: u.email for u in s.execute(select(UserRow).where(UserRow.id.in_(
            [r.user_id for r in subs]))).scalars()} if subs else {}
        s.expunge_all()
    for r in subs:
        to = emails.get(r.user_id)
        if not to:
            continue
        try:
            with owner_scope(r.scope_id if r.scope == "plant" else r.user_id):
                msg = build_mail(ctx, r, to)
            if msg is None:
                continue
            from .email import send

            if ctx.settings.smtp_enabled:
                send(ctx.settings, msg)
            sent += 1
            with system_scope(), ctx.write_guard(), ctx.db.write() as s:
                row = s.get(DigestSubscriptionRow, r.id)
                if row is not None:
                    row.last_sent_at = now
            _announce(ctx, r)
        except Exception as exc:  # noqa: BLE001 - one bad digest never stops the others
            failed += 1
            log.warning("digest %s failed: %s", r.id, type(exc).__name__)
    return {"sent": sent, "failed": failed, "due": len(subs)}


def build_mail(ctx: Any, r: DigestSubscriptionRow, to: str) -> Any:
    from ..api.db.ownership import bind_actor, bind_owner, system_scope
    from ..api.mfg.services import dashboard
    from .email import build

    with system_scope(), ctx.db.read() as s:
        lab = _scope_label(s, r.scope, r.scope_id, r.user_id)
    if lab is None:                                    # access gone: nothing is sent
        return None
    period = "4w" if r.frequency == "daily" else "13w"
    if r.scope == "plant":
        bind_owner(r.scope_id)
        bind_actor(r.user_id)
        d = dashboard.plant_dashboard(ctx, period)
        sections = [("", d["tiles"])]
        alerts = dashboard.top_alerts(ctx)
        csv_bytes = tiles_csv(d["tiles"], lab[0])
    else:
        d = dashboard.org_dashboard(ctx, r.user_id, r.scope_id, period)
        sections = [(p["plant"].get("name") or p["plant"].get("code") or "", p["tiles"]) for p in d["plants"]]
        sections.append(("Totals", d["totals"]))
        alerts = []
        csv_bytes = b"".join(tiles_csv(p["tiles"], p["plant"].get("code") or "") for p in d["plants"])
    title = f"SuperPlanner {r.frequency} digest - {lab[0]}"
    text, body_html = render(ctx.settings, title, sections, alerts)
    return build(ctx.settings, to, title, text, body_html, [("dashboard.csv", csv_bytes, "text/csv")])


def _announce(ctx: Any, r: DigestSubscriptionRow) -> None:
    try:
        from ..push import delivery

        delivery.send_to_user(ctx, r.user_id, "digest_ready", "Your digest is ready",
                              "The dashboard digest was sent.",
                              "/mfg/dashboard" if r.scope == "plant" else f"/orgs/{r.scope_id}/dashboard")
    except Exception as exc:  # noqa: BLE001
        log.info("digest push skipped: %s", type(exc).__name__)

"""Approvals inbox (M6-DESIGN 2, 5 M5): pending items the user can act on - submitted PRs (pr_approve), submitted
ECOs (eco_approve), completed replan proposals newer than the published schedule (schedule_publish) and the published
schedule's suggested overtime (schedule_run). Each item carries the exact action requests (the UI sends them with
If-Match = `row_version`); nothing is acted on here."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...context import AppContext
from ...schemas import as_utc
from ..db_models_m2 import MfgPurchaseDocRow, MfgSupplierRow
from ..db_models_m3 import MfgApsOvertimeRow, MfgApsRunRow
from ..db_models_m5 import MfgChangeRequestRow
from ..db_models import MfgLineRow
from .common import read_tx

V1 = "/api/v1/mfg"
MAX_ITEMS = 100


def _may_self_approve(p: Any) -> bool:
    return bool(p.is_owner or "plant_admin" in (p.roles or ()))


def approvals(ctx: AppContext, p: Any) -> dict[str, Any]:
    """Review m3: the user's own submissions are not listed (four eyes) unless owner / plant_admin."""
    items: list[dict[str, Any]] = []
    self_ok = _may_self_approve(p)
    with read_tx(ctx) as s:
        if p.has("pr_approve"):
            sups = {x.id: x for x in s.execute(select(MfgSupplierRow)).scalars()}
            for d in s.execute(select(MfgPurchaseDocRow).where(MfgPurchaseDocRow.doc_type == "pr",
                                                               MfgPurchaseDocRow.status == "submitted")
                               .order_by(MfgPurchaseDocRow.submitted_at).limit(MAX_ITEMS)).scalars():
                if d.submitted_by == p.user_id and not self_ok:
                    continue
                sup = sups.get(d.supplier_id or "")
                items.append({"kind": "pr", "id": d.id, "number": d.number,
                              "title": f"{d.number}" + (f" ({sup.name})" if sup else ""), "summary": d.note[:200],
                              "waiting_since": as_utc(d.submitted_at), "permission": "pr_approve",
                              "row_version": d.row_version, "link": f"/mfg/purchasing/requests/{d.id}",
                              "actions": [{"label": "Approve", "method": "POST",
                                           "path": f"{V1}/purchase-requests/{d.id}/approve", "body": {}},
                                          {"label": "Reject", "method": "POST",
                                           "path": f"{V1}/purchase-requests/{d.id}/reject", "body": {"reason": ""}}]})
        if p.has("eco_approve"):
            for c in s.execute(select(MfgChangeRequestRow).where(MfgChangeRequestRow.status == "submitted")
                               .order_by(MfgChangeRequestRow.updated_at).limit(MAX_ITEMS)).scalars():
                if (c.submitted_by or c.requested_by) == p.user_id and not self_ok:
                    continue
                items.append({"kind": "eco", "id": c.id, "number": c.number, "title": f"{c.number} {c.title}"[:200],
                              "summary": c.reason[:200], "waiting_since": as_utc(c.updated_at),
                              "permission": "eco_approve", "row_version": c.row_version, "link": f"/mfg/eco/{c.id}",
                              "actions": [{"label": "Approve", "method": "POST", "path": f"{V1}/eco/{c.id}/approve",
                                           "body": {}},
                                          {"label": "Reject", "method": "POST", "path": f"{V1}/eco/{c.id}/reject",
                                           "body": {"note": ""}}]})
        pub = s.execute(select(MfgApsRunRow).where(MfgApsRunRow.is_published.is_(True))).scalars().first()
        if p.has("schedule_publish"):
            q = select(MfgApsRunRow).where(MfgApsRunRow.kind == "live", MfgApsRunRow.status == "completed",
                                           MfgApsRunRow.is_published.is_(False))
            if pub is not None:
                q = q.where(MfgApsRunRow.created_at > pub.created_at)
            for r in s.execute(q.order_by(MfgApsRunRow.created_at.desc()).limit(20)).scalars():
                if not (r.extras or {}).get("replan") or not (r.validation or {}).get("ok"):
                    continue
                summ = r.summary or {}
                items.append({"kind": "replan_proposal", "id": r.id, "number": str(r.run_no),
                              "title": f"Replan proposal {r.run_no}" + (f" ({r.label})" if r.label else ""),
                              "summary": f"{summ.get('late_orders', 0)} late order(s)",
                              "waiting_since": as_utc(r.finished_at or r.created_at), "permission": "schedule_publish",
                              "row_version": r.row_version, "link": f"/mfg/schedule/runs/{r.id}?compare={pub.id}"
                              if pub is not None else f"/mfg/schedule/runs/{r.id}",
                              "actions": [{"label": "Publish", "method": "POST",
                                           "path": f"{V1}/aps/runs/{r.id}/publish", "body": {}}]})
        if p.has("schedule_run") and pub is not None:
            lines = {x.id: x.code for x in s.execute(select(MfgLineRow)).scalars()}
            for o in s.execute(select(MfgApsOvertimeRow).where(MfgApsOvertimeRow.run_id == pub.id,
                                                               MfgApsOvertimeRow.status == "suggested")
                               .order_by(MfgApsOvertimeRow.start_at).limit(MAX_ITEMS)).scalars():
                start, end = as_utc(o.start_at), as_utc(o.end_at)
                items.append({"kind": "overtime", "id": f"{pub.id}:{o.line_id}:{start.isoformat()}",
                              "number": str(pub.run_no),
                              "title": f"Overtime on {lines.get(o.line_id, '?')} {start:%Y-%m-%d %H:%M}Z-"
                                       f"{end:%H:%M}Z",
                              "summary": f"saves {round((o.tardiness_saved_minutes or 0) / 1440, 1)} day(s) of "
                                         f"tardiness, {o.minutes:g} min",
                              "waiting_since": as_utc(pub.published_at), "permission": "schedule_run",
                              "row_version": None, "link": f"/mfg/schedule/runs/{pub.id}?view=overtime",
                              "actions": [{"label": "Accept", "method": "POST", "path": f"{V1}/aps/runs",
                                           "body": {"copy_of": pub.id, "open_shifts": [
                                               {"line_id": o.line_id, "start": start.isoformat(),
                                                "end": end.isoformat()}]}}]})
    counts = {k: sum(1 for x in items if x["kind"] == k) for k in ("pr", "eco", "replan_proposal", "overtime")}
    return {"items": items, "counts": counts}

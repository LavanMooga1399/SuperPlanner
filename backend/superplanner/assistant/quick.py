"""Quick explanations without AI (M6-DESIGN 1.7): deterministic answers built only from existing views -
"Why late?" (M2 limiting path + M3 late chain), "What limits this week?" (M3 bottlenecks + overtime suggestions),
"What changed?" (M4 triggers since the last publish). Always available (permission `view`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..api.errors import ApiError
from ..api.schemas import as_utc


class _Refs:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.keys: dict[tuple[str, str], str] = {}

    def add(self, type_: str, id_: str, label: str, link: str) -> str:
        from .citations import safe_link

        k = (type_, id_)
        if k in self.keys:
            return self.keys[k]
        ref = f"Q{len(self.items) + 1}"
        self.keys[k] = ref
        self.items.append({"ref": ref, "type": type_, "id": id_, "label": label[:200], "link": safe_link(link) or ""})
        return ref


def _latest_mrp(ctx: Any) -> Any:
    from ..api.mfg.db_models_m2 import MfgMrpRunRow

    with ctx.db.read() as s:
        return s.execute(select(MfgMrpRunRow.id, MfgMrpRunRow.run_no).where(
            MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed").order_by(MfgMrpRunRow.run_no.desc())
            .limit(1)).first()


def _published(ctx: Any) -> Any:
    from ..api.mfg.db_models_m3 import MfgApsRunRow

    with ctx.db.read() as s:
        return s.execute(select(MfgApsRunRow.id, MfgApsRunRow.run_no, MfgApsRunRow.published_at).where(
            MfgApsRunRow.is_published.is_(True)).limit(1)).first()


def explain(ctx: Any, p: Any, kind: str, type_: str | None, id_: str | None) -> dict[str, Any]:
    if kind == "why_late":
        return why_late(ctx, type_, id_)
    if kind == "limits":
        return limits(ctx)
    return changes(ctx)


def why_late(ctx: Any, type_: str | None, id_: str | None) -> dict[str, Any]:
    from ..api.mfg.services import aps, demand, mrp

    if type_ not in ("demand_line", "demand_order") or not id_:
        raise ApiError(422, "VALIDATION_ERROR", "why_late needs type=demand_line|demand_order and id.",
                       {"errors": [{"loc": ["query", "type"], "msg": "demand_line or demand_order",
                                    "type": "value_error"}]})
    refs = _Refs()
    order_id, line_id = id_, None
    if type_ == "demand_line":
        from ..api.mfg.db_models_m2 import MfgDemandLineRow

        with ctx.db.read() as s:
            row = s.execute(select(MfgDemandLineRow.order_id).where(MfgDemandLineRow.id == id_)).first()
        if row is None:
            from ..api.errors import not_found

            raise not_found("Demand line", id_)
        order_id, line_id = row[0], id_
    order = demand.get_order(ctx, order_id)
    lines = [x for x in order["lines"] if line_id is None or x["id"] == line_id]
    title_subject = order["number"] + (f"/{lines[0]['line_no']}" if line_id and lines else "")
    sections: list[dict[str, Any]] = []
    sources: list[str] = []
    run = _latest_mrp(ctx)
    if run is not None:
        rows = mrp.list_demand(ctx, run[0], status=None, program=None, order_id=order_id, late_only=False,
                               sort="due_date", limit=200, offset=0)["items"]
        items = []
        for r in rows:
            if line_id and r.get("demand_line_id") != line_id:
                continue
            q = refs.add("demand_line", r.get("demand_line_id") or "", f"{order['number']}/{r['line_no']}",
                         r.get("link") or f"/mfg/demand/{order_id}")
            if r["late_days"] > 0:
                items.append({"text": f"Line {r['line_no']}: projected {r['projected_date']}, {r['late_days']} "
                                      f"day(s) after the due date {r['due_date']}.", "refs": [q]})
                for st in r.get("limiting") or []:
                    q2 = refs.add("mrp_item", st["item"]["id"], st["item"].get("part_number", ""),
                                  f"/mfg/mrp/runs/{run[0]}/items/{st['item']['id']}")
                    items.append({"text": f"Limiting: {st.get('label') or st['item'].get('part_number')} - "
                                          f"{st.get('reason', '')} ({st.get('date')}).", "refs": [q2]})
            else:
                items.append({"text": f"Line {r['line_no']}: on time in MRP (projected {r['projected_date']}).",
                              "refs": [q]})
        sections.append({"title": f"Material (latest MRP run {run[1]})", "items": items})
        sources.append("GET /mfg/mrp/runs/{id}/demand")
    pub = _published(ctx)
    if pub is not None:
        dem = aps.demand(ctx, pub[0], late_only=False, program=None)["items"]
        items = []
        for d in dem:
            if d.get("order_id") != order_id or (line_id and d.get("demand_line_id") != line_id):
                continue
            q = refs.add("aps_run", pub[0], f"schedule run {pub[1]}", f"/mfg/schedule/runs/{pub[0]}")
            if d["late_minutes"] > 0:
                items.append({"text": f"Line {d['line_no']}: scheduled end {d.get('scheduled_end')}, "
                                      f"{round(d['late_minutes'] / 1440, 1)} day(s) late. {d.get('late_text', '')}"
                                      .strip(), "refs": [q]})
            else:
                items.append({"text": f"Line {d['line_no']}: on time in the published schedule.", "refs": [q]})
        sections.append({"title": f"Schedule (published run {pub[1]})", "items": items})
        sources.append("GET /mfg/aps/runs/{id}/demand")
    return {"kind": "why_late", "title": f"Why is {title_subject} late?",
            "subject": {"type": type_, "id": id_, "label": title_subject}, "sections": sections,
            "citations": refs.items, "sources": sources,
            "empty_message": "" if sections else "Run MRP and publish a schedule to explain lateness."}


def limits(ctx: Any) -> dict[str, Any]:
    from ..api.mfg.services import aps

    refs = _Refs()
    pub = _published(ctx)
    if pub is None:
        return {"kind": "limits", "title": "What limits this week?", "sections": [], "citations": [],
                "sources": [], "empty_message": "No published schedule yet."}
    b = aps.bottlenecks(ctx, pub[0])["items"]
    q = refs.add("aps_run", pub[0], f"schedule run {pub[1]}", f"/mfg/schedule/runs/{pub[0]}")
    items = [{"text": f"Stage {x['group'].get('code')}: utilisation {round(100 * x['utilisation'])}%, "
                      f"{x['late_chains']} late chain(s)." + (f" {x['suggestion']}" if x.get("suggestion") else ""),
              "refs": [q]} for x in b[:5]]
    ot = aps.overtime(ctx, pub[0], status="suggested")
    oitems = [{"text": f"Overtime on {x['line'].get('code')} {x.get('start') or x.get('start_at')}: "
                       f"{x['minutes']:g} min, saves {x.get('tardiness_saved_minutes') or 0:g} min of tardiness.",
               "refs": [q]} for x in ot["items"][:5]]
    return {"kind": "limits", "title": "What limits this week?", "sections": [
        {"title": "Bottlenecks", "items": items}, {"title": "Suggested overtime", "items": oitems}],
        "citations": refs.items, "sources": ["GET /mfg/aps/runs/{id}/bottlenecks", "GET /mfg/aps/runs/{id}/overtime"]}


def changes(ctx: Any) -> dict[str, Any]:
    from ..api.mfg.services import replan

    refs = _Refs()
    pub = _published(ctx)
    since = as_utc(pub[2]) if pub is not None and pub[2] is not None else None
    trig = replan.list_triggers(ctx, status=None, kind=None, limit=200, offset=0)["items"]
    sel = [t for t in trig if since is None or (t["detected_at"] and t["detected_at"] >= since)]
    items = []
    for t in sel[:20]:
        q = refs.add("replan_trigger", t["id"], f"{t['kind']} ({t['severity']})", "/mfg/replan")
        items.append({"text": f"{t['kind'].replace('_', ' ')} ({t['severity']}, {t['status']}): "
                              f"{(t.get('message') or '')[:200]}".strip(), "refs": [q]})
    return {"kind": "changes", "title": "What changed since the last publish?",
            "sections": [{"title": f"Replan triggers ({len(sel)})", "items": items}], "citations": refs.items,
            "sources": ["GET /mfg/replan/triggers"],
            "empty_message": "" if sel else "No replan triggers since the last publish."}

"""Builds `example_run.json` (S0 contract examples, typed via `aps.model`): `python superplanner/mfg/aps/fixtures/build_example.py`."""
import json, sys
from datetime import datetime, date, timedelta, timezone
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[4]))
from superplanner.mfg.aps import model as M

U = timezone.utc
T0 = datetime(2026, 11, 2, 3, 30, tzinfo=U)   # 09:00 Asia/Kolkata
def t(m): return T0 + timedelta(minutes=m)
def iid(p, n): return f"{p}_{n:032x}"
RUN, RUN2, MRP = iid("apr", 1), iid("apr", 2), iid("mrr", 7)
SMT1, SMT2, BI1 = iid("lin", 1), iid("lin", 2), iid("lin", 3)
G_SMT, G_BI = iid("wcg", 1), iid("wcg", 2)
WO1, PO1 = iid("wko", 1), iid("mpo", 1)
ITEM_A, ITEM_B = iid("itm", 1), iid("itm", 2)
EMP1, EMP2 = iid("emp", 1), iid("emp", 2)
TOOL = iid("tlp", 1)
o_wo = M.OrderRef(type="wo", id=WO1, number="WO-000143", item_id=ITEM_A)
o_pl = M.OrderRef(type="planned", id=PO1, number="P-12", planned_no=12, item_id=ITEM_B)
ops = [
  M.ScheduledOp(op_no=1, order=o_wo, seq=10, name="SMT top", group_id=G_SMT, qty=10, line_id=SMT1, start=t(0), end=t(140),
    setup_minutes=45, run_minutes=95, pieces=[M.Span(start=t(0), end=t(140))],
    crew=[M.CrewSlot(operator_id=EMP1, start=t(0), end=t(140))], tools=[M.ToolUse(tool_pool_id=TOOL, qty=1)],
    release=M.ReleaseInfo(material_at=t(0), predecessor_at=None, refs=[M.RefItem(type="stock", id=iid("bal",1), label="Stock STORES", at=t(0))]),
    reason=M.StartReason(code="as_of", text="Starts at the planning start (as of)."), due=t(60*24*5), late_minutes=0,
    family="PCBA-HDI", setup_from_family=None),
  M.ScheduledOp(op_no=2, order=o_wo, seq=20, name="Burn-in", group_id=G_BI, qty=10, line_id=BI1, start=t(170), end=t(170+720),
    setup_minutes=0, run_minutes=720, pieces=[M.Span(start=t(170), end=t(540)), M.Span(start=t(1440), end=t(1790))],
    crew=[], tools=[], release=M.ReleaseInfo(material_at=None, predecessor_at=t(170), refs=[M.RefItem(type="operation", id="1", label="WO-000143 op 10 SMT top", at=t(140))]),
    reason=M.StartReason(code="predecessor", refs=[M.RefItem(type="operation", id="1", label="op 1")], text="Waits for op 10 SMT top on SMT-1 (ends 11:20) + 30 min move."),
    due=t(60*24*5), late_minutes=0, family="PCBA-HDI"),
  M.ScheduledOp(op_no=3, order=o_pl, seq=10, name="SMT top", group_id=G_SMT, qty=50, split=M.SplitInfo(index=0, count=2), line_id=SMT1,
    start=t(140), end=t(400), setup_minutes=60, run_minutes=200, pieces=[M.Span(start=t(140), end=t(400))],
    crew=[M.CrewSlot(operator_id=EMP2, start=t(140), end=t(400))], tools=[],
    release=M.ReleaseInfo(material_at=t(60), refs=[M.RefItem(type="po_schedule", id=iid("psc",1), label="PO-KV-0101/10/2", at=t(60))]),
    reason=M.StartReason(code="line_busy", refs=[M.RefItem(type="operation", id="1", label="op 1")], text="SMT-1 busy with WO-000143 op 10 until 11:50."),
    due=t(60*24*3), late_minutes=0, family="PCBA-STD", setup_from_family="PCBA-HDI"),
  M.ScheduledOp(op_no=4, order=o_pl, seq=10, name="SMT top", group_id=G_SMT, qty=50, split=M.SplitInfo(index=1, count=2), line_id=SMT2,
    start=t(60), end=t(320), setup_minutes=60, run_minutes=200, pieces=[M.Span(start=t(60), end=t(320))], crew=[], tools=[],
    release=M.ReleaseInfo(material_at=t(60), refs=[]), reason=M.StartReason(code="material", refs=[M.RefItem(type="po_schedule", id=iid("psc",1), label="PO-KV-0101/10/2", at=t(60))], text="Material: KV-IC-FPGA-V1 from PO-KV-0101/10/2 available 10:00."),
    due=t(60*24*3), late_minutes=0, family="PCBA-STD", setup_from_family=None),
  M.ScheduledOp(op_no=5, order=o_pl, seq=20, name="Burn-in", group_id=G_BI, qty=100, status="unscheduled",
    reason=M.StartReason(code="beyond_horizon", text="Cannot start before the horizon end (14 Dec); MRP date 18 Dec."),
    due=t(60*24*3), late_minutes=0, family="PCBA-STD"),
]
summary = M.ApsSummary(policy="suggest", operations=5, scheduled_operations=4, unscheduled={"beyond_horizon": 1}, orders=2,
  late_orders=1, late_wos=0, demand_lines=2, demand_lines_on_time=1, demand_lines_late=1, late_demand_count=1,
  weighted_tardiness=7680.0, max_lateness_minutes=480, overtime_minutes=0, overtime_cost=0.0,
  suggested_overtime_minutes=240, suggested_overtime_cost=1600.0, suggested_tardiness_saved=7680.0,
  utilisation={G_SMT: 0.81, G_BI: 0.64}, bottlenecks=[G_SMT, G_BI], setup_minutes=165, changeovers=2, avg_flow_days=1.4,
  makespan_minutes=1790, validation_ok=True, violations=0, splits=1, iterations=12, accepted_moves=3, budget_used=4.2,
  budget_cut=False, timings_ms={"load": 410, "construct": 1830, "improve": 9200, "validate": 240, "store": 860})
ot = [M.OvertimeWindow(line_id=SMT1, assignment_id=iid("sha",9), start=t(540), end=t(780), minutes=240, cost=1600.0, status="suggested", tardiness_saved_minutes=7680.0)]
orders = [M.OrderResult(order=o_wo, part_number="KV-TPU-1000", qty=10, due=t(60*24*5), start=t(0), end=t(1790), late_minutes=0, weight=256, priority=1, rank_label="P1 DO-KV-001/10",
  demand_refs=[M.DemandRef(demand_line_id=iid("dml",1), order_number="DO-KV-001", line_no=10)]),
  M.OrderResult(order=o_pl, part_number="KV-PCB-FLT", qty=100, due=t(60*24*3), start=t(60), end=None, late_minutes=480, weight=16, priority=5, rank_label="P5 DO-KV-004/10",
  demand_refs=[M.DemandRef(demand_line_id=iid("dml",2), order_number="DO-KV-004", line_no=10)],
  late_chain=[M.LateStep(kind="capacity", op_no=5, text="Burn-in BI-1/BI-2 full 12-15 Dec with WO-000139 (P1)", refs=[M.RefItem(type="group", id=G_BI, label="BURNIN")]),
              M.LateStep(kind="material", op_no=4, text="SMT-2 waits for KV-IC-FPGA-V1 (PO-KV-0101/10/2, 2 Nov 10:00)", refs=[M.RefItem(type="po_schedule", id=iid("psc",1), label="PO-KV-0101/10/2")])],
  late_text="P-12 (KV-PCB-FLT x100) ends after its due date, 8 h late: burn-in BI-1/BI-2 full 12-15 Dec with WO-000139 (P1); earlier: SMT-2 waits for KV-IC-FPGA-V1 (PO-KV-0101/10/2, 2 Nov 10:00)", unscheduled_ops=1)]
demand = [M.DemandResult(demand_line_id=iid("dml",1), order_id=iid("dmo",1), order_number="DO-KV-001", line_no=10, item_id=ITEM_A, part_number="KV-TPU-1000", qty=10,
  due=t(60*24*5), scheduled_end=t(1790), late_minutes=0, priority=1, program="KAVACH", orders=[o_wo]),
  M.DemandResult(demand_line_id=iid("dml",2), order_id=iid("dmo",4), order_number="DO-KV-004", line_no=10, item_id=ITEM_B, part_number="KV-PCB-FLT", qty=100,
  due=t(60*24*3), scheduled_end=None, late_minutes=480, priority=5, program=None, orders=[o_pl], late_text="P-12 is not completely scheduled within the horizon.")]
exc = [M.ApsException(code="APS_ORDER_LATE", severity="critical", subject=M.RefItem(type="planned", id=PO1, label="P-12"), order=o_pl, message="P-12 (KV-PCB-FLT x100) is 8 h late.", refs=[]),
       M.ApsException(code="APS_BEYOND_HORIZON", severity="info", subject=M.RefItem(type="planned", id=PO1, label="P-12"), op_no=5, order=o_pl, message="1 operation starts after the horizon end.", refs=[]),
       M.ApsException(code="APS_OVERTIME_SUGGESTED", severity="info", subject=M.RefItem(type="line", id=SMT1, label="SMT-1"), message="Opening SMT-1 EVE on Mon 2 Nov (4 h, 1,600) saves 7,680 weighted late minutes.", refs=[])]
load = [M.LoadRow(group_id=G_SMT, line_id=SMT1, day=date(2026,11,2), scheduled_minutes=400, required_minutes=380, base_minutes=495, optional_minutes=240, opened_minutes=0),
        M.LoadRow(group_id=G_SMT, line_id=None, day=date(2026,11,2), scheduled_minutes=660, required_minutes=640, base_minutes=990, optional_minutes=480, opened_minutes=0)]
bn = [M.Bottleneck(group_id=G_SMT, rank=1, utilisation=0.81, late_chains=1, suggestion="Adding the EVE shift on SMT-1 saves 7,680 weighted late minutes.", saved_minutes=7680.0),
      M.Bottleneck(group_id=G_BI, rank=2, utilisation=0.64, late_chains=1)]
val = M.Validation(ok=True, violations=[], counts={})
params = M.ApsParams(label="Weekly", overtime="suggest", improve_seconds=30)
res = M.ApsResult(params=params, kind="live", as_of=T0, horizon_end=T0+timedelta(days=42), summary=summary, score=[0, 7680.0, 0.0, 1790.0, 1790.0, 165.0],
  validation=val, operations=ops, overtime=ot, orders=orders, demand=demand, exceptions=exc, load=load, bottlenecks=bn, iterations=12, budget_used=4.2)
J = lambda m: json.loads(m.model_dump_json())
actor = {"id": iid("usr",1), "name": "Planner Pia"}
def run_record(rid, no, policy, status="completed", summ=None, **kw):
    r = {"id": rid, "run_no": no, "kind": "live", "status": status, "label": "Weekly", "note": "", "pinned": False,
         "is_published": False, "published_at": None, "published_by": None, "parent_run_id": None, "copy_of_run_id": None,
         "mrp_run": {"id": MRP, "run_no": 7}, "as_of": T0.isoformat(), "horizon_end": (T0+timedelta(days=42)).isoformat(),
         "horizon_days": 42, "policy": policy, "master_fingerprint": "9f2c" + "0"*60, "row_version": 1,
         "started_at": T0.isoformat(), "finished_at": (T0+timedelta(seconds=14)).isoformat(), "duration_ms": 14200,
         "actor": actor, "progress": {"phase": "done", "percent": 100, "best_score": res.score, "updated_at": (T0+timedelta(seconds=14)).isoformat()},
         "summary": summ, "score": res.score, "validation": {"ok": True, "counts": {}},
         "stale": {"is_stale": False, "master_changed": False, "transactions_changed": False, "mrp_changed": False},
         "late_demand_remains": bool(summ and summ["late_demand_count"]), "publishable": True, "error": None,
         "link": f"/mfg/schedule/runs/{rid}"}
    r.update(kw)
    return r
run = run_record(RUN, 4, "suggest", summ=J(summary))
run_detail = dict(run, params=J(params))
s2 = summary.model_copy(update={"policy": "allow", "late_orders": 0, "demand_lines_late": 0, "demand_lines_on_time": 2, "late_demand_count": 0,
       "weighted_tardiness": 0.0, "max_lateness_minutes": 0, "overtime_minutes": 240, "overtime_cost": 1600.0, "suggested_overtime_minutes": 0,
       "suggested_overtime_cost": 0.0, "suggested_tardiness_saved": 0.0})
run2 = run_record(RUN2, 5, "allow", summ=J(s2), copy_of_run_id=RUN, label="Weekly (Allow)")
running = run_record(iid("apr",3), 6, "suggest", status="running", summ=None, finished_at=None, duration_ms=None, score=None, validation=None,
       stale=None, publishable=False, late_demand_remains=False,
       progress={"phase": "improve", "percent": 55, "best_score": [0, 9120.0, 0.0, 2010.0, 1890.0, 180.0], "updated_at": T0.isoformat()})
items = {"id": ITEM_A, "part_number": "KV-TPU-1000", "revision": "A", "description": "Telematics processing unit", "uom": "EA", "make_buy": "make", "active": True}
def op_row(o):
    d = J(o)
    d["item"] = items if o.order.item_id == ITEM_A else dict(items, id=ITEM_B, part_number="KV-PCB-FLT", description="Filter board")
    d["line"] = None if o.line_id is None else {"id": o.line_id, "code": {SMT1: "SMT-1", SMT2: "SMT-2", BI1: "BI-1"}[o.line_id]}
    d["group"] = {"id": o.group_id, "code": "SMT" if o.group_id == G_SMT else "BURNIN"}
    d["link"] = f"/mfg/schedule/runs/{RUN}/gantt?op={o.op_no}"
    return d
gantt = M.Gantt(view="line", rows=[M.GanttRow(key=f"group:{G_SMT}", label="SMT", kind="group"),
    M.GanttRow(key=f"line:{SMT1}", label="SMT-1", kind="line", parent_key=f"group:{G_SMT}"),
    M.GanttRow(key=f"line:{SMT2}", label="SMT-2", kind="line", parent_key=f"group:{G_SMT}")],
  bars=[M.GanttBar(op_no=1, row_key=f"line:{SMT1}", start=t(0), end=t(140), setup_end=t(45), pieces=[M.Span(start=t(0), end=t(140))], label="WO-000143 10 SMT top",
        order_number="WO-000143", item_part_number="KV-TPU-1000", qty=10, late_minutes=0, frozen=True, locked=False, split=M.SplitInfo(), status_color="frozen"),
        M.GanttBar(op_no=3, row_key=f"line:{SMT1}", start=t(140), end=t(400), setup_end=t(200), pieces=[M.Span(start=t(140), end=t(400))], label="P-12 10 SMT top (1/2)",
        order_number="P-12", item_part_number="KV-PCB-FLT", qty=50, late_minutes=0, frozen=False, locked=False, split=M.SplitInfo(index=0, count=2), status_color="critical")],
  bands=[M.GanttBand(row_key=f"line:{SMT1}", start=t(0), end=t(540), kind="base"), M.GanttBand(row_key=f"line:{SMT1}", start=t(540), end=t(780), kind="optional_suggested"),
         M.GanttBand(row_key=f"line:{SMT2}", start=t(1440*5), end=t(1440*6), kind="closed")], truncated=False)
dispatch = [M.DispatchRow(op_no=1, position=1, start=t(0), end=t(140), order=o_wo, part_number="KV-TPU-1000", qty=10, seq=10, name="SMT top",
   setup_minutes=45, run_minutes=95, setup_from_family=None, family="PCBA-HDI", crew=ops[0].crew, tools=ops[0].tools, predecessor_status="none",
   material_status="kitted", done=False, shift_label="KV-3SHIFT/A")]
cmp = M.Compare(a={"id": RUN, "run_no": 4, "label": "Weekly", "policy": "suggest"}, b={"id": RUN2, "run_no": 5, "label": "Weekly (Allow)", "policy": "allow"},
  kpis=[M.CompareDelta(key="weighted_tardiness", a=7680, b=0, delta=-7680), M.CompareDelta(key="late_demand_count", a=1, b=0, delta=-1),
        M.CompareDelta(key="overtime_minutes", a=0, b=240, delta=240), M.CompareDelta(key="overtime_cost", a=0, b=1600, delta=1600)],
  tradeoff={"weighted_tardiness_saved": 7680.0, "late_minutes_saved": 480.0, "late_demand_saved": 1.0, "overtime_hours_added": 4.0, "overtime_cost_added": 1600.0},
  orders=[M.OrderDelta(order=o_pl, end_a=None, end_b=t(4000), delta_minutes=None, late_a=480, late_b=0)],
  utilisation=[M.CompareDelta(key=G_SMT, a=0.81, b=0.86, delta=0.05)], truncated=False)
page = lambda items_, total=None: {"items": items_, "total": len(items_) if total is None else total, "limit": 50, "offset": 0}
fx = {
 "_doc": "M3 S0 contract examples (M3-DESIGN 6.1, 11). Shapes are frozen; values are illustrative. Instants are UTC ISO-8601.",
 "post_runs_body": J(params),
 "post_runs_copy_of_body": {"copy_of": RUN, "overtime": "allow", "label": "Weekly (Allow)"},
 "post_runs_response_202": dict(running, status="queued", progress={"phase": "queued", "percent": 0, "best_score": None, "updated_at": T0.isoformat()}),
 "run_running": running,
 "run": run_detail,
 "run_copy_allow": run2,
 "runs_page": page([run2, run]),
 "result": J(res),
 "operations_page": page([op_row(o) for o in ops]),
 "operation_detail": {"op": op_row(ops[2]), "reason": J(ops[2].reason), "release": J(ops[2].release),
                      "neighbours": {"before": op_row(ops[0]), "after": None}},
 "orders_page": page([J(o) for o in orders]),
 "demand": {"items": [J(d) for d in demand], "counts": {"on_time": 1, "late": 1}},
 "load": {"bucket": "day", "items": [J(x) for x in load]},
 "dispatch": {"line": {"id": SMT1, "code": "SMT-1"}, "date": "2026-11-02", "shift": "A", "run_id": RUN, "items": [J(x) for x in dispatch]},
 "overtime": {"items": [J(x) for x in ot], "totals": {"opened_minutes": 0, "opened_cost": 0.0, "suggested_minutes": 240, "suggested_cost": 1600.0, "tardiness_saved_minutes": 7680.0}},
 "exceptions_page": dict(page([J(e) | {"id": iid("aex", i+1), "ex_no": i+1} for i, e in enumerate(exc)]), counts={"by_severity": {"critical": 1, "warning": 0, "info": 2}, "by_code": {"APS_ORDER_LATE": 1, "APS_BEYOND_HORIZON": 1, "APS_OVERTIME_SUGGESTED": 1}}),
 "bottlenecks": {"items": [J(b) | {"group": {"id": b.group_id, "code": "SMT" if b.group_id == G_SMT else "BURNIN"}} for b in bn]},
 "gantt": J(gantt),
 "compare": J(cmp),
 "edits_body": {"edits": [{"kind": "move", "op_no": 3, "line_id": SMT2, "start": t(400).isoformat()}, {"kind": "lock", "op_no": 1},
                          {"kind": "resequence", "line_id": SMT1, "op_nos": [3, 1]}], "override_freeze": False},
 "edits_response_201": dict(run_detail, id=iid("apr",4), run_no=7, parent_run_id=RUN, label="Weekly (edited)"),
 "edit_infeasible_422": {"error": {"code": "APS_EDIT_INFEASIBLE", "message": "The edit breaks 1 hard constraint.",
      "details": {"violations": [{"code": "APS_V_WINDOW", "op_no": 3, "message": "Op 3 on SMT-2 runs outside an open window (Sun 8 Nov 10:00).", "refs": {"line_id": SMT2}}]}}},
 "wo_operations": {"wo": {"id": WO1, "number": "WO-000143", "row_version": 4}, "items": [
    {"seq": 10, "name": "SMT top", "group": {"id": G_SMT, "code": "SMT", "name": "SMT"}, "setup_minutes": 45, "run_minutes": 9.5, "labor": "attended", "done": True,
     "done_at": T0.isoformat(), "done_by": {"id": actor["id"], "code": "", "name": actor["name"]}, "placement": []},
    {"seq": 20, "name": "Burn-in", "group": {"id": G_BI, "code": "BURNIN", "name": "Burn-in"}, "setup_minutes": 0, "run_minutes": 72, "labor": "unattended", "done": False,
     "done_at": None, "done_by": None, "placement": [{"run_id": RUN, "op_no": 2, "line": {"id": BI1, "code": "BI-1"}, "start": t(170).isoformat(), "end": t(890).isoformat(), "split": {"index": 0, "count": 1}}]}]},
 "operation_line_rate": {"id": iid("olr",1), "operation_id": iid("opr",1), "line_id": SMT2, "setup_minutes": None, "run_minutes": 2.0, "note": "SMT-3 slower on BPL",
    "row_version": 1, "created_at": T0.isoformat(), "updated_at": T0.isoformat(), "line": {"id": SMT2, "code": "SMT-2", "name": "SMT line 2"}, "routing_id": iid("rtg",1), "item_id": ITEM_B, "seq": 10},
 "setup_matrix_row": {"id": iid("stm",1), "line_setup_family": "SMT", "from_family": "PCBA-HDI", "to_family": "PCBA-STD", "setup_minutes": 60,
    "row_version": 1, "created_at": T0.isoformat(), "updated_at": T0.isoformat(), "line_count": 3},
 "operator_absence": {"id": iid("oab",1), "operator_id": EMP1, "start": t(1440*7).isoformat(), "end": t(1440*11).isoformat(), "kind": "leave", "note": "",
    "row_version": 1, "created_at": T0.isoformat(), "updated_at": T0.isoformat(), "operator": {"id": EMP1, "code": "OP-COAT-1", "name": "Coating operator 1"}},
 "summary_published_schedule": {"id": RUN, "run_no": 4, "published_at": T0.isoformat(), "late_orders": 1, "stale": False},
 "plant_aps_fields": {"time_zone": "Asia/Kolkata", "utc_offset": "+05:30", "aps_freeze_hours": 48, "aps_horizon_days": 42, "aps_overtime_policy": "suggest"},
 "meta_time_zones": {"items": ["Asia/Kolkata", "Europe/Berlin", "UTC"]},
}
out = str(__import__("pathlib").Path(__file__).resolve().parent / "example_run.json")
open(out, "w").write(json.dumps(fx, indent=1, sort_keys=False) + "\n")
print("written", out)

"""Builds `example_floor.json` (M4 S0 contract examples, typed via `mfg.model_m4`):
`python superplanner/mfg/floor/fixtures/build_example.py`. Every example that has a model is validated by it."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from superplanner.mfg import model_m4 as M  # noqa: E402

U = timezone.utc
T0 = datetime(2026, 11, 2, 3, 30, tzinfo=U)   # 09:00 Asia/Kolkata


def t(m: float) -> datetime:
    return T0 + timedelta(minutes=m)


def iso(m: float) -> str:
    return t(m).isoformat()


def iid(p: str, n: int) -> str:
    return f"{p}_{n:032x}"


WO1, WO2 = iid("wko", 1), iid("wko", 2)
OP10, OP20, OP30, OP2_10 = iid("wop", 1), iid("wop", 2), iid("wop", 3), iid("wop", 4)
SMT1, ICT1, BI1 = iid("lin", 1), iid("lin", 2), iid("lin", 3)
G_SMT, G_ICT, G_BI = iid("wcg", 1), iid("wcg", 2), iid("wcg", 3)
ITEM_PCB, ITEM_TPU, ITEM_R = iid("itm", 1), iid("itm", 2), iid("itm", 3)
EMP1, EMP2 = iid("emp", 1), iid("emp", 2)
LOC_LS, LOC_FG = iid("loc", 1), iid("loc", 2)
RUN = iid("apr", 4)
DT1 = iid("dtm", 1)
BL1 = iid("bld", 1)
SER1, SER2, SER3 = iid("ser", 1), iid("ser", 2), iid("ser", 3)
TRG1, TRG2 = iid("rpt", 1), iid("rpt", 2)
NTF1 = iid("ntf", 1)
SIM1 = iid("asm", 1)
EV = [iid("fev", i) for i in range(1, 8)]
USER = {"id": "usr_00000000000000000000000000000001", "code": "", "name": "Station SMT"}
POST1 = iid("pst", 1)

g_smt = {"id": G_SMT, "code": "SMT", "name": "SMT"}
g_ict = {"id": G_ICT, "code": "ICT", "name": "In-circuit test"}
g_bi = {"id": G_BI, "code": "BURNIN", "name": "Burn-in"}
l_smt = {"id": SMT1, "code": "SMT-1", "name": "SMT line 1"}
l_ict = {"id": ICT1, "code": "ICT-1", "name": "ICT station 1"}
l_bi = {"id": BI1, "code": "BI-1", "name": "Burn-in rack 1"}
emp1 = {"id": EMP1, "code": "OP-SMT-1", "name": "Asha"}
emp2 = {"id": EMP2, "code": "OP-ICT-1", "name": "Ravi"}
wo1 = {"id": WO1, "number": "WO-000143", "status": "in_progress", "qty": 100.0, "qty_completed": 0.0,
       "qty_scrapped": 2.0, "row_version": 5, "item": {"id": ITEM_PCB, "part_number": "KV-PCB-MAIN",
                                                       "description": "Main PCB"},
       "due_date": "2026-11-09", "priority": 3, "released_to_floor_at": iso(-600), "receipt_location_id": None}


def stamp(n: int = 1, m: float = 0) -> dict:
    return {"row_version": n, "created_at": iso(-600), "updated_at": iso(m)}


def wo_op(oid: str, seq: int, name: str, group: dict, status: str, **kw) -> dict:
    d = {"id": oid, "wo_id": WO1, "seq": seq, "name": name, "group": group, "status": status, "qty_planned": 100.0,
         "qty_good": 0.0, "qty_scrap": 0.0, "qty_rework_out": 0.0, "qty_rework_in": 0.0, "qty_input": 100.0,
         "qty_available": 100.0, "line": None, "setup_minutes_actual": 0.0, "run_minutes_actual": 0.0,
         "labour_minutes": 0.0, "actual_start": None, "actual_end": None, "started_short": False,
         "source": "release", "capture_serial": False, "last_event_seq": None, "setup_minutes": 45.0,
         "run_minutes": 1.2, "labor": "attended", "done": status in ("completed", "skipped"), "done_at": None,
         "done_by": None, "placement": [], **stamp()}
    d.update(kw)
    return json.loads(M.WoOperationRecord.model_validate(d).model_dump_json())


op10 = wo_op(OP10, 10, "SMT top + bottom", g_smt, "running", qty_good=40.0, qty_scrap=2.0, qty_available=58.0,
             line=l_smt, setup_minutes_actual=38.0, run_minutes_actual=52.0, labour_minutes=90.0,
             actual_start=iso(-120), last_event_seq=1043, row_version=4,
             placement=[{"run_id": RUN, "op_no": 1, "line": {"id": SMT1, "code": "SMT-1"}, "start": iso(-130),
                         "end": iso(110), "split": {"index": 0, "count": 1}}])
op20 = wo_op(OP20, 20, "ICT", g_ict, "pending", qty_input=40.0, qty_available=40.0, capture_serial=True,
             setup_minutes=10.0, run_minutes=3.0)
op30 = wo_op(OP30, 30, "Burn-in", g_bi, "pending", qty_input=0.0, qty_available=0.0, setup_minutes=0.0,
             run_minutes=720.0, labor="unattended")
op10_done = dict(op10, status="completed", qty_good=95.0, qty_scrap=5.0, qty_available=0.0, actual_end=iso(0),
                 run_minutes_actual=168.0, labour_minutes=206.0, done=True, done_at=iso(0), done_by=USER,
                 last_event_seq=1047, row_version=6)


def event(eid: str, seq: int, et: str, m: float, **kw) -> dict:
    d = {"id": eid, "seq": seq, "wo_operation_id": OP10, "wo_id": WO1, "wo_number": "WO-000143", "op_seq": 10,
         "event_type": et, "event_at": iso(m), "recorded_at": iso(m), "line": l_smt, "operators": [emp1],
         "qty_good": None, "qty_scrap": None, "qty_rework": None, "rework_to_seq": None, "reason_code": None,
         "note": "", "client_event_id": f"tab-smt1-{seq:06d}", "batch_load_id": None, "serials": None,
         "corrects_event_id": None, "corrected": False, "forced": None, "actor": USER, "details": {}}
    d.update(kw)
    return json.loads(M.FloorEventRecord.model_validate(d).model_dump_json())


events = [event(EV[0], 1040, "setup_start", -128), event(EV[1], 1041, "start", -90),
          event(EV[2], 1042, "report", -40, qty_good=40.0, qty_scrap=2.0, reason_code="SOLDER_BRIDGE"),
          event(EV[3], 1043, "pause", -30, reason_code="BREAK"), event(EV[4], 1044, "resume", 0)]
ev_complete = event(EV[5], 1047, "complete", 0, qty_good=55.0, qty_scrap=3.0, reason_code="TOMBSTONE",
                    operators=[emp1, emp2], details={"backflush": [{"component_id": iid("woc", 1), "qty": 116.0}]})


def J(model, d):
    return json.loads(model.model_validate(d).model_dump_json())


receipt_posting = {"id": POST1, "number": "TXN-000912", "type": "wo_receipt",
                   "lines": [{"item_id": ITEM_TPU, "location_id": LOC_FG, "qty": 10.0, "lot_code": "WO-000150"}]}
backflush_posting = {"id": iid("pst", 2), "number": "TXN-000911", "type": "wo_issue",
                     "lines": [{"item_id": ITEM_R, "location_id": LOC_LS, "qty": 116.0, "lot_code": "R-2611"}]}

trigger_line_down = J(M.ReplanTriggerRecord, {
    "id": TRG1, "kind": "line_down", "severity": "critical", "ref_type": "downtime", "ref_id": DT1,
    "detected_at": iso(5), "dedupe_key": f"line_down:{DT1}",
    "details": {"line_id": SMT1, "line_code": "SMT-1", "ops_affected": 3, "first_op_start": iso(20)},
    "status": "open", "aps_run_id": None, "handled_by": None, "handled_at": None,
    "message": "SMT-1 is down (breakdown) with 3 published operations in the next 24 h."})
trigger_overrun = J(M.ReplanTriggerRecord, {
    "id": TRG2, "kind": "overrun", "severity": "warning", "ref_type": "wo_operation", "ref_id": OP10,
    "detected_at": iso(-40), "dedupe_key": f"overrun:{OP10}",
    "details": {"planned_end": iso(110), "projected_end": iso(190), "tolerance_minutes": 48},
    "status": "attached", "aps_run_id": iid("apr", 9), "handled_by": None, "handled_at": None,
    "message": "WO-000143 op 10 is projected to end 80 min after its planned end."})

downtime = J(M.DowntimeRecord, {
    "id": DT1, **stamp(1, 5), "line": l_smt, "kind": "breakdown", "planned": False, "start_at": iso(5),
    "end_at": None, "expected_end_at": iso(245), "open": True, "minutes": None, "reason": "Reflow oven fan",
    "note": "", "reported_by": USER, "closed_by": None, "triggers": [trigger_line_down]})
downtime_closed = dict(downtime, end_at=iso(305), open=False, minutes=300.0, closed_by=USER,
                       row_version=2, updated_at=iso(305), triggers=[])

load = J(M.BatchLoadRecord, {
    "id": BL1, **stamp(1, 10), "load_no": "BL:00000001", "line": l_bi, "status": "open", "started_at": None,
    "ended_at": None, "aps_run_id": RUN, "units": 8.0,
    "members": [{"wo_operation_id": OP30, "wo": {"id": WO1, "number": "WO-000143"}, "seq": 30, "qty": 5.0},
                {"wo_operation_id": iid("wop", 9), "wo": {"id": WO2, "number": "WO-000144"}, "seq": 30,
                 "qty": 3.0}]})


def serial(sid: str, s: str, status: str, **kw) -> dict:
    d = {"id": sid, **stamp(), "item": {"id": ITEM_TPU, "part_number": "KV-TPU-1000",
                                        "description": "Train protection unit"},
         "serial": s, "wo": {"id": WO2, "number": "WO-000150"}, "status": status, "captured_at": iso(0),
         "captured_op_seq": 90, "parent_serial_id": None, "consumed_at": None, "consumed_wo_id": None}
    d.update(kw)
    return J(M.UnitSerialRecord, d)


ser_tpu = serial(SER1, "TPU-26-0001", "in_stock")
ser_pcb = serial(SER2, "PCB-26-0417", "consumed", item={"id": ITEM_PCB, "part_number": "KV-PCB-MAIN",
                                                         "description": "Main PCB"},
                 wo={"id": WO1, "number": "WO-000143"}, captured_op_seq=20, parent_serial_id=SER1,
                 consumed_at=iso(-30), consumed_wo_id=WO2)
serial_detail = J(M.UnitSerialDetail, dict(ser_tpu, parent=None, children=[ser_pcb], consumed_by_wo=None))

notif = J(M.NotificationRecord, {
    "id": NTF1, "kind": "trigger.line_down", "severity": "critical", "title": "SMT-1 is down",
    "body": "Breakdown (Reflow oven fan) since 09:05; 3 published operations affected in the next 24 h.",
    "link": "/mfg/replan?trigger=" + TRG1, "trigger_id": TRG1, "created_at": iso(5), "acknowledged_at": None,
    "acknowledged_by": None})

kpi_v = lambda v, n, d, unit="ratio": {"value": v, "num": n, "den": d, "unit": unit}  # noqa: E731
kpis = J(M.KpiResponse, {
    "period": {"from": "2026-10-19", "to": "2026-11-01", "bucket": "day", "dim": "plant", "dim_id": None,
               "time_zone": "Asia/Kolkata"},
    "metrics": {"otd": kpi_v(0.8, 4, 5), "wo_on_time": kpi_v(0.833, 10, 12),
                "utilisation": kpi_v(0.71, 6816, 9600), "availability": kpi_v(0.95, 9120, 9600),
                "performance": kpi_v(0.91, 6202, 6816), "fpy": kpi_v(0.97, 970, 1000),
                "oee": kpi_v(0.839, 0.839, 1), "scrap_rate": kpi_v(0.03, 30, 1000),
                "adherence": kpi_v(0.7, 28, 40),
                "wip": {"count": 6, "value": 412500.0, "avg_age_days": 3.4},
                "setup": {"actual_minutes": 1260.0, "planned_minutes": 1140.0, "changeovers": 21}},
    "series": {"otd": [{"bucket": "2026-10-19", "value": 1.0}, {"bucket": "2026-10-20", "value": None}],
               "oee": [{"bucket": "2026-10-19", "value": 0.82}, {"bucket": "2026-10-20", "value": 0.85}]},
    "top_scrap": [{"reason_code": "SOLDER_BRIDGE", "qty": 18.0, "item_family": "PCBA-HDI", "operation": "ICT"}],
    "top_downtime": [{"reason": "Reflow oven fan", "kind": "breakdown", "minutes": 300.0, "line": l_smt}],
    "worst_adherence_lines": [{"line": l_smt, "value": 0.55, "num": 11, "den": 20}],
    "by_dim": [{"dim": "line", "ref": l_smt, "utilisation": 0.78, "availability": 0.88, "oee": 0.71}]})

adherence = {"items": [J(M.AdherenceRow, {
    "wo_operation_id": OP10, "wo": {"id": WO1, "number": "WO-000143"}, "seq": 10, "line": l_smt,
    "planned_start": iso(-130), "planned_end": iso(110), "actual_start": iso(-120), "actual_end": iso(0),
    "start_delta_minutes": 10.0, "end_delta_minutes": -110.0, "adherent": True})],
    "total": 1, "limit": 200, "offset": 0, "run_id": RUN, "tolerance_minutes": 120}

sim_q = J(M.SimulationRecord, {"id": SIM1, **stamp(1, 0), "base_run_id": RUN, "status": "queued", "samples": 20,
                               "params": {"seed": 7, "horizon_days": 42}, "results": None, "error": None,
                               "job_id": iid("job", 1), "started_at": None, "finished_at": None,
                               "duration_ms": None})
sim_done = J(M.SimulationRecord, dict(sim_q, status="completed", row_version=3, started_at=iso(0),
                                      finished_at=iso(1.5), duration_ms=88400, results={
    "samples_done": 20, "seed": 7,
    "demand": [{"demand_line_id": iid("dln", 1), "order": "DO-KV-003/1", "part_number": "KV-TPU-1000",
                "due": iso(60 * 24 * 6), "p_on_time": 0.35, "p50": iso(60 * 24 * 6.5), "p90": iso(60 * 24 * 8),
                "base_end": iso(60 * 24 * 5.8)}],
    "lines": [{"line": l_smt, "expected_lost_hours": 3.1, "mtbf_hours": 160.0, "breakdowns_sampled": 9}],
    "suppliers": [{"supplier": {"id": iid("sup", 1), "code": "SUP-FPGA", "name": "FPGA Distribution"},
                   "late_lines": 7, "mean_delay_days": 4.2, "history_receipts": 11}]}))

queue = J(M.QueueResponse, {
    "line": l_smt, "date": "2026-11-02", "shift": "A", "run_id": RUN, "down": None,
    "shifts": [{"label": "3SHIFT/A", "start": iso(-210), "end": iso(270), "kind": "base"}],
    "items": [
        {"wo_operation_id": OP10, "wo": {"id": WO1, "number": "WO-000143", "item": wo1["item"], "qty": 100.0,
                                         "due_date": "2026-11-09", "priority": 3, "row_version": 5},
         "seq": 10, "name": "SMT top + bottom", "status": "running", "planned_start": iso(-130),
         "planned_end": iso(110), "op_no": 1, "qty_planned": 100.0, "qty_good": 40.0, "kit": "kitted",
         "batch_load_id": None, "next_actions": ["pause", "report", "complete"]},
        {"wo_operation_id": OP2_10, "wo": {"id": WO2, "number": "WO-000144", "item": wo1["item"], "qty": 50.0,
                                           "due_date": "2026-11-11", "priority": 5, "row_version": 2},
         "seq": 10, "name": "SMT top + bottom", "status": "ready", "planned_start": iso(140), "planned_end": iso(260),
         "op_no": 3, "qty_planned": 50.0, "qty_good": 0.0, "kit": "short", "batch_load_id": None,
         "next_actions": ["setup_start", "start"]}]})

op_detail = J(M.FloorOperationDetail, {
    "operation": op10, "wo": wo1, "instructions": "Load panel program KV-MAIN-R3; check stencil S-17.",
    "components": [
        {"component_id": iid("woc", 1), "item": {"id": ITEM_R, "part_number": "KV-R-10K-0402",
                                                 "description": "Resistor 10k 0402"},
         "required_qty": 2900.0, "issued_qty": 1160.0, "backflush": True, "backflush_posted": 1160.0,
         "backflush_pending": 0.0, "kit": "kitted", "location": {"id": LOC_LS, "code": "LS-SMT"}},
        {"component_id": iid("woc", 2), "item": {"id": iid("itm", 4), "part_number": "KV-IC-FPGA-V1",
                                                 "description": "FPGA"},
         "required_qty": 100.0, "issued_qty": 100.0, "backflush": False, "backflush_posted": 0.0,
         "backflush_pending": 0.0, "kit": "kitted", "location": None}],
    "tools": [{"tool_pool": {"id": iid("tlp", 1), "code": "STENCIL-17", "name": "Stencil 17"}, "qty": 1}],
    "eligible_lines": [l_smt, {"id": iid("lin", 5), "code": "SMT-2", "name": "SMT line 2"}],
    "expected_input": 100.0, "events": events, "allowed_actions": ["pause", "report", "complete"],
    "serials": {"capture": False, "produced": [], "consumable": []}})

event_body = {"client_event_id": "tab-smt1-001048", "wo_operation_id": OP10, "event_type": "complete",
              "line_id": SMT1, "operator_codes": ["OP-SMT-1", "OP-ICT-1"], "qty_good": 55, "qty_scrap": 3,
              "reason_code": "TOMBSTONE", "note": ""}
M.FloorEventInput.model_validate(event_body)
serial_event_body = {"client_event_id": "tab-fct1-000201", "scan": "WO-000150/90", "event_type": "complete",
                     "qty_good": 3, "serials": {"produced": ["TPU-26-0001", "TPU-26-0002", "TPU-26-0003"],
                                                "consumed": [{"item_id": ITEM_PCB, "serial": "PCB-26-0417"}]}}
M.FloorEventInput.model_validate(serial_event_body)
event_result = J(M.FloorEventResult, {
    "event": ev_complete, "operation": op10_done, "operations": [dict(op20, qty_input=95.0, qty_available=95.0,
                                                                       status="ready")],
    "wo": dict(wo1, qty_scrapped=5.0, row_version=6), "postings": [backflush_posting],
    "warnings": [], "triggers": []})
event_result_last_op = J(M.FloorEventResult, {
    "event": dict(ev_complete, wo_operation_id=OP30, op_seq=30, qty_good=10.0, qty_scrap=0.0, reason_code=None,
                  details={"receipt_posting_id": POST1}),
    "operation": dict(op30, status="completed", qty_good=10.0, qty_input=10.0, qty_available=0.0,
                      done=True, done_at=iso(0)),
    "operations": [], "wo": dict(wo1, status="completed", qty_completed=10.0, qty=10.0),
    "postings": [receipt_posting], "warnings": [{"code": "FLR_BACKFLUSH_PENDING",
                                                 "message": "1 backflush could not be posted (KV-R-10K-0402: 40 "
                                                            "needed, 30 available at LS-SMT).",
                                                 "details": {"pending": [{"component_id": iid("woc", 1),
                                                                          "item_id": ITEM_R, "qty": 40.0,
                                                                          "available": 30.0,
                                                                          "location_id": LOC_LS}]}}],
    "triggers": []})

page = lambda items, **kw: {"items": items, "total": len(items), "limit": 50, "offset": 0, **kw}  # noqa: E731

fx = {
    "_doc": "M4 S0 contract examples (M4-DESIGN 11). Built by build_example.py; every model-backed example "
            "is validated against superplanner.mfg.model_m4. Ids are synthetic.",
    "scan_wo": J(M.ScanResult, {"type": "work_order", "id": WO1, "label": "WO-000143 KV-PCB-MAIN x 100",
                                "link": f"/mfg/work-orders/{WO1}", "context": {"status": "in_progress"}}),
    "scan_operation": J(M.ScanResult, {"type": "operation", "id": OP10, "label": "WO-000143 op 10 SMT top + bottom",
                                       "link": f"/mfg/floor/operations/{OP10}",
                                       "context": {"wo_id": WO1, "seq": 10, "status": "running", "line_id": SMT1}}),
    "scan_operator": J(M.ScanResult, {"type": "operator", "id": EMP1, "label": "OP-SMT-1 Asha", "link": "",
                                      "context": {"code": "OP-SMT-1"}}),
    "scan_unknown_404": {"error": {"code": "FLR_SCAN_UNKNOWN", "message": "Nothing matches 'XYZ-1'.",
                                   "details": {"code": "XYZ-1"}}},
    "queue": queue,
    "operation_detail": op_detail,
    "event_body": event_body,
    "serial_event_body": serial_event_body,
    "event_result_201": event_result,
    "event_result_last_op_201": event_result_last_op,
    "event_invalid_transition_409": {"error": {"code": "FLR_INVALID_TRANSITION",
                                               "message": "WO-000143 op 10 is completed; start is not allowed.",
                                               "details": {"status": "completed", "event": "start",
                                                           "allowed": ["reopen", "correct"]}}},
    "event_qty_exceeds_422": {"error": {"code": "FLR_QTY_EXCEEDS_INPUT",
                                        "message": "Good 96 + scrap 5 exceeds the available input 100.",
                                        "details": {"available": 100.0, "good": 96.0, "scrap": 5.0}}},
    "events_page": page(events + [ev_complete]),
    "backflush_retry_body": {"wo_id": WO1},
    "backflush_retry": {"results": [{"wo_operation_id": OP10, "wo": {"id": WO1, "number": "WO-000143"},
                                     "component_id": iid("woc", 1), "item_id": ITEM_R,
                                     "part_number": "KV-R-10K-0402", "qty": 40.0, "status": "posted",
                                     "posting_id": iid("pst", 3)}],
                        "posted": 1, "pending": 0},
    "wo_operations": {"wo": {"id": WO1, "number": "WO-000143", "row_version": 5, "status": "in_progress",
                             "released_to_floor_at": iso(-600)},
                      "items": [op10, op20, op30]},
    "downtime_body": {"line_id": SMT1, "kind": "breakdown", "expected_end_at": iso(245), "reason": "Reflow oven fan"},
    "downtime_close_body": {"close": True},
    "downtime_201": downtime,
    "downtime_closed": downtime_closed,
    "downtime_page": page([downtime]),
    "batch_load_body": {"line_id": BI1, "members": [{"wo_operation_id": OP30, "qty": 5},
                                                     {"wo_operation_id": iid("wop", 9), "qty": 3}],
                        "aps_run_id": RUN},
    "batch_load_201": load,
    "batch_loads_page": page([load]),
    "serials_page": page([ser_tpu, ser_pcb]),
    "serial_detail": serial_detail,
    "triggers_page": page([trigger_line_down, trigger_overrun], counts={"open": 1, "attached": 1}),
    "trigger_note_body": {"note": "Handled by moving SMT work to SMT-2"},
    "trigger_handled": dict(trigger_line_down, status="handled", handled_by=USER, handled_at=iso(30)),
    "replan_run_body": {"trigger_ids": [TRG1]},
    "notifications_page": page([notif], unacked=1),
    "notification_acked": dict(notif, acknowledged_at=iso(12), acknowledged_by=USER),
    "kpis": kpis,
    "adherence": adherence,
    "simulation_body": {"base_run_id": RUN, "samples": 20, "seed": 7},
    "simulation_202": sim_q,
    "simulation": sim_done,
    "simulations_page": page([dict(sim_done, results=None)]),
    "summary_floor": {"running_ops": 4, "lines_down": 1, "open_triggers": 2, "pending_backflush": 1},
    "plant_m4_fields": {"replan_policy": "notify", "replan_debounce_minutes": 15, "overrun_tolerance_pct": 20.0,
                        "adherence_tolerance_minutes": 120, "wo_receipt_location_id": LOC_FG,
                        "backflush_location_id": LOC_LS},
    "master_m4_fields": {"item": {"issue_method": "backflush"}, "operation": {"capture_serial": True},
                         "line": {"location_id": LOC_LS, "batch_merge": True, "batch_wait_minutes": 120},
                         "operator": {"user_id": "usr_00000000000000000000000000000002"}},
    "release_body": {"override_reason": "Short FPGA arrives at 14:00; start SMT bottom side first"},
    "release_kit_incomplete_409": {"error": {"code": "WO_KIT_INCOMPLETE",
                                             "message": "WO-000143 is short of 1 component for its first operation.",
                                             "details": {"shortages": [{"component_id": iid("woc", 2),
                                                                        "item_id": iid("itm", 4),
                                                                        "part_number": "KV-IC-FPGA-V1",
                                                                        "required": 100.0, "available": 60.0,
                                                                        "short": 40.0, "operation_seq": 10}]}}},
    "aps_params_m4": {"supply_delays": [{"schedule_id": iid("psc", 1), "days": 5}],
                      "line_breakdowns": [{"line_id": SMT1, "start": iso(60), "hours": 6}]},
    "aps_result_m4": {"batches": [{"load_no": 1, "line_id": BI1, "start": iso(400), "end": iso(1120),
                                   "members": [{"op_no": 2, "qty": 5.0}, {"op_no": 7, "qty": 3.0}]}],
                      "operation_actual": {"op_no": 1, "actual": {"status": "running", "actual_start": iso(-120),
                                                                   "wo_operation_id": OP10},
                                           "moved_by_downtime": False}},
}

if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "example_floor.json"
    out.write_text(json.dumps(fx, indent=1) + "\n")
    print("written", out)

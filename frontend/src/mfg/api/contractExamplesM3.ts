/**
 * Typed examples of every M3 shape. The run and view examples are the WP-S S0 fixture responses
 * (`backend/superplanner/mfg/aps/fixtures/example_run.json`, as served by the API) verbatim; the master-data ones are WP-U's (docs/M3-DESIGN.md 11), Kavach-style values, ids written out in full. Typed
 * against `typesM3.ts` (no casts) so `tsc` fails on drift; also the mock data for UI work before S0.
 */
import type { Page } from "./types";
import type {
  ApsCompareResponse,
  ApsDemandResponse,
  ApsExceptionPage,
  ApsParams,
  ApsRunRecord,
  BottleneckRow,
  DispatchResponse,
  EditRequest,
  GanttResponse,
  LoadResponse,
  OpDetail,
  OperationLineRateRecord,
  OperatorAbsenceRecord,
  OrderResultRow,
  OvertimeResponse,
  PublishedScheduleSummary,
  ScheduledOpRow,
  SetupMatrixRowRecord,
  WoOperations,
} from "./typesM3";

const id = (p: string, n: number) => `${p}_${n.toString(16).padStart(32, "0")}`;
const TS = "2026-11-02T03:30:00Z";
const smt = { id: id("grp", 1), code: "SMT", name: "SMT assembly" };
const smt1 = { id: id("lin", 1), code: "SMT-1" };
const smt2 = { id: id("lin", 2), code: "SMT-2" };

export const exampleApsParams: ApsParams = { label: "Week 45", overtime: "suggest", split: true, improve_seconds: 30 };
export const exampleApsRerunAllow: ApsParams = { copy_of: id("apr", 7), overtime: "allow", label: "Week 45 with overtime" };
export const exampleEditRequest: EditRequest = {
  edits: [
    { kind: "move", op_no: 412, line_id: smt2.id, start: "2026-11-03T04:30:00Z" },
    { kind: "lock", op_no: 412 },
    { kind: "resequence", line_id: smt1.id, op_nos: [415, 413, 414] },
  ],
  override_freeze: false,
};

export const examplePublishedSummary: PublishedScheduleSummary = { id: "apr_00000000000000000000000000000001", run_no: 7, published_at: TS, late_orders: 5, stale: false };

export const exampleLineRate: OperationLineRateRecord = {
  id: id("olr", 1),
  operation_id: id("opn", 50),
  line_id: id("lin", 3),
  setup_minutes: null,
  run_minutes: 2,
  note: "SMT-3 slower on BPL",
  line: { id: id("lin", 3), code: "SMT-3", name: "SMT line 3" },
  row_version: 1,
  created_at: TS,
  updated_at: TS,
};

export const exampleSetupRow: SetupMatrixRowRecord = { id: id("stm", 1), line_setup_family: "SMT", from_family: "PCBA-HDI", to_family: "PCBA-STD", setup_minutes: 60, row_version: 1, created_at: TS, updated_at: TS };

export const exampleAbsence: OperatorAbsenceRecord = {
  id: id("oab", 1),
  operator_id: id("opr", 7),
  operator: { id: id("opr", 7), code: "OP-007", name: "Operator 007" },
  start: "2026-11-09T03:30:00Z",
  end: "2026-11-13T12:30:00Z",
  kind: "leave",
  note: "",
  row_version: 1,
  created_at: TS,
  updated_at: TS,
};

export const exampleWoOperations: WoOperations = {
  wo_id: id("wko", 1),
  row_version: 3,
  items: [
    { seq: 10, name: "Solder paste", group: smt, done: true, done_at: TS, done_by: "usr_store1", placement: null },
    { seq: 50, name: "SMT top", group: smt, done: false, done_at: null, done_by: null, placement: { run_id: "apr_00000000000000000000000000000001", run_no: 7, line: smt1, start: "2026-11-02T03:45:00Z", end: "2026-11-02T07:30:00Z" } },
  ],
};


export const exampleApsRun: ApsRunRecord = {
 "id": "apr_00000000000000000000000000000001",
 "run_no": 4,
 "kind": "live",
 "status": "completed",
 "label": "Weekly",
 "note": "",
 "pinned": false,
 "is_published": false,
 "published_at": null,
 "published_by": null,
 "parent_run_id": null,
 "copy_of_run_id": null,
 "mrp_run": {
  "id": "mrr_00000000000000000000000000000007",
  "run_no": 7
 },
 "as_of": "2026-11-02T03:30:00+00:00",
 "horizon_end": "2026-12-14T03:30:00+00:00",
 "horizon_days": 42,
 "policy": "suggest",
 "master_fingerprint": "9f2c000000000000000000000000000000000000000000000000000000000000",
 "row_version": 1,
 "started_at": "2026-11-02T03:30:00+00:00",
 "finished_at": "2026-11-02T03:30:14+00:00",
 "duration_ms": 14200,
 "actor": {
  "id": "usr_00000000000000000000000000000001",
  "name": "Planner Pia"
 },
 "progress": {
  "phase": "done",
  "percent": 100,
  "best_score": [
   0,
   7680,
   0,
   1790,
   1790,
   165
  ],
  "updated_at": "2026-11-02T03:30:14+00:00"
 },
 "summary": {
  "policy": "suggest",
  "operations": 5,
  "scheduled_operations": 4,
  "unscheduled": {
   "beyond_horizon": 1
  },
  "orders": 2,
  "late_orders": 1,
  "late_wos": 0,
  "demand_lines": 2,
  "demand_lines_on_time": 1,
  "demand_lines_late": 1,
  "late_demand_count": 1,
  "weighted_tardiness": 7680,
  "max_lateness_minutes": 480,
  "overtime_minutes": 0,
  "overtime_cost": 0,
  "suggested_overtime_minutes": 240,
  "suggested_overtime_cost": 1600,
  "suggested_tardiness_saved": 7680,
  "utilisation": {
   "wcg_00000000000000000000000000000001": 0.81,
   "wcg_00000000000000000000000000000002": 0.64
  },
  "bottlenecks": [
   "wcg_00000000000000000000000000000001",
   "wcg_00000000000000000000000000000002"
  ],
  "setup_minutes": 165,
  "changeovers": 2,
  "avg_flow_days": 1.4,
  "makespan_minutes": 1790,
  "validation_ok": true,
  "violations": 0,
  "splits": 1,
  "iterations": 12,
  "accepted_moves": 3,
  "budget_used": 4.2,
  "budget_cut": false,
  "timings_ms": {
   "load": 410,
   "construct": 1830,
   "improve": 9200,
   "validate": 240,
   "store": 860
  }
 },
 "score": [
  0,
  7680,
  0,
  1790,
  1790,
  165
 ],
 "validation": {
  "ok": true,
  "counts": {}
 },
 "stale": {
  "is_stale": false,
  "master_changed": false,
  "transactions_changed": false,
  "mrp_changed": false
 },
 "late_demand_remains": true,
 "publishable": true,
 "error": null,
 "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001",
 "params": {
  "label": "Weekly",
  "note": "",
  "as_of": null,
  "horizon_days": null,
  "mrp_run_id": null,
  "include_planned": true,
  "overtime": "suggest",
  "split": true,
  "material": "strict",
  "improve_seconds": 30,
  "capacity_overrides": [],
  "edits": [],
  "copy_of": null
 }
};

export const exampleApsRunRunning: ApsRunRecord = {
 "id": "apr_running",
 "run_no": 9,
 "kind": "live",
 "status": "running",
 "label": "Weekly",
 "note": "",
 "pinned": false,
 "is_published": false,
 "published_at": null,
 "published_by": null,
 "parent_run_id": null,
 "copy_of_run_id": null,
 "mrp_run": {
  "id": "mrr_00000000000000000000000000000007",
  "run_no": 7
 },
 "as_of": "2026-11-02T03:30:00+00:00",
 "horizon_end": "2026-12-14T03:30:00+00:00",
 "horizon_days": 42,
 "policy": "suggest",
 "master_fingerprint": "9f2c000000000000000000000000000000000000000000000000000000000000",
 "row_version": 1,
 "started_at": "2026-11-02T03:30:00+00:00",
 "finished_at": null,
 "duration_ms": null,
 "actor": {
  "id": "usr_00000000000000000000000000000001",
  "name": "Planner Pia"
 },
 "progress": {
  "phase": "improve",
  "percent": 62,
  "best_score": [
   0,
   9000,
   0,
   1800,
   1800,
   170
  ],
  "updated_at": "2026-11-02T03:30:10Z"
 },
 "summary": null,
 "score": [
  0,
  7680,
  0,
  1790,
  1790,
  165
 ],
 "validation": null,
 "stale": {
  "is_stale": false,
  "master_changed": false,
  "transactions_changed": false,
  "mrp_changed": false
 },
 "late_demand_remains": false,
 "publishable": false,
 "error": null,
 "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001",
 "params": {
  "label": "Weekly",
  "note": "",
  "as_of": null,
  "horizon_days": null,
  "mrp_run_id": null,
  "include_planned": true,
  "overtime": "suggest",
  "split": true,
  "material": "strict",
  "improve_seconds": 30,
  "capacity_overrides": [],
  "edits": [],
  "copy_of": null
 }
};

export const exampleApsRunPage: Page<ApsRunRecord> = {
 "items": [
  {
   "id": "apr_00000000000000000000000000000002",
   "run_no": 5,
   "kind": "live",
   "status": "completed",
   "label": "Weekly (Allow)",
   "note": "",
   "pinned": false,
   "is_published": false,
   "published_at": null,
   "published_by": null,
   "parent_run_id": null,
   "copy_of_run_id": "apr_00000000000000000000000000000001",
   "mrp_run": {
    "id": "mrr_00000000000000000000000000000007",
    "run_no": 7
   },
   "as_of": "2026-11-02T03:30:00+00:00",
   "horizon_end": "2026-12-14T03:30:00+00:00",
   "horizon_days": 42,
   "policy": "allow",
   "master_fingerprint": "9f2c000000000000000000000000000000000000000000000000000000000000",
   "row_version": 1,
   "started_at": "2026-11-02T03:30:00+00:00",
   "finished_at": "2026-11-02T03:30:14+00:00",
   "duration_ms": 14200,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "name": "Planner Pia"
   },
   "progress": {
    "phase": "done",
    "percent": 100,
    "best_score": [
     0,
     7680,
     0,
     1790,
     1790,
     165
    ],
    "updated_at": "2026-11-02T03:30:14+00:00"
   },
   "summary": {
    "policy": "allow",
    "operations": 5,
    "scheduled_operations": 4,
    "unscheduled": {
     "beyond_horizon": 1
    },
    "orders": 2,
    "late_orders": 0,
    "late_wos": 0,
    "demand_lines": 2,
    "demand_lines_on_time": 2,
    "demand_lines_late": 0,
    "late_demand_count": 0,
    "weighted_tardiness": 0,
    "max_lateness_minutes": 0,
    "overtime_minutes": 240,
    "overtime_cost": 1600,
    "suggested_overtime_minutes": 0,
    "suggested_overtime_cost": 0,
    "suggested_tardiness_saved": 0,
    "utilisation": {
     "wcg_00000000000000000000000000000001": 0.81,
     "wcg_00000000000000000000000000000002": 0.64
    },
    "bottlenecks": [
     "wcg_00000000000000000000000000000001",
     "wcg_00000000000000000000000000000002"
    ],
    "setup_minutes": 165,
    "changeovers": 2,
    "avg_flow_days": 1.4,
    "makespan_minutes": 1790,
    "validation_ok": true,
    "violations": 0,
    "splits": 1,
    "iterations": 12,
    "accepted_moves": 3,
    "budget_used": 4.2,
    "budget_cut": false,
    "timings_ms": {
     "load": 410,
     "construct": 1830,
     "improve": 9200,
     "validate": 240,
     "store": 860
    }
   },
   "score": [
    0,
    7680,
    0,
    1790,
    1790,
    165
   ],
   "validation": {
    "ok": true,
    "counts": {}
   },
   "stale": {
    "is_stale": false,
    "master_changed": false,
    "transactions_changed": false,
    "mrp_changed": false
   },
   "late_demand_remains": false,
   "publishable": true,
   "error": null,
   "link": "/mfg/schedule/runs/apr_00000000000000000000000000000002"
  },
  {
   "id": "apr_00000000000000000000000000000001",
   "run_no": 4,
   "kind": "live",
   "status": "completed",
   "label": "Weekly",
   "note": "",
   "pinned": false,
   "is_published": false,
   "published_at": null,
   "published_by": null,
   "parent_run_id": null,
   "copy_of_run_id": null,
   "mrp_run": {
    "id": "mrr_00000000000000000000000000000007",
    "run_no": 7
   },
   "as_of": "2026-11-02T03:30:00+00:00",
   "horizon_end": "2026-12-14T03:30:00+00:00",
   "horizon_days": 42,
   "policy": "suggest",
   "master_fingerprint": "9f2c000000000000000000000000000000000000000000000000000000000000",
   "row_version": 1,
   "started_at": "2026-11-02T03:30:00+00:00",
   "finished_at": "2026-11-02T03:30:14+00:00",
   "duration_ms": 14200,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "name": "Planner Pia"
   },
   "progress": {
    "phase": "done",
    "percent": 100,
    "best_score": [
     0,
     7680,
     0,
     1790,
     1790,
     165
    ],
    "updated_at": "2026-11-02T03:30:14+00:00"
   },
   "summary": {
    "policy": "suggest",
    "operations": 5,
    "scheduled_operations": 4,
    "unscheduled": {
     "beyond_horizon": 1
    },
    "orders": 2,
    "late_orders": 1,
    "late_wos": 0,
    "demand_lines": 2,
    "demand_lines_on_time": 1,
    "demand_lines_late": 1,
    "late_demand_count": 1,
    "weighted_tardiness": 7680,
    "max_lateness_minutes": 480,
    "overtime_minutes": 0,
    "overtime_cost": 0,
    "suggested_overtime_minutes": 240,
    "suggested_overtime_cost": 1600,
    "suggested_tardiness_saved": 7680,
    "utilisation": {
     "wcg_00000000000000000000000000000001": 0.81,
     "wcg_00000000000000000000000000000002": 0.64
    },
    "bottlenecks": [
     "wcg_00000000000000000000000000000001",
     "wcg_00000000000000000000000000000002"
    ],
    "setup_minutes": 165,
    "changeovers": 2,
    "avg_flow_days": 1.4,
    "makespan_minutes": 1790,
    "validation_ok": true,
    "violations": 0,
    "splits": 1,
    "iterations": 12,
    "accepted_moves": 3,
    "budget_used": 4.2,
    "budget_cut": false,
    "timings_ms": {
     "load": 410,
     "construct": 1830,
     "improve": 9200,
     "validate": 240,
     "store": 860
    }
   },
   "score": [
    0,
    7680,
    0,
    1790,
    1790,
    165
   ],
   "validation": {
    "ok": true,
    "counts": {}
   },
   "stale": {
    "is_stale": false,
    "master_changed": false,
    "transactions_changed": false,
    "mrp_changed": false
   },
   "late_demand_remains": true,
   "publishable": true,
   "error": null,
   "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001"
  }
 ],
 "total": 2,
 "limit": 50,
 "offset": 0
};

export const exampleGantt: GanttResponse = {
 "view": "line",
 "rows": [
  {
   "key": "group:wcg_00000000000000000000000000000001",
   "label": "SMT",
   "kind": "group",
   "parent_key": null
  },
  {
   "key": "line:lin_00000000000000000000000000000001",
   "label": "SMT-1",
   "kind": "line",
   "parent_key": "group:wcg_00000000000000000000000000000001"
  },
  {
   "key": "line:lin_00000000000000000000000000000002",
   "label": "SMT-2",
   "kind": "line",
   "parent_key": "group:wcg_00000000000000000000000000000001"
  }
 ],
 "bars": [
  {
   "op_no": 1,
   "row_key": "line:lin_00000000000000000000000000000001",
   "start": "2026-11-02T03:30:00Z",
   "end": "2026-11-02T05:50:00Z",
   "setup_end": "2026-11-02T04:15:00Z",
   "pieces": [
    {
     "start": "2026-11-02T03:30:00Z",
     "end": "2026-11-02T05:50:00Z"
    }
   ],
   "label": "WO-000143 10 SMT top",
   "order_number": "WO-000143",
   "item_part_number": "KV-TPU-1000",
   "qty": 10,
   "late_minutes": 0,
   "frozen": true,
   "locked": false,
   "split": {
    "index": 0,
    "count": 1
   },
   "status_color": "frozen"
  },
  {
   "op_no": 3,
   "row_key": "line:lin_00000000000000000000000000000001",
   "start": "2026-11-02T05:50:00Z",
   "end": "2026-11-02T10:10:00Z",
   "setup_end": "2026-11-02T06:50:00Z",
   "pieces": [
    {
     "start": "2026-11-02T05:50:00Z",
     "end": "2026-11-02T10:10:00Z"
    }
   ],
   "label": "P-12 10 SMT top (1/2)",
   "order_number": "P-12",
   "item_part_number": "KV-PCB-FLT",
   "qty": 50,
   "late_minutes": 0,
   "frozen": false,
   "locked": false,
   "split": {
    "index": 0,
    "count": 2
   },
   "status_color": "critical"
  }
 ],
 "bands": [
  {
   "row_key": "line:lin_00000000000000000000000000000001",
   "start": "2026-11-02T03:30:00Z",
   "end": "2026-11-02T12:30:00Z",
   "kind": "base"
  },
  {
   "row_key": "line:lin_00000000000000000000000000000001",
   "start": "2026-11-02T12:30:00Z",
   "end": "2026-11-02T16:30:00Z",
   "kind": "optional_suggested"
  },
  {
   "row_key": "line:lin_00000000000000000000000000000002",
   "start": "2026-11-07T03:30:00Z",
   "end": "2026-11-08T03:30:00Z",
   "kind": "closed"
  }
 ],
 "truncated": false
};

export const exampleOpPage: Page<ScheduledOpRow> = {
 "items": [
  {
   "op_no": 1,
   "order": {
    "type": "wo",
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143",
    "planned_no": null,
    "item_id": "itm_00000000000000000000000000000001"
   },
   "seq": 10,
   "name": "SMT top",
   "group_id": "wcg_00000000000000000000000000000001",
   "qty": 10,
   "split": {
    "index": 0,
    "count": 1
   },
   "line_id": "lin_00000000000000000000000000000001",
   "start": "2026-11-02T03:30:00Z",
   "end": "2026-11-02T05:50:00Z",
   "setup_minutes": 45,
   "run_minutes": 95,
   "pieces": [
    {
     "start": "2026-11-02T03:30:00Z",
     "end": "2026-11-02T05:50:00Z"
    }
   ],
   "crew": [
    {
     "operator_id": "emp_00000000000000000000000000000001",
     "start": "2026-11-02T03:30:00Z",
     "end": "2026-11-02T05:50:00Z"
    }
   ],
   "tools": [
    {
     "tool_pool_id": "tlp_00000000000000000000000000000001",
     "qty": 1
    }
   ],
   "release": {
    "material_at": "2026-11-02T03:30:00Z",
    "predecessor_at": null,
    "refs": [
     {
      "type": "stock",
      "id": "bal_00000000000000000000000000000001",
      "label": "Stock STORES",
      "at": "2026-11-02T03:30:00Z"
     }
    ]
   },
   "locked": false,
   "frozen": false,
   "status": "scheduled",
   "reason": {
    "code": "as_of",
    "refs": [],
    "text": "Starts at the planning start (as of)."
   },
   "due": "2026-11-07T03:30:00Z",
   "late_minutes": 0,
   "family": "PCBA-HDI",
   "setup_from_family": null,
   "item": {
    "id": "itm_00000000000000000000000000000001",
    "part_number": "KV-TPU-1000",
    "revision": "A",
    "description": "Telematics processing unit",
    "uom": "EA",
    "make_buy": "make",
    "active": true
   },
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1"
   },
   "group": {
    "id": "wcg_00000000000000000000000000000001",
    "code": "SMT"
   },
   "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001/gantt?op=1"
  },
  {
   "op_no": 2,
   "order": {
    "type": "wo",
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143",
    "planned_no": null,
    "item_id": "itm_00000000000000000000000000000001"
   },
   "seq": 20,
   "name": "Burn-in",
   "group_id": "wcg_00000000000000000000000000000002",
   "qty": 10,
   "split": {
    "index": 0,
    "count": 1
   },
   "line_id": "lin_00000000000000000000000000000003",
   "start": "2026-11-02T06:20:00Z",
   "end": "2026-11-02T18:20:00Z",
   "setup_minutes": 0,
   "run_minutes": 720,
   "pieces": [
    {
     "start": "2026-11-02T06:20:00Z",
     "end": "2026-11-02T12:30:00Z"
    },
    {
     "start": "2026-11-03T03:30:00Z",
     "end": "2026-11-03T09:20:00Z"
    }
   ],
   "crew": [],
   "tools": [],
   "release": {
    "material_at": null,
    "predecessor_at": "2026-11-02T06:20:00Z",
    "refs": [
     {
      "type": "operation",
      "id": "1",
      "label": "WO-000143 op 10 SMT top",
      "at": "2026-11-02T05:50:00Z"
     }
    ]
   },
   "locked": false,
   "frozen": false,
   "status": "scheduled",
   "reason": {
    "code": "predecessor",
    "refs": [
     {
      "type": "operation",
      "id": "1",
      "label": "op 1",
      "at": null
     }
    ],
    "text": "Waits for op 10 SMT top on SMT-1 (ends 11:20) + 30 min move."
   },
   "due": "2026-11-07T03:30:00Z",
   "late_minutes": 0,
   "family": "PCBA-HDI",
   "setup_from_family": null,
   "item": {
    "id": "itm_00000000000000000000000000000001",
    "part_number": "KV-TPU-1000",
    "revision": "A",
    "description": "Telematics processing unit",
    "uom": "EA",
    "make_buy": "make",
    "active": true
   },
   "line": {
    "id": "lin_00000000000000000000000000000003",
    "code": "BI-1"
   },
   "group": {
    "id": "wcg_00000000000000000000000000000002",
    "code": "BURNIN"
   },
   "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001/gantt?op=2"
  },
  {
   "op_no": 3,
   "order": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "number": "P-12",
    "planned_no": 12,
    "item_id": "itm_00000000000000000000000000000002"
   },
   "seq": 10,
   "name": "SMT top",
   "group_id": "wcg_00000000000000000000000000000001",
   "qty": 50,
   "split": {
    "index": 0,
    "count": 2
   },
   "line_id": "lin_00000000000000000000000000000001",
   "start": "2026-11-02T05:50:00Z",
   "end": "2026-11-02T10:10:00Z",
   "setup_minutes": 60,
   "run_minutes": 200,
   "pieces": [
    {
     "start": "2026-11-02T05:50:00Z",
     "end": "2026-11-02T10:10:00Z"
    }
   ],
   "crew": [
    {
     "operator_id": "emp_00000000000000000000000000000002",
     "start": "2026-11-02T05:50:00Z",
     "end": "2026-11-02T10:10:00Z"
    }
   ],
   "tools": [],
   "release": {
    "material_at": "2026-11-02T04:30:00Z",
    "predecessor_at": null,
    "refs": [
     {
      "type": "po_schedule",
      "id": "psc_00000000000000000000000000000001",
      "label": "PO-KV-0101/10/2",
      "at": "2026-11-02T04:30:00Z"
     }
    ]
   },
   "locked": false,
   "frozen": false,
   "status": "scheduled",
   "reason": {
    "code": "line_busy",
    "refs": [
     {
      "type": "operation",
      "id": "1",
      "label": "op 1",
      "at": null
     }
    ],
    "text": "SMT-1 busy with WO-000143 op 10 until 11:50."
   },
   "due": "2026-11-05T03:30:00Z",
   "late_minutes": 0,
   "family": "PCBA-STD",
   "setup_from_family": "PCBA-HDI",
   "item": {
    "id": "itm_00000000000000000000000000000002",
    "part_number": "KV-PCB-FLT",
    "revision": "A",
    "description": "Filter board",
    "uom": "EA",
    "make_buy": "make",
    "active": true
   },
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1"
   },
   "group": {
    "id": "wcg_00000000000000000000000000000001",
    "code": "SMT"
   },
   "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001/gantt?op=3"
  },
  {
   "op_no": 4,
   "order": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "number": "P-12",
    "planned_no": 12,
    "item_id": "itm_00000000000000000000000000000002"
   },
   "seq": 10,
   "name": "SMT top",
   "group_id": "wcg_00000000000000000000000000000001",
   "qty": 50,
   "split": {
    "index": 1,
    "count": 2
   },
   "line_id": "lin_00000000000000000000000000000002",
   "start": "2026-11-02T04:30:00Z",
   "end": "2026-11-02T08:50:00Z",
   "setup_minutes": 60,
   "run_minutes": 200,
   "pieces": [
    {
     "start": "2026-11-02T04:30:00Z",
     "end": "2026-11-02T08:50:00Z"
    }
   ],
   "crew": [],
   "tools": [],
   "release": {
    "material_at": "2026-11-02T04:30:00Z",
    "predecessor_at": null,
    "refs": []
   },
   "locked": false,
   "frozen": false,
   "status": "scheduled",
   "reason": {
    "code": "material",
    "refs": [
     {
      "type": "po_schedule",
      "id": "psc_00000000000000000000000000000001",
      "label": "PO-KV-0101/10/2",
      "at": "2026-11-02T04:30:00Z"
     }
    ],
    "text": "Material: KV-IC-FPGA-V1 from PO-KV-0101/10/2 available 10:00."
   },
   "due": "2026-11-05T03:30:00Z",
   "late_minutes": 0,
   "family": "PCBA-STD",
   "setup_from_family": null,
   "item": {
    "id": "itm_00000000000000000000000000000002",
    "part_number": "KV-PCB-FLT",
    "revision": "A",
    "description": "Filter board",
    "uom": "EA",
    "make_buy": "make",
    "active": true
   },
   "line": {
    "id": "lin_00000000000000000000000000000002",
    "code": "SMT-2"
   },
   "group": {
    "id": "wcg_00000000000000000000000000000001",
    "code": "SMT"
   },
   "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001/gantt?op=4"
  },
  {
   "op_no": 5,
   "order": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "number": "P-12",
    "planned_no": 12,
    "item_id": "itm_00000000000000000000000000000002"
   },
   "seq": 20,
   "name": "Burn-in",
   "group_id": "wcg_00000000000000000000000000000002",
   "qty": 100,
   "split": {
    "index": 0,
    "count": 1
   },
   "line_id": null,
   "start": null,
   "end": null,
   "setup_minutes": 0,
   "run_minutes": 0,
   "pieces": [],
   "crew": [],
   "tools": [],
   "release": {
    "material_at": null,
    "predecessor_at": null,
    "refs": []
   },
   "locked": false,
   "frozen": false,
   "status": "unscheduled",
   "reason": {
    "code": "beyond_horizon",
    "refs": [],
    "text": "Cannot start before the horizon end (14 Dec); MRP date 18 Dec."
   },
   "due": "2026-11-05T03:30:00Z",
   "late_minutes": 0,
   "family": "PCBA-STD",
   "setup_from_family": null,
   "item": {
    "id": "itm_00000000000000000000000000000002",
    "part_number": "KV-PCB-FLT",
    "revision": "A",
    "description": "Filter board",
    "uom": "EA",
    "make_buy": "make",
    "active": true
   },
   "line": null,
   "group": {
    "id": "wcg_00000000000000000000000000000002",
    "code": "BURNIN"
   },
   "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001/gantt?op=5"
  }
 ],
 "total": 5,
 "limit": 50,
 "offset": 0
};

export const exampleOpDetail: OpDetail = {
 "op": {
  "op_no": 3,
  "order": {
   "type": "planned",
   "id": "mpo_00000000000000000000000000000001",
   "number": "P-12",
   "planned_no": 12,
   "item_id": "itm_00000000000000000000000000000002"
  },
  "seq": 10,
  "name": "SMT top",
  "group_id": "wcg_00000000000000000000000000000001",
  "qty": 50,
  "split": {
   "index": 0,
   "count": 2
  },
  "line_id": "lin_00000000000000000000000000000001",
  "start": "2026-11-02T05:50:00Z",
  "end": "2026-11-02T10:10:00Z",
  "setup_minutes": 60,
  "run_minutes": 200,
  "pieces": [
   {
    "start": "2026-11-02T05:50:00Z",
    "end": "2026-11-02T10:10:00Z"
   }
  ],
  "crew": [
   {
    "operator_id": "emp_00000000000000000000000000000002",
    "start": "2026-11-02T05:50:00Z",
    "end": "2026-11-02T10:10:00Z"
   }
  ],
  "tools": [],
  "release": {
   "material_at": "2026-11-02T04:30:00Z",
   "predecessor_at": null,
   "refs": [
    {
     "type": "po_schedule",
     "id": "psc_00000000000000000000000000000001",
     "label": "PO-KV-0101/10/2",
     "at": "2026-11-02T04:30:00Z"
    }
   ]
  },
  "locked": false,
  "frozen": false,
  "status": "scheduled",
  "reason": {
   "code": "line_busy",
   "refs": [
    {
     "type": "operation",
     "id": "1",
     "label": "op 1",
     "at": null
    }
   ],
   "text": "SMT-1 busy with WO-000143 op 10 until 11:50."
  },
  "due": "2026-11-05T03:30:00Z",
  "late_minutes": 0,
  "family": "PCBA-STD",
  "setup_from_family": "PCBA-HDI",
  "item": {
   "id": "itm_00000000000000000000000000000002",
   "part_number": "KV-PCB-FLT",
   "revision": "A",
   "description": "Filter board",
   "uom": "EA",
   "make_buy": "make",
   "active": true
  },
  "line": {
   "id": "lin_00000000000000000000000000000001",
   "code": "SMT-1"
  },
  "group": {
   "id": "wcg_00000000000000000000000000000001",
   "code": "SMT"
  },
  "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001/gantt?op=3"
 },
 "reason": {
  "code": "line_busy",
  "refs": [
   {
    "type": "operation",
    "id": "1",
    "label": "op 1",
    "at": null
   }
  ],
  "text": "SMT-1 busy with WO-000143 op 10 until 11:50."
 },
 "release": {
  "material_at": "2026-11-02T04:30:00Z",
  "predecessor_at": null,
  "refs": [
   {
    "type": "po_schedule",
    "id": "psc_00000000000000000000000000000001",
    "label": "PO-KV-0101/10/2",
    "at": "2026-11-02T04:30:00Z"
   }
  ]
 },
 "neighbours": {
  "before": {
   "op_no": 1,
   "order": {
    "type": "wo",
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143",
    "planned_no": null,
    "item_id": "itm_00000000000000000000000000000001"
   },
   "seq": 10,
   "name": "SMT top",
   "group_id": "wcg_00000000000000000000000000000001",
   "qty": 10,
   "split": {
    "index": 0,
    "count": 1
   },
   "line_id": "lin_00000000000000000000000000000001",
   "start": "2026-11-02T03:30:00Z",
   "end": "2026-11-02T05:50:00Z",
   "setup_minutes": 45,
   "run_minutes": 95,
   "pieces": [
    {
     "start": "2026-11-02T03:30:00Z",
     "end": "2026-11-02T05:50:00Z"
    }
   ],
   "crew": [
    {
     "operator_id": "emp_00000000000000000000000000000001",
     "start": "2026-11-02T03:30:00Z",
     "end": "2026-11-02T05:50:00Z"
    }
   ],
   "tools": [
    {
     "tool_pool_id": "tlp_00000000000000000000000000000001",
     "qty": 1
    }
   ],
   "release": {
    "material_at": "2026-11-02T03:30:00Z",
    "predecessor_at": null,
    "refs": [
     {
      "type": "stock",
      "id": "bal_00000000000000000000000000000001",
      "label": "Stock STORES",
      "at": "2026-11-02T03:30:00Z"
     }
    ]
   },
   "locked": false,
   "frozen": false,
   "status": "scheduled",
   "reason": {
    "code": "as_of",
    "refs": [],
    "text": "Starts at the planning start (as of)."
   },
   "due": "2026-11-07T03:30:00Z",
   "late_minutes": 0,
   "family": "PCBA-HDI",
   "setup_from_family": null,
   "item": {
    "id": "itm_00000000000000000000000000000001",
    "part_number": "KV-TPU-1000",
    "revision": "A",
    "description": "Telematics processing unit",
    "uom": "EA",
    "make_buy": "make",
    "active": true
   },
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1"
   },
   "group": {
    "id": "wcg_00000000000000000000000000000001",
    "code": "SMT"
   },
   "link": "/mfg/schedule/runs/apr_00000000000000000000000000000001/gantt?op=1"
  },
  "after": null
 }
};

export const exampleOrderPage: Page<OrderResultRow> = {
 "items": [
  {
   "order": {
    "type": "wo",
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143",
    "planned_no": null,
    "item_id": "itm_00000000000000000000000000000001"
   },
   "part_number": "KV-TPU-1000",
   "qty": 10,
   "due": "2026-11-07T03:30:00Z",
   "start": "2026-11-02T03:30:00Z",
   "end": "2026-11-03T09:20:00Z",
   "late_minutes": 0,
   "weight": 256,
   "priority": 1,
   "rank_label": "P1 DO-KV-001/10",
   "demand_refs": [
    {
     "demand_line_id": "dml_00000000000000000000000000000001",
     "order_number": "DO-KV-001",
     "line_no": 10
    }
   ],
   "late_chain": [],
   "late_text": "",
   "unscheduled_ops": 0
  },
  {
   "order": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "number": "P-12",
    "planned_no": 12,
    "item_id": "itm_00000000000000000000000000000002"
   },
   "part_number": "KV-PCB-FLT",
   "qty": 100,
   "due": "2026-11-05T03:30:00Z",
   "start": "2026-11-02T04:30:00Z",
   "end": null,
   "late_minutes": 480,
   "weight": 16,
   "priority": 5,
   "rank_label": "P5 DO-KV-004/10",
   "demand_refs": [
    {
     "demand_line_id": "dml_00000000000000000000000000000002",
     "order_number": "DO-KV-004",
     "line_no": 10
    }
   ],
   "late_chain": [
    {
     "kind": "capacity",
     "op_no": 5,
     "text": "Burn-in BI-1/BI-2 full 12-15 Dec with WO-000139 (P1)",
     "refs": [
      {
       "type": "group",
       "id": "wcg_00000000000000000000000000000002",
       "label": "BURNIN",
       "at": null
      }
     ]
    },
    {
     "kind": "material",
     "op_no": 4,
     "text": "SMT-2 waits for KV-IC-FPGA-V1 (PO-KV-0101/10/2, 2 Nov 10:00)",
     "refs": [
      {
       "type": "po_schedule",
       "id": "psc_00000000000000000000000000000001",
       "label": "PO-KV-0101/10/2",
       "at": null
      }
     ]
    }
   ],
   "late_text": "P-12 (KV-PCB-FLT x100) ends after its due date, 8 h late: burn-in BI-1/BI-2 full 12-15 Dec with WO-000139 (P1); earlier: SMT-2 waits for KV-IC-FPGA-V1 (PO-KV-0101/10/2, 2 Nov 10:00)",
   "unscheduled_ops": 1
  }
 ],
 "total": 2,
 "limit": 50,
 "offset": 0
};

export const exampleApsDemand: ApsDemandResponse = {
 "items": [
  {
   "demand_line_id": "dml_00000000000000000000000000000001",
   "order_id": "dmo_00000000000000000000000000000001",
   "order_number": "DO-KV-001",
   "line_no": 10,
   "item_id": "itm_00000000000000000000000000000001",
   "part_number": "KV-TPU-1000",
   "qty": 10,
   "due": "2026-11-07T03:30:00Z",
   "scheduled_end": "2026-11-03T09:20:00Z",
   "late_minutes": 0,
   "priority": 1,
   "program": "KAVACH",
   "orders": [
    {
     "type": "wo",
     "id": "wko_00000000000000000000000000000001",
     "number": "WO-000143",
     "planned_no": null,
     "item_id": "itm_00000000000000000000000000000001"
    }
   ],
   "late_text": ""
  },
  {
   "demand_line_id": "dml_00000000000000000000000000000002",
   "order_id": "dmo_00000000000000000000000000000004",
   "order_number": "DO-KV-004",
   "line_no": 10,
   "item_id": "itm_00000000000000000000000000000002",
   "part_number": "KV-PCB-FLT",
   "qty": 100,
   "due": "2026-11-05T03:30:00Z",
   "scheduled_end": null,
   "late_minutes": 480,
   "priority": 5,
   "program": null,
   "orders": [
    {
     "type": "planned",
     "id": "mpo_00000000000000000000000000000001",
     "number": "P-12",
     "planned_no": 12,
     "item_id": "itm_00000000000000000000000000000002"
    }
   ],
   "late_text": "P-12 is not completely scheduled within the horizon."
  }
 ],
 "counts": {
  "on_time": 1,
  "late": 1
 }
};

export const exampleLoad: LoadResponse = {
 "bucket": "day",
 "items": [
  {
   "group_id": "wcg_00000000000000000000000000000001",
   "line_id": "lin_00000000000000000000000000000001",
   "day": "2026-11-02",
   "scheduled_minutes": 400,
   "required_minutes": 380,
   "base_minutes": 495,
   "optional_minutes": 240,
   "opened_minutes": 0
  },
  {
   "group_id": "wcg_00000000000000000000000000000001",
   "line_id": null,
   "day": "2026-11-02",
   "scheduled_minutes": 660,
   "required_minutes": 640,
   "base_minutes": 990,
   "optional_minutes": 480,
   "opened_minutes": 0
  }
 ]
};

export const exampleDispatch: DispatchResponse = {
 "line": {
  "id": "lin_00000000000000000000000000000001",
  "code": "SMT-1"
 },
 "date": "2026-11-02",
 "shift": "A",
 "run_id": "apr_00000000000000000000000000000001",
 "items": [
  {
   "op_no": 1,
   "position": 1,
   "start": "2026-11-02T03:30:00Z",
   "end": "2026-11-02T05:50:00Z",
   "order": {
    "type": "wo",
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143",
    "planned_no": null,
    "item_id": "itm_00000000000000000000000000000001"
   },
   "part_number": "KV-TPU-1000",
   "qty": 10,
   "seq": 10,
   "name": "SMT top",
   "setup_minutes": 45,
   "run_minutes": 95,
   "setup_from_family": null,
   "family": "PCBA-HDI",
   "crew": [
    {
     "operator_id": "emp_00000000000000000000000000000001",
     "start": "2026-11-02T03:30:00Z",
     "end": "2026-11-02T05:50:00Z"
    }
   ],
   "tools": [
    {
     "tool_pool_id": "tlp_00000000000000000000000000000001",
     "qty": 1
    }
   ],
   "predecessor_status": "none",
   "material_status": "kitted",
   "done": false,
   "shift_label": "KV-3SHIFT/A"
  }
 ]
};

export const exampleOvertime: OvertimeResponse = {
 "items": [
  {
   "line_id": "lin_00000000000000000000000000000001",
   "assignment_id": "sha_00000000000000000000000000000009",
   "start": "2026-11-02T12:30:00Z",
   "end": "2026-11-02T16:30:00Z",
   "minutes": 240,
   "cost": 1600,
   "status": "suggested",
   "tardiness_saved_minutes": 7680
  }
 ],
 "totals": {
  "opened_minutes": 0,
  "opened_cost": 0,
  "suggested_minutes": 240,
  "suggested_cost": 1600,
  "tardiness_saved_minutes": 7680
 }
};

export const exampleApsExceptions: ApsExceptionPage = {
 "items": [
  {
   "code": "APS_ORDER_LATE",
   "severity": "critical",
   "subject": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "label": "P-12",
    "at": null
   },
   "op_no": null,
   "order": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "number": "P-12",
    "planned_no": 12,
    "item_id": "itm_00000000000000000000000000000002"
   },
   "message": "P-12 (KV-PCB-FLT x100) is 8 h late.",
   "refs": [],
   "id": "aex_00000000000000000000000000000001",
   "ex_no": 1
  },
  {
   "code": "APS_BEYOND_HORIZON",
   "severity": "info",
   "subject": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "label": "P-12",
    "at": null
   },
   "op_no": 5,
   "order": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "number": "P-12",
    "planned_no": 12,
    "item_id": "itm_00000000000000000000000000000002"
   },
   "message": "1 operation starts after the horizon end.",
   "refs": [],
   "id": "aex_00000000000000000000000000000002",
   "ex_no": 2
  },
  {
   "code": "APS_OVERTIME_SUGGESTED",
   "severity": "info",
   "subject": {
    "type": "line",
    "id": "lin_00000000000000000000000000000001",
    "label": "SMT-1",
    "at": null
   },
   "op_no": null,
   "order": null,
   "message": "Opening SMT-1 EVE on Mon 2 Nov (4 h, 1,600) saves 7,680 weighted late minutes.",
   "refs": [],
   "id": "aex_00000000000000000000000000000003",
   "ex_no": 3
  }
 ],
 "total": 3,
 "limit": 50,
 "offset": 0,
 "counts": {
  "by_severity": {
   "critical": 1,
   "warning": 0,
   "info": 2
  },
  "by_code": {
   "APS_ORDER_LATE": 1,
   "APS_BEYOND_HORIZON": 1,
   "APS_OVERTIME_SUGGESTED": 1
  }
 }
};

export const exampleBottlenecks: { items: BottleneckRow[] } = {
 "items": [
  {
   "group_id": "wcg_00000000000000000000000000000001",
   "rank": 1,
   "utilisation": 0.81,
   "late_chains": 1,
   "suggestion": "Adding the EVE shift on SMT-1 saves 7,680 weighted late minutes.",
   "saved_minutes": 7680,
   "group": {
    "id": "wcg_00000000000000000000000000000001",
    "code": "SMT"
   }
  },
  {
   "group_id": "wcg_00000000000000000000000000000002",
   "rank": 2,
   "utilisation": 0.64,
   "late_chains": 1,
   "suggestion": null,
   "saved_minutes": null,
   "group": {
    "id": "wcg_00000000000000000000000000000002",
    "code": "BURNIN"
   }
  }
 ]
};

export const exampleApsCompare: ApsCompareResponse = {
 "a": {
  "id": "apr_00000000000000000000000000000001",
  "run_no": 4,
  "label": "Weekly",
  "policy": "suggest"
 },
 "b": {
  "id": "apr_00000000000000000000000000000002",
  "run_no": 5,
  "label": "Weekly (Allow)",
  "policy": "allow"
 },
 "kpis": [
  {
   "key": "weighted_tardiness",
   "a": 7680,
   "b": 0,
   "delta": -7680
  },
  {
   "key": "late_demand_count",
   "a": 1,
   "b": 0,
   "delta": -1
  },
  {
   "key": "overtime_minutes",
   "a": 0,
   "b": 240,
   "delta": 240
  },
  {
   "key": "overtime_cost",
   "a": 0,
   "b": 1600,
   "delta": 1600
  }
 ],
 "tradeoff": {
  "weighted_tardiness_saved": 7680,
  "late_minutes_saved": 480,
  "late_demand_saved": 1,
  "overtime_hours_added": 4,
  "overtime_cost_added": 1600
 },
 "orders": [
  {
   "order": {
    "type": "planned",
    "id": "mpo_00000000000000000000000000000001",
    "number": "P-12",
    "planned_no": 12,
    "item_id": "itm_00000000000000000000000000000002"
   },
   "end_a": null,
   "end_b": "2026-11-04T22:10:00Z",
   "delta_minutes": null,
   "late_a": 480,
   "late_b": 0
  }
 ],
 "utilisation": [
  {
   "key": "wcg_00000000000000000000000000000001",
   "a": 0.81,
   "b": 0.86,
   "delta": 0.05
  }
 ],
 "truncated": false
};

export const exampleOvertimeAllow: OvertimeResponse = {
 "items": [
  {
   "line_id": "lin_00000000000000000000000000000001",
   "assignment_id": "sha_00000000000000000000000000000009",
   "start": "2026-11-02T12:30:00Z",
   "end": "2026-11-02T16:30:00Z",
   "minutes": 240,
   "cost": 1600,
   "status": "opened",
   "tardiness_saved_minutes": null
  }
 ],
 "totals": {
  "opened_minutes": 240,
  "opened_cost": 1600,
  "suggested_minutes": 0,
  "suggested_cost": 0,
  "tardiness_saved_minutes": 0
 }
};

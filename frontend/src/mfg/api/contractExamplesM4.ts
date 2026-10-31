/**
 * M4 S0 contract examples (docs/M4-DESIGN.md 11): the fixture `backend/superplanner/mfg/floor/fixtures/example_floor.json`
 * verbatim, typed against `typesM4.ts` so the compiler flags any drift. Regenerate with the scratch generator when the
 * fixture changes (16.WP-U).
 */
import type { Page } from "./types";
import type {
  AdherencePage,
  BackflushRetryResult,
  BatchLoad,
  BatchLoadInput,
  Downtime,
  DowntimeInput,
  DowntimeUpdate,
  FloorEventInput,
  FloorEventRecord,
  FloorEventResult,
  FloorOperationDetail,
  FloorQueueResponse,
  FloorSummary,
  KitShortage,
  KpiResponse,
  MfgNotification,
  NotificationPage,
  PlantM4Fields,
  ReplanTrigger,
  ScanResult,
  Simulation,
  SimulationInput,
  TriggerPage,
  UnitSerial,
  UnitSerialDetail,
  WoBriefM4,
  WoOperation,
} from "./typesM4";

export const exampleScanWo: ScanResult = {
 "type": "work_order",
 "id": "wko_00000000000000000000000000000001",
 "label": "WO-000143 KV-PCB-MAIN x 100",
 "link": "/mfg/work-orders/wko_00000000000000000000000000000001",
 "context": {
  "status": "in_progress"
 }
};

export const exampleScanOperation: ScanResult = {
 "type": "operation",
 "id": "wop_00000000000000000000000000000001",
 "label": "WO-000143 op 10 SMT top + bottom",
 "link": "/mfg/floor/operations/wop_00000000000000000000000000000001",
 "context": {
  "wo_id": "wko_00000000000000000000000000000001",
  "seq": 10,
  "status": "running",
  "line_id": "lin_00000000000000000000000000000001"
 }
};

export const exampleScanOperator: ScanResult = {
 "type": "operator",
 "id": "emp_00000000000000000000000000000001",
 "label": "OP-SMT-1 Asha",
 "link": "",
 "context": {
  "code": "OP-SMT-1"
 }
};

export const exampleFloorQueue: FloorQueueResponse = {
 "line": {
  "id": "lin_00000000000000000000000000000001",
  "code": "SMT-1",
  "name": "SMT line 1"
 },
 "date": "2026-11-02",
 "shift": "A",
 "run_id": "apr_00000000000000000000000000000004",
 "down": null,
 "shifts": [
  {
   "label": "3SHIFT/A",
   "start": "2026-11-02T00:00:00+00:00",
   "end": "2026-11-02T08:00:00+00:00",
   "kind": "base"
  }
 ],
 "items": [
  {
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo": {
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143",
    "item": {
     "id": "itm_00000000000000000000000000000001",
     "part_number": "KV-PCB-MAIN",
     "description": "Main PCB"
    },
    "qty": 100.0,
    "due_date": "2026-11-09",
    "priority": 3,
    "row_version": 5
   },
   "seq": 10,
   "name": "SMT top + bottom",
   "status": "running",
   "planned_start": "2026-11-02T01:20:00Z",
   "planned_end": "2026-11-02T05:20:00Z",
   "op_no": 1,
   "qty_planned": 100.0,
   "qty_good": 40.0,
   "kit": "kitted",
   "batch_load_id": null,
   "next_actions": [
    "pause",
    "report",
    "complete"
   ]
  },
  {
   "wo_operation_id": "wop_00000000000000000000000000000004",
   "wo": {
    "id": "wko_00000000000000000000000000000002",
    "number": "WO-000144",
    "item": {
     "id": "itm_00000000000000000000000000000001",
     "part_number": "KV-PCB-MAIN",
     "description": "Main PCB"
    },
    "qty": 50.0,
    "due_date": "2026-11-11",
    "priority": 5,
    "row_version": 2
   },
   "seq": 10,
   "name": "SMT top + bottom",
   "status": "ready",
   "planned_start": "2026-11-02T05:50:00Z",
   "planned_end": "2026-11-02T07:50:00Z",
   "op_no": 3,
   "qty_planned": 50.0,
   "qty_good": 0.0,
   "kit": "short",
   "batch_load_id": null,
   "next_actions": [
    "setup_start",
    "start"
   ]
  }
 ]
};

export const exampleFloorOperation: FloorOperationDetail = {
 "operation": {
  "id": "wop_00000000000000000000000000000001",
  "wo_id": "wko_00000000000000000000000000000001",
  "seq": 10,
  "name": "SMT top + bottom",
  "group": {
   "id": "wcg_00000000000000000000000000000001",
   "code": "SMT",
   "name": "SMT"
  },
  "status": "running",
  "qty_planned": 100.0,
  "qty_good": 40.0,
  "qty_scrap": 2.0,
  "qty_rework_out": 0.0,
  "qty_rework_in": 0.0,
  "qty_input": 100.0,
  "qty_available": 58.0,
  "line": {
   "id": "lin_00000000000000000000000000000001",
   "code": "SMT-1",
   "name": "SMT line 1"
  },
  "setup_minutes_actual": 38.0,
  "run_minutes_actual": 52.0,
  "labour_minutes": 90.0,
  "actual_start": "2026-11-02T01:30:00Z",
  "actual_end": null,
  "started_short": false,
  "source": "release",
  "capture_serial": false,
  "last_event_seq": 1043,
  "setup_minutes": 45.0,
  "run_minutes": 1.2,
  "labor": "attended",
  "done": false,
  "done_at": null,
  "done_by": null,
  "placement": [
   {
    "run_id": "apr_00000000000000000000000000000004",
    "op_no": 1,
    "line": {
     "id": "lin_00000000000000000000000000000001",
     "code": "SMT-1"
    },
    "start": "2026-11-02T01:20:00+00:00",
    "end": "2026-11-02T05:20:00+00:00",
    "split": {
     "index": 0,
     "count": 1
    }
   }
  ],
  "row_version": 4,
  "created_at": "2026-11-01T17:30:00Z",
  "updated_at": "2026-11-02T03:30:00Z"
 },
 "wo": {
  "id": "wko_00000000000000000000000000000001",
  "number": "WO-000143",
  "status": "in_progress",
  "qty": 100.0,
  "qty_completed": 0.0,
  "qty_scrapped": 2.0,
  "row_version": 5,
  "item": {
   "id": "itm_00000000000000000000000000000001",
   "part_number": "KV-PCB-MAIN",
   "description": "Main PCB"
  },
  "due_date": "2026-11-09",
  "priority": 3,
  "released_to_floor_at": "2026-11-01T17:30:00+00:00",
  "receipt_location_id": null
 },
 "instructions": "Load panel program KV-MAIN-R3; check stencil S-17.",
 "components": [
  {
   "component_id": "woc_00000000000000000000000000000001",
   "item": {
    "id": "itm_00000000000000000000000000000003",
    "part_number": "KV-R-10K-0402",
    "description": "Resistor 10k 0402"
   },
   "required_qty": 2900.0,
   "issued_qty": 1160.0,
   "backflush": true,
   "backflush_posted": 1160.0,
   "backflush_pending": 0.0,
   "kit": "kitted",
   "location": {
    "id": "loc_00000000000000000000000000000001",
    "code": "LS-SMT"
   }
  },
  {
   "component_id": "woc_00000000000000000000000000000002",
   "item": {
    "id": "itm_00000000000000000000000000000004",
    "part_number": "KV-IC-FPGA-V1",
    "description": "FPGA"
   },
   "required_qty": 100.0,
   "issued_qty": 100.0,
   "backflush": false,
   "backflush_posted": 0.0,
   "backflush_pending": 0.0,
   "kit": "kitted",
   "location": null
  }
 ],
 "tools": [
  {
   "tool_pool": {
    "id": "tlp_00000000000000000000000000000001",
    "code": "STENCIL-17",
    "name": "Stencil 17"
   },
   "qty": 1
  }
 ],
 "eligible_lines": [
  {
   "id": "lin_00000000000000000000000000000001",
   "code": "SMT-1",
   "name": "SMT line 1"
  },
  {
   "id": "lin_00000000000000000000000000000005",
   "code": "SMT-2",
   "name": "SMT line 2"
  }
 ],
 "expected_input": 100.0,
 "events": [
  {
   "id": "fev_00000000000000000000000000000001",
   "seq": 1040,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "setup_start",
   "event_at": "2026-11-02T01:22:00Z",
   "recorded_at": "2026-11-02T01:22:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": null,
   "qty_scrap": null,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": null,
   "note": "",
   "client_event_id": "tab-smt1-001040",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000002",
   "seq": 1041,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "start",
   "event_at": "2026-11-02T02:00:00Z",
   "recorded_at": "2026-11-02T02:00:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": null,
   "qty_scrap": null,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": null,
   "note": "",
   "client_event_id": "tab-smt1-001041",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000003",
   "seq": 1042,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "report",
   "event_at": "2026-11-02T02:50:00Z",
   "recorded_at": "2026-11-02T02:50:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": 40.0,
   "qty_scrap": 2.0,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": "SOLDER_BRIDGE",
   "note": "",
   "client_event_id": "tab-smt1-001042",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000004",
   "seq": 1043,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "pause",
   "event_at": "2026-11-02T03:00:00Z",
   "recorded_at": "2026-11-02T03:00:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": null,
   "qty_scrap": null,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": "BREAK",
   "note": "",
   "client_event_id": "tab-smt1-001043",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000005",
   "seq": 1044,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "resume",
   "event_at": "2026-11-02T03:30:00Z",
   "recorded_at": "2026-11-02T03:30:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": null,
   "qty_scrap": null,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": null,
   "note": "",
   "client_event_id": "tab-smt1-001044",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  }
 ],
 "allowed_actions": [
  "pause",
  "report",
  "complete"
 ],
 "serials": {
  "capture": false,
  "produced": [],
  "consumable": []
 }
};

export const exampleEventBody: FloorEventInput = {
 "client_event_id": "tab-smt1-001048",
 "wo_operation_id": "wop_00000000000000000000000000000001",
 "event_type": "complete",
 "line_id": "lin_00000000000000000000000000000001",
 "operator_codes": [
  "OP-SMT-1",
  "OP-ICT-1"
 ],
 "qty_good": 55,
 "qty_scrap": 3,
 "reason_code": "TOMBSTONE",
 "note": ""
};

export const exampleSerialEventBody: FloorEventInput = {
 "client_event_id": "tab-fct1-000201",
 "scan": "WO-000150/90",
 "event_type": "complete",
 "qty_good": 3,
 "serials": {
  "produced": [
   "TPU-26-0001",
   "TPU-26-0002",
   "TPU-26-0003"
  ],
  "consumed": [
   {
    "item_id": "itm_00000000000000000000000000000001",
    "serial": "PCB-26-0417"
   }
  ]
 }
};

export const exampleFloorEventResult: FloorEventResult = {
 "event": {
  "id": "fev_00000000000000000000000000000006",
  "seq": 1047,
  "wo_operation_id": "wop_00000000000000000000000000000001",
  "wo_id": "wko_00000000000000000000000000000001",
  "wo_number": "WO-000143",
  "op_seq": 10,
  "event_type": "complete",
  "event_at": "2026-11-02T03:30:00Z",
  "recorded_at": "2026-11-02T03:30:00Z",
  "line": {
   "id": "lin_00000000000000000000000000000001",
   "code": "SMT-1",
   "name": "SMT line 1"
  },
  "operators": [
   {
    "id": "emp_00000000000000000000000000000001",
    "code": "OP-SMT-1",
    "name": "Asha"
   },
   {
    "id": "emp_00000000000000000000000000000002",
    "code": "OP-ICT-1",
    "name": "Ravi"
   }
  ],
  "qty_good": 55.0,
  "qty_scrap": 3.0,
  "qty_rework": null,
  "rework_to_seq": null,
  "reason_code": "TOMBSTONE",
  "note": "",
  "client_event_id": "tab-smt1-001047",
  "batch_load_id": null,
  "serials": null,
  "corrects_event_id": null,
  "corrected": false,
  "forced": null,
  "actor": {
   "id": "usr_00000000000000000000000000000001",
   "code": "",
   "name": "Station SMT"
  },
  "details": {
   "backflush": [
    {
     "component_id": "woc_00000000000000000000000000000001",
     "qty": 116.0
    }
   ]
  }
 },
 "operation": {
  "id": "wop_00000000000000000000000000000001",
  "wo_id": "wko_00000000000000000000000000000001",
  "seq": 10,
  "name": "SMT top + bottom",
  "group": {
   "id": "wcg_00000000000000000000000000000001",
   "code": "SMT",
   "name": "SMT"
  },
  "status": "completed",
  "qty_planned": 100.0,
  "qty_good": 95.0,
  "qty_scrap": 5.0,
  "qty_rework_out": 0.0,
  "qty_rework_in": 0.0,
  "qty_input": 100.0,
  "qty_available": 0.0,
  "line": {
   "id": "lin_00000000000000000000000000000001",
   "code": "SMT-1",
   "name": "SMT line 1"
  },
  "setup_minutes_actual": 38.0,
  "run_minutes_actual": 168.0,
  "labour_minutes": 206.0,
  "actual_start": "2026-11-02T01:30:00Z",
  "actual_end": "2026-11-02T03:30:00Z",
  "started_short": false,
  "source": "release",
  "capture_serial": false,
  "last_event_seq": 1047,
  "setup_minutes": 45.0,
  "run_minutes": 1.2,
  "labor": "attended",
  "done": true,
  "done_at": "2026-11-02T03:30:00Z",
  "done_by": {
   "id": "usr_00000000000000000000000000000001",
   "code": "",
   "name": "Station SMT"
  },
  "placement": [
   {
    "run_id": "apr_00000000000000000000000000000004",
    "op_no": 1,
    "line": {
     "id": "lin_00000000000000000000000000000001",
     "code": "SMT-1"
    },
    "start": "2026-11-02T01:20:00+00:00",
    "end": "2026-11-02T05:20:00+00:00",
    "split": {
     "index": 0,
     "count": 1
    }
   }
  ],
  "row_version": 6,
  "created_at": "2026-11-01T17:30:00Z",
  "updated_at": "2026-11-02T03:30:00Z"
 },
 "operations": [
  {
   "id": "wop_00000000000000000000000000000002",
   "wo_id": "wko_00000000000000000000000000000001",
   "seq": 20,
   "name": "ICT",
   "group": {
    "id": "wcg_00000000000000000000000000000002",
    "code": "ICT",
    "name": "In-circuit test"
   },
   "status": "ready",
   "qty_planned": 100.0,
   "qty_good": 0.0,
   "qty_scrap": 0.0,
   "qty_rework_out": 0.0,
   "qty_rework_in": 0.0,
   "qty_input": 95.0,
   "qty_available": 95.0,
   "line": null,
   "setup_minutes_actual": 0.0,
   "run_minutes_actual": 0.0,
   "labour_minutes": 0.0,
   "actual_start": null,
   "actual_end": null,
   "started_short": false,
   "source": "release",
   "capture_serial": true,
   "last_event_seq": null,
   "setup_minutes": 10.0,
   "run_minutes": 3.0,
   "labor": "attended",
   "done": false,
   "done_at": null,
   "done_by": null,
   "placement": [],
   "row_version": 1,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:30:00Z"
  }
 ],
 "wo": {
  "id": "wko_00000000000000000000000000000001",
  "number": "WO-000143",
  "status": "in_progress",
  "qty": 100.0,
  "qty_completed": 0.0,
  "qty_scrapped": 5.0,
  "row_version": 6,
  "item": {
   "id": "itm_00000000000000000000000000000001",
   "part_number": "KV-PCB-MAIN",
   "description": "Main PCB"
  },
  "due_date": "2026-11-09",
  "priority": 3,
  "released_to_floor_at": "2026-11-01T17:30:00+00:00",
  "receipt_location_id": null
 },
 "postings": [
  {
   "id": "pst_00000000000000000000000000000002",
   "number": "TXN-000911",
   "type": "wo_issue",
   "lines": [
    {
     "item_id": "itm_00000000000000000000000000000003",
     "location_id": "loc_00000000000000000000000000000001",
     "qty": 116.0,
     "lot_code": "R-2611"
    }
   ]
  }
 ],
 "warnings": [],
 "triggers": []
};

export const exampleFloorEventResultLastOp: FloorEventResult = {
 "event": {
  "id": "fev_00000000000000000000000000000006",
  "seq": 1047,
  "wo_operation_id": "wop_00000000000000000000000000000003",
  "wo_id": "wko_00000000000000000000000000000001",
  "wo_number": "WO-000143",
  "op_seq": 30,
  "event_type": "complete",
  "event_at": "2026-11-02T03:30:00Z",
  "recorded_at": "2026-11-02T03:30:00Z",
  "line": {
   "id": "lin_00000000000000000000000000000001",
   "code": "SMT-1",
   "name": "SMT line 1"
  },
  "operators": [
   {
    "id": "emp_00000000000000000000000000000001",
    "code": "OP-SMT-1",
    "name": "Asha"
   },
   {
    "id": "emp_00000000000000000000000000000002",
    "code": "OP-ICT-1",
    "name": "Ravi"
   }
  ],
  "qty_good": 10.0,
  "qty_scrap": 0.0,
  "qty_rework": null,
  "rework_to_seq": null,
  "reason_code": null,
  "note": "",
  "client_event_id": "tab-smt1-001047",
  "batch_load_id": null,
  "serials": null,
  "corrects_event_id": null,
  "corrected": false,
  "forced": null,
  "actor": {
   "id": "usr_00000000000000000000000000000001",
   "code": "",
   "name": "Station SMT"
  },
  "details": {
   "receipt_posting_id": "pst_00000000000000000000000000000001"
  }
 },
 "operation": {
  "id": "wop_00000000000000000000000000000003",
  "wo_id": "wko_00000000000000000000000000000001",
  "seq": 30,
  "name": "Burn-in",
  "group": {
   "id": "wcg_00000000000000000000000000000003",
   "code": "BURNIN",
   "name": "Burn-in"
  },
  "status": "completed",
  "qty_planned": 100.0,
  "qty_good": 10.0,
  "qty_scrap": 0.0,
  "qty_rework_out": 0.0,
  "qty_rework_in": 0.0,
  "qty_input": 10.0,
  "qty_available": 0.0,
  "line": null,
  "setup_minutes_actual": 0.0,
  "run_minutes_actual": 0.0,
  "labour_minutes": 0.0,
  "actual_start": null,
  "actual_end": null,
  "started_short": false,
  "source": "release",
  "capture_serial": false,
  "last_event_seq": null,
  "setup_minutes": 0.0,
  "run_minutes": 720.0,
  "labor": "unattended",
  "done": true,
  "done_at": "2026-11-02T03:30:00Z",
  "done_by": null,
  "placement": [],
  "row_version": 1,
  "created_at": "2026-11-01T17:30:00Z",
  "updated_at": "2026-11-02T03:30:00Z"
 },
 "operations": [],
 "wo": {
  "id": "wko_00000000000000000000000000000001",
  "number": "WO-000143",
  "status": "completed",
  "qty": 10.0,
  "qty_completed": 10.0,
  "qty_scrapped": 2.0,
  "row_version": 5,
  "item": {
   "id": "itm_00000000000000000000000000000001",
   "part_number": "KV-PCB-MAIN",
   "description": "Main PCB"
  },
  "due_date": "2026-11-09",
  "priority": 3,
  "released_to_floor_at": "2026-11-01T17:30:00+00:00",
  "receipt_location_id": null
 },
 "postings": [
  {
   "id": "pst_00000000000000000000000000000001",
   "number": "TXN-000912",
   "type": "wo_receipt",
   "lines": [
    {
     "item_id": "itm_00000000000000000000000000000002",
     "location_id": "loc_00000000000000000000000000000002",
     "qty": 10.0,
     "lot_code": "WO-000150"
    }
   ]
  }
 ],
 "warnings": [
  {
   "code": "FLR_BACKFLUSH_PENDING",
   "message": "1 backflush could not be posted (KV-R-10K-0402: 40 needed, 30 available at LS-SMT).",
   "details": {
    "pending": [
     {
      "component_id": "woc_00000000000000000000000000000001",
      "item_id": "itm_00000000000000000000000000000003",
      "qty": 40.0,
      "available": 30.0,
      "location_id": "loc_00000000000000000000000000000001"
     }
    ]
   }
  }
 ],
 "triggers": []
};

export const exampleEventsPage: Page<FloorEventRecord> = {
 "items": [
  {
   "id": "fev_00000000000000000000000000000001",
   "seq": 1040,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "setup_start",
   "event_at": "2026-11-02T01:22:00Z",
   "recorded_at": "2026-11-02T01:22:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": null,
   "qty_scrap": null,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": null,
   "note": "",
   "client_event_id": "tab-smt1-001040",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000002",
   "seq": 1041,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "start",
   "event_at": "2026-11-02T02:00:00Z",
   "recorded_at": "2026-11-02T02:00:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": null,
   "qty_scrap": null,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": null,
   "note": "",
   "client_event_id": "tab-smt1-001041",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000003",
   "seq": 1042,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "report",
   "event_at": "2026-11-02T02:50:00Z",
   "recorded_at": "2026-11-02T02:50:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": 40.0,
   "qty_scrap": 2.0,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": "SOLDER_BRIDGE",
   "note": "",
   "client_event_id": "tab-smt1-001042",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000004",
   "seq": 1043,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "pause",
   "event_at": "2026-11-02T03:00:00Z",
   "recorded_at": "2026-11-02T03:00:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": null,
   "qty_scrap": null,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": "BREAK",
   "note": "",
   "client_event_id": "tab-smt1-001043",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000005",
   "seq": 1044,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "resume",
   "event_at": "2026-11-02T03:30:00Z",
   "recorded_at": "2026-11-02T03:30:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    }
   ],
   "qty_good": null,
   "qty_scrap": null,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": null,
   "note": "",
   "client_event_id": "tab-smt1-001044",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {}
  },
  {
   "id": "fev_00000000000000000000000000000006",
   "seq": 1047,
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "wo_number": "WO-000143",
   "op_seq": 10,
   "event_type": "complete",
   "event_at": "2026-11-02T03:30:00Z",
   "recorded_at": "2026-11-02T03:30:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "operators": [
    {
     "id": "emp_00000000000000000000000000000001",
     "code": "OP-SMT-1",
     "name": "Asha"
    },
    {
     "id": "emp_00000000000000000000000000000002",
     "code": "OP-ICT-1",
     "name": "Ravi"
    }
   ],
   "qty_good": 55.0,
   "qty_scrap": 3.0,
   "qty_rework": null,
   "rework_to_seq": null,
   "reason_code": "TOMBSTONE",
   "note": "",
   "client_event_id": "tab-smt1-001047",
   "batch_load_id": null,
   "serials": null,
   "corrects_event_id": null,
   "corrected": false,
   "forced": null,
   "actor": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "details": {
    "backflush": [
     {
      "component_id": "woc_00000000000000000000000000000001",
      "qty": 116.0
     }
    ]
   }
  }
 ],
 "total": 6,
 "limit": 50,
 "offset": 0
};

export const exampleBackflushRetry: BackflushRetryResult = {
 "results": [
  {
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo": {
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143"
   },
   "component_id": "woc_00000000000000000000000000000001",
   "item_id": "itm_00000000000000000000000000000003",
   "part_number": "KV-R-10K-0402",
   "qty": 40.0,
   "status": "posted",
   "posting_id": "pst_00000000000000000000000000000003"
  }
 ],
 "posted": 1,
 "pending": 0
};

export const exampleWoOperations: { wo: Partial<WoBriefM4> & { id: string; number: string }; items: WoOperation[] } = {
 "wo": {
  "id": "wko_00000000000000000000000000000001",
  "number": "WO-000143",
  "row_version": 5,
  "status": "in_progress",
  "released_to_floor_at": "2026-11-01T17:30:00+00:00"
 },
 "items": [
  {
   "id": "wop_00000000000000000000000000000001",
   "wo_id": "wko_00000000000000000000000000000001",
   "seq": 10,
   "name": "SMT top + bottom",
   "group": {
    "id": "wcg_00000000000000000000000000000001",
    "code": "SMT",
    "name": "SMT"
   },
   "status": "running",
   "qty_planned": 100.0,
   "qty_good": 40.0,
   "qty_scrap": 2.0,
   "qty_rework_out": 0.0,
   "qty_rework_in": 0.0,
   "qty_input": 100.0,
   "qty_available": 58.0,
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "setup_minutes_actual": 38.0,
   "run_minutes_actual": 52.0,
   "labour_minutes": 90.0,
   "actual_start": "2026-11-02T01:30:00Z",
   "actual_end": null,
   "started_short": false,
   "source": "release",
   "capture_serial": false,
   "last_event_seq": 1043,
   "setup_minutes": 45.0,
   "run_minutes": 1.2,
   "labor": "attended",
   "done": false,
   "done_at": null,
   "done_by": null,
   "placement": [
    {
     "run_id": "apr_00000000000000000000000000000004",
     "op_no": 1,
     "line": {
      "id": "lin_00000000000000000000000000000001",
      "code": "SMT-1"
     },
     "start": "2026-11-02T01:20:00+00:00",
     "end": "2026-11-02T05:20:00+00:00",
     "split": {
      "index": 0,
      "count": 1
     }
    }
   ],
   "row_version": 4,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:30:00Z"
  },
  {
   "id": "wop_00000000000000000000000000000002",
   "wo_id": "wko_00000000000000000000000000000001",
   "seq": 20,
   "name": "ICT",
   "group": {
    "id": "wcg_00000000000000000000000000000002",
    "code": "ICT",
    "name": "In-circuit test"
   },
   "status": "pending",
   "qty_planned": 100.0,
   "qty_good": 0.0,
   "qty_scrap": 0.0,
   "qty_rework_out": 0.0,
   "qty_rework_in": 0.0,
   "qty_input": 40.0,
   "qty_available": 40.0,
   "line": null,
   "setup_minutes_actual": 0.0,
   "run_minutes_actual": 0.0,
   "labour_minutes": 0.0,
   "actual_start": null,
   "actual_end": null,
   "started_short": false,
   "source": "release",
   "capture_serial": true,
   "last_event_seq": null,
   "setup_minutes": 10.0,
   "run_minutes": 3.0,
   "labor": "attended",
   "done": false,
   "done_at": null,
   "done_by": null,
   "placement": [],
   "row_version": 1,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:30:00Z"
  },
  {
   "id": "wop_00000000000000000000000000000003",
   "wo_id": "wko_00000000000000000000000000000001",
   "seq": 30,
   "name": "Burn-in",
   "group": {
    "id": "wcg_00000000000000000000000000000003",
    "code": "BURNIN",
    "name": "Burn-in"
   },
   "status": "pending",
   "qty_planned": 100.0,
   "qty_good": 0.0,
   "qty_scrap": 0.0,
   "qty_rework_out": 0.0,
   "qty_rework_in": 0.0,
   "qty_input": 0.0,
   "qty_available": 0.0,
   "line": null,
   "setup_minutes_actual": 0.0,
   "run_minutes_actual": 0.0,
   "labour_minutes": 0.0,
   "actual_start": null,
   "actual_end": null,
   "started_short": false,
   "source": "release",
   "capture_serial": false,
   "last_event_seq": null,
   "setup_minutes": 0.0,
   "run_minutes": 720.0,
   "labor": "unattended",
   "done": false,
   "done_at": null,
   "done_by": null,
   "placement": [],
   "row_version": 1,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:30:00Z"
  }
 ]
};

export const exampleDowntimeBody: DowntimeInput = {
 "line_id": "lin_00000000000000000000000000000001",
 "kind": "breakdown",
 "expected_end_at": "2026-11-02T07:35:00+00:00",
 "reason": "Reflow oven fan"
};

export const exampleDowntimeCloseBody: DowntimeUpdate = {
 "close": true
};

export const exampleDowntime: Downtime = {
 "id": "dtm_00000000000000000000000000000001",
 "row_version": 1,
 "created_at": "2026-11-01T17:30:00Z",
 "updated_at": "2026-11-02T03:35:00Z",
 "line": {
  "id": "lin_00000000000000000000000000000001",
  "code": "SMT-1",
  "name": "SMT line 1"
 },
 "kind": "breakdown",
 "planned": false,
 "start_at": "2026-11-02T03:35:00Z",
 "end_at": null,
 "expected_end_at": "2026-11-02T07:35:00Z",
 "open": true,
 "minutes": null,
 "reason": "Reflow oven fan",
 "note": "",
 "reported_by": {
  "id": "usr_00000000000000000000000000000001",
  "code": "",
  "name": "Station SMT"
 },
 "closed_by": null,
 "triggers": [
  {
   "id": "rpt_00000000000000000000000000000001",
   "kind": "line_down",
   "severity": "critical",
   "ref_type": "downtime",
   "ref_id": "dtm_00000000000000000000000000000001",
   "detected_at": "2026-11-02T03:35:00Z",
   "dedupe_key": "line_down:dtm_00000000000000000000000000000001",
   "details": {
    "line_id": "lin_00000000000000000000000000000001",
    "line_code": "SMT-1",
    "ops_affected": 3,
    "first_op_start": "2026-11-02T03:50:00+00:00"
   },
   "status": "open",
   "aps_run_id": null,
   "handled_by": null,
   "handled_at": null,
   "message": "SMT-1 is down (breakdown) with 3 published operations in the next 24 h."
  }
 ]
};

export const exampleDowntimeClosed: Downtime = {
 "id": "dtm_00000000000000000000000000000001",
 "row_version": 2,
 "created_at": "2026-11-01T17:30:00Z",
 "updated_at": "2026-11-02T08:35:00+00:00",
 "line": {
  "id": "lin_00000000000000000000000000000001",
  "code": "SMT-1",
  "name": "SMT line 1"
 },
 "kind": "breakdown",
 "planned": false,
 "start_at": "2026-11-02T03:35:00Z",
 "end_at": "2026-11-02T08:35:00+00:00",
 "expected_end_at": "2026-11-02T07:35:00Z",
 "open": false,
 "minutes": 300.0,
 "reason": "Reflow oven fan",
 "note": "",
 "reported_by": {
  "id": "usr_00000000000000000000000000000001",
  "code": "",
  "name": "Station SMT"
 },
 "closed_by": {
  "id": "usr_00000000000000000000000000000001",
  "code": "",
  "name": "Station SMT"
 },
 "triggers": []
};

export const exampleDowntimePage: Page<Downtime> = {
 "items": [
  {
   "id": "dtm_00000000000000000000000000000001",
   "row_version": 1,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:35:00Z",
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "kind": "breakdown",
   "planned": false,
   "start_at": "2026-11-02T03:35:00Z",
   "end_at": null,
   "expected_end_at": "2026-11-02T07:35:00Z",
   "open": true,
   "minutes": null,
   "reason": "Reflow oven fan",
   "note": "",
   "reported_by": {
    "id": "usr_00000000000000000000000000000001",
    "code": "",
    "name": "Station SMT"
   },
   "closed_by": null,
   "triggers": [
    {
     "id": "rpt_00000000000000000000000000000001",
     "kind": "line_down",
     "severity": "critical",
     "ref_type": "downtime",
     "ref_id": "dtm_00000000000000000000000000000001",
     "detected_at": "2026-11-02T03:35:00Z",
     "dedupe_key": "line_down:dtm_00000000000000000000000000000001",
     "details": {
      "line_id": "lin_00000000000000000000000000000001",
      "line_code": "SMT-1",
      "ops_affected": 3,
      "first_op_start": "2026-11-02T03:50:00+00:00"
     },
     "status": "open",
     "aps_run_id": null,
     "handled_by": null,
     "handled_at": null,
     "message": "SMT-1 is down (breakdown) with 3 published operations in the next 24 h."
    }
   ]
  }
 ],
 "total": 1,
 "limit": 50,
 "offset": 0
};

export const exampleBatchLoadBody: BatchLoadInput = {
 "line_id": "lin_00000000000000000000000000000003",
 "members": [
  {
   "wo_operation_id": "wop_00000000000000000000000000000003",
   "qty": 5
  },
  {
   "wo_operation_id": "wop_00000000000000000000000000000009",
   "qty": 3
  }
 ],
 "aps_run_id": "apr_00000000000000000000000000000004"
};

export const exampleBatchLoad: BatchLoad = {
 "id": "bld_00000000000000000000000000000001",
 "row_version": 1,
 "created_at": "2026-11-01T17:30:00Z",
 "updated_at": "2026-11-02T03:40:00Z",
 "load_no": "BL:00000001",
 "line": {
  "id": "lin_00000000000000000000000000000003",
  "code": "BI-1",
  "name": "Burn-in rack 1"
 },
 "status": "open",
 "started_at": null,
 "ended_at": null,
 "aps_run_id": "apr_00000000000000000000000000000004",
 "units": 8.0,
 "members": [
  {
   "wo_operation_id": "wop_00000000000000000000000000000003",
   "wo": {
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143"
   },
   "seq": 30,
   "qty": 5.0
  },
  {
   "wo_operation_id": "wop_00000000000000000000000000000009",
   "wo": {
    "id": "wko_00000000000000000000000000000002",
    "number": "WO-000144"
   },
   "seq": 30,
   "qty": 3.0
  }
 ]
};

export const exampleBatchLoadsPage: Page<BatchLoad> = {
 "items": [
  {
   "id": "bld_00000000000000000000000000000001",
   "row_version": 1,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:40:00Z",
   "load_no": "BL:00000001",
   "line": {
    "id": "lin_00000000000000000000000000000003",
    "code": "BI-1",
    "name": "Burn-in rack 1"
   },
   "status": "open",
   "started_at": null,
   "ended_at": null,
   "aps_run_id": "apr_00000000000000000000000000000004",
   "units": 8.0,
   "members": [
    {
     "wo_operation_id": "wop_00000000000000000000000000000003",
     "wo": {
      "id": "wko_00000000000000000000000000000001",
      "number": "WO-000143"
     },
     "seq": 30,
     "qty": 5.0
    },
    {
     "wo_operation_id": "wop_00000000000000000000000000000009",
     "wo": {
      "id": "wko_00000000000000000000000000000002",
      "number": "WO-000144"
     },
     "seq": 30,
     "qty": 3.0
    }
   ]
  }
 ],
 "total": 1,
 "limit": 50,
 "offset": 0
};

export const exampleSerialsPage: Page<UnitSerial> = {
 "items": [
  {
   "id": "ser_00000000000000000000000000000001",
   "row_version": 1,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:30:00Z",
   "item": {
    "id": "itm_00000000000000000000000000000002",
    "part_number": "KV-TPU-1000",
    "description": "Train protection unit"
   },
   "serial": "TPU-26-0001",
   "wo": {
    "id": "wko_00000000000000000000000000000002",
    "number": "WO-000150"
   },
   "status": "in_stock",
   "captured_at": "2026-11-02T03:30:00Z",
   "captured_op_seq": 90,
   "parent_serial_id": null,
   "consumed_at": null,
   "consumed_wo_id": null
  },
  {
   "id": "ser_00000000000000000000000000000002",
   "row_version": 1,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:30:00Z",
   "item": {
    "id": "itm_00000000000000000000000000000001",
    "part_number": "KV-PCB-MAIN",
    "description": "Main PCB"
   },
   "serial": "PCB-26-0417",
   "wo": {
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143"
   },
   "status": "consumed",
   "captured_at": "2026-11-02T03:30:00Z",
   "captured_op_seq": 20,
   "parent_serial_id": "ser_00000000000000000000000000000001",
   "consumed_at": "2026-11-02T03:00:00Z",
   "consumed_wo_id": "wko_00000000000000000000000000000002"
  }
 ],
 "total": 2,
 "limit": 50,
 "offset": 0
};

export const exampleSerial: UnitSerialDetail = {
 "id": "ser_00000000000000000000000000000001",
 "row_version": 1,
 "created_at": "2026-11-01T17:30:00Z",
 "updated_at": "2026-11-02T03:30:00Z",
 "item": {
  "id": "itm_00000000000000000000000000000002",
  "part_number": "KV-TPU-1000",
  "description": "Train protection unit"
 },
 "serial": "TPU-26-0001",
 "wo": {
  "id": "wko_00000000000000000000000000000002",
  "number": "WO-000150"
 },
 "status": "in_stock",
 "captured_at": "2026-11-02T03:30:00Z",
 "captured_op_seq": 90,
 "parent_serial_id": null,
 "consumed_at": null,
 "consumed_wo_id": null,
 "parent": null,
 "children": [
  {
   "id": "ser_00000000000000000000000000000002",
   "row_version": 1,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:30:00Z",
   "item": {
    "id": "itm_00000000000000000000000000000001",
    "part_number": "KV-PCB-MAIN",
    "description": "Main PCB"
   },
   "serial": "PCB-26-0417",
   "wo": {
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143"
   },
   "status": "consumed",
   "captured_at": "2026-11-02T03:30:00Z",
   "captured_op_seq": 20,
   "parent_serial_id": "ser_00000000000000000000000000000001",
   "consumed_at": "2026-11-02T03:00:00Z",
   "consumed_wo_id": "wko_00000000000000000000000000000002"
  }
 ],
 "consumed_by_wo": null
};

export const exampleTriggersPage: TriggerPage = {
 "items": [
  {
   "id": "rpt_00000000000000000000000000000001",
   "kind": "line_down",
   "severity": "critical",
   "ref_type": "downtime",
   "ref_id": "dtm_00000000000000000000000000000001",
   "detected_at": "2026-11-02T03:35:00Z",
   "dedupe_key": "line_down:dtm_00000000000000000000000000000001",
   "details": {
    "line_id": "lin_00000000000000000000000000000001",
    "line_code": "SMT-1",
    "ops_affected": 3,
    "first_op_start": "2026-11-02T03:50:00+00:00"
   },
   "status": "open",
   "aps_run_id": null,
   "handled_by": null,
   "handled_at": null,
   "message": "SMT-1 is down (breakdown) with 3 published operations in the next 24 h."
  },
  {
   "id": "rpt_00000000000000000000000000000002",
   "kind": "overrun",
   "severity": "warning",
   "ref_type": "wo_operation",
   "ref_id": "wop_00000000000000000000000000000001",
   "detected_at": "2026-11-02T02:50:00Z",
   "dedupe_key": "overrun:wop_00000000000000000000000000000001",
   "details": {
    "planned_end": "2026-11-02T05:20:00+00:00",
    "projected_end": "2026-11-02T06:40:00+00:00",
    "tolerance_minutes": 48
   },
   "status": "attached",
   "aps_run_id": "apr_00000000000000000000000000000009",
   "handled_by": null,
   "handled_at": null,
   "message": "WO-000143 op 10 is projected to end 80 min after its planned end."
  }
 ],
 "total": 2,
 "limit": 50,
 "offset": 0,
 "counts": {
  "open": 1,
  "attached": 1
 }
};

export const exampleTrigger: ReplanTrigger = {
 "id": "rpt_00000000000000000000000000000001",
 "kind": "line_down",
 "severity": "critical",
 "ref_type": "downtime",
 "ref_id": "dtm_00000000000000000000000000000001",
 "detected_at": "2026-11-02T03:35:00Z",
 "dedupe_key": "line_down:dtm_00000000000000000000000000000001",
 "details": {
  "line_id": "lin_00000000000000000000000000000001",
  "line_code": "SMT-1",
  "ops_affected": 3,
  "first_op_start": "2026-11-02T03:50:00+00:00"
 },
 "status": "handled",
 "aps_run_id": null,
 "handled_by": {
  "id": "usr_00000000000000000000000000000001",
  "code": "",
  "name": "Station SMT"
 },
 "handled_at": "2026-11-02T04:00:00+00:00",
 "message": "SMT-1 is down (breakdown) with 3 published operations in the next 24 h."
};

export const exampleNotificationsPage: NotificationPage = {
 "items": [
  {
   "id": "ntf_00000000000000000000000000000001",
   "kind": "trigger.line_down",
   "severity": "critical",
   "title": "SMT-1 is down",
   "body": "Breakdown (Reflow oven fan) since 09:05; 3 published operations affected in the next 24 h.",
   "link": "/mfg/replan?trigger=rpt_00000000000000000000000000000001",
   "trigger_id": "rpt_00000000000000000000000000000001",
   "created_at": "2026-11-02T03:35:00Z",
   "acknowledged_at": null,
   "acknowledged_by": null
  }
 ],
 "total": 1,
 "limit": 50,
 "offset": 0,
 "unacked": 1
};

export const exampleNotification: MfgNotification = {
 "id": "ntf_00000000000000000000000000000001",
 "kind": "trigger.line_down",
 "severity": "critical",
 "title": "SMT-1 is down",
 "body": "Breakdown (Reflow oven fan) since 09:05; 3 published operations affected in the next 24 h.",
 "link": "/mfg/replan?trigger=rpt_00000000000000000000000000000001",
 "trigger_id": "rpt_00000000000000000000000000000001",
 "created_at": "2026-11-02T03:35:00Z",
 "acknowledged_at": "2026-11-02T03:42:00+00:00",
 "acknowledged_by": {
  "id": "usr_00000000000000000000000000000001",
  "code": "",
  "name": "Station SMT"
 }
};

export const exampleKpis: KpiResponse = {
 "period": {
  "from": "2026-10-19",
  "to": "2026-11-01",
  "bucket": "day",
  "dim": "plant",
  "dim_id": null,
  "time_zone": "Asia/Kolkata"
 },
 "metrics": {
  "otd": {
   "value": 0.8,
   "num": 4,
   "den": 5,
   "unit": "ratio"
  },
  "wo_on_time": {
   "value": 0.833,
   "num": 10,
   "den": 12,
   "unit": "ratio"
  },
  "utilisation": {
   "value": 0.71,
   "num": 6816,
   "den": 9600,
   "unit": "ratio"
  },
  "availability": {
   "value": 0.95,
   "num": 9120,
   "den": 9600,
   "unit": "ratio"
  },
  "performance": {
   "value": 0.91,
   "num": 6202,
   "den": 6816,
   "unit": "ratio"
  },
  "fpy": {
   "value": 0.97,
   "num": 970,
   "den": 1000,
   "unit": "ratio"
  },
  "oee": {
   "value": 0.839,
   "num": 0.839,
   "den": 1,
   "unit": "ratio"
  },
  "scrap_rate": {
   "value": 0.03,
   "num": 30,
   "den": 1000,
   "unit": "ratio"
  },
  "adherence": {
   "value": 0.7,
   "num": 28,
   "den": 40,
   "unit": "ratio"
  },
  "wip": {
   "count": 6,
   "value": 412500.0,
   "avg_age_days": 3.4
  },
  "setup": {
   "actual_minutes": 1260.0,
   "planned_minutes": 1140.0,
   "changeovers": 21
  }
 },
 "series": {
  "otd": [
   {
    "bucket": "2026-10-19",
    "value": 1.0
   },
   {
    "bucket": "2026-10-20",
    "value": null
   }
  ],
  "oee": [
   {
    "bucket": "2026-10-19",
    "value": 0.82
   },
   {
    "bucket": "2026-10-20",
    "value": 0.85
   }
  ]
 },
 "top_scrap": [
  {
   "reason_code": "SOLDER_BRIDGE",
   "qty": 18.0,
   "item_family": "PCBA-HDI",
   "operation": "ICT"
  }
 ],
 "top_downtime": [
  {
   "reason": "Reflow oven fan",
   "kind": "breakdown",
   "minutes": 300.0,
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   }
  }
 ],
 "worst_adherence_lines": [
  {
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "value": 0.55,
   "num": 11,
   "den": 20
  }
 ],
 "by_dim": [
  {
   "dim": "line",
   "ref": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "utilisation": 0.78,
   "availability": 0.88,
   "oee": 0.71
  }
 ]
};

export const exampleAdherence: AdherencePage = {
 "items": [
  {
   "wo_operation_id": "wop_00000000000000000000000000000001",
   "wo": {
    "id": "wko_00000000000000000000000000000001",
    "number": "WO-000143"
   },
   "seq": 10,
   "line": {
    "id": "lin_00000000000000000000000000000001",
    "code": "SMT-1",
    "name": "SMT line 1"
   },
   "planned_start": "2026-11-02T01:20:00Z",
   "planned_end": "2026-11-02T05:20:00Z",
   "actual_start": "2026-11-02T01:30:00Z",
   "actual_end": "2026-11-02T03:30:00Z",
   "start_delta_minutes": 10.0,
   "end_delta_minutes": -110.0,
   "adherent": true
  }
 ],
 "total": 1,
 "limit": 200,
 "offset": 0,
 "run_id": "apr_00000000000000000000000000000004",
 "tolerance_minutes": 120
};

export const exampleSimulationBody: SimulationInput = {
 "base_run_id": "apr_00000000000000000000000000000004",
 "samples": 20,
 "seed": 7
};

export const exampleSimulationQueued: Simulation = {
 "id": "asm_00000000000000000000000000000001",
 "row_version": 1,
 "created_at": "2026-11-01T17:30:00Z",
 "updated_at": "2026-11-02T03:30:00Z",
 "base_run_id": "apr_00000000000000000000000000000004",
 "status": "queued",
 "samples": 20,
 "params": {
  "seed": 7,
  "horizon_days": 42
 },
 "results": null,
 "error": null,
 "job_id": "job_00000000000000000000000000000001",
 "started_at": null,
 "finished_at": null,
 "duration_ms": null
};

export const exampleSimulation: Simulation = {
 "id": "asm_00000000000000000000000000000001",
 "row_version": 3,
 "created_at": "2026-11-01T17:30:00Z",
 "updated_at": "2026-11-02T03:30:00Z",
 "base_run_id": "apr_00000000000000000000000000000004",
 "status": "completed",
 "samples": 20,
 "params": {
  "seed": 7,
  "horizon_days": 42
 },
 "results": {
  "samples_done": 20,
  "seed": 7,
  "demand": [
   {
    "demand_line_id": "dln_00000000000000000000000000000001",
    "order": "DO-KV-003/1",
    "part_number": "KV-TPU-1000",
    "due": "2026-11-08T03:30:00+00:00",
    "p_on_time": 0.35,
    "p50": "2026-11-08T15:30:00+00:00",
    "p90": "2026-11-10T03:30:00+00:00",
    "base_end": "2026-11-07T22:42:00+00:00"
   }
  ],
  "lines": [
   {
    "line": {
     "id": "lin_00000000000000000000000000000001",
     "code": "SMT-1",
     "name": "SMT line 1"
    },
    "expected_lost_hours": 3.1,
    "mtbf_hours": 160.0,
    "breakdowns_sampled": 9
   }
  ],
  "suppliers": [
   {
    "supplier": {
     "id": "sup_00000000000000000000000000000001",
     "code": "SUP-FPGA",
     "name": "FPGA Distribution"
    },
    "late_lines": 7,
    "mean_delay_days": 4.2,
    "history_receipts": 11
   }
  ]
 },
 "error": null,
 "job_id": "job_00000000000000000000000000000001",
 "started_at": "2026-11-02T03:30:00Z",
 "finished_at": "2026-11-02T03:31:30Z",
 "duration_ms": 88400
};

export const exampleSimulationsPage: Page<Simulation> = {
 "items": [
  {
   "id": "asm_00000000000000000000000000000001",
   "row_version": 3,
   "created_at": "2026-11-01T17:30:00Z",
   "updated_at": "2026-11-02T03:30:00Z",
   "base_run_id": "apr_00000000000000000000000000000004",
   "status": "completed",
   "samples": 20,
   "params": {
    "seed": 7,
    "horizon_days": 42
   },
   "results": null,
   "error": null,
   "job_id": "job_00000000000000000000000000000001",
   "started_at": "2026-11-02T03:30:00Z",
   "finished_at": "2026-11-02T03:31:30Z",
   "duration_ms": 88400
  }
 ],
 "total": 1,
 "limit": 50,
 "offset": 0
};

export const exampleSummaryFloor: FloorSummary = {
 "running_ops": 4,
 "lines_down": 1,
 "open_triggers": 2,
 "pending_backflush": 1
};

export const examplePlantM4: PlantM4Fields = {
 "replan_policy": "notify",
 "replan_debounce_minutes": 15,
 "overrun_tolerance_pct": 20.0,
 "adherence_tolerance_minutes": 120,
 "wo_receipt_location_id": "loc_00000000000000000000000000000002",
 "backflush_location_id": "loc_00000000000000000000000000000001"
};

export const exampleKitShortages: { error: { code: string; message: string; details: { shortages: KitShortage[] } } } = {
 "error": {
  "code": "WO_KIT_INCOMPLETE",
  "message": "WO-000143 is short of 1 component for its first operation.",
  "details": {
   "shortages": [
    {
     "component_id": "woc_00000000000000000000000000000002",
     "item_id": "itm_00000000000000000000000000000004",
     "part_number": "KV-IC-FPGA-V1",
     "required": 100.0,
     "available": 60.0,
     "short": 40.0,
     "operation_seq": 10
    }
   ]
  }
 }
};

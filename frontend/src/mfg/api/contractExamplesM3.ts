/**
 * Typed examples of every M3 shape (docs/M3-DESIGN.md 11), Kavach-style values, ids written out in full. Typed
 * against `typesM3.ts` (no casts) so `tsc` fails on drift; also the mock data for UI work before S0.
 */
import type { ItemRef, Page, Ref } from "./types";
import type {
  ApsCompareResponse,
  ApsDemandRow,
  ApsExceptionPage,
  ApsParams,
  ApsRunRecord,
  BottleneckRow,
  DispatchResponse,
  EditRequest,
  GanttResponse,
  LoadRow,
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
const item = (n: number, pn: string, desc: string): ItemRef => ({ id: id("itm", n), part_number: pn, revision: "A", description: desc, uom: "EA", make_buy: "make", active: true });
const cpu = item(5, "KV-PCB-CPU", "CPU board");
const tpu = item(2, "KV-TPU-1000", "Kavach TPU, final assembly");
const smt: Ref = { id: id("grp", 1), code: "SMT", name: "SMT assembly" };
const bi: Ref = { id: id("grp", 6), code: "BURNIN", name: "Burn-in" };
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

export const exampleApsRun: ApsRunRecord = {
  id: id("apr", 7),
  run_no: 7,
  kind: "live",
  status: "completed",
  label: "Week 45",
  note: "",
  pinned: false,
  as_of: TS,
  horizon_end: "2026-12-14T18:30:00Z",
  horizon_days: 42,
  params: exampleApsParams,
  master_fingerprint: "a1b2c3d4",
  row_version: 1,
  started_at: TS,
  finished_at: "2026-11-02T03:30:41Z",
  duration_ms: 41200,
  actor: { id: "usr_planner1", name: "Planner 1" },
  summary: {
    overtime_policy: "suggest",
    operations: 1512,
    scheduled_operations: 1488,
    demand_lines: 8,
    demand_on_time: 6,
    demand_late: 2,
    orders: 104,
    late_orders: 5,
    weighted_tardiness_minutes: 93120,
    max_late_minutes: 4320,
    overtime_minutes: 0,
    overtime_cost: 0,
    suggested_overtime_minutes: 1440,
    suggested_overtime_cost: 9600,
    suggested_tardiness_saved_minutes: 61200,
    utilisation: [
      { group: bi, utilisation_pct: 96.4 },
      { group: smt, utilisation_pct: 88.1 },
    ],
    bottlenecks: [bi, smt],
    setup_minutes: 2340,
    changeovers: 61,
    avg_flow_days: 6.4,
    makespan_minutes: 51840,
    unscheduled: { beyond_horizon: 24 },
    budget_cut: false,
    iterations: 212,
    timings_ms: { load: 820, construct: 3900, improve: 30000, validate: 610, store: 1900 },
    exceptions: { by_severity: { critical: 5, warning: 3, info: 9 }, by_code: { APS_ORDER_LATE: 5, APS_OVERTIME_SUGGESTED: 6, APS_BEYOND_HORIZON: 1 } },
  },
  score: [0, 93120, 0, 412000, 51840, 2340],
  stale: { is_stale: false, master_changed: false, transactions_changed: false },
  error: null,
  progress: { phase: "store", percent: 100, best_score: [0, 93120, 0, 412000, 51840, 2340], updated_at: "2026-11-02T03:30:41Z" },
  parent_run_id: null,
  mrp_run: { id: id("mrr", 12), run_no: 12 },
  is_published: false,
  published_at: null,
  published_by: null,
  validation: { ok: true, counts: {}, violations: [] },
};

export const exampleApsRunRunning: ApsRunRecord = {
  ...exampleApsRun,
  id: id("apr", 8),
  run_no: 8,
  status: "running",
  finished_at: null,
  duration_ms: null,
  summary: null,
  validation: null,
  progress: { phase: "improve", percent: 62, best_score: [0, 98000, 0, 420000, 51840, 2400], updated_at: "2026-11-02T04:00:10Z" },
};

export const exampleApsRunPage: Page<ApsRunRecord> = { items: [exampleApsRunRunning, exampleApsRun], total: 2, limit: 50, offset: 0 };
export const examplePublishedSummary: PublishedScheduleSummary = { id: exampleApsRun.id, run_no: 7, published_at: TS, late_orders: 5, stale: false };

const op = (n: number, line: { id: string; code: string }, start: string, end: string, extra: Partial<ScheduledOpRow> = {}): ScheduledOpRow => ({
  op_no: n,
  order: { type: "wo", id: id("wko", 1), number: "WO-KV-0001", planned_no: null, item_id: cpu.id },
  item: cpu,
  seq: 50,
  name: "SMT top",
  group: { id: smt.id, code: smt.code },
  line,
  qty: 30,
  split: null,
  start,
  end,
  setup_minutes: 45,
  run_minutes: 180,
  pieces: [[start, end]],
  crew: [{ operator_id: id("opr", 1), code: "OP-001", start, end }],
  tools: [{ tool_pool_id: id("tlp", 1), code: "KV-STN-CPU-T", qty: 1 }],
  release: { material_at: TS, predecessor_at: null, refs: [] },
  locked: false,
  frozen: false,
  status: "scheduled",
  reason: { code: "line_busy", text: "SMT-1 busy with WO-KV-0003 until 09:15", refs: [{ type: "op", id: null, label: "op 411" }] },
  due: "2026-11-08T18:30:00Z",
  late_minutes: 0,
  link: `/mfg/schedule/runs/${id("apr", 7)}/gantt?op=${n}`,
  ...extra,
});

export const exampleScheduledOp: ScheduledOpRow = op(412, smt1, "2026-11-02T03:45:00Z", "2026-11-02T07:30:00Z");
export const exampleOpPage: Page<ScheduledOpRow> = { items: [exampleScheduledOp], total: 1, limit: 200, offset: 0 };
export const exampleOpDetail: OpDetail = { ...exampleScheduledOp, neighbours: { prev: op(411, smt1, "2026-11-02T03:30:00Z", "2026-11-02T03:45:00Z"), next: null } };

export const exampleGantt: GanttResponse = {
  rows: [
    { key: `g:${smt.id}`, label: "SMT assembly", kind: "group", parent_key: null },
    { key: `l:${smt1.id}`, label: "SMT-1", kind: "line", parent_key: `g:${smt.id}`, line_id: smt1.id },
    { key: `l:${smt2.id}`, label: "SMT-2", kind: "line", parent_key: `g:${smt.id}`, line_id: smt2.id },
  ],
  bars: [
    {
      op_no: 412,
      row_key: `l:${smt1.id}`,
      start: "2026-11-02T03:45:00Z",
      end: "2026-11-02T07:30:00Z",
      setup_end: "2026-11-02T04:30:00Z",
      pieces: [["2026-11-02T03:45:00Z", "2026-11-02T07:30:00Z"]],
      label: "WO-KV-0001 / 50 SMT top",
      order_number: "WO-KV-0001",
      item_part_number: "KV-PCB-CPU",
      qty: 30,
      late_minutes: 0,
      frozen: true,
      locked: false,
      split: null,
      status_color: "frozen",
    },
    {
      op_no: 520,
      row_key: `l:${smt2.id}`,
      start: "2026-11-02T05:00:00Z",
      end: "2026-11-03T06:00:00Z",
      setup_end: null,
      pieces: [
        ["2026-11-02T05:00:00Z", "2026-11-02T12:30:00Z"],
        ["2026-11-03T03:30:00Z", "2026-11-03T06:00:00Z"],
      ],
      label: "P-81 / 50 SMT top",
      order_number: "P-81",
      item_part_number: "KV-PCB-CPU",
      qty: 12,
      late_minutes: 1440,
      frozen: false,
      locked: false,
      split: { index: 1, count: 2 },
      status_color: "late",
    },
  ],
  bands: [
    { row_key: `l:${smt1.id}`, start: "2026-11-02T03:30:00Z", end: "2026-11-02T12:30:00Z", kind: "base" },
    { row_key: `l:${smt1.id}`, start: "2026-11-02T12:30:00Z", end: "2026-11-02T16:30:00Z", kind: "optional_suggested" },
    { row_key: `l:${smt2.id}`, start: "2026-11-02T03:30:00Z", end: "2026-11-02T12:30:00Z", kind: "base" },
  ],
  truncated: false,
  from: "2026-11-02T00:00:00Z",
  to: "2026-11-09T00:00:00Z",
};

export const exampleOrderRow: OrderResultRow = {
  order_type: "wo",
  order_id: id("wko", 143),
  number: "WO-000143",
  item: tpu,
  qty: 10,
  due_at: "2026-12-14T18:30:00Z",
  start_at: "2026-12-01T03:30:00Z",
  end_at: "2026-12-17T12:30:00Z",
  late_minutes: 4320,
  weight: 256,
  priority: 1,
  demand_refs: [{ demand_line_id: id("dml", 41), label: "DO-KV-004/10", link: `/mfg/demand/${id("dmo", 4)}?line=${id("dml", 41)}` }],
  late_chain: {
    text: "WO-000143 (KV-TPU-1000 x10) ends 18 Dec, 3 days late: burn-in BI-1/BI-2 full 12-15 Dec with WO-000139 (P1).",
    steps: [
      { kind: "capacity", label: "BURNIN full 12-15 Dec", op_no: 900, ref: { type: "group", id: bi.id, label: "BURNIN" } },
      { kind: "material", label: "KV-IC-FPGA-V1 from PO-KV-0101/10/2 (7 Jan)", op_no: 880, ref: { type: "po_schedule", id: id("psc", 2), label: "PO-KV-0101 / 10 / 2", link: null } },
    ],
  },
  link: `/mfg/work-orders/${id("wko", 143)}`,
};

export const exampleOrderPage: Page<OrderResultRow> = { items: [exampleOrderRow], total: 1, limit: 200, offset: 0 };

export const exampleApsDemand: { items: ApsDemandRow[] } = {
  items: [
    {
      demand_line_id: id("dml", 41),
      order: { id: id("dmo", 4), number: "DO-KV-004", program: "KVP-PROTO" },
      line_no: 10,
      item: tpu,
      qty: 2,
      due_date: "2026-11-20",
      scheduled_end: "2026-11-23T12:30:00Z",
      late_minutes: 4320,
      status: "late",
      late_chain: { text: "SMT-1 and BURNIN full; KV-IC-FPGA-V1 arrives 24 Nov." },
      link: `/mfg/demand/${id("dmo", 4)}?line=${id("dml", 41)}`,
    },
  ],
};

export const exampleLoad: { items: LoadRow[] } = {
  items: [
    { group: smt, line: null, day: "2026-11-02", scheduled_minutes: 1980, required_minutes: 2400, base_minutes: 2160, optional_minutes: 720, opened_minutes: 0 },
    { group: bi, line: null, day: "2026-11-02", scheduled_minutes: 2700, required_minutes: 3100, base_minutes: 2880, optional_minutes: 0, opened_minutes: 0 },
  ],
};

export const exampleDispatch: DispatchResponse = {
  line: { id: smt1.id, code: "SMT-1", name: "SMT line 1" },
  date: "2026-11-02",
  shift: "REG",
  shifts: [{ name: "REG", start: "2026-11-02T03:30:00Z", end: "2026-11-02T12:30:00Z" }],
  rows: [
    {
      op_no: 412,
      seq: 50,
      name: "SMT top",
      start: "2026-11-02T03:45:00Z",
      end: "2026-11-02T07:30:00Z",
      order: { type: "wo", id: id("wko", 1), number: "WO-KV-0001" },
      item: cpu,
      qty: 30,
      setup_from_family: "PCBA-STD",
      setup_to_family: "PCBA-HDI",
      setup_minutes: 60,
      crew: [{ operator_id: id("opr", 1), code: "OP-001", name: "Operator 001" }],
      tools: [{ tool_pool_id: id("tlp", 1), code: "KV-STN-CPU-T", qty: 1 }],
      predecessor_status: "done",
      material: { kit_complete: false, short_components: 1 },
      done: false,
      wo_row_version: 3,
      link: `/mfg/work-orders/${id("wko", 1)}`,
    },
  ],
};

export const exampleOvertime: OvertimeResponse = {
  items: [
    {
      id: id("aot", 1),
      line: { id: id("lin", 20), code: "THT-1" },
      group: { id: id("grp", 3), code: "THT", name: "Through-hole" },
      assignment_id: id("sha", 9),
      shift_label: "EVE",
      start: "2026-11-04T12:30:00Z",
      end: "2026-11-04T16:30:00Z",
      minutes: 240,
      cost: 1600,
      status: "suggested",
      tardiness_saved_minutes: 10240,
      reason: "WO-000143 (P1) would finish 4 h earlier",
      orders: [{ id: id("wko", 143), number: "WO-000143" }],
    },
  ],
  totals: { opened_minutes: 0, opened_cost: 0, suggested_minutes: 240, suggested_cost: 1600, suggested_saved_minutes: 10240 },
};

export const exampleBottlenecks: { items: BottleneckRow[] } = {
  items: [{ group: bi, utilisation_pct: 96.4, late_chains: 4, suggestion: { text: "Adding the EVE shift on THT saves 410 weighted late minutes.", saved_minutes: 410, line: null } }],
};

export const exampleApsExceptions: ApsExceptionPage = {
  items: [
    {
      id: id("aex", 1),
      ex_no: 1,
      code: "APS_ORDER_LATE",
      severity: "critical",
      item: tpu,
      subject: { type: "work_order", id: id("wko", 143), label: "WO-000143" },
      demand_line_id: id("dml", 41),
      date: "2026-12-17",
      qty: 10,
      days: 3,
      message: exampleOrderRow.late_chain!.text,
      action: "Open the suggested overtime or re-run with Allow.",
      suggested: null,
      related: [],
      link: `/mfg/work-orders/${id("wko", 143)}`,
    },
  ],
  total: 1,
  limit: 200,
  offset: 0,
  counts: { by_severity: { critical: 1, warning: 0, info: 0 }, by_code: { APS_ORDER_LATE: 1 } },
};

export const exampleApsCompare: ApsCompareResponse = {
  a: exampleApsRun,
  b: { ...exampleApsRun, id: id("apr", 9), run_no: 9, label: "Week 45 with overtime", params: exampleApsRerunAllow },
  kpis: [
    { key: "weighted_tardiness_minutes", label: "Weighted lateness (min)", a: 93120, b: 31920, delta: -61200, better: "lower" },
    { key: "late_orders", label: "Late orders", a: 5, b: 2, delta: -3, better: "lower" },
    { key: "overtime_minutes", label: "Overtime (min)", a: 0, b: 1440, delta: 1440, better: "lower" },
    { key: "overtime_cost", label: "Overtime cost", a: 0, b: 9600, delta: 9600, better: "lower" },
  ],
  orders: [{ order_id: id("wko", 143), number: "WO-000143", due_at: "2026-12-14T18:30:00Z", a_end: "2026-12-17T12:30:00Z", b_end: "2026-12-14T16:00:00Z", a_late_minutes: 4320, b_late_minutes: 0, delta_minutes: -4350 }],
  groups: [{ group: bi, a_util: 96.4, b_util: 91.2 }],
  overtime: { a_minutes: 0, b_minutes: 1440, a_cost: 0, b_cost: 9600 },
  truncated: false,
};

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
    { seq: 50, name: "SMT top", group: smt, done: false, done_at: null, done_by: null, placement: { run_id: exampleApsRun.id, run_no: 7, line: smt1, start: "2026-11-02T03:45:00Z", end: "2026-11-02T07:30:00Z" } },
  ],
};

/**
 * JSON examples of docs/M2-DESIGN.md 12.4 (and one example per further shape of 3 / 7.4 / 10 / 12.3), typed
 * against `typesM2.ts` (no `any`, no casts), so `tsc --noEmit` fails when the mirror drifts from the contract.
 * Elided fields (`...`) are filled with plausible Kavach-style values; ids are written out in full.
 */
import type { ItemRef, Page, Ref } from "./types";
import type {
  BalancePage,
  BalanceRow,
  CompareResponse,
  ConvertPrResponse,
  ConvertRequest,
  ConvertResponse,
  DemandOrderInput,
  DemandOrderRecord,
  DemandOrderSummary,
  DemandProjectionRow,
  ExceptionPage,
  InsufficientStockDetails,
  ItemStock,
  ItemSupplierRecord,
  KittingCheckResponse,
  KittingResponse,
  LocationRecord,
  LotRecord,
  MeResponse,
  MemberRecord,
  MrpExceptionRow,
  MrpItemPlan,
  MrpItemRow,
  MrpParams,
  MrpRunRecord,
  PeggingResponse,
  PlannedOrderPage,
  PlannedOrderRow,
  PostingHeader,
  PostingInput,
  PostingRecord,
  PurchaseDocInput,
  PurchaseDocRecord,
  PurchaseDocSummary,
  ScheduleRow,
  ShortageDashboard,
  SupplierDetail,
  SupplierRecord,
  TransactionRow,
  WorkOrderRecord,
  WorkOrderSummary,
  WorkspaceInfo,
} from "./typesM2";

const id = (prefix: string, n: number) => `${prefix}_${n.toString(16).padStart(32, "0")}`;
const TS = "2026-11-02T05:31:10Z";
const actor = { id: "usr_store1", name: "Store 1" };

const item = (n: number, part_number: string, make_buy: ItemRef["make_buy"] = "buy", uom = "EA", description = ""): ItemRef => ({
  id: id("itm", n),
  part_number,
  revision: "A",
  description,
  uom,
  make_buy,
  active: true,
});

export const exFpga = item(1, "KV-IC-FPGA-V1", "buy", "EA", "FPGA, vital logic");
export const exTpu = item(2, "KV-TPU-1000", "make", "EA", "Kavach TPU, final assembly");
export const exGsm = item(3, "KV-MOD-GSM", "buy", "EA", "GSM radio module");
export const exCon = item(4, "KV-CON-M12-8P", "buy", "EA", "M12 connector, 8 pin");
export const exCpu = item(5, "KV-PCB-CPU", "make", "EA", "CPU board");
const supRef: Ref = { id: id("sup", 1), code: "SUP-SEMI-A", name: "Supplier A (fictional)" };
const goodsIn = { id: id("loc", 1), code: "GOODS-IN", name: "Goods-in inspection", kind: "inspection" as const };
const stores = { id: id("loc", 2), code: "STORES-MAIN", name: "Main stores", kind: "stores" as const };

// ---------------------------------------------------------------- 3.2 / 3.3 master records
export const exampleLocation: LocationRecord = {
  id: stores.id,
  code: stores.code,
  name: stores.name,
  kind: "stores",
  receipt_default: false,
  active: true,
  external_ref: null,
  note: "",
  row_version: 1,
  created_at: TS,
  updated_at: TS,
};

export const exampleSupplier: SupplierRecord = {
  id: supRef.id,
  code: supRef.code,
  name: supRef.name,
  lead_time_days: 70,
  currency: "INR",
  contact_name: "Sales desk",
  email: "sales@example.invalid",
  phone: "",
  address: "",
  active: true,
  external_ref: "V-100231",
  note: "",
  item_count: 14,
  row_version: 1,
  created_at: TS,
  updated_at: TS,
};

export const exampleItemSupplier: ItemSupplierRecord = {
  id: id("isu", 1),
  item_id: exFpga.id,
  supplier_id: supRef.id,
  supplier_part_number: "XC-V1-484",
  lead_time_days: 70,
  min_order_qty: 0,
  order_multiple: 0,
  purchase_unit: null,
  units_per_purchase_unit: 1,
  unit_price: 412.5,
  currency: "INR",
  preferred: true,
  active: true,
  note: "",
  item: exFpga,
  supplier: supRef,
  row_version: 1,
  created_at: TS,
  updated_at: TS,
};

export const exampleSupplierDetail: SupplierDetail = { ...exampleSupplier, items: [exampleItemSupplier] };

export const exampleLot: LotRecord = {
  id: id("lot", 1),
  item: exFpga,
  lot_code: "FV1-2611-A",
  expires_on: "2028-11-01",
  received_on: "2026-11-02",
  supplier_lot: "AX99812",
  hold: false,
  note: "",
  on_hand: 30,
  row_version: 1,
  created_at: TS,
  updated_at: TS,
};

// ---------------------------------------------------------------- 3.4 / 12.4 postings
export const examplePostingInput: PostingInput = {
  type: "po_receipt",
  txn_date: "2026-11-02",
  note: "GRN 7",
  lines: [{ schedule_id: id("psc", 1), location_id: null, qty: 30, lot_code: "FV1-2611-A", expires_on: "2028-11-01", supplier_lot: "AX99812" }],
};

export const exampleTransaction: TransactionRow = {
  id: id("txn", 1),
  seq: 90211,
  posting_id: id("pst", 1),
  posting_number: "TXN-000041",
  line_no: 1,
  txn_type: "po_receipt",
  txn_date: "2026-11-02",
  item: exFpga,
  location: goodsIn,
  lot: { id: exampleLot.id, lot_code: "FV1-2611-A", expires_on: "2028-11-01", hold: false },
  qty: 30,
  balance_after: 30,
  unit_cost: 412.5,
  ref: { type: "po", id: id("pdc", 1), number: "PO-KV-0101", line_no: 10, schedule_seq: 1, label: "PO-KV-0101 / 10 / 1" },
  actor,
  created_at: TS,
};

export const examplePosting: PostingRecord = {
  id: id("pst", 1),
  number: "TXN-000041",
  type: "po_receipt",
  txn_date: "2026-11-02",
  note: "GRN 7",
  reason_code: null,
  actor,
  created_at: TS,
  reversal_of: null,
  reversed_by: null,
  warnings: [],
  lines: [exampleTransaction],
};

export const examplePostingHeader: PostingHeader = {
  id: examplePosting.id,
  number: examplePosting.number,
  type: examplePosting.type,
  txn_date: examplePosting.txn_date,
  note: examplePosting.note,
  reason_code: null,
  actor,
  created_at: TS,
  reversal_of_id: null,
  reversed_by_number: null,
  line_count: 1,
};

export const exampleInsufficientStock: { error: { code: string; message: string; details: InsufficientStockDetails } } = {
  error: {
    code: "INV_INSUFFICIENT_STOCK",
    message: "Only 12 of KV-CON-M12-8P are available in STORES-MAIN (20 on hand, 8 reserved); 15 requested.",
    details: { item_id: exCon.id, location_id: stores.id, lot_code: null, on_hand: 20, reserved: 8, available: 12, requested: 15, line: 0 },
  },
};

export const exampleBalance: BalanceRow = {
  id: id("bal", 1),
  item: exCon,
  location: stores,
  lot: null,
  qty_on_hand: 20,
  qty_reserved: 8,
  qty_available: 12,
  nettable: true,
  last_receipt_on: "2026-10-20",
  value: 1700,
  updated_at: TS,
};

export const exampleBalancePage: BalancePage = {
  items: [exampleBalance],
  total: 1,
  limit: 200,
  offset: 0,
  totals: { qty_on_hand: 20, qty_reserved: 8, value: 1700 },
};

export const exampleItemStock: ItemStock = {
  item: exCon,
  totals: { nettable: 20, inspection: 0, quarantine: 50, reserved: 8, available: 12, value: 1700 },
  balances: [exampleBalance],
  open_supply: [{ type: "po_schedule", ref: { id: id("psc", 7), doc_id: id("pdc", 2), label: "PO-KV-0102 / 10 / 1" }, date: "2026-10-21", qty: 200 }],
  open_demand: [{ type: "wo_component", ref: { id: id("woc", 2), wo_id: id("wko", 1), label: "WO-KV-0001" }, date: "2026-10-30", qty: 60 }],
  latest_run: { run_id: id("mrr", 12), run_no: 12, first_short_date: "2026-11-04", short_qty: 48 },
};

// ---------------------------------------------------------------- 3.5 / 12.4 purchasing
export const examplePoInput: PurchaseDocInput = {
  number: "PO-KV-0101",
  supplier_id: supRef.id,
  currency: "INR",
  order_date: "2026-06-10",
  note: "",
  lines: [
    {
      line_no: 10,
      item_id: exFpga.id,
      unit_price: 412.5,
      schedules: [
        { seq: 1, requested_date: "2026-11-20", qty: 30 },
        { seq: 2, requested_date: "2026-12-20", confirmed_date: "2027-01-05", qty: 30 },
        { seq: 3, requested_date: "2027-02-20", qty: 30 },
      ],
    },
  ],
};

const schedule = (n: number, seq: number, requested: string, confirmed: string | null, received = 0) => {
  const dock = confirmed ?? requested;
  const avail = new Date(`${dock}T00:00:00Z`);
  avail.setUTCDate(avail.getUTCDate() + 2);
  return {
    id: id("psc", n),
    seq,
    requested_date: requested,
    confirmed_date: confirmed,
    qty: 30,
    received_qty: received,
    open_qty: 30 - received,
    closed: false,
    dock_date: dock,
    available_date: avail.toISOString().slice(0, 10),
    overdue: false,
    overdue_days: 0,
  };
};

export const examplePo: PurchaseDocRecord = {
  id: id("pdc", 1),
  doc_type: "po",
  number: "PO-KV-0101",
  status: "draft",
  supplier_id: supRef.id,
  supplier: supRef,
  currency: "INR",
  order_date: "2026-06-10",
  note: "",
  external_ref: null,
  source: "manual",
  source_run_no: null,
  submitted_at: null,
  submitted_by: null,
  approved_at: null,
  approved_by: null,
  rejected_reason: "",
  value: 37125.0,
  open_value: 37125.0,
  overdue_count: 0,
  row_version: 1,
  created_at: TS,
  updated_at: TS,
  lines: [
    {
      id: id("pln", 1),
      line_no: 10,
      item_id: exFpga.id,
      item: exFpga,
      unit_price: 412.5,
      note: "",
      status: "open",
      qty: 90,
      received_qty: 0,
      open_qty: 90,
      converted_to: null,
      source_pr: null,
      schedules: [schedule(1, 1, "2026-11-20", null), schedule(2, 2, "2026-12-20", "2027-01-05"), schedule(3, 3, "2027-02-20", null)],
    },
  ],
  receipts: [],
};

export const examplePoSummary: PurchaseDocSummary = (() => {
  const { lines: _lines, receipts: _receipts, ...head } = examplePo;
  return { ...head, line_count: 1, next_dock_date: "2026-11-20" };
})();

export const examplePr: PurchaseDocRecord = {
  ...examplePo,
  id: id("pdc", 9),
  doc_type: "pr",
  number: "PR-000031",
  status: "approved",
  source: "mrp",
  source_run_no: 12,
  submitted_at: TS,
  submitted_by: "usr_planner1",
  approved_at: TS,
  approved_by: "usr_approver1",
  receipts: undefined,
};

export const exampleConvertPr: ConvertPrResponse = { pr: { ...examplePr, status: "ordered" }, po: examplePo };

export const exampleScheduleRow: ScheduleRow = {
  schedule_id: id("psc", 7),
  seq: 1,
  doc: { id: id("pdc", 2), doc_type: "po", number: "PO-KV-0102", status: "open" },
  line_no: 10,
  item: exCon,
  supplier: { id: id("sup", 5), code: "SUP-CON", name: "Supplier E (fictional)" },
  requested_date: "2026-10-21",
  confirmed_date: null,
  dock_date: "2026-10-21",
  available_date: "2026-10-21",
  qty: 200,
  received_qty: 0,
  open_qty: 200,
  overdue: true,
  overdue_days: 12,
  link: `/mfg/purchasing/orders/${id("pdc", 2)}?schedule=${id("psc", 7)}`,
};

// ---------------------------------------------------------------- 3.6 demand
export const exampleDemandInput: DemandOrderInput = {
  number: "DO-KV-002",
  demand_type: "customer",
  customer: "Zonal Railway B (fictional)",
  program: "KVP-27",
  priority: 2,
  note: "",
  lines: [{ line_no: 10, item_id: exTpu.id, qty: 15, due_date: "2027-01-31", serial_from: 121, serial_to: 135 }],
};

export const exampleDemandOrder: DemandOrderRecord = {
  id: id("dmo", 2),
  number: "DO-KV-002",
  demand_type: "customer",
  customer: "Zonal Railway B (fictional)",
  program: "KVP-27",
  priority: 2,
  status: "open",
  note: "",
  external_ref: null,
  row_version: 2,
  created_at: TS,
  updated_at: TS,
  lines: [
    {
      id: id("dml", 21),
      line_no: 10,
      item_id: exTpu.id,
      item: exTpu,
      qty: 15,
      due_date: "2027-01-31",
      serial_from: 121,
      serial_to: 135,
      priority: null,
      note: "",
      shipped_qty: 0,
      open_qty: 15,
      line_status: "open",
      effective_priority: 2,
      projection: { run_id: id("mrr", 12), run_no: 12, projected_date: "2027-02-16", late_days: 16, status: "late" },
    },
  ],
};

export const exampleDemandSummary: DemandOrderSummary = (() => {
  const { lines: _lines, ...head } = exampleDemandOrder;
  return { ...head, line_count: 1, open_qty: 15, next_due: "2027-01-31", late_lines: 1 };
})();

// ---------------------------------------------------------------- 3.7 / 7.4 work orders and kitting
export const exampleWorkOrder: WorkOrderRecord = {
  id: id("wko", 1),
  number: "WO-KV-0001",
  status: "released",
  item_id: exCpu.id,
  item: exCpu,
  qty: 30,
  qty_completed: 0,
  qty_scrapped: 0,
  open_qty: 30,
  start_date: "2026-10-30",
  due_date: "2026-11-09",
  priority: 5,
  serial_from: null,
  serial_to: null,
  demand_line_id: null,
  demand_line: null,
  bom: { id: id("bom", 5), revision: "A", version: 1 },
  routing: { id: id("rtg", 5), code: "MAIN", version: 1 },
  source: "manual",
  source_run_no: null,
  source_planned_no: null,
  released_at: TS,
  completed_at: null,
  closed_at: null,
  note: "",
  external_ref: null,
  row_version: 3,
  created_at: TS,
  updated_at: TS,
  shortage_count: 1,
  components: [
    {
      id: id("woc", 1),
      item: exFpga,
      required_qty: 30,
      issued_qty: 15,
      open_qty: 15,
      reserved_qty: 15,
      operation_seq: 10,
      find_number: "U1",
      alt_group: null,
      bom_line_id: id("bml", 1),
      note: "",
    },
    {
      id: id("woc", 2),
      item: exCon,
      required_qty: 60,
      issued_qty: 30,
      open_qty: 30,
      reserved_qty: 0,
      operation_seq: 20,
      find_number: "J1",
      alt_group: null,
      bom_line_id: id("bml", 2),
      note: "",
    },
  ],
  warnings: [],
};

export const exampleWorkOrderSummary: WorkOrderSummary = (() => {
  const { components: _c, shortage_count: _s, warnings: _w, reserved: _r, ...head } = exampleWorkOrder;
  return { ...head, component_count: 2 };
})();

const nextSupply = { type: "po_schedule", label: "PO-KV-0102 / 10 / 1", date: "2026-11-02", qty: 200, link: exampleScheduleRow.link };

export const exampleKitting: KittingResponse = {
  wo: { id: exampleWorkOrder.id, number: exampleWorkOrder.number, status: "released" },
  rows: [
    { component_id: id("woc", 1), item_id: exFpga.id, item: exFpga, required: 30, issued: 15, open: 15, reserved: 15, free: 30, shortage: 0, locations: [{ balance_id: id("bal", 2), location_id: stores.id, location_code: stores.code, lot_code: "FV1-2609", available: 30 }], next_supply: null },
    { component_id: id("woc", 2), item_id: exCon.id, item: exCon, required: 60, issued: 30, open: 30, reserved: 0, free: 12, shortage: 18, locations: [{ balance_id: id("bal", 1), location_id: stores.id, location_code: stores.code, lot_code: null, available: 12 }], next_supply: nextSupply },
  ],
  totals: { components: 2, short_components: 1, kit_complete: false },
};

export const exampleKittingCheck: KittingCheckResponse = {
  rows: [
    {
      wo: { id: exampleWorkOrder.id, number: exampleWorkOrder.number },
      link: `/mfg/work-orders/${exampleWorkOrder.id}`,
      start_date: "2026-10-30",
      priority: 5,
      status: "released",
      kit_complete: false,
      short_components: 1,
      shortages: [{ item: exCon, shortage: 18, next_supply: nextSupply }],
    },
  ],
  items_short: [{ item: exCon, total_shortage: 18, wo_count: 1, first_start_date: "2026-10-30", next_supply: nextSupply }],
};

// ---------------------------------------------------------------- 10 me, workspaces, members
export const exampleMe: MeResponse = {
  user_id: "usr_store1",
  workspace_owner_id: "usr_owner",
  workspace_name: "Kavach plant (fictional)",
  is_owner: false,
  roles: ["store_keeper"],
  permissions: ["view", "inventory"],
};

export const exampleWorkspaces: { items: WorkspaceInfo[] } = {
  items: [
    { owner_id: "usr_store1", plant_name: "My plant", is_owner: true, roles: [] },
    { owner_id: "usr_owner", plant_name: "Kavach plant (fictional)", is_owner: false, roles: ["store_keeper"] },
  ],
};

export const exampleMember: MemberRecord = {
  id: id("mbr", 1),
  user: { id: "usr_store1", email: "store1@example.invalid", display_name: "Store 1" },
  roles: ["store_keeper"],
  active: true,
  row_version: 1,
  created_at: TS,
  updated_at: TS,
};

// ---------------------------------------------------------------- 8.2 / 12.4 MRP
export const exampleMrpParams: MrpParams = { label: "Weekly plan", allocation: "priority", alternates: "when_short" };

export const exampleMrpWhatIf: MrpParams = {
  label: "FPGA 30 days late",
  supply_date_overrides: [{ schedule_id: id("psc", 1), date: "2026-12-20" }],
  include_pr_supply: true,
};

export const exampleRun: MrpRunRecord = {
  id: id("mrr", 12),
  run_no: 12,
  kind: "live",
  status: "completed",
  label: "Weekly plan",
  note: "",
  pinned: false,
  as_of: "2026-11-02",
  horizon_days: 90,
  params: exampleMrpParams,
  master_fingerprint: "6f1c0a9b2d3e4f5a",
  row_version: 1,
  started_at: "2026-11-02T06:00:00Z",
  finished_at: "2026-11-02T06:00:03Z",
  duration_ms: 2870,
  actor: { id: "usr_planner1", name: "Planner 1" },
  summary: {
    demand_lines: 8,
    demand_on_time: 5,
    demand_late: 2,
    demand_past_due: 0,
    max_late_days: 28,
    items: 1173,
    items_short: 41,
    planned_make: 96,
    planned_buy: 603,
    release_now: 188,
    start_in_past: 37,
    alternates_used: 2,
    iterations: 2,
    exceptions_truncated: false,
    exceptions: { by_severity: { critical: 2, warning: 85, info: 240 }, by_code: { MRP_DEMAND_LATE: 2, MRP_SHORTAGE: 41, MRP_EXPEDITE: 12, MRP_RELEASE_NOW: 188 } },
    timings_ms: { load: 410, compute: 1520, store: 940 },
  },
  stale: { is_stale: false, master_changed: false, transactions_changed: false },
  error: null,
};

export const exampleRunPage: Page<MrpRunRecord> = { items: [exampleRun], total: 1, limit: 50, offset: 0 };

export const exampleMrpItemRow: MrpItemRow = {
  item: exGsm,
  llc: 4,
  make_buy: "buy",
  uom: "EA",
  on_hand: 8,
  gross_qty: 37,
  existing_supply_qty: 40,
  planned_qty: 0,
  planned_count: 0,
  first_short_date: "2027-01-01",
  short_qty: 12,
  late_qty: 12,
  min_balance: -12,
  exception_count: 1,
  lead_time: { source: "item_supplier", days: 120, unit: "calendar" },
  link: `/mfg/mrp/runs/${id("mrr", 12)}/items/${exGsm.id}`,
};

export const exampleItemPlan: MrpItemPlan = {
  run: { id: exampleRun.id, run_no: 12, as_of: "2026-11-02", stale: false },
  row: exampleMrpItemRow,
  lot: { rule: "lot_for_lot", moq: 0, multiple: 0, pack: 1, period_days: null, fixed_qty: null },
  supplier: { id: id("sup", 7), code: "SUP-RADIO", name: "Supplier G (fictional)" },
  timeline: [
    { date: "2026-11-02", kind: "on_hand", node: null, label: "On hand", qty: 8, balance_existing: 8, balance_planned: 8 },
    { date: "2026-11-30", kind: "supply", node: 2, label: "PO-KV-0103 / 10 / 1", qty: 10, balance_existing: 18, balance_planned: 18 },
    { date: "2027-01-01", kind: "requirement", node: 1, label: "P2 DO-KV-002/10", qty: -30, balance_existing: -12, balance_planned: -12 },
  ],
  buckets: [
    { start: "2026-11-30", end: "2026-12-06", gross: 0, existing_supply: 10, planned: 0, balance_existing_end: 18, balance_planned_end: 18, short: false },
    { start: "2026-12-28", end: "2027-01-03", gross: 30, existing_supply: 0, planned: 0, balance_existing_end: -12, balance_planned_end: -12, short: true },
  ],
  requirements: [
    {
      node: 1,
      kind: "planned_component",
      need_date: "2027-01-01",
      qty: 30,
      rank_label: "P2 DO-KV-002/10",
      segment: null,
      source: { type: "planned_order", id: id("mpo", 77), label: "P-77 KV-VCU-2000", item_id: id("itm", 9), node: 4, link: `/mfg/mrp/runs/${id("mrr", 12)}/planned?order=${id("mpo", 77)}` },
      satisfied_date: "2027-03-01",
      late_days: 59,
      pegs: [
        { supply_node: 0, supply_label: "On hand STORES-MAIN", qty: 8, late_days: 0 },
        { supply_node: 2, supply_label: "PO-KV-0103 / 10 / 1", qty: 10, late_days: 0 },
        { supply_node: 3, supply_label: "PO-KV-0103 / 10 / 3", qty: 12, late_days: 59 },
      ],
    },
  ],
  supplies: [
    { node: 2, kind: "po", label: "PO-KV-0103 / 10 / 1", avail_date: "2026-11-30", projected_date: "2026-11-30", qty: 10, pegged_qty: 10, expires_on: null, ref: { type: "po_schedule", id: id("psc", 31), number: "PO-KV-0103", link: `/mfg/purchasing/orders/${id("pdc", 3)}?schedule=${id("psc", 31)}` }, planned_no: null, exception_codes: [] },
  ],
};

export const examplePlannedOrder: PlannedOrderRow = {
  id: id("mpo", 412),
  planned_no: 412,
  kind: "buy",
  item: item(20, "KV-CAP-0402-100N", "buy", "EA", "Capacitor 100 nF 0402"),
  supplier: { id: id("sup", 3), code: "SUP-PASS-A", name: "Supplier C (fictional)" },
  qty: 5000,
  need_date: "2026-11-20",
  start_date: "2026-10-21",
  dock_date: "2026-11-20",
  projected_start: "2026-11-02",
  projected_due: "2026-12-02",
  late_days: 12,
  release_status: "start_in_past",
  segment: null,
  lot_note: "lot-for-lot; MOQ 5,000; multiple 5,000",
  peg_summary: [{ demand_line_id: id("dml", 41), label: "DO-KV-004/10", qty: 412 }],
  status: "open",
  converted: null,
  link: `/mfg/mrp/runs/${id("mrr", 12)}/planned?order=${id("mpo", 412)}`,
};

export const examplePlannedPage: PlannedOrderPage = {
  items: [examplePlannedOrder],
  total: 1,
  limit: 200,
  offset: 0,
  counts: { by_kind: { buy: 1 }, by_release_status: { start_in_past: 1 }, by_status: { open: 1 } },
};

export const exampleConvertRequest: ConvertRequest = {
  mode: "release",
  orders: [{ id: id("mpo", 10) }, { id: id("mpo", 11), qty: 6000 }],
  pr_grouping: "per_supplier",
  add_to_pr_id: null,
  reserve: false,
};

export const exampleConvertResponse: ConvertResponse = {
  converted: [
    { planned_order_id: id("mpo", 10), type: "wo", id: id("wko", 143), number: "WO-000143" },
    { planned_order_id: id("mpo", 11), type: "pr", id: id("pdc", 88), number: "PR-000088", line_no: 10 },
  ],
  created: {
    work_orders: [{ id: id("wko", 143), number: "WO-000143" }],
    purchase_requests: [{ id: id("pdc", 88), number: "PR-000088", supplier: supRef, line_count: 1 }],
  },
};

export const exampleException: MrpExceptionRow = {
  id: id("mex", 1),
  ex_no: 1,
  code: "MRP_DEMAND_LATE",
  severity: "critical",
  item: exTpu,
  subject: { type: "demand_line", id: id("dml", 41), label: "DO-KV-004/10" },
  demand_line_id: id("dml", 41),
  date: "2026-12-18",
  qty: 2,
  days: 28,
  message:
    "DO-KV-004/10: 2 x KV-TPU-1000 due 20 Nov 2026 is projected for 18 Dec 2026 (28 days late). Limiting: KV-TPU-1000 needs 16 working days; KV-IC-FPGA-V1 from PO-KV-0101/10/1 available 24 Nov.",
  action: "Expedite the parts on the limiting path, or agree a new date.",
  suggested: null,
  related: [{ type: "po_schedule", id: id("psc", 1), label: "PO-KV-0101 / 10 / 1" }],
  link: `/mfg/demand/${id("dmo", 4)}?line=${id("dml", 41)}`,
};

export const exampleExceptionPage: ExceptionPage = {
  items: [exampleException],
  total: 1,
  limit: 200,
  offset: 0,
  counts: { by_severity: { critical: 1, warning: 0, info: 0 }, by_code: { MRP_DEMAND_LATE: 1 } },
};

export const exampleDemandProjection: DemandProjectionRow = {
  demand_line_id: id("dml", 41),
  extra: false,
  order: { id: id("dmo", 4), number: "DO-KV-004", demand_type: "project", customer: "", program: "KVP-PROTO" },
  line_no: 10,
  item: exTpu,
  qty: 2,
  due_date: "2026-11-20",
  priority: 1,
  segment: [99, 100],
  projected_date: "2026-12-18",
  late_days: 28,
  status: "late",
  limiting: [
    { item: exTpu, label: "final assembly, 16 working days", date: "2026-12-18", reason: "component" },
    { item: item(9, "KV-VCU-2000", "make"), label: "P-77", date: "2026-11-25", reason: "component" },
    { item: exCpu, label: "P-81", date: "2026-11-24", reason: "component" },
    { item: exFpga, label: "PO-KV-0101 / 10 / 1 available 24 Nov 2026", date: "2026-11-24", reason: "supply_date" },
  ],
  link: `/mfg/demand/${id("dmo", 4)}?line=${id("dml", 41)}`,
};

export const examplePegging: PeggingResponse = {
  root: { item_id: examplePlannedOrder.item.id, node: 9, kind: "supply" },
  direction: "up",
  rows: [
    { row: 0, parent_row: null, level: 0, item: examplePlannedOrder.item, node: 9, kind: "planned", label: "P-412 planned PR", qty: 5000, date: "2026-11-20", projected_date: "2026-12-02", late_days: 12, link: examplePlannedOrder.link },
    { row: 1, parent_row: 0, level: 1, item: exCpu, node: 3, kind: "planned_component", label: "P-81 KV-PCB-CPU", qty: 412, date: "2026-11-20", projected_date: "2026-12-02", late_days: 12, link: null },
    { row: 2, parent_row: 1, level: 2, item: exTpu, node: 1, kind: "demand", label: "DO-KV-004/10", qty: 2, date: "2026-11-20", projected_date: "2026-12-18", late_days: 28, link: exampleDemandProjection.link },
  ],
  truncated: false,
};

export const exampleCompare: CompareResponse = {
  a: exampleRun,
  b: { ...exampleRun, id: id("mrr", 13), run_no: 13, kind: "what_if", label: "FPGA 30 days late", params: exampleMrpWhatIf },
  demand: [{ demand_line_id: id("dml", 41), label: "DO-KV-004/10", due_date: "2026-11-20", a_projected: "2026-12-18", b_projected: "2027-01-07", delta_days: 20 }],
  planned: { a: { make: 96, buy: 603, make_qty: 410, buy_value: 1250000 }, b: { make: 96, buy: 605, make_qty: 410, buy_value: 1262000 } },
  exceptions_by_code: [{ code: "MRP_DEMAND_LATE", a: 2, b: 3 }],
  items: [{ item: exFpga, a_planned_qty: 0, b_planned_qty: 30, a_short_qty: 0, b_short_qty: 30 }],
  truncated: { demand: false, items: false },
};

export const exampleShortages: ShortageDashboard = {
  run: { id: exampleRun.id, run_no: 12, as_of: "2026-11-02", stale: false },
  counts: { late_demand: 2, short_items: 41, overdue_schedules: 1, wo_short: 1 },
  late_demand: [exampleDemandProjection],
  short_items: [exampleMrpItemRow],
  overdue_supply: [exampleScheduleRow],
  wo_shortages: exampleKittingCheck.items_short,
};

/**
 * JSON examples of docs/M1-DESIGN.md 7.1 and 9.4, plus one example per shape of 9.6, typed against `types.ts`
 * (no `any`, no casts). They exist so `tsc --noEmit` fails when the TypeScript mirror drifts from the contract.
 * Where the design elides fields with `"...": "..."`, the example fills them with plausible values; ids are
 * written out in full (`<prefix>_` + 32 hex) instead of the abbreviated `itm_3f...`.
 */
import type {
  BomInput,
  BomRecord,
  BomReleaseResponse,
  BomSummary,
  CalendarExceptionRecord,
  DuplicateKeyDetails,
  ExplosionRow,
  GroupDetail,
  GroupRecord,
  HealthReport,
  ImportHasErrorsDetails,
  ImportMappingRequest,
  ImportPreview,
  ImportRecord,
  ImportResult,
  IndentedExplosion,
  ItemInput,
  ItemRef,
  ItemRecord,
  LineRecord,
  LineWindows,
  List,
  Meta,
  OperatorRecord,
  Page,
  PlantRecord,
  ReleaseBlockedDetails,
  ReleaseRequest,
  ResetResponse,
  RoutingRecord,
  RoutingSummary,
  SampleLoadResponse,
  ShiftAssignmentRecord,
  ShiftPreview,
  ShiftTemplateInput,
  ShiftTemplateRecord,
  SkillRecord,
  SummarizedExplosion,
  Summary,
  TimePreview,
  ToolPoolRecord,
  WeekWindow,
  WhereUsed,
  Window,
} from "./types";

const id = (prefix: string, n: number) => `${prefix}_${n.toString(16).padStart(32, "0")}`;
const TS = "2026-11-02T06:10:00Z";

// ---------------------------------------------------------------- 7.1 health report
export const exampleHealthReport: HealthReport = {
  ok: false,
  as_of: "2026-11-02",
  horizon_days: 90,
  fingerprint: "6f1c0000000000000000000000000000000000000000000000000000000000e2",
  counts: { error: 7, warning: 0, info: 1 },
  by_code: { MFG_MAKE_NO_ROUTING: 1, MFG_GROUP_NO_SHIFT: 1, MFG_BUY_NO_LEAD_TIME: 5, MFG_LONG_LEAD_TIME: 1 },
  truncated: false,
  issues: [
    {
      code: "MFG_MAKE_NO_ROUTING",
      severity: "error",
      message:
        'Make item KV-HAR-L03 "Brake interface harness" has no released routing effective on 2 Nov 2026 (it has a draft routing STD v1).',
      fix: "Open the routing STD v1 and release it, or add a routing for this item.",
      entity: { type: "item", id: id("itm", 0x9c), label: "KV-HAR-L03" },
      related: [{ type: "routing", id: id("rtg", 0x41), label: "STD v1 (draft)" }],
      link: `/mfg/items/${id("itm", 0x9c)}/routing?routing=${id("rtg", 0x41)}`,
      field: null,
    },
  ],
  data_version: 12,
};

// ---------------------------------------------------------------- 9.4 item create (#6) and duplicate
export const exampleItemCreate: ItemInput = {
  part_number: "KV-PCB-CPU",
  revision: "C",
  description: "Vital CPU board assembly",
  uom: "EA",
  make_buy: "make",
  family: "PCBA-HDI",
  serialized: true,
  lot_rule: "lot_for_lot",
};

export const exampleItemRecord: ItemRecord = {
  id: id("itm", 0x3f),
  row_version: 1,
  part_number: "KV-PCB-CPU",
  revision: "C",
  description: "Vital CPU board assembly",
  uom: "EA",
  make_buy: "make",
  family: "PCBA-HDI",
  setup_family: null,
  lead_time_days: null,
  receiving_days: 0,
  lot_rule: "lot_for_lot",
  fixed_lot_qty: null,
  min_order_qty: 0,
  order_multiple: 0,
  safety_stock: 0,
  serialized: true,
  shelf_life_days: null,
  handling_class: null,
  handling_note: "",
  attributes: {},
  active: true,
  has_bom: false,
  has_routing: false,
  used_in_count: 0,
  created_at: TS,
  updated_at: TS,
};

export const exampleDuplicateKey: { error: { code: string; message: string; details: DuplicateKeyDetails } } = {
  error: {
    code: "MFG_DUPLICATE_KEY",
    message: "An item with part number 'KV-PCB-CPU' already exists.",
    details: { key: { part_number: "KV-PCB-CPU" }, existing_id: id("itm", 0x3f) },
  },
};

export const exampleItemsPage: Page<ItemRecord> = { items: [exampleItemRecord], total: 1234, limit: 50, offset: 0 };

// ---------------------------------------------------------------- 9.4 BOM document PUT (#16)
export const exampleBomPut: BomInput = {
  item_id: id("itm", 0x3f),
  revision: "C",
  version: 2,
  effective_from: null,
  effective_to: null,
  serial_from: null,
  serial_to: null,
  note: "",
  lines: [
    { id: id("bml", 0x01), find_number: "10", child_item_id: id("itm", 0xb1), qty_per: 1, uom: "EA" },
    { find_number: "20", child_item_id: id("itm", 0xc1), qty_per: 48, uom: "EA", scrap_pct: 1, ref_designators: "C1-C48" },
    { find_number: "30", child_item_id: id("itm", 0xa1), qty_per: 2, alt_group: "30", alt_priority: 1 },
    { find_number: "30", child_item_id: id("itm", 0xa2), qty_per: 2, alt_group: "30", alt_priority: 2 },
    { find_number: "90", child_item_id: id("itm", 0xd1), qty_per: 4, uom: "ML", operation_seq: 80 },
  ],
};

const cpuRef: ItemRef = {
  id: id("itm", 0x3f),
  part_number: "KV-PCB-CPU",
  revision: "C",
  description: "Vital CPU board assembly",
  uom: "EA",
  make_buy: "make",
  active: true,
};

export const exampleBomRecord: BomRecord = {
  id: id("bom", 0x8a),
  row_version: 5,
  item_id: cpuRef.id,
  revision: "C",
  version: 2,
  status: "draft",
  effective_from: null,
  effective_to: null,
  serial_from: null,
  serial_to: null,
  note: "",
  released_at: null,
  obsoleted_at: null,
  created_at: TS,
  updated_at: TS,
  item: cpuRef,
  lines: [
    {
      id: id("bml", 0x01),
      find_number: "10",
      child_item_id: id("itm", 0xb1),
      qty_per: 1,
      uom: "EA",
      scrap_pct: 0,
      ref_designators: "",
      alt_group: null,
      alt_priority: 1,
      operation_seq: null,
      note: "",
      child: {
        id: id("itm", 0xb1),
        part_number: "KV-BPCB-CPU",
        revision: "A",
        description: "Bare PCB, CPU",
        uom: "EA",
        make_buy: "buy",
        active: true,
      },
    },
  ],
};

// ---------------------------------------------------------------- 9.4 release (#18) and blocked
export const exampleReleaseRequest: ReleaseRequest = { effective_from: "2026-12-01", supersede_previous: true };

export const exampleReleaseResponse: BomReleaseResponse = {
  bom: { ...exampleBomRecord, status: "released", effective_from: "2026-12-01", row_version: 6, released_at: TS },
  superseded: [{ id: id("bom", 0x77), version: 1, effective_to: "2026-12-01" }],
};

export const exampleReleaseBlocked: { error: { code: string; message: string; details: ReleaseBlockedDetails } } = {
  error: {
    code: "MFG_RELEASE_BLOCKED",
    message: "This BOM cannot be released yet (2 problems).",
    details: {
      issues: [
        {
          code: "MFG_UOM_MISMATCH",
          severity: "error",
          message: "Line find 90 uses ML but KV-CAP-0402-100N is counted in EA.",
          fix: "Use a unit of the same kind as the item's unit (EA, or M/CM/MM ...).",
          entity: { type: "bom_line", id: id("bml", 0x90), label: "find 90" },
          related: [],
          link: `/mfg/items/${cpuRef.id}/bom/${id("bom", 0x8a)}/edit?line=${id("bml", 0x90)}`,
          field: "uom",
        },
      ],
    },
  },
};

// ---------------------------------------------------------------- 9.4 explosion (#10)
const rootRow: ExplosionRow = {
  row: 0,
  parent_row: null,
  subtree_end: 2431,
  level: 0,
  line_id: null,
  bom_id: id("bom", 0x71),
  item_id: id("itm", 0x70),
  part_number: "KV-TPU-1000",
  revision: "B",
  description: "Loco TPU unit (fictional)",
  make_buy: "make",
  uom: "EA",
  family: "FINAL",
  lead_time_days: null,
  active: true,
  find_number: null,
  ref_designators: "",
  qty_per: null,
  line_uom: null,
  scrap_pct: null,
  operation_seq: null,
  extended_qty: 2.0,
  alternates: [],
  is_phantom: false,
  has_children: true,
  is_shared: false,
  routing_id: id("rtg", 0x71),
};

export const exampleExplosion: IndentedExplosion = {
  item_id: id("itm", 0x70),
  part_number: "KV-TPU-1000",
  on: "2026-11-02",
  serial: null,
  qty: 2,
  mode: "indented",
  rows: [
    rootRow,
    {
      ...rootRow,
      row: 1,
      parent_row: 0,
      subtree_end: 1203,
      level: 1,
      line_id: id("bml", 0x200),
      bom_id: id("bom", 0x200),
      item_id: id("itm", 0x200),
      part_number: "KV-VCU-2000",
      revision: "A",
      description: "Vital computer unit",
      family: "SUBASSY",
      find_number: "10",
      qty_per: 1,
      line_uom: "EA",
      scrap_pct: 0,
      extended_qty: 2.083333,
      routing_id: id("rtg", 0x200),
      alternates: [
        { line_id: id("bml", 0x201), item_id: id("itm", 0x201), part_number: "KV-VCU-2001", qty_per: 1, line_uom: "EA", alt_priority: 2 },
      ],
    },
  ],
  totals: { rows: 2431, distinct_items: 1312, max_level: 4, make_items: 61, buy_items: 1243, phantom_items: 8 },
  warnings: [],
};

export const exampleSummarizedExplosion: SummarizedExplosion = {
  item_id: id("itm", 0x70),
  part_number: "KV-TPU-1000",
  on: "2026-11-02",
  serial: null,
  qty: 1,
  mode: "summarized",
  rows: [
    {
      item_id: id("itm", 0xc1),
      part_number: "KV-CAP-0402-100N",
      description: "Capacitor 100 nF 0402",
      make_buy: "buy",
      uom: "EA",
      total_qty: 1210.5,
      min_level: 3,
      max_level: 4,
      occurrences: 14,
      lead_time_days: 28,
    },
  ],
  totals: { rows: 1, distinct_items: 1, max_level: 4, make_items: 0, buy_items: 1, phantom_items: 0 },
  warnings: [{ code: "MFG_NO_EFFECTIVE_BOM", message: "KV-X has no effective BOM on 2 Nov 2026.", item_id: id("itm", 0x99) }],
};

// ---------------------------------------------------------------- 9.4 where-used (#11)
export const exampleWhereUsed: WhereUsed = {
  item_id: id("itm", 0xc1),
  part_number: "KV-CAP-0402-100N",
  mode: "indented",
  include: "effective",
  on: "2026-11-02",
  rows: [
    {
      row: 0,
      parent_row: null,
      level: 1,
      item_id: cpuRef.id,
      part_number: "KV-PCB-CPU",
      revision: "C",
      description: "Vital CPU board assembly",
      make_buy: "make",
      bom_id: id("bom", 0x8a),
      bom_revision: "C",
      bom_version: 2,
      bom_status: "released",
      line_id: id("bml", 0x20),
      find_number: "20",
      qty_per: 48,
      line_uom: "EA",
      is_top: false,
    },
    {
      row: 1,
      parent_row: 0,
      level: 2,
      item_id: id("itm", 0x200),
      part_number: "KV-VCU-2000",
      revision: "A",
      description: "Vital computer unit",
      make_buy: "make",
      bom_id: id("bom", 0x200),
      bom_revision: "A",
      bom_version: 1,
      bom_status: "released",
      line_id: id("bml", 0x210),
      find_number: "10",
      qty_per: 3,
      line_uom: "EA",
      is_top: false,
    },
  ],
  totals: { rows: 37, top_items: 1 },
};

// ---------------------------------------------------------------- 9.4 time preview (#28)
export const exampleTimePreview: TimePreview = {
  routing_id: id("rtg", 0x10),
  item_id: id("itm", 0x10),
  qty: 250,
  uom: "EA",
  operations: [
    {
      seq: 10,
      name: "SMT top",
      group: { id: id("wcg", 0x1), code: "SMT" },
      input_qty: 264,
      output_qty: 264,
      run_per: "panel",
      loads: 66,
      queue_minutes: 0,
      move_minutes: 5,
      wait_minutes: 0,
      labor: "attended",
      lines: [
        { line_id: id("lin", 0x1), code: "SMT-1", speed_factor: 1.0, eligible: true, setup_minutes: 45, run_minutes: 79.2, total_minutes: 124.2 },
        {
          line_id: id("lin", 0x3),
          code: "SMT-3",
          speed_factor: 0.7,
          eligible: false,
          reason: "family PCBA-HDI not eligible",
          setup_minutes: 45,
          run_minutes: 113.142857,
          total_minutes: 158.142857,
        },
      ],
    },
  ],
  totals: { fastest_minutes: 2210.4, slowest_minutes: 2731.0, passive_minutes: 260, cumulative_yield: 0.9506 },
};

// ---------------------------------------------------------------- 9.4 shift template + preview (#41/#42)
export const exampleShiftTemplate: ShiftTemplateInput = {
  code: "3SHIFT",
  name: "24 hours, three shifts (Mon-Sat)",
  shifts: [
    { name: "A", days: ["mon", "tue", "wed", "thu", "fri", "sat"], start: "06:00", end: "14:00", breaks: [{ name: "Meal", start: "10:00", end: "10:30" }] },
    { name: "B", days: ["mon", "tue", "wed", "thu", "fri", "sat"], start: "14:00", end: "22:00", breaks: [{ name: "Meal", start: "18:00", end: "18:30" }] },
    { name: "C", days: ["mon", "tue", "wed", "thu", "fri", "sat"], start: "22:00", end: "06:00", breaks: [{ name: "Meal", start: "02:00", end: "02:30" }] },
  ],
};

const exampleWeekWindows: WeekWindow[] = [
  { shift: "A", day: "mon", start_minute: 360, end_minute: 600 },
  { shift: "A", day: "mon", start_minute: 630, end_minute: 840 },
  { shift: "C", day: "sat", start_minute: 8520, end_minute: 8760 },
  { shift: "C", day: "sat", start_minute: 8790, end_minute: 9000 },
];

export const exampleShiftPreview: ShiftPreview = {
  week_windows: exampleWeekWindows,
  minutes_per_day: { mon: 1350, tue: 1350, wed: 1350, thu: 1350, fri: 1350, sat: 1350, sun: 0 },
  total_minutes: 8100,
};

// ---------------------------------------------------------------- 9.4 line windows (#39)
const exampleWindows: Window[] = [
  { start: "2026-11-02T09:00:00+05:30", end: "2026-11-02T13:00:00+05:30", kind: "base", assignment_id: id("sha", 1), shift_label: "REG/Day", cost_per_hour: null },
  { start: "2026-11-02T13:45:00+05:30", end: "2026-11-02T18:00:00+05:30", kind: "base", assignment_id: id("sha", 1), shift_label: "REG/Day", cost_per_hour: null },
  { start: "2026-11-02T18:00:00+05:30", end: "2026-11-02T19:30:00+05:30", kind: "optional", assignment_id: id("sha", 2), shift_label: "EVE/Evening", cost_per_hour: 450.0 },
];

export const exampleLineWindows: LineWindows = {
  line_id: id("lin", 1),
  from: "2026-11-02",
  to: "2026-11-04",
  utc_offset: "+05:30",
  windows: exampleWindows,
  totals: { base_minutes: 990, optional_minutes: 450 },
};

// ---------------------------------------------------------------- 9.4 import (#68 -> #70 -> #71)
export const exampleImportUploaded: ImportRecord = {
  id: id("imp", 1),
  row_version: 1,
  status: "uploaded",
  filename: "kavach-bom.xlsx",
  format: "xlsx",
  expires_at: "2026-11-03T06:10:00Z",
  sheets: [
    {
      name: "BOM",
      row_count: 2431,
      headers: ["Parent", "Find No", "Component", "Qty", "UoM", "Ref Des"],
      sample_rows: [["KV-PCB-CPU", "10", "KV-BPCB-CPU", 1, "Nos", ""]],
      suggested: {
        target: "bom_lines",
        columns: {
          Parent: "parent_part_number",
          "Find No": "find_number",
          Component: "child_part_number",
          Qty: "qty_per",
          UoM: "uom",
          "Ref Des": "ref_designators",
        },
      },
    },
  ],
  mapping: null,
  preview: null,
  result: null,
};

export const exampleImportMapping: ImportMappingRequest = {
  sheets: {
    BOM: {
      target: "bom_lines",
      columns: {
        Parent: "parent_part_number",
        "Find No": "find_number",
        Component: "child_part_number",
        Qty: "qty_per",
        UoM: "uom",
        "Ref Des": "ref_designators",
      },
    },
  },
  options: { replace_children: true, release: false, default_effective_from: null },
};

export const exampleImportPreview: ImportPreview = {
  ok: false,
  counts: {
    bom_lines: { create: 2390, update: 12, unchanged: 28, delete: 0, error: 1 },
    boms: { create: 3, update: 0, unchanged: 58, delete: 0, error: 0 },
  },
  error_count: 1,
  row_errors: [
    {
      sheet: "BOM",
      row: 1207,
      column: "Component",
      code: "IMP_UNKNOWN_REFERENCE",
      message: "Part number 'KV-IC-XC7A35T' is not in your items or in this file.",
    },
  ],
  warnings: [],
  changes_sample: [
    {
      sheet: "bom_lines",
      key: { parent_part_number: "KV-PCB-VIO", revision: "B", version: 1, find_number: "40", child_part_number: "KV-RES-0603-10K" },
      action: "update",
      fields: { qty_per: [6, 8] },
    },
  ],
};

export const exampleImportMapped: ImportRecord = {
  ...exampleImportUploaded,
  row_version: 2,
  status: "mapped",
  mapping: exampleImportMapping,
  preview: exampleImportPreview,
};

export const exampleImportHasErrors: { error: { code: string; message: string; details: ImportHasErrorsDetails } } = {
  error: {
    code: "MFG_IMPORT_HAS_ERRORS",
    message: "The import still has 1 row error.",
    details: { row_errors: exampleImportPreview.row_errors, error_count: 1 },
  },
};

export const exampleImportResult: ImportResult = {
  counts: { bom_lines: { create: 2391, update: 12, unchanged: 28, delete: 0 }, boms: {} },
  duration_ms: 2140,
};

export const exampleImportCommitted: ImportRecord = {
  ...exampleImportMapped,
  row_version: 3,
  status: "committed",
  committed_at: "2026-11-02T06:14:02Z",
  result: exampleImportResult,
};

// ---------------------------------------------------------------- 9.4 sample load (#76)
export const exampleSampleLoad: SampleLoadResponse = {
  sample_id: "kavach",
  result: { counts: { items: { create: 1312, update: 0, unchanged: 0, delete: 0 } }, duration_ms: 6120, data_version: 2 },
  health: { ok: true, counts: { error: 0, warning: 3, info: 9 } },
};

// ---------------------------------------------------------------- 9.6 shapes (one example each)
export const exampleMeta: Meta = {
  uoms: [
    { code: "EA", dimension: "count", factor: 1, aliases: ["EA", "EACH", "PC", "PCS", "NOS"] },
    { code: "ML", dimension: "volume", factor: 0.001, aliases: ["ML"] },
  ],
  enums: {
    make_buy: ["make", "buy", "phantom"],
    lot_rule: ["lot_for_lot", "fixed"],
    status: ["draft", "released", "obsolete"],
    run_per: ["unit", "panel", "batch"],
    labor: ["attended", "unattended"],
    assignment_kind: ["base", "optional"],
    target_type: ["group", "line"],
    exception_scope: ["plant", "group", "line"],
    exception_kind: ["holiday", "shutdown", "maintenance"],
    weekday: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
  },
  limits: { MAX_ITEMS: 50000, PAGE_MAX: 200, MAX_WINDOW_RANGE_DAYS: 62, max_body_bytes: 5242880 },
  import_spec: {
    sheets: [
      {
        name: "items",
        columns: [
          { field: "part_number", type: "str", required_on_create: true, key: true, enum_values: null, synonyms: ["part no", "pn"] },
          { field: "make_buy", type: "enum", required_on_create: true, key: false, enum_values: ["make", "buy", "phantom"], synonyms: [] },
        ],
      },
    ],
  },
  samples: [{ id: "small", name: "SM-100 Sensor interface board", description: "Fictional sample data.", counts: { items: 10 } }],
  health_codes: [{ code: "MFG_BOM_CYCLE", severity: "error" }],
};

export const exampleSummary: Summary = {
  counts: {
    items: 10,
    make: 1,
    buy: 9,
    phantom: 0,
    boms: 1,
    bom_lines: 8,
    routings: 1,
    operations: 4,
    groups: 4,
    lines: 4,
    shift_templates: 3,
    operators: 3,
    tool_pools: 2,
  },
  end_items: [{ ...cpuRef, part_number: "SM-100" }],
  data_version: 2,
};

export const examplePlantDefault: PlantRecord = {
  id: null,
  row_version: 0,
  created_at: null,
  updated_at: null,
  name: "Plant",
  utc_offset: "+00:00",
  planning_horizon_days: 90,
  currency: "",
  attributes: {},
};

const { lines: _lines, ...bomHeader } = exampleBomRecord;
void _lines;
export const exampleBomSummary: BomSummary = { ...bomHeader, line_count: 5 };

const smtGroup = { id: id("wcg", 1), code: "SMT", name: "SMT placement" };

export const exampleRoutingRecord: RoutingRecord = {
  id: id("rtg", 0x10),
  row_version: 1,
  item_id: cpuRef.id,
  revision: "C",
  code: "STD",
  version: 1,
  priority: 1,
  status: "released",
  effective_from: "2026-01-01",
  effective_to: null,
  serial_from: null,
  serial_to: null,
  note: "",
  released_at: TS,
  obsoleted_at: null,
  created_at: TS,
  updated_at: TS,
  item: cpuRef,
  operations: [
    {
      id: id("opr", 1),
      seq: 10,
      name: "SMT top",
      description: "",
      group_id: smtGroup.id,
      setup_minutes: 45,
      run_minutes: 1.2,
      run_per: "panel",
      units_per_panel: 4,
      units_per_batch: null,
      queue_minutes: 0,
      move_minutes: 5,
      wait_minutes: 0,
      labor: "attended",
      crew_size: 1,
      skill_id: id("skl", 1),
      tools: [{ tool_pool_id: id("tlp", 1), qty: 1, tool_pool: { id: id("tlp", 1), code: "KV-STN-CPU-T", name: "Stencil CPU top" } }],
      transfer_batch: null,
      yield_pct: 100,
      inspection_gate: false,
      interruptible: true,
      group: smtGroup,
      skill: { id: id("skl", 1), code: "SMT-OP", name: "SMT operator" },
    },
  ],
};

const { operations: _ops, ...routingHeader } = exampleRoutingRecord;
void _ops;
export const exampleRoutingSummary: RoutingSummary = { ...routingHeader, operation_count: 1 };

export const exampleGroupRecord: GroupRecord = {
  ...smtGroup,
  row_version: 1,
  description: "",
  kind: "machine",
  active: true,
  line_count: 1,
  created_at: TS,
  updated_at: TS,
};

export const exampleLineRecord: LineRecord = {
  id: id("lin", 1),
  row_version: 1,
  group_id: smtGroup.id,
  code: "SMT-1",
  name: "SMT line 1",
  speed_factor: 1.0,
  parallel_capacity: 1,
  setup_family: null,
  eligible_families: [],
  eligible_item_ids: [],
  cost_per_hour: 0,
  active: true,
  group: smtGroup,
  eligible_items: [],
  created_at: TS,
  updated_at: TS,
};

export const exampleAssignment: ShiftAssignmentRecord = {
  id: id("sha", 1),
  row_version: 1,
  shift_template_id: id("sht", 1),
  target_type: "group",
  group_id: smtGroup.id,
  line_id: null,
  kind: "optional",
  shift_names: [],
  effective_from: "2026-01-01",
  effective_to: null,
  cost_per_hour: 1200,
  max_hours_per_week: 16,
  note: "",
  template: { id: id("sht", 1), code: "SUN", name: "Sunday 06-22" },
  target: { type: "group", ...smtGroup },
  created_at: TS,
  updated_at: TS,
};

export const exampleGroupDetail: GroupDetail = {
  ...exampleGroupRecord,
  lines: [exampleLineRecord],
  assignments: [exampleAssignment],
};

export const exampleShiftTemplateRecord: ShiftTemplateRecord = {
  id: id("sht", 2),
  row_version: 1,
  code: exampleShiftTemplate.code,
  name: exampleShiftTemplate.name,
  description: "",
  shifts: exampleShiftTemplate.shifts,
  assignment_count: 3,
  operator_count: 12,
  created_at: TS,
  updated_at: TS,
};

export const exampleCalendarException: CalendarExceptionRecord = {
  id: id("cex", 1),
  row_version: 1,
  scope: "line",
  group_id: null,
  line_id: id("lin", 2),
  kind: "maintenance",
  start: "2026-11-14T06:00:00+05:30",
  end: "2026-11-14T18:00:00+05:30",
  label: "Maintenance SMT-2",
  target: { type: "line", id: id("lin", 2), code: "SMT-2", name: "SMT line 2" },
  created_at: TS,
  updated_at: TS,
};

export const examplePlantHoliday: CalendarExceptionRecord = {
  ...exampleCalendarException,
  id: id("cex", 2),
  scope: "plant",
  line_id: null,
  kind: "holiday",
  start: "2026-11-09T00:00:00+05:30",
  end: "2026-11-10T00:00:00+05:30",
  label: "Plant holiday",
  target: null,
};

export const exampleSkill: SkillRecord = {
  id: id("skl", 6),
  row_version: 1,
  code: "COATING",
  name: "Conformal coating",
  description: "",
  operator_count: 2,
  operation_count: 17,
  created_at: TS,
  updated_at: TS,
};

export const exampleOperator: OperatorRecord = {
  id: id("emp", 1),
  row_version: 1,
  code: "OP-001",
  name: "Operator 001",
  skill_ids: [exampleSkill.id],
  shift_template_id: id("sht", 3),
  shift_names: [],
  home_group_id: null,
  active: true,
  skills: [{ id: exampleSkill.id, code: exampleSkill.code, name: exampleSkill.name }],
  shift_template: { id: id("sht", 3), code: "REG", name: "Regular day shift" },
  home_group: null,
  created_at: TS,
  updated_at: TS,
};

export const exampleToolPool: ToolPoolRecord = {
  id: id("tlp", 1),
  row_version: 1,
  code: "KV-STN-CPU-T",
  name: "Stencil CPU top",
  kind: "stencil",
  quantity: 2,
  note: "",
  operation_count: 1,
  created_at: TS,
  updated_at: TS,
};

export const exampleSkillList: List<SkillRecord> = { items: [exampleSkill] };

export const exampleReset: ResetResponse = { deleted: { items: 10, boms: 1, bom_lines: 8, plant: 1 } };

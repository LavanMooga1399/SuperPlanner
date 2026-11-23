/**
 * Data hooks for the Manufacturing area (M 11.2 `lib/useMfg.ts`): loads with AbortController, debouncing,
 * error-to-text helpers and the version-conflict helper (412 -> reload banner, never silently drop edits).
 */
import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { ApiError } from "../../api/client";
import { getMeta, getPlant } from "../api/client";
import type { Meta, PlantRecord } from "../api/types";
import { t as tr } from "../../lib/i18n";

export interface Loaded<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload(): void;
  setData(next: T | null | ((prev: T | null) => T | null)): void;
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/** Run `fn` when `deps` change; aborts the previous request. `fn` returning null means "nothing to load". */
export function useLoad<T>(fn: (signal: AbortSignal) => Promise<T> | null, deps: DependencyList): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    const ctl = new AbortController();
    const p = fnRef.current(ctl.signal);
    if (!p) {
      setLoading(false);
      return () => ctl.abort();
    }
    setLoading(true);
    setError(null);
    p.then(
      (d) => {
        if (ctl.signal.aborted) return;
        setData(d);
        setLoading(false);
      },
      (e: unknown) => {
        if (ctl.signal.aborted || isAbortError(e)) return;
        setError(e);
        setLoading(false);
      },
    );
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

const LOC_ROOTS = new Set(["body", "query", "path", "header"]);

const FIELD_WORDS: Record<string, string> = {
  part_number: tr("mfg.useMfg.str.partNumber"),
  make_buy: tr("mfg.useMfg.str.makeOrBuy"),
  uom: tr("mfg.useMfg.str.unit"),
  lead_time_days: tr("mfg.useMfg.str.leadTimeDays"),
  fixed_lot_qty: tr("mfg.useMfg.str.fixedLotQuantity"),
  qty_per: tr("mfg.useMfg.str.quantityPer"),
  child_item_id: tr("mfg.useMfg.str.component"),
  find_number: tr("mfg.useMfg.str.findNumber"),
  scrap_pct: tr("mfg.useMfg.str.scrap"),
  ref_designators: tr("mfg.useMfg.str.referenceDesignators"),
  alt_group: tr("mfg.useMfg.str.alternateGroup"),
  alt_priority: tr("mfg.useMfg.str.alternatePriority"),
  operation_seq: tr("mfg.useMfg.str.consumedAtOperation"),
  group_id: tr("mfg.useMfg.str.stage"),
  skill_id: tr("mfg.useMfg.str.skill"),
  yield_pct: tr("mfg.useMfg.str.yield"),
  speed_factor: tr("mfg.useMfg.str.speedFactor"),
  parallel_capacity: tr("mfg.useMfg.str.parallelCapacity"),
  utc_offset: tr("mfg.useMfg.str.timeZoneOffset"),
  planning_horizon_days: tr("mfg.useMfg.str.planningHorizonDays"),
  shift_template_id: tr("mfg.useMfg.str.shiftTemplate"),
  effective_from: tr("mfg.useMfg.str.effectiveFrom"),
  effective_to: tr("mfg.useMfg.str.effectiveUntil"),
  item_id: tr("mfg.useMfg.str.item"),
  location_id: tr("mfg.useMfg.str.location"),
  from_location_id: tr("mfg.useMfg.str.fromLocation"),
  to_location_id: tr("mfg.useMfg.str.toLocation"),
  lot_code: tr("mfg.useMfg.str.lot"),
  expires_on: tr("mfg.useMfg.str.expiresOn"),
  counted_qty: tr("mfg.useMfg.str.countedQuantity"),
  qty: tr("mfg.useMfg.str.quantity"),
  supplier_id: tr("mfg.useMfg.str.supplier"),
  requested_date: tr("mfg.useMfg.str.requestedDockDate"),
  confirmed_date: tr("mfg.useMfg.str.confirmedDockDate"),
  due_date: tr("mfg.useMfg.str.dueDate"),
  start_date: tr("mfg.useMfg.str.startDate"),
  serial_from: tr("mfg.useMfg.str.serialFrom"),
  serial_to: tr("mfg.useMfg.str.serialTo"),
  unit_price: tr("mfg.useMfg.str.unitPrice"),
  required_qty: tr("mfg.useMfg.str.requiredQuantity"),
  reason_code: tr("mfg.useMfg.str.reason"),
  txn_date: tr("mfg.useMfg.str.postingDate"),
  schedule_id: tr("mfg.useMfg.str.delivery"),
  wo_component_id: tr("mfg.useMfg.str.component"),
  demand_line_id: tr("mfg.useMfg.str.demandLine"),
  units_per_purchase_unit: tr("mfg.useMfg.str.unitsPerPack"),
  min_order_qty: tr("mfg.useMfg.str.minimumOrderQuantity"),
  order_multiple: tr("mfg.useMfg.str.orderMultiple"),
  lot_period_days: tr("mfg.useMfg.str.lotPeriodDays"),
  standard_cost: tr("mfg.useMfg.str.standardCost"),
  external_ref: tr("mfg.useMfg.str.externalReference"),
};

const LIST_WORDS: Record<string, string> = {
  lines: tr("mfg.useMfg.str.line"),
  operations: tr("mfg.useMfg.str.operation"),
  shifts: "Shift",
  breaks: tr("mfg.useMfg.str.break"),
  tools: tr("mfg.useMfg.str.tool"),
  schedules: tr("mfg.useMfg.str.delivery"),
  components: tr("mfg.useMfg.str.component"),
  orders: tr("mfg.useMfg.str.order"),
  extra_demand: tr("mfg.useMfg.str.extraDemand"),
  supply_date_overrides: tr("mfg.useMfg.str.supplyDateChange"),
  lead_time_overrides: tr("mfg.useMfg.str.leadTimeChange"),
};

function words(name: string): string {
  const w = name.replace(/_/g, " ").trim();
  return w ? w[0].toUpperCase() + w.slice(1) : name;
}

/** `["body","lines",2,"qty_per"]` -> "Line 3, Quantity per". */
export function describeLoc(loc: unknown[]): string {
  const path = loc.filter((x, i) => !(i === 0 && typeof x === "string" && LOC_ROOTS.has(x)));
  const parts: string[] = [];
  for (let i = 0; i < path.length; i++) {
    const seg = path[i];
    const next = path[i + 1];
    if (typeof seg === "string" && typeof next === "number" && LIST_WORDS[seg]) {
      parts.push(`${LIST_WORDS[seg]} ${next + 1}`);
      i++;
    } else if (typeof seg === "string") {
      parts.push(FIELD_WORDS[seg] ?? words(seg));
    }
  }
  return parts.join(", ");
}

export interface FieldError {
  loc: unknown[];
  field: string;
  message: string;
}

/** Field errors of `VALIDATION_ERROR` / `MFG_SHIFT_INVALID` (A 14 `details.errors`) and `MFG_UNKNOWN_REFERENCE`. */
export function fieldErrors(err: unknown): FieldError[] {
  if (!(err instanceof ApiError)) return [];
  const list = err.details.errors;
  if (Array.isArray(list)) {
    return list
      .filter((e): e is { loc?: unknown; msg?: unknown } => typeof e === "object" && e !== null)
      .map((e) => {
        const loc = Array.isArray(e.loc) ? e.loc : [];
        const raw = String(e.msg ?? tr("mfg.useMfg.str.invalidValue")).replace(/^Value error, /, "");
        return { loc, field: describeLoc(loc), message: raw ? raw[0].toUpperCase() + raw.slice(1) : raw };
      });
  }
  if (err.code === "MFG_UNKNOWN_REFERENCE" && Array.isArray(err.details.loc)) {
    const loc = err.details.loc;
    return [{ loc, field: describeLoc(loc), message: err.message }];
  }
  return [];
}

/** One readable sentence for any error (network errors keep the shared NETWORK_MESSAGE text). */
export function errorText(err: unknown): string {
  if (!err) return "";
  if (err instanceof ApiError) {
    if (err.code === "MFG_IN_USE") {
      const refs = err.details.references;
      if (refs && typeof refs === "object") {
        const list = Object.entries(refs as Record<string, unknown>)
          .filter(([, n]) => typeof n === "number" && n > 0)
          .map(([k, n]) => `${String(n)} ${k.replace(/_/g, " ")}`)
          .join(", ");
        if (list) return tr("mfg.useMfg.tpl.stillUsedBy", { message: err.message, list: list });
      }
    }
    // M5 4.4: a local write to fields the ERP owns
    if (err.code === "INT_ERP_OWNED") {
      const f = Array.isArray(err.details.fields) ? (err.details.fields as unknown[]).map((x) => String(x).replace(/_/g, " ")) : [];
      return `This data is maintained in the ERP and cannot be changed here${f.length ? `: ${f.join(", ")}` : ""}. Change it in the ERP; it comes in with the next sync.`;
    }
    if (err.code === "ECO_DOC_LOCKED") return tr("mfg.useMfg.str.thisDraftBelongsToAn");
    if (err.code === "ECO_SELF_APPROVAL") return tr("mfg.useMfg.str.youSubmittedThisChangeRequest");
    if (err.code === "TRF_PLANT_ACCESS") return tr("mfg.useMfg.str.youHaveNoRoleIn");
    if (err.code === "TRF_ITEM_UNMATCHED") return tr("mfg.useMfg.tpl.theReceivingPlantNeedsAn", { message: err.message });
    if (err.code === "MFG_BOM_CYCLE" && Array.isArray(err.details.cycle)) {
      return `${err.message} (${(err.details.cycle as unknown[]).map(String).join(" -> ")})`;
    }
    const fe = fieldErrors(err);
    if (fe.length) return fe.map((f) => (f.field ? `${f.field}: ${f.message}` : f.message)).join(" ");
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

export function isConflict(err: unknown): boolean {
  return err instanceof ApiError && err.status === 412;
}

/** 403 `MFG_FORBIDDEN` (M2 10.2): the role in this workspace lacks the permission. */
export function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}

export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

export function errorCode(err: unknown): string | null {
  return err instanceof ApiError ? err.code : null;
}

// ---------------------------------------------------------------- shared meta / plant caches
let metaPromise: Promise<Meta> | null = null;

/** `/meta` is static per server; one request per page load. */
export function useMeta(): Meta | null {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    let alive = true;
    if (!metaPromise) {
      metaPromise = getMeta().catch((e: unknown) => {
        metaPromise = null;
        throw e;
      });
    }
    metaPromise.then(
      (m) => alive && setMeta(m),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, []);
  return meta;
}

/** Plant settings (offset for dates/times); reloads on mount. */
export function usePlant(): Loaded<PlantRecord> {
  return useLoad((signal) => getPlant(signal), []);
}

/** Today's date in a `+HH:MM` offset (M 9.1: default `on`/`as_of` = today in the plant offset). */
export function todayInOffset(offset: string | undefined): string {
  const m = offset?.match(/^([+-])(\d{2}):(\d{2})$/);
  const mins = m ? (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])) : 0;
  const d = new Date(Date.now() + mins * 60000);
  return d.toISOString().slice(0, 10);
}

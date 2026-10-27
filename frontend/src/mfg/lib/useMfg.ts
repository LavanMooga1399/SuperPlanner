/**
 * Data hooks for the Manufacturing area (M 11.2 `lib/useMfg.ts`): loads with AbortController, debouncing,
 * error-to-text helpers and the version-conflict helper (412 -> reload banner, never silently drop edits).
 */
import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { ApiError } from "../../api/client";
import { getMeta, getPlant } from "../api/client";
import type { Meta, PlantRecord } from "../api/types";

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
  part_number: "Part number",
  make_buy: "Make or buy",
  uom: "Unit",
  lead_time_days: "Lead time (days)",
  fixed_lot_qty: "Fixed lot quantity",
  qty_per: "Quantity per",
  child_item_id: "Component",
  find_number: "Find number",
  scrap_pct: "Scrap %",
  ref_designators: "Reference designators",
  alt_group: "Alternate group",
  alt_priority: "Alternate priority",
  operation_seq: "Consumed at operation",
  group_id: "Stage",
  skill_id: "Skill",
  yield_pct: "Yield %",
  speed_factor: "Speed factor",
  parallel_capacity: "Parallel capacity",
  utc_offset: "Time zone offset",
  planning_horizon_days: "Planning horizon (days)",
  shift_template_id: "Shift template",
  effective_from: "Effective from",
  effective_to: "Effective until",
  item_id: "Item",
  location_id: "Location",
  from_location_id: "From location",
  to_location_id: "To location",
  lot_code: "Lot",
  expires_on: "Expires on",
  counted_qty: "Counted quantity",
  qty: "Quantity",
  supplier_id: "Supplier",
  requested_date: "Requested dock date",
  confirmed_date: "Confirmed dock date",
  due_date: "Due date",
  start_date: "Start date",
  serial_from: "Serial from",
  serial_to: "Serial to",
  unit_price: "Unit price",
  required_qty: "Required quantity",
  reason_code: "Reason",
  txn_date: "Posting date",
  schedule_id: "Delivery",
  wo_component_id: "Component",
  demand_line_id: "Demand line",
  units_per_purchase_unit: "Units per pack",
  min_order_qty: "Minimum order quantity",
  order_multiple: "Order multiple",
  lot_period_days: "Lot period (days)",
  standard_cost: "Standard cost",
  external_ref: "External reference",
};

const LIST_WORDS: Record<string, string> = {
  lines: "Line",
  operations: "Operation",
  shifts: "Shift",
  breaks: "Break",
  tools: "Tool",
  schedules: "Delivery",
  components: "Component",
  orders: "Order",
  extra_demand: "Extra demand",
  supply_date_overrides: "Supply date change",
  lead_time_overrides: "Lead time change",
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
        const raw = String(e.msg ?? "Invalid value").replace(/^Value error, /, "");
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
        if (list) return `${err.message} (still used by ${list})`;
      }
    }
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

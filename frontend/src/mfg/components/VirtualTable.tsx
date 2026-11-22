/**
 * Generic windowed table (M 11.4): fixed row height (`--mfg-row-h`, 32 px), renders only the visible rows plus
 * an overscan of 10 on each side between two spacers, sticky header, `role="grid"`/`"treegrid"` with
 * `aria-rowcount`/`aria-rowindex`, roving-tabindex keyboard navigation (Up/Down/PageUp/PageDown/Home/End;
 * Left/Right and Enter are passed to the owner, e.g. collapse/expand in the BOM tree). DOM rows stay well
 * under 80 regardless of data size. No dependency on any virtualisation library.
 *
 * UX-STANDARD 4 (shared data table): density-aware row height (compact 28 px / comfortable 36 px), header
 * sorting (server-side through `sort`/`onSortChange` + `Column.sortKey`, or client-side through
 * `Column.sortValue`), column show/hide/reorder/resize persisted per table (`sp.table.<tableId>`), CSV export
 * of the loaded rows, skeleton rows while the first page loads, and a footer toolbar with the row count.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { Icon } from "../../components/Icon";
import { useRowHeight } from "../../lib/prefs";
import { savePref, syncPref } from "../../lib/serverPrefs";
import { plural, t } from "../../lib/i18n";

/** Default (compact) row height; the live value follows the density preference (`useRowHeight`). */
export const ROW_HEIGHT = 28;
export const OVERSCAN = 10;

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** CSS grid track, e.g. "120px" or "minmax(220px, 1fr)". */
  width: string;
  align?: "right" | "center";
  /** Let long text wrap onto more lines (non-virtual tables only; virtual rows have a fixed height). */
  wrap?: boolean;
  /** Accessible header text when `header` is not plain text. */
  label?: string;
  render(row: T, index: number): ReactNode;
  /** Server sort key: header click calls `onSortChange` (the list re-queries). */
  sortKey?: string;
  /** Server key of the opposite direction (e.g. "-due_date"): clicks cycle sortKey -> sortKeyDesc -> default. */
  sortKeyDesc?: string;
  /** Client-side sort value (tables without `onSortChange`). */
  sortValue?(row: T): string | number | null | undefined;
  /** Text for CSV export (default: the text content of `render`). */
  exportValue?(row: T): string | number | null | undefined;
  /** False keeps the column always visible (default: the first column cannot be hidden). */
  hideable?: boolean;
  /**
   * Narrow screens: when the default column set is wider than the table, columns with a `drop` rank leave the
   * default set, lowest rank first, until the rest fits (no sideways scroll at 1024 px). The person can still show
   * them from Columns; an explicit choice wins.
   */
  drop?: number;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

export interface RowExtras {
  className?: string;
  testId?: string;
  data?: Record<string, string | number | boolean | null | undefined>;
  ariaLevel?: number;
  ariaExpanded?: boolean;
  ariaSelected?: boolean;
  title?: string;
}

export interface VirtualTableProps<T> {
  rows: readonly T[];
  columns: Column<T>[];
  rowKey(row: T, index: number): string | number;
  label: string;
  role?: "grid" | "treegrid";
  /** CSS height of the scroll area (the table shrinks when there are fewer rows). */
  height?: string;
  testId?: string;
  rowExtras?(row: T, index: number): RowExtras;
  /** Total rows on the server (paged lists); defaults to `rows.length`. */
  totalCount?: number;
  activeIndex?: number;
  onActiveChange?(index: number): void;
  onRowClick?(row: T, index: number, e: MouseEvent<HTMLDivElement>): void;
  /** Enter on a focused row. */
  onActivate?(row: T, index: number): void;
  /** Left/Right/other keys on a focused row; return true when handled. */
  onRowKey?(e: KeyboardEvent<HTMLDivElement>, row: T, index: number): boolean;
  /** Bring this row into view (centred) whenever `seq` changes. */
  scrollTo?: { index: number; seq: number } | null;
  onEndReached?(): void;
  empty?: ReactNode;
  footer?: ReactNode;
  /** Persistence key for column layout (default: `testId`, then `label`). */
  tableId?: string;
  /** Server-side sort state (with `onSortChange`). */
  sort?: SortState | null;
  onSortChange?(sort: SortState | null): void;
  /** True while the first page loads: skeleton rows instead of the empty text. */
  loading?: boolean;
  /** File name stem for "Export CSV" of the loaded rows; omit to hide export. */
  exportName?: string;
  /** False hides the column settings button (e.g. editable grids). */
  columnSettings?: boolean;
  /** Phone layout (< 768 px): rows become cards built from these column keys (UX-STANDARD 4). */
  card?: CardSpec;
  /** Row selection for bulk actions: a checkbox column; Space toggles the focused row. */
  selection?: TableSelection<T>;
  /**
   * False renders every row (short lists: run history, KPI by line, recall lines): no windowing, no fixed scroll
   * height, rows grow with their content, and phone cards are derived from the columns when `card` is omitted
   * (first column = title, a `status` column top right, the next three columns as fields).
   */
  virtual?: boolean;
  /** Non-virtual tables: a full-width line under the row (e.g. why an order is late); null for none. */
  rowDetail?(row: T, index: number): ReactNode;
}

export interface TableSelection<T> {
  selected: ReadonlySet<string>;
  onChange(next: Set<string>): void;
  rowId(row: T): string;
  /** Accessible name of a row (e.g. its number) for the checkbox label. */
  rowLabel(row: T): string;
}

export interface CardSpec {
  /** Column shown as the card title (the record id). */
  title: string;
  /** Column shown top right (status). */
  status?: string;
  /** Two or three key columns shown as "label value" pairs. */
  fields: string[];
  /** Column with row buttons (Edit, Remove), shown at the right of the card title row. */
  actions?: string;
}

const CARD_H = 84;

/** Phone card built from the column list (non-virtual tables without an explicit `card`). */
function autoCard<T>(columns: Column<T>[]): CardSpec | undefined {
  const cols = columns.filter((c) => c.key !== "actions" && c.key !== "__select");
  if (cols.length < 2) return undefined;
  const status = cols.find((c, i) => i > 0 && /status|state|result/i.test(c.key));
  const actions = columns.find((c) => c.key === "actions");
  return { title: cols[0].key, status: status?.key, actions: actions?.key, fields: cols.filter((c, i) => i > 0 && c !== status).slice(0, 3).map((c) => c.key) };
}
const PHONE_QUERY = "(max-width: 767px)";

function usePhone(enabled: boolean): boolean {
  const [phone, setPhone] = useState(() => enabled && typeof window !== "undefined" && window.matchMedia(PHONE_QUERY).matches);
  useEffect(() => {
    if (!enabled) return;
    const mq = window.matchMedia(PHONE_QUERY);
    const on = () => setPhone(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [enabled]);
  return enabled && phone;
}

interface ColumnPrefs {
  hidden: string[];
  order: string[];
  widths: Record<string, number>;
  /** Columns the person showed explicitly (they stay even when a narrow screen would drop them). */
  shown?: string[];
}

const EMPTY_PREFS: ColumnPrefs = { hidden: [], order: [], widths: {}, shown: [] };

/** Smallest width of a grid track ("120px", "minmax(150px, 1fr)"). */
function minTrack(w: string): number {
  const m = w.match(/(\d+(?:\.\d+)?)px/);
  return m ? Number(m[1]) : 80;
}

function loadPrefs(id: string): ColumnPrefs {
  try {
    const raw = window.localStorage.getItem(`sp.table.${id}`);
    if (!raw) return EMPTY_PREFS;
    const p = JSON.parse(raw) as Partial<ColumnPrefs>;
    return { hidden: p.hidden ?? [], order: p.order ?? [], widths: p.widths ?? {}, shown: p.shown ?? [] };
  } catch {
    return EMPTY_PREFS;
  }
}

/** Server preference key of a table layout (allowed characters only). */
const prefKey = (id: string) => `table.${id.replace(/[^A-Za-z0-9._:-]+/g, "-")}`.slice(0, 128);

function savePrefs(id: string, p: ColumnPrefs): void {
  const empty = !p.hidden.length && !p.order.length && !Object.keys(p.widths).length && !p.shown?.length;
  // local cache now, the person's server preferences shortly after (UX-STANDARD "Backend support")
  savePref(prefKey(id), `sp.table.${id}`, empty ? undefined : p);
}

/** Plain text of a rendered cell (for CSV export and tooltips). */
export function nodeText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (typeof node === "object" && "props" in node) {
    const props = (node as { props: Record<string, unknown> }).props ?? {};
    if (props.children !== undefined) return nodeText(props.children as ReactNode);
    for (const k of ["label", "status", "title", "value", "text"]) {
      const v = props[k];
      if (typeof v === "string" || typeof v === "number") return String(v).replace(/_/g, " ");
    }
  }
  return "";
}

function csvCell(v: string): string {
  return /[",\n;]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

function headerText<T>(c: Column<T>): string {
  return c.label ?? (nodeText(c.header) || c.key);
}

export function VirtualTable<T>({
  rows,
  columns,
  rowKey,
  label,
  role = "grid",
  height = "min(62vh, 640px)",
  testId,
  rowExtras,
  totalCount,
  activeIndex,
  onActiveChange,
  onRowClick,
  onActivate,
  onRowKey,
  scrollTo,
  onEndReached,
  empty,
  footer,
  tableId,
  sort,
  onSortChange,
  loading,
  exportName,
  columnSettings = true,
  card: cardProp,
  selection,
  virtual = true,
  rowDetail,
}: VirtualTableProps<T>) {
  const denseRow = useRowHeight();
  const card = cardProp ?? (virtual ? undefined : autoCard(columns));
  const cardMode = usePhone(!!card);
  const ROW_HEIGHT = cardMode ? CARD_H : denseRow;
  const HEAD_H = cardMode ? 0 : ROW_HEIGHT;
  const prefsId = tableId ?? testId ?? label;
  const [colPrefs, setColPrefs] = useState<ColumnPrefs>(() => loadPrefs(prefsId));
  useEffect(() => {
    syncPref<ColumnPrefs>(prefKey(prefsId), `sp.table.${prefsId}`, (v) => setColPrefs({ hidden: v?.hidden ?? [], order: v?.order ?? [], widths: v?.widths ?? {}, shown: v?.shown ?? [] }));
  }, [prefsId]);
  const updatePrefs = (p: ColumnPrefs) => {
    setColPrefs(p);
    savePrefs(prefsId, p);
  };
  const [clientSort, setClientSort] = useState<SortState | null>(null);
  const activeSort = onSortChange ? (sort ?? null) : clientSort;

  // ordered + visible columns with user widths
  const orderedAll = useMemo(() => {
    const byKey = new Map(columns.map((c) => [c.key, c]));
    const out: Column<T>[] = [];
    for (const k of colPrefs.order) {
      const c = byKey.get(k);
      if (c) {
        out.push(c);
        byKey.delete(k);
      }
    }
    // columns not in the saved order keep their original position relative to each other
    for (const c of columns) if (byKey.has(c.key)) out.splice(Math.min(columns.indexOf(c), out.length), 0, c);
    return out;
  }, [columns, colPrefs.order]);
  const lockedKey = columns[0]?.key;
  const canHide = (c: Column<T>) => c.hideable ?? c.key !== lockedKey;
  // available width of the table (for dropping `drop`-ranked columns on narrow screens)
  const [tableW, setTableW] = useState(0);
  const autoHidden = useMemo(() => {
    const out = new Set<string>();
    if (!tableW) return out;
    const shown = colPrefs.shown ?? [];
    const visible = orderedAll.filter((c) => !colPrefs.hidden.includes(c.key) || !canHide(c));
    let total = visible.reduce((a, c) => a + (colPrefs.widths[c.key] ?? minTrack(c.width)), selection ? 36 : 0);
    const droppable = visible.filter((c) => c.drop !== undefined && !shown.includes(c.key)).sort((a, b) => (a.drop ?? 0) - (b.drop ?? 0));
    for (const c of droppable) {
      if (total <= tableW) break;
      out.add(c.key);
      total -= colPrefs.widths[c.key] ?? minTrack(c.width);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderedAll, colPrefs, tableW, !!selection]);
  const visibleCols = useMemo(
    () => orderedAll.filter((c) => (!colPrefs.hidden.includes(c.key) && !autoHidden.has(c.key)) || !canHide(c)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [orderedAll, colPrefs.hidden, autoHidden],
  );
  const widthOf = (c: Column<T>) => (colPrefs.widths[c.key] ? `${colPrefs.widths[c.key]}px` : c.width);

  // client-side sorting (only when the table is not server-sorted)
  const sortedRows = useMemo(() => {
    if (onSortChange || !clientSort) return rows;
    const col = columns.find((c) => c.key === clientSort.key);
    if (!col?.sortValue) return rows;
    const f = col.sortValue;
    const m = clientSort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = f(a);
      const y = f(b);
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * m;
    });
  }, [rows, columns, clientSort, onSortChange]);
  rows = sortedRows;
  columns = visibleCols;
  if (selection) {
    const sel = selection;
    const ids = rows.map((r) => sel.rowId(r));
    const all = ids.length > 0 && ids.every((id) => sel.selected.has(id));
    const some = !all && ids.some((id) => sel.selected.has(id));
    const toggle = (id: string, on: boolean) => {
      const next = new Set(sel.selected);
      if (on) next.add(id);
      else next.delete(id);
      sel.onChange(next);
    };
    columns = [
      {
        key: "__select",
        width: "36px",
        align: "center",
        label: "Select",
        hideable: false,
        header: (
          <input
            type="checkbox"
            className="vt-check"
            aria-label={all ? "Clear the selection" : "Select all loaded rows"}
            checked={all}
            ref={(el) => {
              if (el) el.indeterminate = some;
            }}
            onChange={(e) => sel.onChange(e.target.checked ? new Set([...sel.selected, ...ids]) : new Set([...sel.selected].filter((id) => !ids.includes(id))))}
            data-testid="vt-select-all"
          />
        ),
        exportValue: () => "",
        render: (r) => (
          <input
            type="checkbox"
            className="vt-check"
            tabIndex={-1}
            aria-label={`Select ${sel.rowLabel(r)}`}
            checked={sel.selected.has(sel.rowId(r))}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => toggle(sel.rowId(r), e.target.checked)}
            data-testid="vt-select-row"
          />
        ),
      },
      ...columns,
    ];
  }

  const sortable = (c: Column<T>) => (onSortChange ? !!c.sortKey : !!c.sortValue);
  const toggleSort = (c: Column<T>) => {
    if (onSortChange) {
      // server sort keys carry their own direction ("-created_at"): click selects it, a second click resets
      const key = c.sortKey!;
      const dirOf = (k: string): "asc" | "desc" => (k.startsWith("-") ? "desc" : "asc");
      // two-direction columns toggle asc <-> desc; single-key columns toggle on <-> the list default
      if (activeSort?.key === key) onSortChange(c.sortKeyDesc ? { key: c.sortKeyDesc, dir: dirOf(c.sortKeyDesc) } : null);
      else onSortChange({ key, dir: dirOf(key) });
      return;
    }
    const cur = clientSort && clientSort.key === c.key ? clientSort.dir : null;
    setClientSort(cur === null ? { key: c.key, dir: "asc" } : cur === "asc" ? { key: c.key, dir: "desc" } : null);
  };

  // column resize (pointer drag on the header edge)
  const [dragging, setDragging] = useState<string | null>(null);
  const startResize = (e: ReactPointerEvent<HTMLSpanElement>, c: Column<T>) => {
    e.preventDefault();
    e.stopPropagation();
    const cell = (e.currentTarget.parentElement as HTMLElement | null)?.getBoundingClientRect();
    const startW = cell?.width ?? 120;
    const startX = e.clientX;
    let w = startW;
    setDragging(c.key);
    const move = (ev: PointerEvent) => {
      w = Math.max(48, Math.round(startW + ev.clientX - startX));
      setColPrefs((p) => ({ ...p, widths: { ...p.widths, [c.key]: w } }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDragging(null);
      setColPrefs((p) => {
        savePrefs(prefsId, p);
        return p;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const resizeKey = (e: KeyboardEvent<HTMLSpanElement>, c: Column<T>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    e.stopPropagation();
    const cell = (e.currentTarget.parentElement as HTMLElement | null)?.getBoundingClientRect();
    const w = Math.max(48, Math.round((colPrefs.widths[c.key] ?? cell?.width ?? 120) + (e.key === "ArrowRight" ? 16 : -16)));
    updatePrefs({ ...colPrefs, widths: { ...colPrefs.widths, [c.key]: w } });
  };

  const exportCsv = () => {
    const cols = columns.filter((c) => c.key !== "__select");
    const head = cols.map((c) => csvCell(headerText(c))).join(",");
    const body = rows.map((r, i) => cols.map((c) => csvCell(String((c.exportValue ? c.exportValue(r) : nodeText(c.render(r, i))) ?? ""))).join(","));
    const blob = new Blob([[head, ...body].join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${exportName ?? "export"}.csv`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(600);
  const [innerActive, setInnerActive] = useState(0);
  const active = activeIndex ?? innerActive;
  const focusPending = useRef(false);
  const raf = useRef<number | null>(null);
  const n = rows.length;

  const setActive = useCallback(
    (i: number) => {
      if (onActiveChange) onActiveChange(i);
      else setInnerActive(i);
    },
    [onActiveChange],
  );

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => {
      setViewport(el.clientHeight || 600);
      setTableW(el.clientWidth);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(
    () => () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current);
    },
    [],
  );

  const onScroll = () => {
    if (raf.current !== null) return;
    raf.current = requestAnimationFrame(() => {
      raf.current = null;
      const el = scrollRef.current;
      if (el) setScrollTop(el.scrollTop);
    });
  };

  const bodyViewport = Math.max(ROW_HEIGHT, viewport - HEAD_H);
  const first = Math.floor(scrollTop / ROW_HEIGHT);
  const count = Math.ceil(bodyViewport / ROW_HEIGHT) + 1;
  const start = virtual ? Math.max(0, first - OVERSCAN) : 0;
  const end = virtual ? Math.min(n, first + count + OVERSCAN) : n;

  useEffect(() => {
    if (virtual && onEndReached && n > 0 && end >= n - OVERSCAN) onEndReached();
  }, [end, n, onEndReached, virtual]);

  const ensureVisible = useCallback(
    (i: number, centre = false) => {
      const el = scrollRef.current;
      if (!el) return;
      if (!virtual) {
        // every row is in the DOM and the page scrolls: let the browser bring it into view
        el.querySelector<HTMLElement>(`[data-vt-index="${i}"]`)?.scrollIntoView({ block: centre ? "center" : "nearest" });
        return;
      }
      const top = i * ROW_HEIGHT;
      const vh = Math.max(ROW_HEIGHT, el.clientHeight - HEAD_H);
      let next = el.scrollTop;
      if (centre) next = Math.max(0, top - vh / 2 + ROW_HEIGHT / 2);
      else if (top < el.scrollTop) next = top;
      else if (top + ROW_HEIGHT > el.scrollTop + vh) next = top + ROW_HEIGHT - vh;
      if (next !== el.scrollTop) {
        el.scrollTop = next;
        setScrollTop(next);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [virtual],
  );

  useEffect(() => {
    if (!scrollTo || scrollTo.index < 0 || scrollTo.index >= n) return;
    ensureVisible(scrollTo.index, true);
    setActive(scrollTo.index);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollTo?.seq, scrollTo?.index]);

  useEffect(() => {
    if (!focusPending.current) return;
    const el = scrollRef.current?.querySelector<HTMLElement>(`[data-vt-index="${active}"]`);
    if (el) {
      focusPending.current = false;
      el.focus({ preventScroll: virtual });
    }
  });

  const move = (i: number) => {
    if (n === 0) return;
    const next = Math.max(0, Math.min(n - 1, i));
    focusPending.current = true;
    setActive(next);
    ensureVisible(next);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const idxAttr = target.getAttribute("data-vt-index");
    if (idxAttr === null) return; // keys inside cell controls (inputs, buttons) stay with them
    const i = Number(idxAttr);
    const pageRows = Math.max(1, Math.floor(bodyViewport / ROW_HEIGHT) - 1);
    if (selection && e.key === " ") {
      const id = selection.rowId(rows[i]);
      const next = new Set(selection.selected);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      selection.onChange(next);
      e.preventDefault();
      return;
    }
    if (onRowKey && onRowKey(e, rows[i], i)) {
      e.preventDefault();
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        move(i + 1);
        break;
      case "ArrowUp":
        move(i - 1);
        break;
      case "PageDown":
        move(i + pageRows);
        break;
      case "PageUp":
        move(i - pageRows);
        break;
      case "Home":
        move(0);
        break;
      case "End":
        move(n - 1);
        break;
      case "Enter":
        if (onActivate) onActivate(rows[i], i);
        else return;
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  const template = columns.map(widthOf).join(" ");
  const sizing: CSSProperties = virtual ? { height: ROW_HEIGHT } : { height: "auto", minHeight: ROW_HEIGHT };
  const gridStyle: CSSProperties = cardMode ? sizing : { gridTemplateColumns: template, ...sizing };
  const headStyle: CSSProperties = cardMode ? { height: ROW_HEIGHT } : { gridTemplateColumns: template, height: ROW_HEIGHT };
  const contentHeight = Math.max(n, 1) * ROW_HEIGHT + HEAD_H + 2;
  const byKey = new Map(orderedAll.map((c) => [c.key, c]));
  const cell = (c: Column<T> | undefined, row: T, i: number, cls: string, label?: boolean) => {
    if (!c) return null;
    const v = c.render(row, i);
    // labelled card fields without a value are left out (no dangling "Receipts" label)
    if (label && (v === null || v === undefined || v === false || v === "")) return null;
    return (
      <div key={c.key} role="gridcell" className={cls}>
        {label ? <span className="vt-card-label">{headerText(c)}</span> : null}
        <span className="vt-card-value">{v}</span>
      </div>
    );
  };
  const safeActive = Math.min(active, Math.max(0, n - 1));

  const body: ReactNode[] = [];
  for (let i = start; i < end; i++) {
    const row = rows[i];
    const x = rowExtras ? rowExtras(row, i) : {};
    const dataAttrs: Record<string, string> = {};
    if (x.data) {
      for (const [k, v] of Object.entries(x.data)) if (v !== undefined && v !== null) dataAttrs[`data-${k}`] = String(v);
    }
    body.push(
      <div
        key={rowKey(row, i)}
        role="row"
        className={`vt-row${cardMode ? " vt-card" : ""}${i === safeActive ? " vt-active" : ""}${x.className ? ` ${x.className}` : ""}`}
        style={gridStyle}
        aria-rowindex={i + 2}
        aria-level={x.ariaLevel}
        aria-expanded={x.ariaExpanded}
        aria-selected={selection ? selection.selected.has(selection.rowId(row)) : x.ariaSelected}
        tabIndex={i === safeActive ? 0 : -1}
        data-vt-index={i}
        data-testid={x.testId}
        title={x.title}
        onClick={(e) => {
          setActive(i);
          onRowClick?.(row, i, e);
        }}
        {...dataAttrs}
      >
        {cardMode && card ? (
          <>
            <div className="vt-card-top">
              {selection ? cell(columns[0], row, i, "vt-card-check") : null}
              {cell(byKey.get(card.title), row, i, "vt-card-title")}
              {card.status ? cell(byKey.get(card.status), row, i, "vt-card-status") : null}
              {card.actions ? cell(byKey.get(card.actions), row, i, "vt-card-status vt-card-actions") : null}
            </div>
            <div className="vt-card-fields">{card.fields.map((k) => cell(byKey.get(k), row, i, "vt-card-field", true))}</div>
          </>
        ) : columns.map((c) => {
          const content = c.render(row, i);
          // full text as a tooltip for plain-text cells that may be truncated (UX-STANDARD 4)
          const tip = typeof content === "string" || typeof content === "number" ? String(content) : nodeText(content) || undefined;
          return (
            <div key={c.key} role="gridcell" className={`vt-cell${c.align ? ` ${c.align}` : ""}${c.wrap && !virtual ? " wrap" : ""}`} title={c.wrap && !virtual ? undefined : tip}>
              {content}
            </div>
          );
        })}
      </div>,
    );
    const detail = !virtual && rowDetail ? rowDetail(row, i) : null;
    if (detail !== null && detail !== undefined && detail !== false)
      body.push(
        <div key={`${rowKey(row, i)}-detail`} role="row" className="vt-detail">
          <div role="gridcell" aria-colspan={columns.length}>
            {detail}
          </div>
        </div>,
      );
  }

  return (
    <div className={`vt${virtual ? "" : " vt-plain"}`} data-testid={testId}>
      <div
        ref={scrollRef}
        className={`vt-scroll${virtual ? "" : " vt-static"}`}
        style={n === 0 || !virtual ? undefined : { height: `min(${height}, ${contentHeight}px)` }}
        onScroll={onScroll}
        role={role}
        aria-label={label}
        aria-rowcount={(totalCount ?? n) + 1}
        aria-colcount={columns.length}
        onKeyDown={onKeyDown}
      >
        <div className="vt-inner">
          <div role="row" className={`vt-head${cardMode ? " vt-head-hidden" : ""}`} style={headStyle} aria-rowindex={1}>
            {columns.map((c) => {
              const sk = onSortChange ? c.sortKey : c.key;
              const dir = activeSort && sortable(c) && (activeSort.key === sk || (onSortChange && activeSort.key === c.sortKeyDesc)) ? activeSort.dir : null;
              return (
                <div
                  key={c.key}
                  role="columnheader"
                  className={`vt-cell${c.align ? ` ${c.align}` : ""}`}
                  aria-label={c.label}
                  aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : sortable(c) ? "none" : undefined}
                  title={headerText(c)}
                >
                  {sortable(c) ? (
                    <button type="button" className="vt-sort" onClick={() => toggleSort(c)} data-sorted={dir ?? undefined} data-testid={`sort-${c.key}`}>
                      <span className="vt-sort-text">{c.header}</span>
                      <Icon name={dir === "asc" ? "sort-asc" : dir === "desc" ? "sort-desc" : "sort"} size={12} />
                    </button>
                  ) : (
                    c.header
                  )}
                  {columnSettings ? (
                    <span
                      className={`vt-resize${dragging === c.key ? " dragging" : ""}`}
                      role="separator"
                      aria-orientation="vertical"
                      aria-label={t("table.resize", { name: headerText(c) })}
                      tabIndex={-1}
                      onPointerDown={(e) => startResize(e, c)}
                      onKeyDown={(e) => resizeKey(e, c)}
                      onDoubleClick={() => {
                        const { [c.key]: _drop, ...rest } = colPrefs.widths;
                        updatePrefs({ ...colPrefs, widths: rest });
                      }}
                    />
                  ) : null}
                </div>
              );
            })}
          </div>
          {n === 0 && loading ? (
            <div role="status" aria-label="Loading">
              {Array.from({ length: 6 }, (_, i) => (
                <div key={i} className="vt-skel-row" style={{ height: ROW_HEIGHT }} aria-hidden>
                  <span className="skel" style={{ width: 90, height: 10 }} />
                  <span className="skel" style={{ width: `${18 + ((i * 13) % 22)}%`, height: 10 }} />
                  <span className="skel" style={{ width: "12%", height: 10 }} />
                </div>
              ))}
            </div>
          ) : n === 0 ? (
            <div className="vt-empty">{empty ?? t("table.empty")}</div>
          ) : (
            <>
              <div aria-hidden style={{ height: start * ROW_HEIGHT }} />
              {body}
              <div aria-hidden style={{ height: (n - end) * ROW_HEIGHT }} />
            </>
          )}
        </div>
      </div>
      {footer || columnSettings || exportName ? (
        <div className="vt-footer vt-toolbar">
          <div className="vt-footer-main">{footer ?? <span className="muted small">{plural(totalCount ?? n, "row")}</span>}</div>
          <div className="row" style={{ gap: 4 }}>
            {exportName ? (
              <button type="button" className="btn ghost sm" onClick={exportCsv} disabled={n === 0} title={t("table.csvTitle")} data-testid="vt-export">
                <Icon name="download" size={14} /> {t("table.csv")}
              </button>
            ) : null}
            {columnSettings ? <ColumnMenu all={orderedAll} prefs={colPrefs} canHide={canHide} onChange={updatePrefs} label={label} autoHidden={autoHidden} /> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ColumnMenu<T>({ all, prefs, canHide, onChange, label, autoHidden }: { all: Column<T>[]; prefs: ColumnPrefs; canHide(c: Column<T>): boolean; onChange(p: ColumnPrefs): void; label: string; autoHidden: ReadonlySet<string> }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<CSSProperties>({});
  const ref = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const toggle = () => {
    if (!open && btn.current) {
      // fixed position next to the button, on the side with more room, never off-screen
      const r = btn.current.getBoundingClientRect();
      const below = window.innerHeight - r.bottom - 8;
      const above = r.top - 8;
      const right = Math.max(8, window.innerWidth - r.right);
      setPos(below >= Math.min(420, above) ? { position: "fixed", right, top: r.bottom + 4, maxHeight: below - 4 } : { position: "fixed", right, top: "auto", bottom: window.innerHeight - r.top + 4, maxHeight: above - 4 });
    }
    setOpen((v) => !v);
  };
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: globalThis.MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const keys = all.map((c) => c.key);
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= keys.length) return;
    const next = [...keys];
    [next[i], next[j]] = [next[j], next[i]];
    onChange({ ...prefs, order: next });
  };
  const isHidden = (c: Column<T>) => canHide(c) && (prefs.hidden.includes(c.key) || autoHidden.has(c.key));
  const hiddenCount = all.filter(isHidden).length;
  const shown = prefs.shown ?? [];
  const customised = prefs.hidden.length > 0 || prefs.order.length > 0 || Object.keys(prefs.widths).length > 0 || shown.length > 0;
  return (
    <div className="popover-anchor" ref={ref}>
      <button ref={btn} type="button" className="btn ghost sm" aria-haspopup="dialog" aria-expanded={open} onClick={toggle} data-testid="vt-columns">
        <Icon name="columns" size={14} /> {hiddenCount ? t("table.columnsHidden", { count: hiddenCount }) : t("table.columns")}
      </button>
      {open ? (
        <div className="popover col-menu" role="dialog" aria-label={`Columns of ${label}`} style={pos}>
          <div className="popover-group">
            <span className="small muted" style={{ padding: "0 6px" }}>
              {t("table.columnsHelp")}
            </span>
          </div>
          <div>
            {all.map((c, i) => (
              <div key={c.key} className="col-row">
                <label>
                  <input
                    type="checkbox"
                    checked={!isHidden(c)}
                    disabled={!canHide(c)}
                    onChange={(e) =>
                      onChange(
                        e.target.checked
                          ? { ...prefs, hidden: prefs.hidden.filter((k) => k !== c.key), shown: c.drop !== undefined ? [...shown.filter((k) => k !== c.key), c.key] : shown }
                          : { ...prefs, hidden: [...prefs.hidden, c.key], shown: shown.filter((k) => k !== c.key) },
                      )
                    }
                  />
                  <span className="mfg-ellipsis">{headerText(c)}</span>
                  {autoHidden.has(c.key) && !prefs.hidden.includes(c.key) ? <span className="faint small">{t("table.narrowHidden")}</span> : null}
                </label>
                <button type="button" className="btn ghost sm icon" onClick={() => move(i, -1)} disabled={i === 0} aria-label={t("table.moveUp", { name: headerText(c) })}>
                  <Icon name="sort-asc" size={12} />
                </button>
                <button type="button" className="btn ghost sm icon" onClick={() => move(i, 1)} disabled={i === all.length - 1} aria-label={t("table.moveDown", { name: headerText(c) })}>
                  <Icon name="sort-desc" size={12} />
                </button>
              </div>
            ))}
          </div>
          <div className="menu-sep" />
          <button type="button" className="btn sm" onClick={() => onChange(EMPTY_PREFS)} disabled={!customised}>
            <Icon name="refresh" size={14} /> {t("table.columnsReset")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

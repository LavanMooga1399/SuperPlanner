/**
 * Generic windowed table (M 11.4): fixed row height (`--mfg-row-h`, 32 px), renders only the visible rows plus
 * an overscan of 10 on each side between two spacers, sticky header, `role="grid"`/`"treegrid"` with
 * `aria-rowcount`/`aria-rowindex`, roving-tabindex keyboard navigation (Up/Down/PageUp/PageDown/Home/End;
 * Left/Right and Enter are passed to the owner, e.g. collapse/expand in the BOM tree). DOM rows stay well
 * under 80 regardless of data size. No dependency on any virtualisation library.
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
  type ReactNode,
} from "react";

export const ROW_HEIGHT = 32;
export const OVERSCAN = 10;

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** CSS grid track, e.g. "120px" or "minmax(220px, 1fr)". */
  width: string;
  align?: "right" | "center";
  /** Accessible header text when `header` is not plain text. */
  label?: string;
  render(row: T, index: number): ReactNode;
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
}: VirtualTableProps<T>) {
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
    const measure = () => setViewport(el.clientHeight || 600);
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

  const bodyViewport = Math.max(ROW_HEIGHT, viewport - ROW_HEIGHT);
  const first = Math.floor(scrollTop / ROW_HEIGHT);
  const count = Math.ceil(bodyViewport / ROW_HEIGHT) + 1;
  const start = Math.max(0, first - OVERSCAN);
  const end = Math.min(n, first + count + OVERSCAN);

  useEffect(() => {
    if (onEndReached && n > 0 && end >= n - OVERSCAN) onEndReached();
  }, [end, n, onEndReached]);

  const ensureVisible = useCallback(
    (i: number, centre = false) => {
      const el = scrollRef.current;
      if (!el) return;
      const top = i * ROW_HEIGHT;
      const vh = Math.max(ROW_HEIGHT, el.clientHeight - ROW_HEIGHT);
      let next = el.scrollTop;
      if (centre) next = Math.max(0, top - vh / 2 + ROW_HEIGHT / 2);
      else if (top < el.scrollTop) next = top;
      else if (top + ROW_HEIGHT > el.scrollTop + vh) next = top + ROW_HEIGHT - vh;
      if (next !== el.scrollTop) {
        el.scrollTop = next;
        setScrollTop(next);
      }
    },
    [],
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
      el.focus({ preventScroll: true });
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

  const template = useMemo(() => columns.map((c) => c.width).join(" "), [columns]);
  const gridStyle: CSSProperties = { gridTemplateColumns: template };
  const contentHeight = (Math.max(n, 1) + 1) * ROW_HEIGHT + 2;
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
        className={`vt-row${i === safeActive ? " vt-active" : ""}${x.className ? ` ${x.className}` : ""}`}
        style={gridStyle}
        aria-rowindex={i + 2}
        aria-level={x.ariaLevel}
        aria-expanded={x.ariaExpanded}
        aria-selected={x.ariaSelected}
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
        {columns.map((c) => (
          <div key={c.key} role="gridcell" className={`vt-cell${c.align ? ` ${c.align}` : ""}`}>
            {c.render(row, i)}
          </div>
        ))}
      </div>,
    );
  }

  return (
    <div className="vt" data-testid={testId}>
      <div
        ref={scrollRef}
        className="vt-scroll"
        style={{ height: `min(${height}, ${contentHeight}px)` }}
        onScroll={onScroll}
        role={role}
        aria-label={label}
        aria-rowcount={(totalCount ?? n) + 1}
        aria-colcount={columns.length}
        onKeyDown={onKeyDown}
      >
        <div className="vt-inner">
          <div role="row" className="vt-head" style={gridStyle} aria-rowindex={1}>
            {columns.map((c) => (
              <div key={c.key} role="columnheader" className={`vt-cell${c.align ? ` ${c.align}` : ""}`} aria-label={c.label}>
                {c.header}
              </div>
            ))}
          </div>
          {n === 0 ? (
            <div className="vt-empty">{empty ?? "Nothing to show."}</div>
          ) : (
            <>
              <div aria-hidden style={{ height: start * ROW_HEIGHT }} />
              {body}
              <div aria-hidden style={{ height: (n - end) * ROW_HEIGHT }} />
            </>
          )}
        </div>
      </div>
      {footer ? <div className="vt-footer">{footer}</div> : null}
    </div>
  );
}

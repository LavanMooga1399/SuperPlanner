/**
 * Paged list loader for the M2 tables (14.4): pages of 200 appended as the virtual table nears its end
 * (`onEndReached`), the previous request aborted on every filter change, stale responses ignored. `last` is the
 * most recent page response (for `totals` / `counts` that some endpoints add to the page).
 */
import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import type { Page } from "../api/types";
import { isAbortError } from "./useMfg";

export const PAGE_SIZE = 200;

export interface Paged<T, P extends Page<T>> {
  rows: T[];
  total: number;
  loading: boolean;
  error: unknown;
  last: P | null;
  onEndReached(): void;
  reload(): void;
  setRows(fn: (rows: T[]) => T[]): void;
}

export function usePaged<T, P extends Page<T> = Page<T>>(
  fetch: ((offset: number, limit: number, signal: AbortSignal) => Promise<P>) | null,
  deps: DependencyList,
  pageSize = PAGE_SIZE,
): Paged<T, P> {
  const [rows, setRowsState] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(Boolean(fetch));
  const [error, setError] = useState<unknown>(null);
  const [last, setLast] = useState<P | null>(null);
  const [tick, setTick] = useState(0);
  const gen = useRef(0);
  const inflight = useRef<AbortController | null>(null);
  const fetchRef = useRef(fetch);
  fetchRef.current = fetch;

  const load = useCallback(
    async (offset: number, replace: boolean) => {
      const f = fetchRef.current;
      if (!f) {
        setLoading(false);
        return;
      }
      const my = replace ? ++gen.current : gen.current;
      inflight.current?.abort();
      const ctl = new AbortController();
      inflight.current = ctl;
      setLoading(true);
      setError(null);
      try {
        const page = await f(offset, pageSize, ctl.signal);
        if (my !== gen.current) return;
        setTotal(page.total);
        setLast(page);
        setRowsState((prev) => (replace ? page.items : [...prev, ...page.items]));
      } catch (e) {
        if (isAbortError(e) || my !== gen.current) return;
        setError(e);
      } finally {
        if (my === gen.current && inflight.current === ctl) setLoading(false);
      }
    },
    [pageSize],
  );

  useEffect(() => {
    void load(0, true);
    return () => inflight.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, load]);

  const onEndReached = useCallback(() => {
    if (!loading && !error && rows.length < total) void load(rows.length, false);
  }, [loading, error, rows.length, total, load]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setRows = useCallback((fn: (r: T[]) => T[]) => setRowsState(fn), []);

  return { rows, total, loading, error, last, onEndReached, reload, setRows };
}

/** URL search-param helper shared by the list pages (`replace` so filters do not flood the history). */
export function setSearchParam(setParams: (fn: (prev: URLSearchParams) => URLSearchParams, o: { replace: boolean }) => void, key: string, value: string) {
  setParams(
    (prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      return next;
    },
    { replace: true },
  );
}

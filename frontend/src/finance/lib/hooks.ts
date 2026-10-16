import { useEffect, useRef, useState } from "react";
import { errorMessage, isAbort } from "../../api/client";
import { previewFinancePlan } from "../api/client";
import type { FinancePlan, FinancePreviewResponse } from "../api/types";

/** Value that settles `delay` ms after the last change. */
export function useDebounced<T>(value: T, delay: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

export interface PreviewState {
  data: FinancePreviewResponse | null;
  loading: boolean;
  error: string | null;
}

/** Live `POST /finance/preview` of the unsaved draft, debounced 800 ms (FINANCE.md 20.3). */
export function usePreview(draft: FinancePlan | null, delay = 800): PreviewState {
  const debounced = useDebounced(draft, delay);
  const [state, setState] = useState<PreviewState>({ data: null, loading: true, error: null });
  const seq = useRef(0);
  useEffect(() => {
    if (!debounced) return;
    const ac = new AbortController();
    const my = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    previewFinancePlan(debounced, ac.signal)
      .then((data) => my === seq.current && setState({ data, loading: false, error: null }))
      .catch((err) => {
        if (isAbort(err) || my !== seq.current) return;
        setState((s) => ({ data: s.data, loading: false, error: errorMessage(err) }));
      });
    return () => ac.abort();
  }, [debounced]);
  return state;
}

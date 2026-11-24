/**
 * Part 11 state shared by the quality screens (M7 4): the plant's Part 11 mode (`GET /mfg/plant/part11`, loaded once
 * per page load and refreshed after a change) and the signer's enrolment (`GET /auth/esig/status`). Both are small
 * module stores so every record page asks the same question without extra requests.
 */
import { useEffect, useSyncExternalStore } from "react";
import { getEsigStatus, getPart11Mode } from "../api/clientM7";
import type { EsigStatus, Part11Mode } from "../api/typesM7";
import { ApiError } from "../../api/client";

interface Store<T> {
  value: T | null;
  error: unknown;
  loading: boolean;
}

function makeStore<T>(load: () => Promise<T>) {
  let state: Store<T> = { value: null, error: null, loading: false };
  let started = false;
  const listeners = new Set<() => void>();
  const emit = (next: Store<T>) => {
    state = next;
    listeners.forEach((l) => l());
  };
  const refresh = () => {
    started = true;
    emit({ ...state, loading: true });
    load().then(
      (value) => emit({ value, error: null, loading: false }),
      (error: unknown) => emit({ value: state.value, error, loading: false }),
    );
  };
  const subscribe = (l: () => void) => {
    listeners.add(l);
    return () => listeners.delete(l);
  };
  return {
    refresh,
    set: (value: T) => emit({ value, error: null, loading: false }),
    use(): Store<T> & { refresh(): void } {
      const s = useSyncExternalStore(subscribe, () => state, () => state);
      useEffect(() => {
        if (!started) refresh();
      }, []);
      return { ...s, refresh };
    },
  };
}

const part11Store = makeStore<Part11Mode | null>(() =>
  getPart11Mode().catch((e: unknown) => {
    // a server without M7 (404) behaves like Part 11 off
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }),
);
const esigStore = makeStore<EsigStatus | null>(() =>
  getEsigStatus().catch((e: unknown) => {
    if (e instanceof ApiError && (e.status === 404 || e.status === 401 || e.status === 403)) return null;
    throw e;
  }),
);

/** Part 11 mode of the current plant (`enabled` false while loading or on servers without M7). */
export function usePart11() {
  const s = part11Store.use();
  return { mode: s.value ?? null, enabled: Boolean(s.value?.enabled), loading: s.loading && !s.value, error: s.error, refresh: s.refresh };
}
export const setPart11Mode = (m: Part11Mode) => part11Store.set(m);

/** The signed-in person's signature enrolment. */
export function useEsigStatus() {
  const s = esigStore.use();
  return { status: s.value ?? null, loading: s.loading && !s.value, error: s.error, refresh: s.refresh };
}
export const setEsigStatus = (v: EsigStatus) => esigStore.set(v);
export const refreshEsigStatus = () => esigStore.refresh();

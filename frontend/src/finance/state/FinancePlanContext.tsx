/**
 * FinancePlanContext (FINANCE.md 20.2/20.3, same rules as A.17.3): the editable draft of one finance plan,
 * 1.5 s debounced autosave with If-Match, 412 conflict banner, and single-flight saves [R23]:
 * every save waits for the in-flight one and then uses the latest known version, so two PUTs with the
 * same If-Match are never in flight together.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, errorMessage } from "../../api/client";
import { getFinancePlan, updateFinancePlan } from "../api/client";
import type { FinancePlan, FinancePlanRecord } from "../api/types";

export type FinSaveState = "saved" | "saving" | "error" | "conflict";

export interface FinancePlanContextValue {
  planId: string;
  record: FinancePlanRecord | null;
  draft: FinancePlan | null;
  dirty: boolean;
  saveState: FinSaveState;
  saveError: string | null;
  loading: boolean;
  loadError: string | null;
  loadStatus: number | null;
  /** Immutable update of the draft; schedules an autosave. */
  update(fn: (p: FinancePlan) => FinancePlan): void;
  /** Save now, after any in-flight save. Resolves true on success or when clean. */
  save(): Promise<boolean>;
  /** Discard local edits and fetch the server version. */
  reload(): Promise<void>;
  /** Conflict banner "Keep editing": adopt the server version number; the next save replaces it. */
  keepEditing(): Promise<void>;
  conflictDismissed: boolean;
  /** Latest known server version (no stale closures). */
  getVersion(): number | null;
  /** Latest draft (no stale closures). */
  getDraft(): FinancePlan | null;
}

const Ctx = createContext<FinancePlanContextValue | null>(null);

const AUTOSAVE_MS = 1500;

export function FinancePlanProvider({ planId, children }: { planId: string; children: ReactNode }) {
  const [record, setRecord] = useState<FinancePlanRecord | null>(null);
  const [draft, setDraft] = useState<FinancePlan | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<FinSaveState>("saved");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadStatus, setLoadStatus] = useState<number | null>(null);
  const [conflictDismissed, setConflictDismissed] = useState(false);

  const draftRef = useRef<FinancePlan | null>(null);
  const recordRef = useRef<FinancePlanRecord | null>(null);
  const editCounter = useRef(0);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const conflictRef = useRef(false);

  const applyRecord = useCallback((rec: FinancePlanRecord, replaceDraft: boolean) => {
    recordRef.current = rec;
    setRecord(rec);
    if (replaceDraft) {
      draftRef.current = rec.plan;
      setDraft(rec.plan);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    setLoadStatus(null);
    try {
      while (inFlight.current) await inFlight.current;
      const rec = await getFinancePlan(planId);
      applyRecord(rec, true);
      setDirty(false);
      editCounter.current = 0;
      conflictRef.current = false;
      setConflictDismissed(false);
      setSaveState("saved");
      setSaveError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
      setLoadStatus(err instanceof ApiError ? err.status : null);
    } finally {
      setLoading(false);
    }
  }, [planId, applyRecord]);

  useEffect(() => {
    void load();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  const scheduleRef = useRef<() => void>(() => undefined);

  const doSave = useCallback(async (): Promise<boolean> => {
    // Single flight: wait for any running save, re-checking after each wait.
    while (inFlight.current) await inFlight.current;
    const rec = recordRef.current;
    const doc = draftRef.current;
    if (!rec || !doc) return false;
    if (conflictRef.current) {
      setSaveState("conflict");
      return false;
    }
    const counterAtStart = editCounter.current;
    if (counterAtStart === 0) return true;
    let resolveFn: (v: boolean) => void = () => undefined;
    const p = new Promise<boolean>((r) => (resolveFn = r));
    inFlight.current = p;
    setSaveState("saving");
    setSaveError(null);
    let ok = false;
    try {
      const saved = await updateFinancePlan(rec.id, doc, rec.version);
      const editedMeanwhile = editCounter.current !== counterAtStart;
      applyRecord(saved, !editedMeanwhile);
      if (!editedMeanwhile) {
        editCounter.current = 0;
        setDirty(false);
      } else {
        editCounter.current -= counterAtStart;
      }
      setSaveState("saved");
      ok = true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        conflictRef.current = true;
        setConflictDismissed(false);
        setSaveState("conflict");
        setSaveError("This plan was changed elsewhere.");
      } else {
        setSaveState("error");
        setSaveError(errorMessage(err));
      }
    } finally {
      inFlight.current = null;
      resolveFn(ok);
    }
    if (ok && editCounter.current > 0) scheduleRef.current();
    return ok;
  }, [applyRecord]);

  const scheduleAutosave = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      void doSave();
    }, AUTOSAVE_MS);
  }, [doSave]);
  scheduleRef.current = scheduleAutosave;

  const update = useCallback(
    (fn: (p: FinancePlan) => FinancePlan) => {
      const cur = draftRef.current;
      if (!cur) return;
      const next = fn(cur);
      if (next === cur) return;
      draftRef.current = next;
      setDraft(next);
      editCounter.current += 1;
      setDirty(true);
      if (!conflictRef.current) scheduleAutosave();
    },
    [scheduleAutosave],
  );

  const save = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (editCounter.current === 0) {
      if (inFlight.current) return inFlight.current.then((ok) => ok && editCounter.current === 0 ? true : doSave());
      return !conflictRef.current;
    }
    return doSave();
  }, [doSave]);

  const keepEditing = useCallback(async () => {
    try {
      const latest = await getFinancePlan(planId);
      applyRecord(latest, false);
      conflictRef.current = false;
      setConflictDismissed(true);
      if (editCounter.current === 0) editCounter.current = 1;
      setDirty(true);
      setSaveState("saved");
      setSaveError(null);
      scheduleAutosave();
    } catch (err) {
      setSaveError(errorMessage(err));
    }
  }, [planId, applyRecord, scheduleAutosave]);

  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const getVersion = useCallback(() => recordRef.current?.version ?? null, []);
  const getDraft = useCallback(() => draftRef.current, []);

  const value = useMemo<FinancePlanContextValue>(
    () => ({
      planId,
      record,
      draft,
      dirty,
      saveState,
      saveError,
      loading,
      loadError,
      loadStatus,
      update,
      save,
      reload: load,
      keepEditing,
      conflictDismissed,
      getVersion,
      getDraft,
    }),
    [planId, record, draft, dirty, saveState, saveError, loading, loadError, loadStatus, update, save, load, keepEditing, conflictDismissed, getVersion, getDraft],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFinancePlan(): FinancePlanContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useFinancePlan must be used inside <FinancePlanProvider>");
  return ctx;
}

/** Same as useFinancePlan but asserts the draft is loaded. */
export function useLoadedFinancePlan(): FinancePlanContextValue & { draft: FinancePlan; record: FinancePlanRecord } {
  const ctx = useFinancePlan();
  if (!ctx.draft || !ctx.record) throw new Error("Finance plan not loaded");
  return ctx as FinancePlanContextValue & { draft: FinancePlan; record: FinancePlanRecord };
}

/**
 * PlanContext (ARCHITECTURE 17.3): the editable draft of one plan, autosave with
 * optimistic concurrency (If-Match), conflict detection (412).
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
import { ApiError, errorMessage, getProblem, updateProblem } from "../api/client";
import type { Problem, ProblemRecord } from "../api/types";

export type SaveState = "saved" | "saving" | "error" | "conflict";

export interface PlanContextValue {
  planId: string;
  record: ProblemRecord | null;
  draft: Problem | null;
  dirty: boolean;
  saveState: SaveState;
  saveError: string | null;
  loading: boolean;
  loadError: string | null;
  /** Immutable update of the draft; schedules an autosave. */
  update(fn: (p: Problem) => Problem): void;
  /** Save now (no-op when clean). Resolves true on success or when clean. */
  save(): Promise<boolean>;
  /** Discard local edits and fetch the server version. */
  reload(): Promise<void>;
  /** Conflict banner "Keep editing": keep the draft; the next save overwrites the other change. */
  keepEditing(): Promise<void>;
  conflictDismissed: boolean;
  /** Replace the record after a server-side change (e.g. replan bumped the version). */
  refreshRecord(): Promise<void>;
  /** Latest known server version (not subject to stale closures). */
  getVersion(): number | null;
}

export const PlanContextRaw = createContext<PlanContextValue | null>(null);

const AUTOSAVE_MS = 1500;

export function PlanProvider({ planId, children }: { planId: string; children: ReactNode }) {
  const [record, setRecord] = useState<ProblemRecord | null>(null);
  const [draft, setDraft] = useState<Problem | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [conflictDismissed, setConflictDismissed] = useState(false);

  // Refs mirror the latest values for async callbacks.
  const draftRef = useRef<Problem | null>(null);
  const recordRef = useRef<ProblemRecord | null>(null);
  const editCounter = useRef(0);
  const savingPromise = useRef<Promise<boolean> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const conflictRef = useRef(false);

  const applyRecord = useCallback((rec: ProblemRecord, replaceDraft: boolean) => {
    recordRef.current = rec;
    setRecord(rec);
    if (replaceDraft) {
      draftRef.current = rec.problem;
      setDraft(rec.problem);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const rec = await getProblem(planId);
      applyRecord(rec, true);
      setDirty(false);
      editCounter.current = 0;
      conflictRef.current = false;
      setConflictDismissed(false);
      setSaveState("saved");
      setSaveError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
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

  const doSave = useCallback(async (): Promise<boolean> => {
    if (savingPromise.current) {
      // Wait for the in-flight save, then save again if still dirty.
      await savingPromise.current;
    }
    const rec = recordRef.current;
    const doc = draftRef.current;
    if (!rec || !doc) return false;
    if (conflictRef.current) {
      setSaveState("conflict");
      return false;
    }
    const counterAtStart = editCounter.current;
    if (counterAtStart === 0) return true;
    const p = (async () => {
      setSaveState("saving");
      setSaveError(null);
      try {
        const saved = await updateProblem(rec.id, doc, rec.version);
        const editedMeanwhile = editCounter.current !== counterAtStart;
        applyRecord(saved, !editedMeanwhile);
        if (!editedMeanwhile) {
          editCounter.current = 0;
          setDirty(false);
        } else {
          editCounter.current -= counterAtStart;
        }
        setSaveState("saved");
        return true;
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
        return false;
      } finally {
        savingPromise.current = null;
      }
    })();
    savingPromise.current = p;
    const ok = await p;
    if (ok && editCounter.current > 0) {
      // Edits arrived during the save: schedule another autosave.
      scheduleAutosave();
    }
    return ok;
  }, [applyRecord]); // eslint-disable-line react-hooks/exhaustive-deps

  const scheduleAutosave = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      void doSave();
    }, AUTOSAVE_MS);
  }, [doSave]);

  const update = useCallback(
    (fn: (p: Problem) => Problem) => {
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
    if (editCounter.current === 0 && !savingPromise.current) return true;
    return doSave();
  }, [doSave]);

  const keepEditing = useCallback(async () => {
    // Adopt the server's current version number so the next save replaces it.
    try {
      const latest = await getProblem(planId);
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

  const refreshRecord = useCallback(async () => {
    try {
      const latest = await getProblem(planId);
      applyRecord(latest, editCounter.current === 0);
    } catch {
      /* ignore */
    }
  }, [planId, applyRecord]);

  // Warn about unsaved edits when leaving the page.
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

  const value = useMemo<PlanContextValue>(
    () => ({
      planId,
      record,
      draft,
      dirty,
      saveState,
      saveError,
      loading,
      loadError,
      update,
      save,
      reload: load,
      keepEditing,
      conflictDismissed,
      refreshRecord,
      getVersion,
    }),
    [planId, record, draft, dirty, saveState, saveError, loading, loadError, update, save, load, keepEditing, conflictDismissed, refreshRecord, getVersion],
  );

  return <PlanContextRaw.Provider value={value}>{children}</PlanContextRaw.Provider>;
}

export function usePlan(): PlanContextValue {
  const ctx = useContext(PlanContextRaw);
  if (!ctx) throw new Error("usePlan must be used inside <PlanProvider>");
  return ctx;
}

/** Same as usePlan but asserts the draft is loaded (use inside workspace tabs). */
export function useLoadedPlan(): PlanContextValue & { draft: Problem; record: ProblemRecord } {
  const ctx = usePlan();
  if (!ctx.draft || !ctx.record) throw new Error("Plan not loaded");
  return ctx as PlanContextValue & { draft: Problem; record: ProblemRecord };
}

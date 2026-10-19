/**
 * Intake flow state (PHASE2.md 3.3): text or table, draft, questions, notes, extractor and step, kept in
 * `sessionStorage["sp.intake.<kind>"]` so a reload does not lose work, and cleared on create and on cancel.
 * The AI assist toggle is never stored (it defaults to off on every visit).
 *
 * The server is stateless: every request carries the whole draft. Editing the draft schedules one quiet
 * `answer` call with no answers (debounced 600 ms) to refresh the questions; when no required question is
 * left, the draft is built automatically so the review can show counts and problems. Nothing is saved until
 * the user presses "Create plan".
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { createProblem, errorMessage, isAbort } from "../../api/client";
import { createFinancePlan } from "../../finance/api/client";
import type { PlanKind } from "../../landing/kinds";
import { useAsync } from "../../lib/useAsync";
import { browserUtcOffset, todayDate } from "../../lib/time";
import * as api from "../api/client";
import type {
  Answer,
  AnyDraft,
  BuildResult,
  Capabilities,
  Domain,
  ExtractContext,
  FinanceBuildResult,
  FinanceDraft,
  IntakeResponse,
  Question,
  ScheduleBuildResult,
  ScheduleDraft,
  TableOptions,
  TableParseResult,
} from "../api/types";
import { draftProblems, markEdited } from "../lib/draft";

export type IntakeFlow = "describe" | "import";
export type IntakeStep = "write" | "map" | "review";

export interface TableState {
  text: string;
  fileName: string | null;
  parse: TableParseResult | null;
  /** field per column index; null = ignore */
  mapping: (string | null)[];
  options: TableOptions;
}

export interface ChatEntry {
  id: string;
  prompt: string;
  answer: string;
}

export interface IntakeState {
  v: 1;
  kind: PlanKind;
  flow: IntakeFlow;
  step: IntakeStep;
  /** text in the box */
  text: string;
  /** the text the current draft was read from (spans point into it) */
  sourceText: string | null;
  table: TableState;
  response: IntakeResponse<AnyDraft> | null;
  build: BuildResult | null;
  /** draft revision; bumped on every change of the draft */
  rev: number;
  /** revision the build result belongs to */
  buildRev: number | null;
  history: ChatEntry[];
}

export type Busy = "describe" | "answer" | "parse" | "apply" | "create" | null;

export const DEFAULT_TABLE_OPTIONS: TableOptions = {
  duration_unit: "days",
  default_row_kind: "expense",
  amount_frequency: "monthly",
  predecessor_ref: "auto",
};

const DEFAULT_LIMITS: Capabilities["limits"] = {
  max_text_chars: 20000,
  max_table_chars: 1_000_000,
  max_table_rows: 2000,
  max_table_columns: 30,
};

/** AI requests can take about 3 minutes with retries (PHASE2.md 8): give up after 200 s. */
export const AI_TIMEOUT_MS = 200_000;
const REFRESH_DEBOUNCE_MS = 600;

export const storageKey = (kind: PlanKind) => `sp.intake.${kind}`;

function initialState(kind: PlanKind, flow: IntakeFlow): IntakeState {
  return {
    v: 1,
    kind,
    flow,
    step: "write",
    text: "",
    sourceText: null,
    table: {
      text: "",
      fileName: null,
      parse: null,
      mapping: [],
      options: { ...DEFAULT_TABLE_OPTIONS, duration_unit: kind === "study" || kind === "production" ? "hours" : "days" },
    },
    response: null,
    build: null,
    rev: 0,
    buildRev: null,
    history: [],
  };
}

function loadState(kind: PlanKind, flow: IntakeFlow): IntakeState {
  try {
    const raw = window.sessionStorage.getItem(storageKey(kind));
    if (raw) {
      const s = JSON.parse(raw) as IntakeState;
      if (s && s.v === 1 && s.kind === kind && s.flow === flow) return s;
    }
  } catch {
    /* storage unavailable or corrupt: start fresh */
  }
  return initialState(kind, flow);
}

function pickLocale(): string {
  const l = typeof navigator !== "undefined" ? navigator.language : "";
  return ["en-IN", "en-GB", "en-US"].includes(l) ? l : "en-IN";
}

export function domainOf(kind: PlanKind): Domain {
  return kind === "money" ? "finance" : "schedule";
}

export function makeContext(kind: PlanKind): ExtractContext {
  return {
    today: todayDate(),
    utc_offset: browserUtcOffset(),
    locale: pickLocale(),
    currency: "INR",
    kind: kind === "money" ? null : kind,
  };
}

/** Questions the user can settle with one click: a suggestion exists, or the question may be skipped. */
export function quickAnswer(q: Question): Answer | null {
  if (q.default !== null && q.default !== undefined) return { question_id: q.id, use_default: true };
  if (!q.required) return { question_id: q.id, skip: true };
  return null;
}

interface IntakeApi {
  state: IntakeState;
  domain: Domain;
  context: ExtractContext;
  capabilities: Capabilities | null;
  limits: Capabilities["limits"];
  busy: Busy;
  /** background refresh or build in flight */
  checking: boolean;
  error: string | null;
  /** the build result belongs to the current draft */
  buildFresh: boolean;
  activePath: string | null;
  setActivePath(p: string | null): void;
  clearError(): void;
  setText(t: string): void;
  setTable(patch: Partial<TableState>): void;
  setStep(step: IntakeStep): void;
  describe(useAi: boolean): Promise<void>;
  cancelRequest(): void;
  answer(answers: Answer[], history: ChatEntry[]): Promise<void>;
  useAllSuggestions(): Promise<void>;
  editDraft(draft: AnyDraft, editedPaths: string[]): void;
  checkDraft(): Promise<void>;
  parseTable(override?: { delimiter?: TableParseResult["delimiter"]; has_header?: boolean }): Promise<void>;
  applyTable(): Promise<void>;
  create(): Promise<void>;
  startOver(): void;
  cancel(): void;
}

const Ctx = createContext<IntakeApi | null>(null);

export function useIntake(): IntakeApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useIntake outside IntakeProvider");
  return v;
}

export function IntakeProvider({ kind, flow, children }: { kind: PlanKind; flow: IntakeFlow; children: ReactNode }) {
  const navigate = useNavigate();
  const domain = domainOf(kind);
  const context = useMemo(() => makeContext(kind), [kind]);
  const caps = useAsync((signal) => api.getCapabilities(signal), []);

  const [state, setState] = useState<IntakeState>(() => loadState(kind, flow));
  const stateRef = useRef(state);
  const [busy, setBusy] = useState<Busy>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activePath, setActivePath] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bgAbortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);
  const clearedRef = useRef(false);

  const commit = useCallback((fn: (s: IntakeState) => IntakeState) => {
    const next = fn(stateRef.current);
    stateRef.current = next;
    setState(next);
  }, []);

  // A different kind or flow in the same mounted provider (route change): reload.
  useEffect(() => {
    if (stateRef.current.kind !== kind || stateRef.current.flow !== flow) {
      const s = loadState(kind, flow);
      stateRef.current = s;
      setState(s);
    }
  }, [kind, flow]);

  useEffect(() => {
    if (clearedRef.current) return;
    try {
      window.sessionStorage.setItem(storageKey(state.kind), JSON.stringify(state));
    } catch {
      /* quota or private mode: the flow still works without persistence */
    }
  }, [state]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      bgAbortRef.current?.abort();
      if (timerRef.current) window.clearTimeout(timerRef.current);
    },
    [],
  );

  const clearTimer = () => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  // ------------------------------------------------------------ build
  const runBuild = useCallback(async () => {
    const s = stateRef.current;
    if (!s.response) return;
    const draft = s.response.draft;
    if (draftProblems(draft).length) return;
    const rev = s.rev;
    bgAbortRef.current?.abort();
    const ac = new AbortController();
    bgAbortRef.current = ac;
    setChecking(true);
    try {
      const result: BuildResult =
        draft.domain === "schedule"
          ? await api.buildSchedule(draft, context, ac.signal)
          : await api.buildFinance(draft, context, ac.signal);
      if (stateRef.current.rev !== rev) return;
      commit((x) => ({ ...x, build: result, buildRev: rev }));
    } catch (err) {
      if (isAbort(err)) return;
      setError(errorMessage(err));
    } finally {
      if (bgAbortRef.current === ac) {
        bgAbortRef.current = null;
        setChecking(false);
      }
    }
  }, [commit, context]);

  /** Take a server response for the draft sent at revision `rev`; build when nothing required is open. */
  const applyResponse = useCallback(
    (resp: IntakeResponse<AnyDraft>, rev: number | null, patch: Partial<IntakeState> = {}) => {
      if (rev !== null && stateRef.current.rev !== rev) return false;
      commit((x) => ({ ...x, ...patch, response: resp, build: null, buildRev: null, rev: x.rev + 1 }));
      if (!resp.questions.some((q) => q.required)) void runBuild();
      return true;
    },
    [commit, runBuild],
  );

  // ------------------------------------------------------------ quiet refresh after edits
  const refresh = useCallback(async () => {
    timerRef.current = null;
    const s = stateRef.current;
    if (!s.response) return;
    const draft = s.response.draft;
    if (draftProblems(draft).length) return;
    const rev = s.rev;
    bgAbortRef.current?.abort();
    const ac = new AbortController();
    bgAbortRef.current = ac;
    setChecking(true);
    let resp: IntakeResponse<AnyDraft>;
    try {
      resp =
        draft.domain === "schedule"
          ? await api.answerSchedule(draft, [], context, ac.signal)
          : await api.answerFinance(draft, [], context, ac.signal);
    } catch (err) {
      if (!isAbort(err)) setError(errorMessage(err));
      if (bgAbortRef.current === ac) {
        bgAbortRef.current = null;
        setChecking(false);
      }
      return;
    }
    if (bgAbortRef.current === ac) {
      bgAbortRef.current = null;
      setChecking(false);
    }
    // keep notes and extractor of the original read; questions come from the refreshed draft
    const prev = stateRef.current.response;
    applyResponse({ ...resp, notes: prev?.notes ?? resp.notes, row_notes: prev?.row_notes ?? [], extractor: prev?.extractor ?? resp.extractor }, rev);
  }, [applyResponse, context]);

  const editDraft = useCallback(
    (draft: AnyDraft, editedPaths: string[]) => {
      commit((x) =>
        x.response
          ? { ...x, response: { ...x.response, draft: markEdited(draft, editedPaths) }, build: null, buildRev: null, rev: x.rev + 1 }
          : x,
      );
      bgAbortRef.current?.abort();
      clearTimer();
      timerRef.current = window.setTimeout(() => void refresh(), REFRESH_DEBOUNCE_MS);
    },
    [commit, refresh],
  );

  // ------------------------------------------------------------ foreground requests
  const startForeground = (b: Exclude<Busy, null>, timeoutMs?: number) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setBusy(b);
    setError(null);
    let timedOut = false;
    const t = timeoutMs
      ? window.setTimeout(() => {
          timedOut = true;
          ac.abort();
        }, timeoutMs)
      : null;
    const done = () => {
      if (t) window.clearTimeout(t);
      if (abortRef.current === ac) {
        abortRef.current = null;
        setBusy(null);
      }
    };
    return { ac, done, timedOut: () => timedOut };
  };

  const describe = useCallback(
    async (useAi: boolean) => {
      const text = stateRef.current.text;
      if (!text.trim()) {
        setError("Write a few lines about your plan first.");
        return;
      }
      const { ac, done, timedOut } = startForeground("describe", useAi ? AI_TIMEOUT_MS : undefined);
      try {
        const body = { text, context, use_ai: useAi };
        const resp = domain === "schedule" ? await api.describeSchedule(body, ac.signal) : await api.describeFinance(body, ac.signal);
        applyResponse(resp, null, { step: "review", sourceText: text, history: [] });
      } catch (err) {
        if (isAbort(err)) {
          if (timedOut()) setError("AI assist took too long, so we stopped waiting. Try again, or turn AI assist off to use the built-in reader.");
        } else setError(errorMessage(err));
      } finally {
        done();
      }
    },
    [applyResponse, context, domain],
  );

  const cancelRequest = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const answer = useCallback(
    async (answers: Answer[], history: ChatEntry[]) => {
      const s = stateRef.current;
      if (!s.response || !answers.length) return;
      clearTimer();
      bgAbortRef.current?.abort();
      const draft = s.response.draft;
      const rev = s.rev;
      const { ac, done } = startForeground("answer");
      try {
        const resp =
          draft.domain === "schedule"
            ? await api.answerSchedule(draft, answers, context, ac.signal)
            : await api.answerFinance(draft as FinanceDraft, answers, context, ac.signal);
        const prev = stateRef.current.response;
        // entries whose question came back with an error were not used
        const failed = new Set(resp.questions.filter((q) => q.error).map((q) => q.id));
        applyResponse(
          { ...resp, notes: prev?.notes ?? resp.notes, row_notes: prev?.row_notes ?? [], extractor: prev?.extractor ?? resp.extractor },
          rev,
          { history: [...stateRef.current.history, ...history.filter((h) => !failed.has(h.id))] },
        );
      } catch (err) {
        if (!isAbort(err)) setError(errorMessage(err));
      } finally {
        done();
      }
    },
    [applyResponse, context],
  );

  const useAllSuggestions = useCallback(async () => {
    const seen = new Set<string>();
    for (let round = 0; round < 6; round++) {
      const s = stateRef.current;
      if (!s.response) return;
      const qs = s.response.questions.filter((q) => !seen.has(q.id) && !q.error);
      const answers = qs.map(quickAnswer).filter((a): a is Answer => a !== null);
      if (!answers.length) return;
      answers.forEach((a) => seen.add(a.question_id));
      const history: ChatEntry[] = qs
        .filter((q) => answers.some((a) => a.question_id === q.id))
        .map((q) => ({
          id: q.id,
          prompt: q.prompt,
          answer: q.default !== null && q.default !== undefined ? `Suggestion used${q.default_label ? `: ${q.default_label}` : ""}` : "Skipped",
        }));
      const revBefore = s.rev;
      await answer(answers, history);
      if (stateRef.current.rev === revBefore) return; // failed or superseded
    }
  }, [answer]);

  const checkDraft = useCallback(async () => {
    const s = stateRef.current;
    if (!s.response) return;
    if (draftProblems(s.response.draft).length) {
      setError("Some fields in the draft need fixing first; they are marked in the draft.");
      return;
    }
    if (timerRef.current) {
      clearTimer();
      await refresh();
      return; // refresh builds when nothing required is open
    }
    await runBuild();
  }, [refresh, runBuild]);

  // ------------------------------------------------------------ tables
  const setTable = useCallback(
    (patch: Partial<TableState>) => commit((x) => ({ ...x, table: { ...x.table, ...patch } })),
    [commit],
  );

  const parseTable = useCallback(
    async (override: { delimiter?: TableParseResult["delimiter"]; has_header?: boolean } = {}) => {
      const t = stateRef.current.table;
      if (!t.text.trim()) {
        setError("Paste a table or choose a file first.");
        return;
      }
      const { ac, done } = startForeground("parse");
      try {
        const body = { text: t.text, delimiter: override.delimiter ?? ("auto" as const), has_header: override.has_header ?? null };
        const res = domain === "schedule" ? await api.parseScheduleTable(body, ac.signal) : await api.parseFinanceTable(body, ac.signal);
        commit((x) => ({
          ...x,
          step: "map",
          table: { ...x.table, parse: res, mapping: res.columns.map((c) => c.suggested_field) },
        }));
      } catch (err) {
        if (!isAbort(err)) setError(errorMessage(err));
      } finally {
        done();
      }
    },
    [commit, domain],
  );

  const applyTable = useCallback(async () => {
    const t = stateRef.current.table;
    if (!t.parse) return;
    const { ac, done } = startForeground("apply");
    try {
      const body = {
        text: t.text,
        delimiter: t.parse.delimiter,
        has_header: t.parse.has_header,
        mapping: t.mapping.map((field, column) => ({ column, field })),
        options: t.options,
        context,
      };
      const resp =
        domain === "schedule" ? await api.applyScheduleTable(body, ac.signal) : await api.applyFinanceTable(body, ac.signal);
      applyResponse(resp, null, { step: "review", sourceText: null, history: [] });
    } catch (err) {
      if (!isAbort(err)) setError(errorMessage(err));
    } finally {
      done();
    }
  }, [applyResponse, context, domain]);

  // ------------------------------------------------------------ finish
  const clearStorage = useCallback(() => {
    clearedRef.current = true;
    try {
      window.sessionStorage.removeItem(storageKey(kind));
    } catch {
      /* ignore */
    }
  }, [kind]);

  const create = useCallback(async () => {
    const s = stateRef.current;
    const b = s.build;
    if (!b || !b.ready || s.buildRev !== s.rev) return;
    const { done } = startForeground("create");
    try {
      if (domain === "schedule") {
        const problem = (b as ScheduleBuildResult).problem;
        if (!problem) return;
        const rec = await createProblem(problem);
        clearStorage();
        navigate(`/plans/${rec.id}/tasks`);
      } else {
        const plan = (b as FinanceBuildResult).plan;
        if (!plan) return;
        const rec = await createFinancePlan(plan);
        clearStorage();
        navigate(`/finance/${rec.id}/setup/review`);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      done();
    }
  }, [clearStorage, domain, navigate]);

  const startOver = useCallback(() => {
    abortRef.current?.abort();
    bgAbortRef.current?.abort();
    clearTimer();
    setError(null);
    commit((x) => ({ ...initialState(kind, flow), text: x.text, table: { ...initialState(kind, flow).table, text: x.table.text, fileName: x.table.fileName } }));
  }, [commit, kind, flow]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    bgAbortRef.current?.abort();
    clearTimer();
    clearStorage();
    navigate(`/new/${kind}`);
  }, [clearStorage, kind, navigate]);

  const value: IntakeApi = {
    state,
    domain,
    context,
    capabilities: caps.data,
    limits: caps.data?.limits ?? DEFAULT_LIMITS,
    busy,
    checking,
    error,
    buildFresh: state.build !== null && state.buildRev === state.rev,
    activePath,
    setActivePath,
    clearError: () => setError(null),
    setText: (t: string) => commit((x) => ({ ...x, text: t })),
    setTable,
    setStep: (step: IntakeStep) => commit((x) => ({ ...x, step })),
    describe,
    cancelRequest,
    answer,
    useAllSuggestions,
    editDraft,
    checkDraft,
    parseTable,
    applyTable,
    create,
    startOver,
    cancel,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export type { ScheduleDraft, FinanceDraft };

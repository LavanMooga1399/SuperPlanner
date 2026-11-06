/**
 * Planning assistant panel (M6 1). Used as a side panel on the desktop Manufacturing pages and as a full screen on
 * `/m/assistant`.
 * - **Quick explanations** (1.7) are always offered for the current page ("Why late?", "What limits this week?",
 *   "What changed?"); they are deterministic server answers, nothing is sent to the AI provider.
 * - **Ask** (1.2): the question runs on the server; the panel polls the turn every second and shows its steps
 *   (thinking, each tool with its summary, answer). One running question per user; Stop cancels it.
 * - Answers are a markdown subset rendered as text; citations become internal links only when the server issued
 *   them with an internal path (`AnswerText`). Draft actions are cards with an explicit Apply (`DraftCardView`).
 * - When the AI part is off, opted out by the plant, over budget or unreachable, the reason (code + text) is shown
 *   and the quick explanations stay usable. The privacy notice is shown before the first question per user.
 * - The what-if switch (1.2 `allow_whatif`, off by default) sits behind "More options".
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { ApiError } from "../../api/client";
import { Icon } from "../../components/Icon";
import {
  cancelTurn,
  createConversation,
  deleteConversation,
  getAssistantStatus,
  getConversation,
  getQuickExplanation,
  getTurn,
  listConversations,
  startTurn,
} from "../api/clientM6";
import type { AssistantStatus, AssistantTurn, Conversation, QuickExplanation, QuickKind } from "../api/typesM6";
import { useAccess } from "../lib/permissions";
import { errorText, isAbortError, useLoad } from "../lib/useMfg";
import { currentWorkspace } from "../lib/workspace";
import { AnswerText, CitationList } from "./AnswerText";
import { DraftCardView } from "./DraftCardView";
import { aiCodeText, budgetText, contextFromPath, isLastingCode, LATE_CONTEXTS, stepView, SUGGESTED_QUESTIONS } from "./assistantText";

const FINAL = new Set(["completed", "failed", "cancelled"]);
const convKey = () => `sp.asst.conversation.${currentWorkspace() ?? "own"}`;
const privacyKey = (uid: string) => `sp.asst.privacy.${uid || "me"}`;

function readSession(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeSession(key: string, v: string | null) {
  try {
    if (v) sessionStorage.setItem(key, v);
    else sessionStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/** The P2 code of a refused call: 422 carries it in `details.code`, 409 `AI_TURN_RUNNING` as the code itself. */
export function aiErrorCode(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  const d = e.details?.code;
  if (typeof d === "string") return d;
  return e.code.startsWith("AI_") || e.code === "MFG_FORBIDDEN" ? e.code : null;
}

function turnError(t: AssistantTurn): { code: string | null; text: string } | null {
  if (t.status === "cancelled") return { code: null, text: "Stopped." };
  if (t.status !== "failed") return null;
  const code = t.error?.code ?? t.error_code ?? null;
  return { code, text: t.error?.message || aiCodeText(code, "The question could not be answered.") };
}

// ---------------------------------------------------------------- quick explanations
function QuickExplanations({ context, onNavigate }: { context: ReturnType<typeof contextFromPath>; onNavigate?: () => void }) {
  const [res, setRes] = useState<{ kind: QuickKind; data: QuickExplanation | null; error: unknown; busy: boolean } | null>(null);
  const ctl = useRef<AbortController | null>(null);
  const run = (kind: QuickKind) => {
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    setRes({ kind, data: null, error: null, busy: true });
    const q = kind === "why_late" && context ? { kind, type: context.type, id: context.id } : { kind };
    getQuickExplanation(q, c.signal).then(
      (data) => !c.signal.aborted && setRes({ kind, data, error: null, busy: false }),
      (error: unknown) => !c.signal.aborted && !isAbortError(error) && setRes({ kind, data: null, error, busy: false }),
    );
  };
  useEffect(() => () => ctl.current?.abort(), []);
  const late = context && LATE_CONTEXTS.has(context.type);
  return (
    <section className="asst-section" aria-labelledby="asst-quick-h" data-testid="asst-quick">
      <h3 id="asst-quick-h" className="asst-h">
        Quick explanations <span className="muted small">(built in, nothing leaves the plant)</span>
      </h3>
      <div className="row wrap" style={{ gap: 6 }}>
        {late ? (
          <button type="button" className="btn sm" onClick={() => run("why_late")} aria-pressed={res?.kind === "why_late"} data-testid="asst-quick-why_late">
            <Icon name="clock" /> Why late?
          </button>
        ) : null}
        <button type="button" className="btn sm" onClick={() => run("limits")} aria-pressed={res?.kind === "limits"} data-testid="asst-quick-limits">
          <Icon name="graph" /> What limits this week?
        </button>
        <button type="button" className="btn sm" onClick={() => run("changes")} aria-pressed={res?.kind === "changes"} data-testid="asst-quick-changes">
          <Icon name="refresh" /> What changed?
        </button>
      </div>
      {!late ? <p className="muted small" style={{ margin: 0 }}>Open a demand order or work order for "Why late?".</p> : null}
      <div aria-live="polite">
        {res?.busy ? (
          <p className="muted small" role="status">
            <span className="spinner" aria-hidden /> Looking it up…
          </p>
        ) : null}
        {res?.error ? (
          <p className="asst-msg danger" role="alert" data-testid="asst-quick-error">
            <Icon name="alert" size={14} /> {errorText(res.error)}
          </p>
        ) : null}
        {res?.data ? (
          <div className="asst-bubble" data-testid="asst-quick-result" data-kind={res.data.kind}>
            <strong>{res.data.title}</strong>
            {res.data.empty && !res.data.answer ? <p className="muted">Nothing to explain here.</p> : <AnswerText text={res.data.answer} citations={res.data.citations} onNavigate={onNavigate} testId="asst-quick-answer" />}
            <CitationList citations={res.data.citations} onNavigate={onNavigate} />
          </div>
        ) : null}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- one question and its answer
function TurnView({ turn, onNavigate, onStop }: { turn: AssistantTurn; onNavigate?: () => void; onStop?: () => void }) {
  const err = turnError(turn);
  const running = !FINAL.has(turn.status);
  const steps = (turn.steps ?? []).map(stepView);
  return (
    <li className="asst-turn" data-testid="asst-turn" data-status={turn.status}>
      <div className="asst-q">
        <span className="sr-only">You asked: </span>
        {turn.user_text}
      </div>
      {running ? (
        <div className="asst-progress" role="status" aria-live="polite" data-testid="asst-progress">
          <ol className="asst-steps">
            {steps.length === 0 ? <li>Waiting for a free slot…</li> : null}
            {steps.map((s, i) => (
              <li key={i} data-kind={s.kind}>
                <Icon name={i === steps.length - 1 ? "loader" : "check"} size={12} /> {s.text}
              </li>
            ))}
          </ol>
          {onStop ? (
            <button type="button" className="btn sm" onClick={onStop} data-testid="asst-stop">
              <Icon name="stop" /> Stop
            </button>
          ) : null}
        </div>
      ) : steps.length ? (
        <details className="asst-steps-done">
          <summary className="muted small">How this was found ({steps.length} steps)</summary>
          <ol className="asst-steps">
            {steps.map((s, i) => (
              <li key={i} data-kind={s.kind}>
                {s.text}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
      {err ? (
        <p className={`asst-msg ${turn.status === "failed" ? "danger" : ""}`} role={turn.status === "failed" ? "alert" : "status"} data-testid="asst-turn-error">
          <Icon name={turn.status === "failed" ? "alert" : "stop"} size={14} /> {err.text}
          {err.code ? <span className="chip mono" style={{ marginLeft: 6 }}>{err.code}</span> : null}
          {turn.status === "failed" ? <span className="muted small"> The quick explanations above still work.</span> : null}
        </p>
      ) : null}
      {turn.answer ? (
        <div className="asst-bubble">
          <AnswerText text={turn.answer} citations={turn.citations ?? []} onNavigate={onNavigate} />
          <CitationList citations={turn.citations ?? []} onNavigate={onNavigate} />
          <p className="muted small" style={{ margin: 0 }}>
            <Icon name="info" size={12} /> Answers may be wrong; check the linked records.
          </p>
        </div>
      ) : null}
      {(turn.notes ?? []).map((n, i) => (
        <p key={i} className="muted small" style={{ margin: 0 }}>
          <Icon name="info" size={12} /> {n}
        </p>
      ))}
      {(turn.drafts ?? []).length ? (
        <div className="col" style={{ gap: 8 }} data-testid="asst-drafts">
          <span className="small muted">Suggested actions (nothing is changed until you apply one):</span>
          {turn.drafts.map((d) => (
            <DraftCardView key={d.draft_id} draft={d} />
          ))}
        </div>
      ) : null}
    </li>
  );
}

// ---------------------------------------------------------------- ask
function Unavailable({ status, onRetry }: { status: AssistantStatus | null; onRetry(): void }) {
  const code = status?.code ?? null;
  return (
    <div className="asst-off" role="status" data-testid="asst-unavailable" data-code={code ?? ""}>
      <Icon name={code === "AI_PLANT_OPTED_OUT" ? "ban" : "info"} />
      <div>
        <strong>Asking in your own words is not available</strong>
        <p style={{ margin: "2px 0" }}>{aiCodeText(code)}</p>
        {code ? <span className="chip mono" data-testid="asst-code">{code}</span> : null}
        <p className="muted small" style={{ margin: "4px 0 0" }}>The quick explanations above work without it.</p>
        {!isLastingCode(code) ? (
          <button type="button" className="btn sm mt" onClick={onRetry}>
            <Icon name="refresh" /> Check again
          </button>
        ) : null}
      </div>
    </div>
  );
}

function PrivacyNotice({ text, onAccept }: { text: string; onAccept(): void }) {
  return (
    <div className="asst-privacy" data-testid="asst-privacy">
      <strong>
        <Icon name="lock" size={14} /> Before you ask
      </strong>
      <p style={{ margin: "4px 0 8px" }}>{text}</p>
      <button type="button" className="btn primary sm" onClick={onAccept} data-testid="asst-privacy-accept">
        I understand
      </button>
    </div>
  );
}

function Ask({ status, reloadStatus, onNavigate }: { status: AssistantStatus; reloadStatus(): void; onNavigate?: () => void }) {
  const access = useAccess();
  const loc = useLocation();
  const context = contextFromPath(loc.pathname, loc.search);
  const uid = access.me?.user_id ?? "";
  const [accepted, setAccepted] = useState(() => {
    try {
      return localStorage.getItem(privacyKey(uid)) === "1";
    } catch {
      return false;
    }
  });
  const [convId, setConvId] = useState<string | null>(() => readSession(convKey()));
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [text, setText] = useState("");
  const [sendCtx, setSendCtx] = useState(true);
  const [whatif, setWhatif] = useState(false);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ code: string | null; text: string } | null>(null);
  const [history, setHistory] = useState<Conversation[] | null>(null);
  const pollRef = useRef<number | null>(null);
  const listEnd = useRef<HTMLLIElement | null>(null);
  const running = turns.find((t) => !FINAL.has(t.status)) ?? null;
  const whatifAllowed = status.allow_whatif !== false;

  // load the remembered conversation
  useEffect(() => {
    if (!convId) return;
    const c = new AbortController();
    getConversation(convId, c.signal).then(
      (conv) => {
        setTurns(conv.turns ?? []);
        setWhatif(conv.allow_whatif && whatifAllowed);
      },
      (e: unknown) => {
        if (isAbortError(e)) return;
        writeSession(convKey(), null);
        setConvId(null);
        setTurns([]);
      },
    );
    return () => c.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convId]);

  // poll the running turn every second (1.2)
  const poll = useCallback((turnId: string) => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
    const tick = () => {
      getTurn(turnId).then(
        (t) => {
          setTurns((prev) => prev.map((x) => (x.id === t.id ? t : x)));
          if (!FINAL.has(t.status)) pollRef.current = window.setTimeout(tick, 1000);
          else {
            pollRef.current = null;
            reloadStatus();
          }
        },
        () => {
          // a lost poll is retried a bit later (network blip); the server marks dead turns failed after 3 min
          pollRef.current = window.setTimeout(tick, 3000);
        },
      );
    };
    pollRef.current = window.setTimeout(tick, 1000);
  }, [reloadStatus]);
  useEffect(() => {
    if (running && !pollRef.current) poll(running.id);
  }, [running, poll]);
  useEffect(() => () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
  }, []);
  useEffect(() => {
    listEnd.current?.scrollIntoView?.({ block: "nearest" });
  }, [turns.length]);

  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy || running) return;
    setBusy(true);
    setErr(null);
    try {
      let id = convId;
      if (!id) {
        const conv = await createConversation({ title: question.slice(0, 80), allow_whatif: whatif });
        id = conv.id;
        setConvId(id);
        writeSession(convKey(), id);
      }
      const r = await startTurn(id, { text: question.slice(0, 4000), context: sendCtx && context ? { type: context.type, id: context.id } : null, allow_whatif: whatif });
      setTurns((prev) => [...prev, { id: r.turn_id, conversation_id: id!, status: "queued", user_text: question, steps: [], answer: null, citations: [], drafts: [] }]);
      setText("");
      poll(r.turn_id);
    } catch (e) {
      const code = aiErrorCode(e);
      setErr({ code, text: code ? aiCodeText(code, errorText(e)) : errorText(e) });
      if (code && isLastingCode(code)) reloadStatus();
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!running) return;
    try {
      const t = await cancelTurn(running.id);
      setTurns((prev) => prev.map((x) => (x.id === t.id ? t : x)));
    } catch (e) {
      setErr({ code: aiErrorCode(e), text: errorText(e) });
    }
  };

  const newConversation = () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
    pollRef.current = null;
    writeSession(convKey(), null);
    setConvId(null);
    setTurns([]);
    setErr(null);
  };

  const loadHistory = () => {
    listConversations().then(
      (r) => setHistory(r.items),
      (e: unknown) => setErr({ code: null, text: errorText(e) }),
    );
  };

  if (!accepted)
    return (
      <PrivacyNotice
        text={status.privacy_notice}
        onAccept={() => {
          try {
            localStorage.setItem(privacyKey(uid), "1");
          } catch {
            /* shown again next time */
          }
          setAccepted(true);
        }}
      />
    );

  const budget = budgetText(status.budget_left);
  return (
    <div className="col" style={{ gap: 10 }} data-testid="asst-ask">
      {turns.length === 0 ? (
        <div className="col" style={{ gap: 6 }}>
          <span className="muted small">For example:</span>
          {SUGGESTED_QUESTIONS.map((q) => (
            <button key={q} type="button" className="btn ghost sm asst-suggest" onClick={() => void send(q)} disabled={busy || Boolean(running)}>
              {q}
            </button>
          ))}
        </div>
      ) : (
        <ol className="asst-turns" aria-label="Conversation">
          {turns.map((t) => (
            <TurnView key={t.id} turn={t} onNavigate={onNavigate} onStop={t === running ? () => void stop() : undefined} />
          ))}
          <li ref={listEnd} aria-hidden style={{ listStyle: "none" }} />
        </ol>
      )}
      {err ? (
        <p className="asst-msg danger" role="alert" data-testid="asst-error">
          <Icon name="alert" size={14} /> {err.text}
          {err.code ? <span className="chip mono" style={{ marginLeft: 6 }}>{err.code}</span> : null}
        </p>
      ) : null}
      <form
        className="col"
        style={{ gap: 6 }}
        onSubmit={(e) => {
          e.preventDefault();
          void send(text);
        }}
      >
        <label htmlFor="asst-input" className="small" style={{ fontWeight: 600 }}>
          Ask about your plan
        </label>
        <textarea
          id="asst-input"
          className="textarea"
          rows={3}
          maxLength={4000}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(text);
            }
          }}
          placeholder="e.g. Why is DO-KV-003/10 late and what can I do?"
          data-testid="asst-input"
        />
        {context ? (
          <label className="checkbox small">
            <input type="checkbox" checked={sendCtx} onChange={(e) => setSendCtx(e.target.checked)} data-testid="asst-context" /> Ask about {context.label}
          </label>
        ) : null}
        <div className="row wrap" style={{ gap: 8, justifyContent: "space-between" }}>
          <button type="submit" className="btn primary sm" disabled={busy || Boolean(running) || !text.trim()} data-testid="asst-send">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />} Ask
          </button>
          {budget ? <span className="muted small" data-testid="asst-budget">{budget}</span> : null}
        </div>
      </form>
      <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={more} onClick={() => setMore((v) => !v)} data-testid="asst-more">
        <Icon name={more ? "chevron-down" : "chevron-right"} /> More options
      </button>
      {more ? (
        <div className="col" style={{ gap: 8 }} data-testid="asst-options">
          <label className="switch small">
            <input
              type="checkbox"
              checked={whatif}
              disabled={!whatifAllowed}
              onChange={(e) => setWhatif(e.target.checked)}
              data-testid="asst-whatif"
            />
            Let the assistant try what-if plans
          </label>
          <span className="muted small">
            {whatifAllowed
              ? "It may start what-if MRP or schedule runs to answer with numbers. They are never live and cannot be published. Off by default."
              : "This plant does not allow what-if runs by the assistant."}
          </span>
          <div className="row wrap" style={{ gap: 6 }}>
            <button type="button" className="btn sm" onClick={newConversation} disabled={Boolean(running)} data-testid="asst-new">
              <Icon name="plus" /> New conversation
            </button>
            <button type="button" className="btn sm" onClick={loadHistory} data-testid="asst-history">
              <Icon name="list" /> Earlier conversations
            </button>
          </div>
          {history ? (
            history.length === 0 ? (
              <p className="muted small">No earlier conversations. They are kept for 30 days.</p>
            ) : (
              <ul className="asst-history">
                {history.map((c) => (
                  <li key={c.id} className="row" style={{ justifyContent: "space-between", gap: 6 }}>
                    <button type="button" className="btn link" onClick={() => { writeSession(convKey(), c.id); setConvId(c.id); }}>
                      {c.title || "Untitled"}
                    </button>
                    <span className="muted small">{new Date(c.updated_at).toLocaleDateString()}</span>
                    <button
                      type="button"
                      className="btn ghost icon sm"
                      aria-label={`Delete conversation ${c.title}`}
                      onClick={() =>
                        void deleteConversation(c.id).then(() => {
                          setHistory((h) => (h ?? []).filter((x) => x.id !== c.id));
                          if (c.id === convId) newConversation();
                        }, (e: unknown) => setErr({ code: null, text: errorText(e) }))
                      }
                    >
                      <Icon name="trash" />
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : null}
          <p className="muted small" style={{ margin: 0 }}>Conversations are stored in this plant for 30 days and only you can see them.</p>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- panel
export function AssistantBody({ onNavigate }: { onNavigate?: () => void }) {
  const access = useAccess();
  const loc = useLocation();
  const context = contextFromPath(loc.pathname, loc.search);
  const mayUse = access.can("assistant_use");
  const status = useLoad((signal) => (mayUse ? getAssistantStatus(signal) : null), [mayUse]);
  const st = status.data;
  return (
    <div className="col" style={{ gap: 16 }}>
      <QuickExplanations context={context} onNavigate={onNavigate} />
      <section className="asst-section" aria-labelledby="asst-ask-h">
        <h3 id="asst-ask-h" className="asst-h">
          Ask the assistant
        </h3>
        {!mayUse && !access.loading ? (
          <Unavailable status={{ available: false, code: "MFG_FORBIDDEN", privacy_notice: "", budget_left: null }} onRetry={() => undefined} />
        ) : status.loading && !st ? (
          <p className="muted small" role="status">
            <span className="spinner" aria-hidden /> Checking…
          </p>
        ) : status.error && !st ? (
          <Unavailable status={{ available: false, code: aiErrorCode(status.error) ?? "AI_CONNECTION_ERROR", privacy_notice: "", budget_left: null }} onRetry={status.reload} />
        ) : st && !st.available ? (
          <Unavailable status={st} onRetry={status.reload} />
        ) : st ? (
          <Ask status={st} reloadStatus={status.reload} onNavigate={onNavigate} />
        ) : null}
      </section>
    </div>
  );
}

/** The side panel of the desktop pages (non-modal: the page stays usable next to it). */
export function AssistantDrawer({ onClose }: { onClose(): void }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside className="drawer asst-drawer" role="dialog" aria-modal="false" aria-labelledby="asst-title" data-testid="asst-panel" tabIndex={-1} ref={ref}>
      <div className="drawer-header">
        <div className="grow">
          <h2 id="asst-title" style={{ margin: 0, fontSize: 17 }}>
            Planning assistant
          </h2>
          <span className="muted small">Explains your plan and suggests actions. It never changes anything by itself.</span>
        </div>
        <button type="button" className="btn ghost icon" onClick={onClose} aria-label="Close the assistant" data-testid="asst-close">
          <Icon name="x" />
        </button>
      </div>
      <div className="drawer-body">
        <AssistantBody />
      </div>
    </aside>
  );
}

/** Top-bar button of the Manufacturing nav. */
export function AssistantButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="btn sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} data-testid="asst-open">
        <Icon name="help" /> Assistant
      </button>
      {open ? <AssistantDrawer onClose={() => setOpen(false)} /> : null}
    </>
  );
}

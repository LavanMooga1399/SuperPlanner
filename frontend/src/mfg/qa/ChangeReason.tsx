/**
 * Part 11 change reasons (M7-DESIGN 4.4, review m4): the reason dialog, `useChangeReason()` for screens that ask up
 * front, and `ChangeReasonHost` - mounted once in the app shell - which answers 422 `AUDIT_REASON_REQUIRED` from any
 * regulated save (ECO, items, BOMs, work orders, ...) with the same dialog; the request is then repeated with the
 * reason in `X-SP-Change-Reason`.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Dialog } from "../../components/Dialog";
import { setReasonPrompt } from "../api/client";
import { savePref, syncPref } from "../../lib/serverPrefs";
import { t } from "../../lib/i18n";
import { usePart11 } from "./part11";

const REASONS_PREF = "qa.reasons";
const REASONS_LOCAL = "sp.qa.reasons";
function recentReasons(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(REASONS_LOCAL) ?? "[]") as unknown;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, 6) : [];
  } catch {
    return [];
  }
}

/**
 * Part 11 plants: every save of a regulated record asks for a reason (sent as `X-SP-Change-Reason`). Outside Part
 * 11 mode `ask()` resolves at once with "" (no header). Recent reasons are offered (server preference `qa.reasons`).
 */
export function useChangeReason(): { ask(what: string): Promise<string | null>; dialog: ReactNode; required: boolean } {
  const { enabled } = usePart11();
  const [pending, setPending] = useState<{ what: string; resolve(v: string | null): void } | null>(null);
  useEffect(() => syncPref<string[]>(REASONS_PREF, REASONS_LOCAL, () => undefined), []);
  const ask = (what: string) => (enabled ? new Promise<string | null>((resolve) => setPending({ what, resolve })) : Promise.resolve(""));
  const dialog = pending ? (
    <ChangeReasonDialog
      what={pending.what}
      onDone={(v) => {
        if (v) savePref(REASONS_PREF, REASONS_LOCAL, [v, ...recentReasons().filter((x) => x !== v)].slice(0, 6));
        pending.resolve(v);
        setPending(null);
      }}
    />
  ) : null;
  return { ask, dialog, required: enabled };
}

export function ChangeReasonDialog({ what, onDone }: { what: string; onDone(v: string | null): void }) {
  const [text, setText] = useState("");
  const recent = recentReasons();
  return (
    <Dialog
      title={t("qa.reason.title")}
      onClose={() => onDone(null)}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onDone(null)} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!text.trim()} onClick={() => onDone(text.trim())} data-testid="change-reason-save">
            {t("qa.reason.btn.save")}
          </button>
        </>
      }
    >
      <form
        className="col"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onDone(text.trim());
        }}
      >
        <p style={{ margin: 0 }}>{t("qa.reason.tpl.body", { what })}</p>
        <div className="field">
          <label htmlFor="qa-reason">{t("qa.reason.label")}</label>
          <textarea id="qa-reason" className="textarea" rows={3} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} data-testid="change-reason" data-autofocus />
          <span className="hint">{t("qa.esig.tpl.chars", { n: text.length })}</span>
        </div>
        {recent.length ? (
          <div className="col" style={{ gap: 4 }}>
            <span className="small muted">{t("qa.reason.recent")}</span>
            <div className="chips">
              {recent.map((r) => (
                <button key={r} type="button" className="chip" style={{ cursor: "pointer", border: 0 }} onClick={() => setText(r)}>
                  {r}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </form>
    </Dialog>
  );
}

/** Answers `AUDIT_REASON_REQUIRED` from any regulated save with the reason dialog (one at a time). */
export function ChangeReasonHost() {
  const [pending, setPending] = useState<{ resolve(v: string | null): void } | null>(null);
  useEffect(() => setReasonPrompt(() => new Promise<string | null>((resolve) => setPending({ resolve }))), []);
  return pending ? (
    <ChangeReasonDialog
      what={t("qa.reason.str.thisRecord")}
      onDone={(v) => {
        if (v) savePref(REASONS_PREF, REASONS_LOCAL, [v, ...recentReasons().filter((x) => x !== v)].slice(0, 6));
        pending.resolve(v);
        setPending(null);
      }}
    />
  ) : null;
}

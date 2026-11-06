/**
 * A draft action card (M6 1.4): what the assistant suggests, as the exact request it would take. Nothing happens
 * until the user presses Apply and confirms; the request is then sent as the user (session, CSRF, workspace,
 * If-Match of the record the draft was built from), so permissions, validation and audit are those of the normal
 * page. The server is told the outcome (A10) for the audit trail. Without the needed permission Apply is disabled.
 */
import { useState } from "react";
import { Icon } from "../../components/Icon";
import { applyDraft, reportDraftApplied, requestPath } from "../api/clientM6";
import type { Permission } from "../api/typesM2";
import type { DraftCard } from "../api/typesM6";
import { needsText, PERMISSION_ROLES, useAccess } from "../lib/permissions";
import { errorCode, errorText, isConflict } from "../lib/useMfg";
import { draftKindText } from "./assistantText";

type State = { s: "idle" } | { s: "confirm" } | { s: "busy" } | { s: "done"; at: string } | { s: "error"; text: string };

function responseRef(data: unknown): string | null {
  if (data && typeof data === "object" && "id" in data && typeof (data as { id: unknown }).id === "string") return (data as { id: string }).id;
  return null;
}

export function DraftCardView({ draft }: { draft: DraftCard }) {
  const access = useAccess();
  const [st, setSt] = useState<State>(
    draft.applied_at && draft.applied_status !== "failed" ? { s: "done", at: draft.applied_at } : { s: "idle" },
  );
  const perm = draft.required_permission as Permission;
  const known = perm in PERMISSION_ROLES;
  // the server says whether the asking user holds the permission (`allowed`); the role here must agree too
  const allowed = draft.allowed && known && access.can(perm);
  const sendable = requestPath(draft) !== null;

  const apply = async () => {
    setSt({ s: "busy" });
    try {
      const r = await applyDraft(draft);
      setSt({ s: "done", at: new Date().toISOString() });
      void reportDraftApplied(draft.draft_id, { status: "succeeded", response_ref: responseRef(r.data) }).catch(() => undefined);
    } catch (e) {
      const text = isConflict(e)
        ? "The record changed after this suggestion was made, so nothing was changed. Open the record to check it, or ask again for a fresh suggestion."
        : errorText(e);
      setSt({ s: "error", text });
      void reportDraftApplied(draft.draft_id, { status: "failed", response_ref: errorCode(e) }).catch(() => undefined);
    }
  };

  return (
    <article className="asst-draft" data-testid="asst-draft" data-kind={draft.kind} aria-label={`Suggestion: ${draftKindText(draft.kind)}`}>
      <header className="row" style={{ justifyContent: "space-between", gap: 8 }}>
        <strong>
          <Icon name="file" size={14} /> {draftKindText(draft.kind)}
        </strong>
        <span className="chip" data-testid="asst-draft-state">
          {st.s === "done" ? (
            <>
              <Icon name="check" size={12} /> Applied
            </>
          ) : (
            <>
              <Icon name="circle" size={12} /> Suggestion, not applied
            </>
          )}
        </span>
      </header>
      <p className="asst-draft-summary">{draft.summary}</p>
      <details className="asst-draft-request">
        <summary>Show the exact request</summary>
        <div className="mono small" data-testid="asst-draft-request">
          {draft.method} {draft.path}
          {draft.if_match_of ? ` (only if ${draft.if_match_of.type.replace(/_/g, " ")} is still at version ${draft.if_match_of.row_version})` : ""}
        </div>
        {draft.body !== undefined && draft.body !== null ? <pre className="asst-draft-body">{JSON.stringify(draft.body, null, 2)}</pre> : null}
      </details>
      {st.s === "error" ? (
        <div className="asst-draft-msg danger" role="alert" data-testid="asst-draft-error">
          <Icon name="alert" size={14} /> {st.text}
        </div>
      ) : null}
      {st.s === "done" ? (
        <div className="asst-draft-msg ok" role="status" data-testid="asst-draft-done">
          <Icon name="check" size={14} /> Applied {new Date(st.at).toLocaleString()}. It is recorded under your name like any change on the page.
        </div>
      ) : null}
      {st.s !== "done" ? (
        <div className="row wrap" style={{ gap: 8 }}>
          {st.s === "confirm" ? (
            <>
              <span className="small">Apply this change now, as you?</span>
              <button type="button" className="btn primary sm" onClick={() => void apply()} data-testid="asst-draft-confirm">
                <Icon name="check" /> Yes, apply
              </button>
              <button type="button" className="btn sm" onClick={() => setSt({ s: "idle" })}>
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn sm"
              disabled={!allowed || !sendable || st.s === "busy"}
              title={!allowed ? (known ? needsText(perm) : "This suggestion needs a permission the app does not know.") : !sendable ? "This suggestion cannot be sent." : undefined}
              onClick={() => setSt({ s: "confirm" })}
              data-testid="asst-draft-apply"
            >
              {st.s === "busy" ? <span className="spinner" aria-hidden /> : <Icon name="play" />} Apply
            </button>
          )}
          {!allowed ? (
            <span className="muted small" data-testid="asst-draft-needs">
              <Icon name="lock" size={12} /> {known ? needsText(perm) : "Not available for your role."}
            </span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

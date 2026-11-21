/** Error, conflict and loading feedback shared by the Manufacturing pages. */
import type { ReactNode } from "react";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { SkeletonPage } from "../../components/Skeleton";
import { errorText, isForbidden, isNotFound } from "../lib/useMfg";
import { ApiError, networkError } from "../../api/client";
import { t } from "../../lib/i18n";

const NETWORK_MESSAGE = networkError().message;

/** Version conflict (412): the user's edits stay on screen until they choose to reload. */
export function ConflictBanner({ onReload, what = "this record" }: { onReload(): void; what?: string }) {
  return (
    <Banner
      tone="warn"
      role="alert"
      testId="conflict-banner"
      title="Someone else changed this in the meantime"
      actions={
        <button type="button" className="btn sm" onClick={onReload} data-testid="conflict-reload">
          <Icon name="refresh" /> Reload latest (discard my changes)
        </button>
      }
    >
      Your changes to {what} were not saved. They are still in the form below; copy anything you need, then reload
      to see the latest version.
    </Banner>
  );
}

export function MfgError({ error, onRetry, title }: { error: unknown; onRetry?(): void; title?: string }) {
  if (!error) return null;
  const text = errorText(error);
  if (isForbidden(error))
    return (
      <Banner tone="warn" role="alert" icon="lock" title="Not allowed for your role" testId="forbidden-banner">
        {text}
      </Banner>
    );
  const network = text === NETWORK_MESSAGE;
  return (
    <Banner
      tone="danger"
      role="alert"
      title={title ?? (network ? "Server not reachable" : isNotFound(error) ? "Not found" : "Something went wrong")}
      testId={network ? "network-error" : "mfg-error"}
      actions={
        onRetry ? (
          <button type="button" className="btn sm" onClick={onRetry}>
            <Icon name="refresh" /> Retry
          </button>
        ) : null
      }
    >
      {text}
      <RequestRef error={error} />
    </Banner>
  );
}

/** "Reference: <request id>" with a copy button, for errors that came back from the server. */
export function RequestRef({ error }: { error: unknown }) {
  const id = error instanceof ApiError ? error.requestId : undefined;
  if (!id) return null;
  return (
    <div className="ref-id" data-testid="error-ref">
      {t("error.reference")} <code>{id}</code>
      <button type="button" className="btn ghost sm icon" aria-label={t("error.copyReference")} title={t("error.copyReference")} onClick={() => void navigator.clipboard?.writeText(id).catch(() => undefined)}>
        <Icon name="copy" size={12} />
      </button>
    </div>
  );
}

export function NotFoundPanel({ what, back }: { what: string; back?: ReactNode }) {
  return (
    <div className="empty" data-testid="mfg-not-found">
      <Icon name="help" size={32} />
      <h2>{what} not found</h2>
      <p>It does not exist, or it belongs to another account.</p>
      {back}
    </div>
  );
}

/** Page/section loading state: a skeleton that reserves the layout (UX-STANDARD 4); `label` is announced. */
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <SkeletonPage label={label} rows={5} />;
}

/** Inline saved / saving state. */
export function SaveState({ busy, saved }: { busy: boolean; saved: boolean }) {
  if (busy)
    return (
      <span className="save-state" role="status">
        <span className="spinner" aria-hidden /> Saving…
      </span>
    );
  if (saved)
    return (
      <span className="save-state" role="status">
        <Icon name="check" size={14} /> Saved
      </span>
    );
  return null;
}

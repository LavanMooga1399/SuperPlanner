/**
 * Release dialog shared by BOMs and routings (M 4.2, 9.3 #18/#25). A blocked release (422
 * `MFG_RELEASE_BLOCKED`) lists the server's issues with their own "Fix" links (never built by the UI).
 */
import { useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import type { HealthIssue, ReleaseRequest } from "../api/types";
import { CheckField, TextField } from "./Field";
import { MfgError } from "./Feedback";
import { SeverityBadge } from "./StatusChip";
import { t } from "../../lib/i18n";

function blockedIssues(err: unknown): HealthIssue[] {
  if (!(err instanceof ApiError) || err.code !== "MFG_RELEASE_BLOCKED") return [];
  const list = err.details.issues;
  return Array.isArray(list) ? (list as HealthIssue[]) : [];
}

export function ReleaseDialog({
  what,
  defaultFrom,
  hasReleased,
  onClose,
  onRelease,
}: {
  what: string;
  defaultFrom: string;
  hasReleased: boolean;
  onClose(): void;
  onRelease(body: ReleaseRequest): Promise<void>;
}) {
  const [from, setFrom] = useState(defaultFrom);
  const [supersede, setSupersede] = useState(hasReleased);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const issues = blockedIssues(error);
  const needsDate = supersede && !from;
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onRelease({ effective_from: from || null, supersede_previous: supersede });
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("mfg.documentActions.tpl.release", { what: what })}
      onClose={onClose}
      wide={issues.length > 0}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("mfg.documentActions.btn.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={busy || needsDate} onClick={() => void run()} data-testid="release-confirm">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />}{" "}{t("mfg.documentActions.text.release")}
          </button>
        </>
      }
    >
      <p className="muted small" style={{ margin: 0 }}>
        {t("mfg.documentActions.text.aReleasedVersionIsRead")}
      </p>
      <TextField
        label={t("mfg.documentActions.label.useFrom")}
        type="date"
        value={from}
        onChange={setFrom}
        testId="release-from"
        hint={t("mfg.documentActions.hint.emptyValidFromThe")}
      />
      {hasReleased ? (
        <CheckField
          label={t("mfg.documentActions.label.replaceTheCurrentReleasedVersion")}
          checked={supersede}
          onChange={setSupersede}
          testId="release-supersede"
          hint={needsDate ? t("mfg.documentActions.str.chooseAStartDateTo") : t("mfg.documentActions.str.theOlderVersionGetsThis")}
        />
      ) : null}
      {issues.length ? (
        <div className="col" role="alert" data-testid="release-blocked">
          <strong>{error instanceof ApiError ? error.message : t("mfg.documentActions.str.releaseBlocked")}</strong>
          <ul className="mfg-plain-list">
            {issues.map((i, n) => (
              <li key={n} className="issue">
                <SeverityBadge severity={i.severity} />
                <div className="grow">
                  <div>{i.message}</div>
                  <div className="muted small">{i.fix}</div>
                </div>
                {i.link ? (
                  <Link className="btn sm" to={i.link} onClick={onClose}>
                    {t("mfg.documentActions.btn.fix")}
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <MfgError error={error} title={t("mfg.documentActions.attr.couldNotRelease")} />
      )}
    </Dialog>
  );
}

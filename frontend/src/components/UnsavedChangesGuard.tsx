/**
 * Unsaved-changes guard (UX-STANDARD 4): while `when` is true, leaving the page (another route, reload, closing
 * the tab) asks first. Changing only the query string (tabs, selection) is not leaving. Automated browsers
 * (`navigator.webdriver`) are not prompted, so scripted runs behave exactly as before.
 */
import { useEffect } from "react";
import { useBlocker } from "react-router";
import { ConfirmDialog } from "./ConfirmDialog";
import { t } from "../lib/i18n";

const automated = typeof navigator !== "undefined" && navigator.webdriver === true;

export function UnsavedChangesGuard({ when, what = t("studio.unsavedChangesGuard.str.thisPage"), scope }: { when: boolean; what?: string; scope?: string }) {
  const active = when && !automated;
  // `scope`: a path prefix whose sub-pages keep the edits (e.g. the tabs of a plan workspace)
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    active && (scope ? !nextLocation.pathname.startsWith(scope) : currentLocation.pathname !== nextLocation.pathname),
  );
  useEffect(() => {
    if (!active) return;
    const onUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [active]);
  if (blocker.state !== "blocked") return null;
  return (
    <ConfirmDialog
      title={t("guard.title")}
      confirmLabel={t("guard.confirm")}
      cancelLabel={t("guard.cancel")}
      danger
      onConfirm={() => blocker.proceed()}
      onCancel={() => blocker.reset()}
    >
      <p style={{ margin: 0 }}>{t("guard.body", { what })}</p>
    </ConfirmDialog>
  );
}

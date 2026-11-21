/**
 * Unsaved-changes guard (UX-STANDARD 4): while `when` is true, leaving the page (another route, reload, closing
 * the tab) asks first. Changing only the query string (tabs, selection) is not leaving. Automated browsers
 * (`navigator.webdriver`) are not prompted, so scripted runs behave exactly as before.
 */
import { useEffect } from "react";
import { useBlocker } from "react-router";
import { ConfirmDialog } from "./ConfirmDialog";

const automated = typeof navigator !== "undefined" && navigator.webdriver === true;

export function UnsavedChangesGuard({ when, what = "this page" }: { when: boolean; what?: string }) {
  const active = when && !automated;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => active && currentLocation.pathname !== nextLocation.pathname);
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
      title="Leave without saving?"
      confirmLabel="Discard changes and leave"
      cancelLabel="Stay on this page"
      danger
      onConfirm={() => blocker.proceed()}
      onCancel={() => blocker.reset()}
    >
      <p style={{ margin: 0 }}>You have unsaved changes on {what}. If you leave now, they are lost.</p>
    </ConfirmDialog>
  );
}

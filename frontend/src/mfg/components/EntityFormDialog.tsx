/**
 * Dialog with a form: submit on Enter, busy state, server error shown inline (field errors listed).
 * Used for "New item", groups, lines, skills, operators, tool pools and similar small records.
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { MfgError } from "./Feedback";

export interface EntityFormDialogProps {
  title: string;
  submitLabel: string;
  onClose(): void;
  /** Throw to keep the dialog open and show the error. */
  onSubmit(): Promise<void>;
  children: ReactNode;
  wide?: boolean;
  disabled?: boolean;
  testId?: string;
  extraFooter?: ReactNode;
}

export function EntityFormDialog({
  title,
  submitLabel,
  onClose,
  onSubmit,
  children,
  wide,
  disabled,
  testId,
  extraFooter,
}: EntityFormDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const formId = `form-${title.replace(/\W+/g, "-").toLowerCase()}`;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit();
    } catch (err) {
      setError(err);
      setBusy(false);
      return;
    }
    setBusy(false);
  };
  return (
    <Dialog
      title={title}
      onClose={onClose}
      wide={wide}
      footer={
        <>
          {extraFooter}
          <span className="grow" />
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            Cancel
          </button>
          <button
            type="submit"
            form={formId}
            className="btn primary"
            disabled={busy || disabled}
            data-testid={testId ? `${testId}-submit` : undefined}
          >
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />}
            {submitLabel}
          </button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} className="col" data-testid={testId} noValidate>
        {error ? <MfgError error={error} title="Could not save" /> : null}
        {children}
      </form>
    </Dialog>
  );
}

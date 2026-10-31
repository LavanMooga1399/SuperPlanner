import type { ReactNode } from "react";
import { Dialog } from "./Dialog";

export interface ConfirmDialogProps {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  /** disables the confirm button without the busy spinner (e.g. a required reason is empty) */
  confirmDisabled?: boolean;
  onConfirm(): void;
  onCancel(): void;
}

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  danger,
  busy,
  confirmDisabled,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Dialog
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="btn" onClick={onCancel} data-dialog-close>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`btn ${danger ? "danger" : "primary"}`}
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
            data-autofocus
          >
            {busy ? <span className="spinner" aria-hidden /> : null}
            {confirmLabel}
          </button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}

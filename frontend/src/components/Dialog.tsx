import { useEffect, useRef, type ReactNode } from "react";

export interface DialogProps {
  title: string;
  onClose(): void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  labelId?: string;
}

/** Modal dialog: focus trap-lite (focus first control, Escape closes, restore focus). */
export function Dialog({ title, onClose, children, footer, wide, labelId }: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const id = labelId ?? "dialog-title-" + title.replace(/\W+/g, "-").toLowerCase();

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>(
      "[data-autofocus], input, select, textarea, button:not([data-dialog-close])",
    );
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      } else if (e.key === "Tab" && el) {
        const focusables = Array.from(
          el.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"),
        ).filter((n) => !n.hasAttribute("disabled"));
        if (!focusables.length) return;
        const a = focusables[0];
        const b = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === a) {
          e.preventDefault();
          b.focus();
        } else if (!e.shiftKey && document.activeElement === b) {
          e.preventDefault();
          a.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={id} ref={ref}>
        <div className="dialog-header">
          <h2 id={id}>{title}</h2>
        </div>
        <div className="dialog-body">{children}</div>
        {footer ? <div className="dialog-footer">{footer}</div> : null}
      </div>
    </div>
  );
}

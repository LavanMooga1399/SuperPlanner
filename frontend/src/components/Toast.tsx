/**
 * Toasts (UX-STANDARD 4): short confirmations after a successful action. Errors are never toasts; they stay as
 * banners next to the thing that failed. `toast()` can be called from anywhere (module store); one polite live
 * region announces them. Auto-dismiss after 5 s, paused while hovered or focused.
 */
import { useEffect, useRef, useSyncExternalStore } from "react";
import { Icon } from "./Icon";

export interface ToastItem {
  id: number;
  tone: "ok" | "info" | "warn";
  text: string;
}

let items: ToastItem[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function toast(text: string, tone: ToastItem["tone"] = "ok"): void {
  items = [...items.slice(-3), { id: ++seq, tone, text }];
  emit();
}

function dismiss(id: number): void {
  items = items.filter((t) => t.id !== id);
  emit();
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

function ToastView({ t }: { t: ToastItem }) {
  const timer = useRef<number | null>(null);
  const start = () => {
    timer.current = window.setTimeout(() => dismiss(t.id), 5000);
  };
  const stop = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  };
  useEffect(() => {
    start();
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className={`toast ${t.tone}`} onMouseEnter={stop} onMouseLeave={start} onFocus={stop} onBlur={start} data-testid="toast">
      <Icon name={t.tone === "ok" ? "check" : t.tone === "warn" ? "alert" : "info"} />
      <span className="toast-text">{t.text}</span>
      <button type="button" className="btn ghost sm icon" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>
        <Icon name="x" size={14} />
      </button>
    </div>
  );
}

export function Toaster() {
  const list = useSyncExternalStore(subscribe, () => items, () => items);
  return (
    <div className="toaster" role="status" aria-live="polite" aria-relevant="additions">
      {list.map((t) => (
        <ToastView key={t.id} t={t} />
      ))}
    </div>
  );
}

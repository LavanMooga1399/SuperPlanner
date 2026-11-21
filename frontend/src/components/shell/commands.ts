/** Global command state: palette and shortcut help open flags (module store, so any button can open them). */
import { useSyncExternalStore } from "react";

let state = { palette: false, shortcuts: false };
const listeners = new Set<() => void>();
const set = (next: Partial<typeof state>) => {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
};

export const openPalette = () => set({ palette: true, shortcuts: false });
export const closePalette = () => set({ palette: false });
export const togglePalette = () => set({ palette: !state.palette, shortcuts: false });
export const openShortcuts = () => set({ shortcuts: true, palette: false });
export const closeShortcuts = () => set({ shortcuts: false });

export function useCommandState() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
    () => state,
  );
}

/** True when the keyboard event comes from a text-entry control (shortcuts must not fire there). */
export function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable;
}

export const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
export const MOD = isMac ? "⌘" : "Ctrl";

/** `g` then a letter (UX-STANDARD 4). */
export const GO_KEYS: { key: string; label: string; to: string }[] = [
  { key: "h", label: "Manufacturing overview", to: "/mfg" },
  { key: "i", label: "Items", to: "/mfg/items" },
  { key: "d", label: "Demand", to: "/mfg/demand" },
  { key: "m", label: "MRP", to: "/mfg/mrp" },
  { key: "s", label: "Schedule", to: "/mfg/schedule" },
  { key: "w", label: "Work orders", to: "/mfg/work-orders" },
  { key: "p", label: "Purchasing", to: "/mfg/purchasing" },
  { key: "v", label: "Inventory", to: "/mfg/inventory" },
  { key: "f", label: "Shop floor", to: "/mfg/floor/overview" },
  { key: "k", label: "KPIs", to: "/mfg/kpis" },
];

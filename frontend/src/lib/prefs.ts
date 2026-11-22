/**
 * User display preferences (UX-STANDARD 2): theme (light / dark / system) and density (compact / comfortable),
 * persisted in localStorage and applied as `data-theme` / `data-density` on <html>. A tiny external store so
 * any component (tables, header) re-renders when they change.
 */
import { useSyncExternalStore } from "react";
import { savePref, syncPref } from "./serverPrefs";

export type ThemePref = "light" | "dark" | "system";
export type Density = "compact" | "comfortable";

const THEME_KEY = "sp.theme"; // JSON: "light" | "dark" | null (null = system); kept compatible with earlier builds
const DENSITY_KEY = "sp.density";

/** Table row height per density, in px (must match `--row-h` in theme.css). */
export const ROW_H: Record<Density, number> = { compact: 28, comfortable: 36 };

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function write(key: string, v: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* storage unavailable */
  }
}

function systemDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

interface Prefs {
  theme: ThemePref;
  resolved: "light" | "dark";
  density: Density;
}

let state: Prefs = load();
const listeners = new Set<() => void>();

function load(): Prefs {
  const t = read<"light" | "dark" | null>(THEME_KEY, null);
  const theme: ThemePref = t === "light" || t === "dark" ? t : "system";
  const d = read<Density>(DENSITY_KEY, "compact");
  return { theme, resolved: theme === "system" ? (systemDark() ? "dark" : "light") : theme, density: d === "comfortable" ? "comfortable" : "compact" };
}

function apply(): void {
  const el = document.documentElement;
  el.setAttribute("data-theme", state.resolved);
  el.setAttribute("data-density", state.density);
}

function emit(next: Prefs): void {
  state = next;
  apply();
  listeners.forEach((l) => l());
}

export function initPrefs(): void {
  apply();
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (state.theme === "system") emit({ ...state, resolved: systemDark() ? "dark" : "light" });
    });
  } catch {
    /* old browsers */
  }
  window.addEventListener("storage", (e) => {
    if (e.key === THEME_KEY || e.key === DENSITY_KEY) emit(load());
  });
}

const DISPLAY_PREF = "display";
const DISPLAY_LOCAL = "sp.display";

function pushDisplay(): void {
  savePref(DISPLAY_PREF, DISPLAY_LOCAL, { theme: state.theme, density: state.density });
}

function applyLocal(theme: ThemePref, density: Density): void {
  write(THEME_KEY, theme === "system" ? null : theme);
  write(DENSITY_KEY, density);
  emit({ theme, resolved: theme === "system" ? (systemDark() ? "dark" : "light") : theme, density });
}

export function setTheme(theme: ThemePref): void {
  applyLocal(theme, state.density);
  pushDisplay();
}

export function setDensity(density: Density): void {
  applyLocal(state.theme, density);
  pushDisplay();
}

/** After sign-in: take the person's server display settings (or upload this browser's once). */
export function syncDisplayPrefs(): void {
  // seed the local cache from the two legacy keys so the one-time migration has something to upload
  if (window.localStorage.getItem(DISPLAY_LOCAL) === null && (window.localStorage.getItem(THEME_KEY) !== null || window.localStorage.getItem(DENSITY_KEY) !== null))
    write(DISPLAY_LOCAL, { theme: state.theme, density: state.density });
  syncPref<{ theme?: ThemePref; density?: Density }>(DISPLAY_PREF, DISPLAY_LOCAL, (v) => {
    const theme = v?.theme === "light" || v?.theme === "dark" || v?.theme === "system" ? v.theme : state.theme;
    const density = v?.density === "comfortable" || v?.density === "compact" ? v.density : state.density;
    applyLocal(theme, density);
  });
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export function usePrefs(): Prefs {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

export function useRowHeight(): number {
  return ROW_H[usePrefs().density];
}

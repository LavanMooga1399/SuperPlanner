/**
 * i18n-ready strings (UX-STANDARD 4/8). English only for now: the shell, tables, filters and dialogs (below), the
 * navigation (`strings/nav.ts`) and the page copy per area (`strings/mfg.ts`, `floor`, `mobile`, `assistant`,
 * `studio`, `finance`, `account`) all come from this one
 * dictionary, so a later translation replaces one map.
 * `t("common.runNo", { n: 3 })` -> "Run #3": values are passed as `{name}` placeholders, so a translation can move
 * them (a language can say "{m}: {n}" instead of "{n} of {m}"); counts with nouns go through `plural()`.
 */
import { accountStrings } from "./strings/account";
import { assistantStrings } from "./strings/assistant";
import { financeStrings } from "./strings/finance";
import { floorStrings } from "./strings/floor";
import { mfgStrings } from "./strings/mfg";
import { mobileStrings } from "./strings/mobile";
import { navStrings } from "./strings/nav";
import { shellStrings } from "./strings/shell";
import { studioStrings } from "./strings/studio";
import { qualityStrings } from "./strings/quality";

const en = {
  ...navStrings,
  ...mfgStrings,
  ...floorStrings,
  ...mobileStrings,
  ...assistantStrings,
  ...studioStrings,
  ...financeStrings,
  ...accountStrings,
  ...shellStrings,
  ...qualityStrings,
  "common.cancel": "Cancel",
  "common.close": "Close",
  "common.dismiss": "Dismiss notification",
  "common.loading": "Loading…",
  "common.search": "Search",
  "common.runNo": "Run #{n}",
  "common.runNoInline": "run #{n}",
  "common.mrpRunNo": "MRP run #{n}",
  "common.scheduleNo": "Schedule #{n}",
  "common.scheduleNoInline": "schedule #{n}",
  "common.nOfM": "{n} of {m}",
  "table.rows": "{count} rows",
  "table.csv": "CSV",
  "table.csvTitle": "Download the rows loaded so far as CSV",
  "table.columns": "Columns",
  "table.columnsHidden": "Columns ({count} hidden)",
  "table.columnsHelp": "Show, hide and order columns. Drag a header edge to resize; double-click it to reset.",
  "table.columnsReset": "Reset to default",
  "table.narrowHidden": "(narrow screen)",
  "table.empty": "Nothing to show.",
  "table.moveUp": "Move {name} up",
  "table.moveDown": "Move {name} down",
  "table.resize": "Resize {name} column",
  "filters.active": "Active filters",
  "filters.button": "Filters",
  "filters.clearAll": "Clear all",
  "filters.remove": "Remove filter {label}: {value}",
  "views.button": "Views",
  "views.title": "Saved views",
  "views.none": "No saved views yet. Set filters, then save them here.",
  "views.namePlaceholder": "Name for current filters",
  "views.save": "Save",
  "views.delete": "Delete view {name}",
  "views.reset": "Reset to default filters",
  "guard.title": "Leave without saving?",
  "guard.confirm": "Discard changes and leave",
  "guard.cancel": "Stay on this page",
  "guard.body": "You have unsaved changes on {what}. If you leave now, they are lost.",
  "shell.skip": "Skip to content",
  "shell.search": "Search or jump to…",
  "shell.help": "Help and keyboard shortcuts",
  "shell.display": "Display settings",
  "palette.placeholder": "Search pages, work orders, items, purchase orders, serials…",
  "palette.none": "No pages, actions or records match \"{q}\".",
  "palette.searching": "Searching…",
  "palette.hint": "Type 2+ characters to search records",
  "error.reference": "Reference",
  "error.copyReference": "Copy reference",
  "shell.lang.label": "Language",
  "shell.lang.en": "English",
  "shell.lang.frCA": "Français (Canada)",
} as const;

export type StringKey = keyof typeof en;

/**
 * Languages (M7 10): English (default) and French (Canada). The choice is read synchronously at start-up from the
 * local cache (`sp.locale`, mirrored in the server display preference), so module-level labels are created in the
 * right language; `loadLocale()` fetches the French dictionary before the app modules load (main.tsx), and
 * `setLocale()` stores the choice and reloads the page.
 */
export type Locale = "en" | "fr-CA";
export const LOCALES: readonly Locale[] = ["en", "fr-CA"];
const LOCALE_KEY = "sp.locale";

function storedLocale(): Locale {
  try {
    const v = window.localStorage.getItem(LOCALE_KEY);
    return v === "fr-CA" ? "fr-CA" : "en";
  } catch {
    return "en";
  }
}

let locale: Locale = typeof window === "undefined" ? "en" : storedLocale();

/** Active language. */
export function getLocale(): Locale {
  return locale;
}

/** Intl locale for numbers and dates (UX-STANDARD 4: en-IN for English, fr-CA for French). */
export function intlLocale(): string {
  return locale === "fr-CA" ? "fr-CA" : "en-IN";
}

let dict: Record<StringKey, string> = en;

/** Replace the active dictionary (a translation); missing keys fall back to English. */
export function setStrings(next: Partial<Record<StringKey, string>>): void {
  dict = { ...en, ...next };
}

/** Load the dictionary of the stored language (before the app modules are evaluated). */
export async function loadLocale(): Promise<void> {
  if (locale === "en") return;
  try {
    const fr = await import("./strings/fr-CA");
    setStrings(fr.frCaStrings);
    document.documentElement.lang = "fr-CA";
  } catch {
    // the French bundle could not be loaded (offline first visit): English stays, nothing breaks
    locale = "en";
  }
}

/** Store the language (local cache now, server preference via `prefs.ts`) and reload so every label follows. */
export function setLocale(next: Locale, reload = true): void {
  try {
    window.localStorage.setItem(LOCALE_KEY, next);
  } catch {
    /* storage unavailable */
  }
  if (reload && next !== locale) window.location.reload();
}

export function t(key: StringKey, vars?: Record<string, unknown>): string {
  let s = dict[key] ?? en[key];
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

/** True when the dictionary has `key` (for dynamic keys such as `errors.<CODE>`). */
export function hasKey(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(en, key);
}

/** Localised text of an API error code (`errors.<CODE>`), else the server message (English sessions keep the server's own words). */
export function errorMessage(code: string | undefined, serverMessage: string, vars?: Record<string, unknown>): string {
  if (!code || locale === "en") return serverMessage;
  const key = `errors.${code}`;
  return hasKey(key) ? t(key as StringKey, vars) : serverMessage;
}

let pluralRules = new Intl.PluralRules(intlLocale());

/** "1 warning", "2 warnings", "1,200 items": count with digit grouping and the right noun form. */
export function plural(n: number | null | undefined, one: string, other: string = `${one}s`): string {
  const v = n ?? 0;
  if (pluralRules.resolvedOptions().locale.slice(0, 2) !== intlLocale().slice(0, 2)) pluralRules = new Intl.PluralRules(intlLocale());
  return `${v.toLocaleString(intlLocale())} ${pluralRules.select(v) === "one" ? one : other}`;
}

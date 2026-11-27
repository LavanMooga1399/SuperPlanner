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
import { planningStrings } from "./strings/planning";
import { networkStrings } from "./strings/network";
import { gxpStrings } from "./strings/gxp";

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
  ...planningStrings,
  ...networkStrings,
  ...gxpStrings,
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
  "noun.day": "day",
  "noun.days": "days",
  "noun.warning": "warning",
  "noun.warnings": "warnings",
  "noun.note": "note",
  "noun.notes": "notes",
  "noun.line": "line",
  "noun.lines": "lines",
  "noun.row": "row",
  "noun.rows": "rows",
  "noun.operation": "operation",
  "noun.operations": "operations",
  "noun.error": "error",
  "noun.errors": "errors",
  "noun.operator": "operator",
  "noun.operators": "operators",
  "noun.lot": "lot",
  "noun.lots": "lots",
  "noun.goal": "goal",
  "noun.goals": "goals",
  "noun.year": "year",
  "noun.years": "years",
  "noun.use": "use",
  "noun.uses": "uses",
  "noun.top-level product": "top-level product",
  "noun.top-level products": "top-level products",
  "noun.step": "step",
  "noun.steps": "steps",
  "noun.savings item": "savings item",
  "noun.savings items": "savings items",
  "noun.rule": "rule",
  "noun.rules": "rules",
  "noun.problem": "problem",
  "noun.problems": "problems",
  "noun.plan": "plan",
  "noun.plans": "plans",
  "noun.person": "person",
  "noun.people": "people",
  "noun.month": "month",
  "noun.months": "months",
  "noun.loan": "loan",
  "noun.loans": "loans",
  "noun.late line": "late line",
  "noun.late lines": "late lines",
  "noun.item": "item",
  "noun.items": "items",
  "noun.income": "income",
  "noun.incomes": "incomes",
  "noun.expense": "expense",
  "noun.expenses": "expenses",
  "noun.document": "document",
  "noun.documents": "documents",
  "noun.action": "action",
  "noun.actions": "actions",
  "noun.orders": "orders",
  "noun.events": "events",
  "noun.deliveries": "deliveries",
  "noun.batches": "batches",
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

/**
 * Number and date format (demo review): the person's choice (`sp.numfmt`, display menu) wins; otherwise the UI
 * language and the plant's country - French -> fr-CA, English -> en-CA for Canadian plants, en-IN for Indian plants,
 * en-US elsewhere. The plant region (`sp.region`) is cached from the plant record (`setPlantRegion`).
 */
export type NumberFormatPref = "auto" | "en-IN" | "en-CA" | "en-US" | "fr-CA";
export const NUMBER_FORMATS: readonly NumberFormatPref[] = ["auto", "en-CA", "en-IN", "en-US", "fr-CA"];
const FORMAT_KEY = "sp.numfmt";
const REGION_KEY = "sp.region";
function readKey(k: string): string | null {
  try {
    return window.localStorage.getItem(k);
  } catch {
    return null;
  }
}
export function numberFormatPref(): NumberFormatPref {
  const v = typeof window === "undefined" ? null : readKey(FORMAT_KEY);
  return (NUMBER_FORMATS as readonly string[]).includes(v ?? "") ? (v as NumberFormatPref) : "auto";
}
export function intlLocale(): string {
  const pref = numberFormatPref();
  if (pref !== "auto") return pref;
  if (locale === "fr-CA") return "fr-CA";
  const region = typeof window === "undefined" ? null : readKey(REGION_KEY);
  return region && ["CA", "IN", "US", "GB", "AU"].includes(region) ? `en-${region}` : "en-US";
}
/** Country of a plant from its currency (else its UTC offset): IN, CA or US (default). */
export function regionOf(currency: string | null | undefined, utcOffset?: string | null): string {
  const c = (currency ?? "").toUpperCase();
  if (c === "INR" || (!c && utcOffset === "+05:30")) return "IN";
  if (c === "CAD") return "CA";
  return "US";
}
/** Store the plant's region; true when the number/date format changed. */
export function setPlantRegion(region: string): boolean {
  const before = intlLocale();
  try {
    window.localStorage.setItem(REGION_KEY, region);
  } catch {
    /* storage unavailable */
  }
  return intlLocale() !== before;
}
/** The person's number/date format override (display menu); reloads so every formatter follows. */
export function setNumberFormat(pref: NumberFormatPref): void {
  try {
    if (pref === "auto") window.localStorage.removeItem(FORMAT_KEY);
    else window.localStorage.setItem(FORMAT_KEY, pref);
  } catch {
    /* storage unavailable */
  }
  window.location.reload();
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
  return `${v.toLocaleString(intlLocale())} ${noun(pluralRules.select(v) === "one" ? one : other)}`;
}

/** A plain English noun passed to `plural()`/`ShowMore` in the UI language (`noun.<word>`; unknown words unchanged). */
export function noun(word: string): string {
  if (locale === "en") return word;
  const key = `noun.${word}`;
  return hasKey(key) ? t(key as StringKey) : word;
}

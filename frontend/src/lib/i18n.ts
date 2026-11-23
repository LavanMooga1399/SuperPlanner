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
} as const;

export type StringKey = keyof typeof en;

let dict: Record<StringKey, string> = en;

/** Replace the active dictionary (e.g. a future translation); missing keys fall back to English. */
export function setStrings(next: Partial<Record<StringKey, string>>): void {
  dict = { ...en, ...next };
}

export function t(key: StringKey, vars?: Record<string, unknown>): string {
  let s = dict[key] ?? en[key];
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

const pluralRules = new Intl.PluralRules("en-IN");

/** "1 warning", "2 warnings", "1,200 items": count with digit grouping and the right noun form. */
export function plural(n: number | null | undefined, one: string, other: string = `${one}s`): string {
  const v = n ?? 0;
  return `${v.toLocaleString("en-IN")} ${pluralRules.select(v) === "one" ? one : other}`;
}

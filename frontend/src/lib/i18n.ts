/**
 * i18n-ready strings for the shared components (UX-STANDARD 4/8). English only for now: every user-visible
 * string of the shell, tables, filters and dialogs comes from here, so a later translation replaces one map.
 * `t("table.showing", { shown: "3", total: "10" })` fills `{name}` placeholders.
 */
const en = {
  "common.cancel": "Cancel",
  "common.close": "Close",
  "common.dismiss": "Dismiss notification",
  "common.loading": "Loading…",
  "common.search": "Search",
  "table.rows": "{count} rows",
  "table.csv": "CSV",
  "table.csvTitle": "Download the rows loaded so far as CSV",
  "table.columns": "Columns",
  "table.columnsHidden": "Columns ({count} hidden)",
  "table.columnsHelp": "Show, hide and order columns. Drag a header edge to resize; double-click it to reset.",
  "table.columnsReset": "Reset to default",
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

export function t(key: StringKey, vars?: Record<string, string | number>): string {
  let s = dict[key] ?? en[key];
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

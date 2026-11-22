/**
 * Short-list variant of the shared data table (UX-STANDARD 4): the same `VirtualTable` (header sorting, column
 * show/hide/reorder/resize, CSV, skeleton loading, empty state, phone cards below 768 px) without windowing, for
 * lists that are short by nature (run history, KPI by line, recall lines, transfer lines). Every row is in the
 * DOM, rows grow with wrapped content (`Column.wrap`), and phone cards are derived from the columns unless
 * `card` is given.
 */
import { VirtualTable, type VirtualTableProps } from "./VirtualTable";

export function DataTable<T>(props: Omit<VirtualTableProps<T>, "virtual" | "height">) {
  return <VirtualTable {...props} virtual={false} />;
}

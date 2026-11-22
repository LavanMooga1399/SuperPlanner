/**
 * Short-list variant of the shared data table (UX-STANDARD 4): the same `VirtualTable` (header sorting, column
 * show/hide/reorder/resize, CSV, skeleton loading, empty state, phone cards below 768 px) without windowing, for
 * lists that are short by nature (run history, KPI by line, recall lines, transfer lines). Every row is in the
 * DOM, rows grow with wrapped content (`Column.wrap`), and phone cards are derived from the columns unless
 * `card` is given. Paged lists add more rows with a "Show more" button (`ShowMore`) instead of `onEndReached`.
 */
import { VirtualTable, type VirtualTableProps } from "./VirtualTable";
import { t } from "../../lib/i18n";

/** Footer of a paged short list: "Showing 50 of 120 events" and a Show more button. */
export function ShowMore({ shown, total, noun, loading, onMore }: { shown: number; total: number; noun: string; loading?: boolean; onMore(): void }) {
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className="muted small">
        Showing {t("common.nOfM", { n: shown.toLocaleString("en-IN"), m: total.toLocaleString("en-IN") })} {noun}
      </span>
      {shown < total ? (
        <button type="button" className="btn sm" onClick={onMore} disabled={loading}>
          Show more
        </button>
      ) : null}
    </span>
  );
}

export function DataTable<T>(props: Omit<VirtualTableProps<T>, "virtual" | "height">) {
  return <VirtualTable {...props} virtual={false} />;
}

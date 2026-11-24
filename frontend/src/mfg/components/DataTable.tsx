/**
 * Short-list variant of the shared data table (UX-STANDARD 4): the same `VirtualTable` (header sorting, column
 * show/hide/reorder/resize, CSV, skeleton loading, empty state, phone cards below 768 px) without windowing, for
 * lists that are short by nature (run history, KPI by line, recall lines, transfer lines). Every row is in the
 * DOM, rows grow with wrapped content (`Column.wrap`), and phone cards are derived from the columns unless
 * `card` is given. Paged lists add more rows with a "Show more" button (`ShowMore`) instead of `onEndReached`.
 */
import { VirtualTable, type VirtualTableProps } from "./VirtualTable";
import { t } from "../../lib/i18n";
import { LOCALE } from "../../lib/locale";

/** Footer of a paged short list: "Showing 50 of 120 events" and a Show more button. */
export function ShowMore({ shown, total, noun, loading, onMore }: { shown: number; total: number; noun: string; loading?: boolean; onMore(): void }) {
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className="muted small">
        {t("mfg.dataTable.text.showing", { t: t("common.nOfM", { n: shown.toLocaleString(LOCALE), m: total.toLocaleString(LOCALE) }), noun: noun })}
      </span>
      {shown < total ? (
        <button type="button" className="btn sm" onClick={onMore} disabled={loading}>
          {t("mfg.dataTable.text.showMore")}
        </button>
      ) : null}
    </span>
  );
}

export function DataTable<T>(props: Omit<VirtualTableProps<T>, "virtual" | "height">) {
  return <VirtualTable {...props} virtual={false} />;
}

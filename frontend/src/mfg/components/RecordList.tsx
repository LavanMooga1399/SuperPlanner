/**
 * Selectable list of small records (skills, operators, tool pools) with highlight + scroll of the `?param=`
 * selection (target of health "Fix" links, M 11.3).
 */
import { useEffect, useRef, type ReactNode } from "react";

export function RecordList<T extends { id: string }>({
  items,
  selectedId,
  onSelect,
  render,
  testId,
  empty,
}: {
  items: T[];
  selectedId: string | null;
  onSelect(id: string): void;
  render(item: T): ReactNode;
  testId: string;
  empty: ReactNode;
}) {
  const ref = useRef<HTMLUListElement>(null);
  useEffect(() => {
    if (!selectedId) return;
    ref.current?.querySelector(`[data-id="${selectedId}"]`)?.scrollIntoView({ block: "center" });
  }, [selectedId, items]);
  if (items.length === 0) return <p className="muted" style={{ padding: 16, margin: 0 }}>{empty}</p>;
  return (
    <ul className="mfg-plain-list mfg-record-list" ref={ref}>
      {items.map((it) => (
        <li key={it.id}>
          <button
            type="button"
            className={`mfg-list-row${it.id === selectedId ? " mfg-selected" : ""}`}
            aria-current={it.id === selectedId ? "true" : undefined}
            onClick={() => onSelect(it.id)}
            data-testid={testId}
            data-id={it.id}
          >
            {render(it)}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Replace one query parameter (keeps history so Back returns to the previous selection). */
export function withParam(prev: URLSearchParams, k: string, v: string | null): URLSearchParams {
  const n = new URLSearchParams(prev);
  if (v) n.set(k, v);
  else n.delete(k);
  return n;
}

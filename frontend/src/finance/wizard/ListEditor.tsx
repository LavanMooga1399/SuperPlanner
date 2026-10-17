import { useState, type ReactNode } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";

export interface ListEditorProps<T extends { id: string; name: string }> {
  items: T[];
  /** e.g. "income" -> rows get data-testid="income-row-<id>" */
  rowTestId: string;
  addLabel: string;
  emptyText: string;
  max?: number;
  onAdd(): void;
  onRemove(index: number): void;
  renderRow(item: T, index: number): ReactNode;
  addExtra?: ReactNode;
}

/** Generic add / remove / edit rows (FINANCE.md 20.2). */
export function ListEditor<T extends { id: string; name: string }>({ items, rowTestId, addLabel, emptyText, max, onAdd, onRemove, renderRow, addExtra }: ListEditorProps<T>) {
  const full = max !== undefined && items.length >= max;
  const [toRemove, setToRemove] = useState<number | null>(null);
  const pending = toRemove !== null ? items[toRemove] : undefined;
  return (
    <div className="list-editor">
      {items.length === 0 ? (
        <p className="muted small list-empty" style={{ margin: 0 }} data-testid={`${rowTestId}-empty`}>
          {emptyText}
        </p>
      ) : null}
      {items.map((it, i) => (
        <div className="list-row" key={it.id} data-testid={`${rowTestId}-row-${it.id}`}>
          <div className="list-row-head">
            <span className="grow">{it.name || "(unnamed)"}</span>
            <button type="button" className="btn sm ghost" onClick={() => setToRemove(i)} aria-label={`Remove ${it.name || "item"}`}>
              <Icon name="trash" /> Remove
            </button>
          </div>
          {renderRow(it, i)}
        </div>
      ))}
      <div className="row wrap">
        <button type="button" className="btn sm" onClick={onAdd} disabled={full} data-testid={`add-${rowTestId}`}>
          <Icon name="plus" /> {addLabel}
        </button>
        {addExtra}
        {full ? <span className="small muted">Limit of {max} reached.</span> : null}
      </div>
      {pending ? (
        <ConfirmDialog
          title={`Remove ${pending.name || "this item"}?`}
          confirmLabel="Remove"
          danger
          onConfirm={() => {
            onRemove(toRemove!);
            setToRemove(null);
          }}
          onCancel={() => setToRemove(null)}
        >
          <p style={{ margin: 0 }}>It is taken out of the plan with all its settings. You can add it again later.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

/**
 * Bulk action bar (UX-STANDARD 4): appears when rows are selected; each action asks for confirmation stating
 * exactly what will happen, runs one bulk request, then shows "n succeeded, m failed" with the reason per
 * failed record. Keyboard: Tab reaches the bar after the filters; dialogs trap focus; Escape closes.
 */
import { useState, type ReactNode } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Dialog } from "../../components/Dialog";
import { Icon, type IconName } from "../../components/Icon";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { ApiError } from "../../api/client";
import { newIdempotencyKey } from "../api/clientM2";
import { runBulk, type BulkAction, type BulkResponse } from "../api/clientUx";
import { MfgError } from "./Feedback";

export interface BulkRow {
  id: string;
  row_version: number;
  /** Shown in confirmations and results, e.g. "WO-KV-0002". */
  label: string;
  status?: string;
}

export interface BulkActionDef {
  action: BulkAction;
  label: string;
  icon: IconName;
  danger?: boolean;
  /** Confirmation sentence for n records, e.g. "Release 3 work orders." */
  what(n: number): string;
  /** What happens to each record (shown under the list). */
  effect: string;
  /** Extra inputs (e.g. a reason); return the params and whether they are complete. */
  form?(state: Record<string, string>, set: (k: string, v: string) => void): ReactNode;
  params?(state: Record<string, string>): Record<string, unknown>;
  ready?(state: Record<string, string>): boolean;
  /** Statuses that allow the action (for the "will be skipped" hint; the server decides). */
  eligible?: string[];
  testId: string;
}

export function BulkActions({ rows, noun, actions, onDone, onClear }: { rows: BulkRow[]; noun: [string, string]; actions: BulkActionDef[]; onDone(): void; onClear(): void }) {
  const [pending, setPending] = useState<BulkActionDef | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<{ def: BulkActionDef; res: BulkResponse; labels: Map<string, string> } | null>(null);
  if (!rows.length && !result) return null;

  const run = async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      // one idempotency key per confirmation: a retry (network, or 409 MFG_BULK_IN_PROGRESS) never runs twice
      const key = newIdempotencyKey("bulk");
      const items = rows.map((r) => ({ id: r.id, row_version: r.row_version }));
      let res: BulkResponse | null = null;
      for (let attempt = 0; !res; attempt++) {
        try {
          res = await runBulk(pending.action, items, pending.params?.(form) ?? {}, key);
        } catch (e) {
          if (!(e instanceof ApiError && e.code === "MFG_BULK_IN_PROGRESS") || attempt >= 5) throw e;
          await new Promise((r) => window.setTimeout(r, 5000));
        }
      }
      const labels = new Map(rows.map((r) => [r.id, r.label]));
      if (res.failed === 0) toast(`${pending.label}: ${plural(res.succeeded, noun[0], noun[1])} done`);
      else setResult({ def: pending, res, labels });
      setPending(null);
      setForm({});
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const shown = rows.slice(0, 8);
  return (
    <>
      {rows.length ? (
        <div className="bulk-bar" role="region" aria-label="Bulk actions" data-testid="bulk-bar">
          <span className="bulk-count" aria-live="polite">
            <b>{plural(rows.length, noun[0], noun[1])}</b> selected
          </span>
          <div className="row wrap" style={{ gap: 6 }}>
            {actions.map((a) => (
              <button key={a.action} type="button" className={`btn sm${a.danger ? " danger" : ""}`} onClick={() => setPending(a)} data-testid={a.testId}>
                <Icon name={a.icon} size={14} /> {a.label}
              </button>
            ))}
          </div>
          <button type="button" className="btn ghost sm" onClick={onClear} data-testid="bulk-clear">
            <Icon name="x" size={14} /> {t("mfg.bulkActions.btn.clearSelection")}
          </button>
        </div>
      ) : null}
      {pending ? (
        <ConfirmDialog
          title={`${pending.label}: ${plural(rows.length, noun[0], noun[1])}`}
          confirmLabel={`${pending.label} ${plural(rows.length, noun[0], noun[1])}`}
          danger={pending.danger}
          busy={busy}
          confirmDisabled={pending.ready ? !pending.ready(form) : false}
          onConfirm={() => void run()}
          onCancel={() => {
            setPending(null);
            setForm({});
            setError(null);
          }}
        >
          <p style={{ margin: 0 }}>{pending.what(rows.length)}</p>
          <ul className="bulk-list" data-testid="bulk-confirm-list">
            {shown.map((r) => (
              <li key={r.id} className="mono">
                {r.label}
              </li>
            ))}
            {rows.length > shown.length ? <li className="faint">and {rows.length - shown.length} more</li> : null}
          </ul>
          <p className="small muted" style={{ margin: 0 }}>
            {pending.effect} Records that cannot take this action are left unchanged and listed with the reason.
          </p>
          {(() => {
            const skip = pending.eligible ? rows.filter((r) => r.status && !pending.eligible!.includes(r.status)).length : 0;
            return skip ? (
              <p className="small" style={{ margin: 0, color: "var(--warn)" }} data-testid="bulk-skip-hint">
                <Icon name="alert" size={12} /> {plural(skip, noun[0], noun[1])} {skip === 1 ? "is" : "are"} not in a status that allows this and will be skipped.
              </p>
            ) : null;
          })()}
          {pending.form?.(form, (k, v) => setForm((f) => ({ ...f, [k]: v })))}
          <MfgError error={error} title="The bulk action could not be sent" />
        </ConfirmDialog>
      ) : null}
      {result ? (
        <Dialog
          title={`${result.def.label}: ${result.res.succeeded} succeeded, ${result.res.failed} failed`}
          onClose={() => setResult(null)}
          footer={
            <button type="button" className="btn primary" onClick={() => setResult(null)} data-testid="bulk-result-close">
              {t("mfg.bulkActions.btn.close")}
            </button>
          }
        >
          <div data-testid="bulk-result" data-succeeded={result.res.succeeded} data-failed={result.res.failed}>
            <p style={{ marginTop: 0 }}>
              {plural(result.res.succeeded, noun[0], noun[1])} done. {plural(result.res.failed, noun[0], noun[1])} unchanged:
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>{noun[0][0].toUpperCase() + noun[0].slice(1)}</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {result.res.results
                  .filter((r) => !r.ok)
                  .map((r) => (
                    <tr key={r.id} data-testid="bulk-failed-row">
                      <td className="mono nowrap">{result.labels.get(r.id) ?? r.id}</td>
                      <td>{r.message ?? r.code}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Dialog>
      ) : null}
    </>
  );
}

/** Selection state for a list; cleared whenever `resetKey` (the filters) changes. */
export function useSelection(resetKey: string): [Set<string>, (s: Set<string>) => void] {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [key, setKey] = useState(resetKey);
  if (key !== resetKey) {
    setKey(resetKey);
    setSelected(new Set());
  }
  return [selected, setSelected];
}

/** The selected loaded rows as bulk rows. */
export function bulkRows<T extends { id: string; number: string; status?: string }>(rows: readonly T[], selected: ReadonlySet<string>): BulkRow[] {
  return rows.filter((r) => selected.has(r.id)).map((r) => ({ id: r.id, row_version: (r as { row_version?: number }).row_version ?? 0, label: r.number, status: r.status }));
}

export function ReasonField({ id, label, value, onChange, required, testId }: { id: string; label: string; value: string; onChange(v: string): void; required?: boolean; testId?: string }) {
  return (
    <div className={`field${required ? " required" : ""}`}>
      <label htmlFor={id}>{label}</label>
      <input id={id} className="input" value={value} maxLength={200} onChange={(e) => onChange(e.target.value)} data-testid={testId} />
    </div>
  );
}

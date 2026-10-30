/**
 * Line-specific times of one routing operation (M3 12 "Line rates", 3.2 `OperationLineRate`): per eligible line
 * of the operation's stage, an own setup and/or run time. An own run time is that line's real rate: the line's
 * speed factor is not applied to it. Empty = use the operation's times (run time / speed factor).
 */
import { useState } from "react";
import { Icon } from "../../components/Icon";
import { listLines } from "../api/client";
import { createLineRate, deleteLineRate, listLineRates, updateLineRate } from "../api/clientM3";
import type { OperationLineRateRecord } from "../api/typesM3";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { MfgError } from "./Feedback";
import { numOrNull } from "./Field";

export function LineRates({ operationId, groupId, readOnly }: { operationId: string | null; groupId: string; readOnly: boolean }) {
  const canEdit = useCan("master_edit") && !readOnly;
  const lines = useLoad((signal) => (groupId ? listLines({ group_id: groupId }, signal) : null), [groupId]);
  const rates = useLoad((signal) => (operationId ? listLineRates({ operation_id: operationId }, signal) : null), [operationId]);
  const [draft, setDraft] = useState<Record<string, { setup: string; run: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  if (!operationId) return <p className="hint" style={{ margin: 0 }}>Line rates can be set after the routing is saved.</p>;
  const byLine = new Map((rates.data?.items ?? []).map((r) => [r.line_id, r]));
  const val = (lineId: string, k: "setup" | "run", r: OperationLineRateRecord | undefined) =>
    draft[lineId]?.[k] ?? (r ? String((k === "setup" ? r.setup_minutes : r.run_minutes) ?? "") : "");
  const save = async (lineId: string) => {
    const r = byLine.get(lineId);
    const setup = numOrNull(val(lineId, "setup", r));
    const run = numOrNull(val(lineId, "run", r));
    setBusy(lineId);
    setError(null);
    try {
      if (setup === null && run === null) {
        if (r) await deleteLineRate(r.id, r.row_version);
      } else {
        const body = { operation_id: operationId, line_id: lineId, setup_minutes: setup, run_minutes: run, note: r?.note ?? "" };
        if (r) await updateLineRate(r.id, body, r.row_version);
        else await createLineRate(body);
      }
      setDraft((d) => {
        const n = { ...d };
        delete n[lineId];
        return n;
      });
      rates.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <fieldset className="mfg-fieldset" data-testid="line-rates">
      <legend>Line rates (optional)</legend>
      <p className="hint" style={{ margin: 0 }}>
        Own times on a particular line. An own run time replaces "run time / speed factor" for that line. Empty = the operation's times.
      </p>
      <MfgError error={rates.error ?? lines.error ?? error} />
      <table className="table mfg-grid-table">
        <thead>
          <tr>
            <th>Line</th>
            <th>Speed</th>
            <th>Setup (min)</th>
            <th>Run (min per load)</th>
            <th>
              <span className="sr-only">Save</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {(lines.data?.items ?? []).map((l) => {
            const r = byLine.get(l.id);
            const dirty = Boolean(draft[l.id]);
            return (
              <tr key={l.id} data-testid="line-rate-row" data-line={l.code} data-has-rate={Boolean(r)}>
                <td className="mono">{l.code}</td>
                <td className="faint">{l.speed_factor}</td>
                <td style={{ width: 120 }}>
                  <input className="input sm num" type="number" min={0} step="any" aria-label={`${l.code} setup minutes`} placeholder="operation's" value={val(l.id, "setup", r)} readOnly={!canEdit}
                    onChange={(e) => setDraft((d) => ({ ...d, [l.id]: { setup: e.target.value, run: d[l.id]?.run ?? val(l.id, "run", r) } }))} />
                </td>
                <td style={{ width: 140 }}>
                  <input className="input sm num" type="number" min={0} step="any" aria-label={`${l.code} run minutes`} placeholder="operation's" value={val(l.id, "run", r)} readOnly={!canEdit}
                    onChange={(e) => setDraft((d) => ({ ...d, [l.id]: { run: e.target.value, setup: d[l.id]?.setup ?? val(l.id, "setup", r) } }))} data-testid="line-rate-run" />
                </td>
                <td>
                  {canEdit && dirty ? (
                    <button type="button" className="btn sm" onClick={() => void save(l.id)} disabled={busy === l.id} data-testid="line-rate-save">
                      {busy === l.id ? <span className="spinner" aria-hidden /> : <Icon name="save" />} Save
                    </button>
                  ) : r ? (
                    <span className="badge accent">own rate</span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </fieldset>
  );
}

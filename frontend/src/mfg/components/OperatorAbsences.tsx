/**
 * Operator absences (M3 12, 3.2 `OperatorAbsence`): leave, training, sickness; removed from the operator's shift
 * windows by the scheduler. Times are entered in plant time.
 */
import { useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { createAbsence, deleteAbsence, listAbsences, updateAbsence } from "../api/clientM3";
import { ABSENCE_KINDS, type AbsenceKind, type OperatorAbsenceRecord } from "../api/typesM3";
import { usePlantClock } from "../lib/plantTime";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { EntityFormDialog } from "./EntityFormDialog";
import { MfgError } from "./Feedback";
import { SelectField, TextField } from "./Field";

const KIND_LABEL: Record<AbsenceKind, string> = { leave: "Leave", training: "Training", sick: "Sick", other: "Other" };

export function OperatorAbsences({ operatorId }: { operatorId: string }) {
  const clock = usePlantClock();
  const canEdit = useCan("master_edit");
  const list = useLoad((signal) => listAbsences({ operator_id: operatorId }, signal), [operatorId]);
  const [editing, setEditing] = useState<OperatorAbsenceRecord | "new" | null>(null);
  const [deleting, setDeleting] = useState<OperatorAbsenceRecord | null>(null);
  const [error, setError] = useState<unknown>(null);
  return (
    <section className="card" data-testid="operator-absences" style={{ marginTop: 12 }}>
      <div className="card-header">
        <h3>Absences</h3>
        {canEdit ? (
          <button type="button" className="btn sm" onClick={() => setEditing("new")} data-testid="absence-new">
            <Icon name="plus" /> Add absence
          </button>
        ) : null}
      </div>
      <MfgError error={list.error ?? error} onRetry={list.reload} />
      <ul className="mfg-plain-list">
        {list.data && list.data.items.length === 0 ? <li className="issue muted">No absences planned.</li> : null}
        {(list.data?.items ?? []).map((a) => (
          <li key={a.id} className="issue" data-testid="absence-row" data-kind={a.kind}>
            <span className="badge info">{KIND_LABEL[a.kind]}</span>
            <span className="grow small">
              {clock.dateTime(a.start)} – {clock.dateTime(a.end)}
              {a.note ? <span className="muted"> · {a.note}</span> : null}
            </span>
            {canEdit ? (
              <>
                <button type="button" className="btn sm" onClick={() => setEditing(a)}>
                  Edit
                </button>
                <button type="button" className="btn sm ghost icon" aria-label="Delete absence" onClick={() => setDeleting(a)}>
                  <Icon name="trash" />
                </button>
              </>
            ) : null}
          </li>
        ))}
      </ul>
      {editing ? (
        <AbsenceDialog
          operatorId={operatorId}
          row={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            list.reload();
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title="Delete this absence?"
          confirmLabel="Delete"
          danger
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const d = deleting;
            setDeleting(null);
            setError(null);
            deleteAbsence(d.id, d.row_version).then(list.reload, setError);
          }}
        >
          <p style={{ margin: 0 }}>The operator counts as available again in the next schedule run.</p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}

function AbsenceDialog({ operatorId, row, onClose, onSaved }: { operatorId: string; row: OperatorAbsenceRecord | null; onClose(): void; onSaved(): void }) {
  const clock = usePlantClock();
  const [f, setF] = useState({
    start: row ? clock.toLocal(row.start) : "",
    end: row ? clock.toLocal(row.end) : "",
    kind: (row?.kind ?? "leave") as AbsenceKind,
    note: row?.note ?? "",
  });
  const bad = !f.start || !f.end || f.start >= f.end;
  return (
    <EntityFormDialog
      title={row ? "Absence" : "New absence"}
      submitLabel={row ? "Save" : "Add"}
      testId="absence-form"
      disabled={bad}
      onClose={onClose}
      onSubmit={async () => {
        const body = { operator_id: operatorId, start: clock.fromLocal(f.start), end: clock.fromLocal(f.end), kind: f.kind, note: f.note };
        if (row) await updateAbsence(row.id, body, row.row_version);
        else await createAbsence(body);
        onSaved();
      }}
    >
      <div className="form-grid">
        <TextField label={`From (${clock.zoneLabel})`} type="datetime-local" value={f.start} onChange={(v) => setF({ ...f, start: v })} testId="absence-start" />
        <TextField label="Until" type="datetime-local" value={f.end} onChange={(v) => setF({ ...f, end: v })} testId="absence-end" hint={f.start && f.end && f.start >= f.end ? "Must be after the start." : undefined} />
        <SelectField label="Kind" value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={ABSENCE_KINDS.map((k) => ({ value: k, label: KIND_LABEL[k] }))} testId="absence-kind" />
      </div>
      <TextField label="Note" value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} />
    </EntityFormDialog>
  );
}

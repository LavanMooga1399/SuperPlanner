/**
 * `/mfg/plant/setups` (M3 12, 3.2, 4): changeover (setup) minutes per line setup family, from one item family to
 * another. `*` means "any"; the most specific row wins ((from,to) > (from,*) > (*,to) > (*,*)). Lines without a
 * matching row use the operation's own setup time.
 */
import { useMemo, useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { listLines } from "../api/client";
import { createSetupRow, deleteSetupRow, listSetupMatrix, updateSetupRow } from "../api/clientM3";
import type { SetupMatrixRowInput, SetupMatrixRowRecord } from "../api/typesM3";
import { EntityFormDialog } from "../components/EntityFormDialog";
import { MfgError, Spinner } from "../components/Feedback";
import { numOr, TextField } from "../components/Field";
import { PermissionGate } from "../components/PermissionGate";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { t } from "../../lib/i18n";

function RowDialog({ row, family, families, onClose, onSaved }: { row: SetupMatrixRowRecord | null; family: string; families: string[]; onClose(): void; onSaved(): void }) {
  const [f, setF] = useState({
    line_setup_family: row?.line_setup_family ?? family,
    from_family: row?.from_family ?? "*",
    to_family: row?.to_family ?? "*",
    minutes: String(row?.setup_minutes ?? ""),
  });
  const body: SetupMatrixRowInput = {
    line_setup_family: f.line_setup_family.trim().toUpperCase(),
    from_family: f.from_family.trim().toUpperCase() || "*",
    to_family: f.to_family.trim().toUpperCase() || "*",
    setup_minutes: numOr(f.minutes, 0),
  };
  const bad = !body.line_setup_family || f.minutes.trim() === "" || body.setup_minutes < 0;
  return (
    <EntityFormDialog
      title={row ? t("mfg.setupMatrixPage.str.changeoverTime") : t("mfg.setupMatrixPage.str.newChangeoverTime")}
      submitLabel={row ? t("mfg.setupMatrixPage.str.save") : t("mfg.setupMatrixPage.str.add")}
      testId="setup-row-form"
      disabled={bad}
      onClose={onClose}
      onSubmit={async () => {
        if (row) await updateSetupRow(row.id, body, row.row_version);
        else await createSetupRow(body);
        onSaved();
      }}
    >
      <datalist id="setup-families">
        <option value="*" />
        {families.map((x) => (
          <option key={x} value={x} />
        ))}
      </datalist>
      <div className="form-grid">
        <TextField label={t("mfg.setupMatrixPage.label.lineSetupFamily")} value={f.line_setup_family} onChange={(v) => setF({ ...f, line_setup_family: v })} maxLength={32} hint={t("mfg.setupMatrixPage.hint.theSetupFamilyOfThe")} testId="setup-line-family" />
        <TextField label={t("mfg.setupMatrixPage.label.fromItemFamily")} value={f.from_family} onChange={(v) => setF({ ...f, from_family: v })} maxLength={32} hint="* = any" testId="setup-from" />
        <TextField label={t("mfg.setupMatrixPage.label.toItemFamily")} value={f.to_family} onChange={(v) => setF({ ...f, to_family: v })} maxLength={32} hint="* = any" testId="setup-to" />
        <TextField label={t("mfg.setupMatrixPage.label.changeoverMinutes")} type="number" value={f.minutes} onChange={(v) => setF({ ...f, minutes: v })} testId="setup-minutes" />
      </div>
    </EntityFormDialog>
  );
}

export function SetupMatrixPage() {
  const rows = useLoad((signal) => listSetupMatrix(signal), []);
  const lines = useLoad((signal) => listLines({}, signal), []);
  const canEdit = useCan("master_edit");
  const [editing, setEditing] = useState<{ row: SetupMatrixRowRecord | null; family: string } | null>(null);
  const [deleting, setDeleting] = useState<SetupMatrixRowRecord | null>(null);
  const [error, setError] = useState<unknown>(null);
  const lineFamilies = useMemo(() => [...new Set((lines.data?.items ?? []).map((l) => l.setup_family).filter((x): x is string => Boolean(x)))].sort(), [lines.data]);
  const byFamily = useMemo(() => {
    const m = new Map<string, SetupMatrixRowRecord[]>();
    for (const f of lineFamilies) m.set(f, []);
    for (const r of rows.data?.items ?? []) m.set(r.line_setup_family, [...(m.get(r.line_setup_family) ?? []), r]);
    for (const v of m.values()) v.sort((a, b) => (a.from_family + a.to_family).localeCompare(b.from_family + b.to_family));
    return [...m.entries()];
  }, [rows.data, lineFamilies]);
  const itemFamilies = useMemo(() => [...new Set((rows.data?.items ?? []).flatMap((r) => [r.from_family, r.to_family]).filter((x) => x !== "*"))].sort(), [rows.data]);

  return (
    <div className="col gap-lg" data-testid="setup-matrix">
      <div className="row between wrap">
        <p className="muted small" style={{ margin: 0, maxWidth: 760 }}>
          {t("mfg.setupMatrixPage.text.changeoverTimeWhenALine")}
        </p>
        <PermissionGate perm="master_edit">
          <button type="button" className="btn primary" onClick={() => setEditing({ row: null, family: lineFamilies[0] ?? "" })} data-testid="setup-row-new">
            <Icon name="plus" /> {t("mfg.setupMatrixPage.btn.addChangeoverTime")}
          </button>
        </PermissionGate>
      </div>
      <MfgError error={rows.error ?? error} onRetry={rows.reload} />
      {rows.loading && !rows.data ? <Spinner /> : null}
      {rows.data && byFamily.length === 0 ? <p className="muted">{t("mfg.setupMatrixPage.text.noLineHasASetup")}</p> : null}
      {byFamily.map(([fam, list]) => (
        <section key={fam} className="card" data-testid="setup-family" data-family={fam}>
          <div className="card-header">
            <h3>
              {t("mfg.setupMatrixPage.text.linesOfFamily")}{" "}<span className="mono">{fam}</span>
            </h3>
            <span className="muted small">{(lines.data?.items ?? []).filter((l) => l.setup_family === fam).map((l) => l.code).join(", ") || t("mfg.setupMatrixPage.str.noLineUsesIt")}</span>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{t("mfg.setupMatrixPage.head.fromItemFamily")}</th>
                <th>{t("mfg.setupMatrixPage.head.toItemFamily")}</th>
                <th className="right">{t("mfg.setupMatrixPage.head.changeover")}</th>
                <th>
                  <span className="sr-only">{t("mfg.setupMatrixPage.text.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.length === 0 ? (
                <tr>
                  <td colSpan={4} className="muted">
                    {t("mfg.setupMatrixPage.text.noRowsOperationsUseTheir")}
                  </td>
                </tr>
              ) : null}
              {list.map((r) => (
                <tr key={r.id} data-testid="setup-matrix-row" data-from={r.from_family} data-to={r.to_family}>
                  <td className="mono">{r.from_family === "*" ? t("mfg.setupMatrixPage.str.any") : r.from_family}</td>
                  <td className="mono">{r.to_family === "*" ? t("mfg.setupMatrixPage.str.any") : r.to_family}</td>
                  <td className="right">{r.setup_minutes} min</td>
                  <td className="right">
                    {canEdit ? (
                      <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                        <button type="button" className="btn sm" onClick={() => setEditing({ row: r, family: fam })}>
                          {t("mfg.setupMatrixPage.btn.edit")}
                        </button>
                        <button type="button" className="btn sm ghost icon" aria-label={t("mfg.setupMatrixPage.tpl.deleteTo", { fromfamily: r.from_family, tofamily: r.to_family })} onClick={() => setDeleting(r)}>
                          <Icon name="trash" />
                        </button>
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {canEdit ? (
            <div className="card-footer">
              <button type="button" className="btn sm" onClick={() => setEditing({ row: null, family: fam })}>
                <Icon name="plus" />{" "}{t("mfg.setupMatrixPage.text.addFor", { fam: fam })}
              </button>
            </div>
          ) : null}
        </section>
      ))}
      {editing ? (
        <RowDialog
          row={editing.row}
          family={editing.family}
          families={itemFamilies}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            rows.reload();
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title={t("mfg.setupMatrixPage.title.deleteThisChangeoverTime")}
          confirmLabel={t("mfg.setupMatrixPage.btn.delete")}
          danger
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const d = deleting;
            setDeleting(null);
            setError(null);
            deleteSetupRow(d.id, d.row_version).then(rows.reload, setError);
          }}
        >
          <p style={{ margin: 0 }}>{t("mfg.setupMatrixPage.text.theNextScheduleRunUses")}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

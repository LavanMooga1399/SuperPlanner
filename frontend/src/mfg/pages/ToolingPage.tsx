/** `/mfg/resources/tooling` (`?tool=`, M 11.1): tool pools (stencils, fixtures, jigs) with the number of identical units. */
import { useState } from "react";
import { useSearchParams } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { createToolPool, deleteToolPool, listToolPools, updateToolPool } from "../api/client";
import type { ToolPoolRecord } from "../api/types";
import { EntityFormDialog } from "../components/EntityFormDialog";
import { MfgError, Spinner } from "../components/Feedback";
import { numOr, strOrNull, TextField } from "../components/Field";
import { RecordList, withParam } from "../components/RecordList";
import { useLoad } from "../lib/useMfg";

export function ToolingPage() {
  const [params, setParams] = useSearchParams();
  const toolParam = params.get("tool");
  const tools = useLoad((signal) => listToolPools(signal), []);
  const [editing, setEditing] = useState<ToolPoolRecord | "new" | null>(null);
  const [del, setDel] = useState<ToolPoolRecord | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [q, setQ] = useState("");
  const all = tools.data?.items ?? [];
  const list = q.trim() ? all.filter((t) => `${t.code} ${t.name} ${t.kind ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()) || t.id === toolParam) : all;
  const selected = all.find((t) => t.id === toolParam) ?? null;

  return (
    <div className="split mfg-split">
      <section className="card" aria-labelledby="tools-title">
        <div className="card-header">
          <h2 id="tools-title">Tooling</h2>
          <button type="button" className="btn sm primary" onClick={() => setEditing("new")} data-testid="tool-new">
            <Icon name="plus" /> New tool pool
          </button>
        </div>
        <div style={{ padding: "8px 16px 0" }}>
          <input className="input sm" type="search" placeholder="Search code, name or kind" aria-label="Search tooling" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <MfgError error={tools.error} onRetry={tools.reload} />
        <MfgError error={error} title="The action failed" />
        {tools.loading && !tools.data ? <Spinner /> : null}
        {tools.data ? (
          <RecordList
            items={list}
            selectedId={toolParam}
            onSelect={(id) => setParams((p) => withParam(p, "tool", id))}
            testId="tool-row"
            empty="No tooling yet. Add stencils, fixtures or jigs that operations hold while they run."
            render={(t) => (
              <>
                <strong className="mono">{t.code}</strong>
                <span className="grow mfg-ellipsis">{t.name}</span>
                {t.kind ? <span className="chip">{t.kind}</span> : null}
                <span className={t.quantity === 0 ? "badge warn" : "muted small"}>
                  {t.quantity === 0 ? <Icon name="alert" /> : null}
                  {t.quantity} available
                </span>
              </>
            )}
          />
        ) : null}
      </section>
      <aside aria-label="Tool pool details">
        {selected ? (
          <section className="card" data-testid="tool-panel" data-tool-id={selected.id}>
            <div className="card-header">
              <h2>
                <span className="mono">{selected.code}</span> {selected.name}
              </h2>
              <span className="row">
                <button type="button" className="btn sm" onClick={() => setEditing(selected)} data-testid="tool-edit">
                  Edit
                </button>
                <button type="button" className="btn sm ghost icon" aria-label={`Delete ${selected.code}`} onClick={() => setDel(selected)}>
                  <Icon name="trash" />
                </button>
              </span>
            </div>
            <div className="card-body">
              <dl className="dl">
                <dt>Kind</dt>
                <dd>{selected.kind ?? "-"}</dd>
                <dt>Units available</dt>
                <dd>{selected.quantity}</dd>
                <dt>Used by</dt>
                <dd>{selected.operation_count} operations</dd>
                <dt>Note</dt>
                <dd>{selected.note || "-"}</dd>
              </dl>
            </div>
          </section>
        ) : (
          <div className="card card-body muted">Select a tool pool to see it.</div>
        )}
      </aside>
      {editing ? (
        <ToolDialog
          tool={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(t) => {
            setEditing(null);
            tools.reload();
            setParams((p) => withParam(p, "tool", t.id));
          }}
        />
      ) : null}
      {del ? (
        <ConfirmDialog
          title={`Delete ${del.code}?`}
          confirmLabel="Delete"
          danger
          onCancel={() => setDel(null)}
          onConfirm={() => {
            const t = del;
            setDel(null);
            setError(null);
            deleteToolPool(t.id, t.row_version).then(() => {
              tools.reload();
              setParams((p) => withParam(p, "tool", null));
            }, setError);
          }}
        >
          <p style={{ margin: 0 }}>Tooling used by operations cannot be deleted.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function ToolDialog({ tool, onClose, onSaved }: { tool: ToolPoolRecord | null; onClose(): void; onSaved(t: ToolPoolRecord): void }) {
  const [code, setCode] = useState(tool?.code ?? "");
  const [name, setName] = useState(tool?.name ?? "");
  const [kind, setKind] = useState(tool?.kind ?? "");
  const [quantity, setQuantity] = useState(String(tool?.quantity ?? 1));
  const [note, setNote] = useState(tool?.note ?? "");
  return (
    <EntityFormDialog
      title={tool ? `Edit ${tool.code}` : "New tool pool"}
      submitLabel="Save"
      onClose={onClose}
      testId="tool-form"
      disabled={!code.trim() || !name.trim()}
      onSubmit={async () => {
        const body = { code: code.trim(), name: name.trim(), kind: strOrNull(kind), quantity: numOr(quantity, 0), note };
        onSaved(tool ? await updateToolPool(tool.id, body, tool.row_version) : await createToolPool(body));
      }}
    >
      <div className="form-grid">
        <TextField label="Code" value={code} onChange={setCode} required maxLength={32} testId="tool-code" />
        <TextField label="Name" value={name} onChange={setName} required testId="tool-name" />
        <TextField label="Kind" value={kind} onChange={setKind} maxLength={32} hint="e.g. stencil, fixture, jig" />
        <TextField label="Units available" type="number" value={quantity} onChange={setQuantity} hint="Identical units that can be used at the same time" testId="tool-quantity" />
      </div>
      <TextField label="Note" value={note} onChange={setNote} maxLength={500} />
    </EntityFormDialog>
  );
}

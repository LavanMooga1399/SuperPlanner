/**
 * `/mfg/import` and `/mfg/import/:importId?step=map|preview|done` (M 11.5). The wizard state lives in the URL
 * and the server's import record, so reloading the browser at any step restores it. Commit is impossible while
 * the preview has row errors. "Fix the file and upload again" keeps the mapping (re-applied by header names).
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { commitImport, deleteImport, getImport, putImportMapping } from "../api/client";
import type { ImportMappingRequest, ImportPreview as PreviewData, ImportRecord, RowError } from "../api/types";
import { ExportButtons, TemplateButtons } from "../components/ExportButtons";
import { MfgError, Spinner } from "../components/Feedback";
import { ImportMapping, mappingBlocked } from "../components/ImportMapping";
import { ImportPreview } from "../components/ImportPreview";
import { ImportResult } from "../components/ImportResult";
import { ImportUpload, sheetKind, sheetLabel } from "../components/ImportUpload";
import { fmtTimestamp } from "../lib/format";
import { initialMapping, remapByHeaders } from "../lib/importMapping";
import { mfgPaths } from "../lib/paths";
import { isConflict, isForbidden, isNotFound, useLoad, useMeta } from "../lib/useMfg";

type Step = "upload" | "map" | "preview" | "done";

/**
 * A commit refused with 409 `MFG_IMPORT_HAS_ERRORS` (the data changed between preview and commit) carries
 * `details: {row_errors, error_count}`: fold them into the shown preview so it no longer says "Ready to import".
 */
export function previewWithCommitErrors(preview: PreviewData | null, details: Record<string, unknown>): PreviewData {
  const rowErrors = Array.isArray(details.row_errors) ? (details.row_errors as RowError[]) : [];
  const count = typeof details.error_count === "number" ? details.error_count : rowErrors.length;
  const base: PreviewData = preview ?? { ok: false, counts: {}, error_count: 0, row_errors: [], warnings: [], changes_sample: [] };
  const counts = { ...base.counts };
  const rowsPerSheet = new Map<string, Set<number>>();
  for (const e of rowErrors) {
    if (!rowsPerSheet.has(e.sheet)) rowsPerSheet.set(e.sheet, new Set());
    rowsPerSheet.get(e.sheet)!.add(e.row);
  }
  for (const [sheet, rows] of rowsPerSheet) if (counts[sheet]) counts[sheet] = { ...counts[sheet], error: Math.max(counts[sheet].error, rows.size) };
  return { ...base, ok: false, counts, row_errors: rowErrors, error_count: Math.max(count, 1) };
}

const STEPS: { key: Step; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "map", label: "Map columns" },
  { key: "preview", label: "Preview" },
  { key: "done", label: "Done" },
];

function Stepper({ current }: { current: Step }) {
  const idx = STEPS.findIndex((s) => s.key === current);
  return (
    <ol className="mfg-stepper" aria-label="Import steps" data-testid="import-stepper" data-step={current}>
      {STEPS.map((s, i) => (
        <li key={s.key} className={i === idx ? "current" : i < idx ? "done" : undefined} aria-current={i === idx ? "step" : undefined}>
          <span className="mfg-step-num" aria-hidden>
            {i < idx ? <Icon name="check" size={12} /> : i + 1}
          </span>
          {s.label}
          {i < idx ? <span className="sr-only"> (done)</span> : null}
        </li>
      ))}
    </ol>
  );
}

/** The step to show for a record and the requested `?step=`. */
function resolveStep(rec: ImportRecord, requested: string | null): Exclude<Step, "upload"> {
  if (rec.status === "committed") return "done";
  if (requested === "preview" || requested === "done") return rec.preview ? "preview" : "map";
  if (requested === "map") return "map";
  return rec.status === "mapped" && rec.preview ? "preview" : "map";
}

export function ImportWizard() {
  const { importId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const reuse = params.get("reuse");

  if (!importId) {
    return (
      <div className="col gap-lg">
        <Header />
        <Stepper current="upload" />
        <ImportUpload
          reuseNote={reuse ? "Your previous column mapping will be applied to the new file (matched by column names)." : null}
          onUploaded={async (rec) => {
            if (reuse) {
              try {
                const prev = await getImport(reuse);
                if (prev.mapping) {
                  const mapped = await putImportMapping(rec.id, remapByHeaders(prev.mapping, prev.sheets, rec), rec.row_version);
                  navigate(mfgPaths.importStep(mapped.id, mapped.preview ? "preview" : "map"));
                  return;
                }
              } catch {
                /* expired or not mappable: continue with the suggestion */
              }
            }
            navigate(mfgPaths.importStep(rec.id, "map"));
          }}
        />
        <div className="grid-2">
          <section className="card card-body col">
            <h3>Start from a template</h3>
            <p className="muted small" style={{ margin: 0 }}>
              One sheet per kind of data with the expected columns, an example row and a README sheet explaining each field.
            </p>
            <TemplateButtons />
          </section>
          <section className="card card-body col">
            <h3>Export your data</h3>
            <p className="muted small" style={{ margin: 0 }}>
              Everything in the same format, ready to edit in Excel and import again.
            </p>
            <ExportButtons compact />
          </section>
        </div>
      </div>
    );
  }
  return <ImportSession key={importId} importId={importId} />;
}

function Header() {
  return (
    <div className="page-header mfg-header">
      <div>
        <h1>Import / export</h1>
        <p>Bring in items, BOMs, routings, plant data, suppliers, stock, purchase orders and requests, demand and work orders from Excel or CSV. Nothing is saved until you confirm the preview.</p>
      </div>
    </div>
  );
}

function ImportSession({ importId }: { importId: string }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const meta = useMeta();
  const loaded = useLoad((signal) => getImport(importId, signal), [importId]);
  const [rec, setRec] = useState<ImportRecord | null>(null);
  const [mapping, setMapping] = useState<ImportMappingRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /** Set when the commit was refused because the data changed after the preview. */
  const [staleCommit, setStaleCommit] = useState(false);

  useEffect(() => {
    if (loaded.data) {
      setRec(loaded.data);
      setMapping(initialMapping(loaded.data));
    }
  }, [loaded.data]);

  if (loaded.error && isNotFound(loaded.error))
    return (
      <div className="col gap-lg">
        <Header />
        <Banner
          tone="warn"
          title="This import is no longer available"
          testId="import-expired"
          actions={
            <Link className="btn sm primary" to={mfgPaths.importStart()}>
              Start a new import
            </Link>
          }
        >
          Uploaded files are kept for 24 hours. Upload the file again to continue.
        </Banner>
      </div>
    );
  if (loaded.error && !rec) return <MfgError error={loaded.error} onRetry={loaded.reload} />;
  if (!rec || !mapping) return <Spinner label="Loading import…" />;

  const step = resolveStep(rec, params.get("step"));
  const go = (s: "map" | "preview" | "done") => navigate(mfgPaths.importStep(rec.id, s));

  const refresh = async (msg: string) => {
    const fresh = await getImport(rec.id);
    setRec(fresh);
    setMapping(initialMapping(fresh));
    setNotice(msg);
  };

  const runPreview = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await putImportMapping(rec.id, mapping, rec.row_version);
      setRec(next);
      setMapping(initialMapping(next));
      go("preview");
    } catch (e) {
      if (isConflict(e)) await refresh("This import was changed in another tab; the latest version is shown.").catch(setError);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await commitImport(rec.id, rec.row_version);
      setRec(next);
      go("done");
    } catch (e) {
      if (e instanceof ApiError && e.code === "MFG_IMPORT_HAS_ERRORS") {
        // the data changed since the preview: show the server's row errors right away and keep commit disabled
        const shown = { ...rec, preview: previewWithCommitErrors(rec.preview, e.details) };
        setRec(shown);
        setStaleCommit(true);
        // then re-check the mapping against the current data for complete counts (the details may be truncated)
        try {
          const fresh = await putImportMapping(rec.id, mapping, rec.row_version);
          if (fresh.preview) {
            setRec(fresh);
            setMapping(initialMapping(fresh));
            setStaleCommit(fresh.preview.error_count > 0);
          }
        } catch {
          /* keep the errors from the refused commit */
        }
      } else if (e instanceof ApiError && e.code === "MFG_IMPORT_ALREADY_COMMITTED") {
        await refresh("This import was already saved.").catch(setError);
        go("done");
      } else if (isConflict(e)) {
        await refresh("This import was changed in another tab; check the preview again.").catch(setError);
      } else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    try {
      await deleteImport(rec.id);
    } catch {
      /* already gone */
    }
    navigate(mfgPaths.importStart());
  };

  const anyTarget = Object.values(mapping.sheets).some((m) => m.target);
  const blocked = mappingBlocked(mapping, meta?.import_spec.sheets ?? []);
  const errors = rec.preview?.error_count ?? 0;

  return (
    <div className="col gap-lg" data-testid="import-session" data-import-id={rec.id} data-status={rec.status}>
      <Header />
      <Stepper current={step} />
      <div className="row wrap small muted">
        <Icon name="file" /> <strong>{rec.filename}</strong> ({rec.format}) · {rec.sheets.length} {rec.sheets.length === 1 ? "sheet" : "sheets"}
        {rec.status !== "committed" ? ` · kept until ${fmtTimestamp(rec.expires_at)}` : ""}
      </div>
      {notice ? <Banner tone="info" role="status" title={notice} /> : null}
      <MfgError error={error} title={step === "preview" ? "Could not save the import" : "Could not check the file"} />
      {isForbidden(error) ? (
        <ul className="mfg-problem-list" data-testid="import-sheet-permissions">
          {Object.values(mapping.sheets)
            .filter((m) => m.target)
            .map((m) => (
              <li key={m.target}>
                {sheetLabel(m.target!)}: needs {sheetKind(m.target).perm}
              </li>
            ))}
        </ul>
      ) : null}

      {step === "map" ? (
        <>
          <ImportMapping record={rec} value={mapping} onChange={setMapping} />
          <div className="row mfg-sticky-actions">
            <button type="button" className="btn primary" onClick={() => void runPreview()} disabled={busy || blocked || !anyTarget} data-testid="import-preview-submit">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />} Preview the changes
            </button>
            {!anyTarget ? <span className="small muted">Choose what at least one sheet contains.</span> : null}
            <span className="grow" />
            <button type="button" className="btn ghost" onClick={() => void discard()} data-testid="import-discard">
              <Icon name="x" /> Cancel import
            </button>
          </div>
        </>
      ) : null}

      {step === "preview" && rec.preview ? (
        <>
          {errors > 0 ? (
            <Banner tone="danger" icon="x" title="Fix these rows before importing" testId="import-has-errors">
              {staleCommit ? "The data changed after the preview, so these rows can no longer be imported. Nothing was saved. " : null}
              Nothing is saved while the file has errors. Correct them in your file and upload it again (your column mapping is kept), or change the mapping.
            </Banner>
          ) : (
            <Banner tone="ok" title="Ready to import">
              All rows can be imported. Everything is saved in one step; if anything fails nothing is changed.
            </Banner>
          )}
          <ImportPreview preview={rec.preview} filename={rec.filename} />
          <div className="row wrap mfg-sticky-actions">
            <button
              type="button"
              className="btn primary"
              onClick={() => void commit()}
              disabled={busy || errors > 0}
              aria-disabled={errors > 0}
              title={errors > 0 ? "Fix the row errors first" : undefined}
              data-testid="import-commit"
            >
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Import now
            </button>
            <button type="button" className="btn" onClick={() => go("map")} data-testid="import-back-to-map">
              Change the mapping
            </button>
            <Link className="btn" to={mfgPaths.importStart(rec.id)} data-testid="import-reupload">
              <Icon name="upload" /> Fix the file and upload again
            </Link>
            <span className="grow" />
            <button type="button" className="btn ghost" onClick={() => void discard()} data-testid="import-discard">
              <Icon name="x" /> Cancel import
            </button>
          </div>
        </>
      ) : null}

      {step === "done" ? <ImportResult record={rec} /> : null}
    </div>
  );
}

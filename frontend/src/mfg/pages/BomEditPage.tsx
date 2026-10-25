/**
 * `/mfg/items/:itemId/bom/:bomId/edit` (M 11.1): the whole draft BOM document (header + lines) is saved with
 * one PUT and If-Match. Released/obsolete BOMs show "Released - copy to a new version to edit" with Copy
 * (M 11.3). `?line=` selects and scrolls to that line.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { copyBom, getBom, listItemBoms, releaseBom, updateBom } from "../api/client";
import type { BomInput, BomRecord } from "../api/types";
import { BomLinesGrid, blankLine, lineProblems, newKey, type LineDraft } from "../components/BomLinesGrid";
import { ReleaseDialog } from "../components/DocumentActions";
import { ConflictBanner, MfgError, NotFoundPanel, SaveState, Spinner } from "../components/Feedback";
import { numOrNull, TextField } from "../components/Field";
import { StatusChip } from "../components/StatusChip";
import { useUomOptions } from "../components/NewItemDialog";
import { mfgPaths } from "../lib/paths";
import { fieldErrors, isConflict, isNotFound, todayInOffset, useLoad, usePlant } from "../lib/useMfg";
import { useItem } from "./ItemShell";

interface Header {
  revision: string;
  version: string;
  effective_from: string;
  effective_to: string;
  serial_from: string;
  serial_to: string;
  note: string;
}

function toDrafts(b: BomRecord): LineDraft[] {
  return b.lines.map((l) => ({
    key: newKey(),
    id: l.id,
    find_number: l.find_number,
    child: l.child,
    qty_per: String(l.qty_per),
    uom: l.uom,
    scrap_pct: String(l.scrap_pct),
    ref_designators: l.ref_designators,
    alt_group: l.alt_group ?? "",
    alt_priority: String(l.alt_priority),
    operation_seq: l.operation_seq === null ? "" : String(l.operation_seq),
    note: l.note,
  }));
}

function toHeader(b: BomRecord): Header {
  return {
    revision: b.revision,
    version: String(b.version),
    effective_from: b.effective_from ?? "",
    effective_to: b.effective_to ?? "",
    serial_from: b.serial_from === null ? "" : String(b.serial_from),
    serial_to: b.serial_to === null ? "" : String(b.serial_to),
    note: b.note,
  };
}

function toInput(b: BomRecord, h: Header, lines: LineDraft[]): BomInput {
  return {
    item_id: b.item_id,
    revision: h.revision.trim() || b.revision,
    version: numOrNull(h.version) ?? b.version,
    effective_from: h.effective_from || null,
    effective_to: h.effective_to || null,
    serial_from: numOrNull(h.serial_from),
    serial_to: numOrNull(h.serial_to),
    note: h.note,
    lines: lines
      .filter((l) => l.child)
      .map((l) => ({
        ...(l.id ? { id: l.id } : {}),
        find_number: l.find_number.trim(),
        child_item_id: l.child ? l.child.id : "",
        qty_per: Number(l.qty_per),
        ...(l.uom ? { uom: l.uom } : {}),
        scrap_pct: numOrNull(l.scrap_pct) ?? 0,
        ref_designators: l.ref_designators.trim(),
        alt_group: l.alt_group.trim() || null,
        alt_priority: numOrNull(l.alt_priority) ?? 1,
        operation_seq: numOrNull(l.operation_seq),
        note: l.note,
      })),
  };
}

export function BomEditPage() {
  const { item } = useItem();
  const { bomId = "" } = useParams();
  const [params] = useSearchParams();
  const lineParam = params.get("line");
  const navigate = useNavigate();
  const plant = usePlant();
  const uomOptions = useUomOptions();
  const uoms = uomOptions.map((u) => u.value);
  const loaded = useLoad((signal) => getBom(bomId, signal), [bomId]);
  const siblings = useLoad((signal) => listItemBoms(item.id, signal), [item.id]);
  const [base, setBase] = useState<BomRecord | null>(null);
  const [header, setHeader] = useState<Header | null>(null);
  const [lines, setLines] = useState<LineDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [scrollTo, setScrollTo] = useState<{ index: number; seq: number } | null>(null);

  const reset = (b: BomRecord) => {
    setBase(b);
    setHeader(toHeader(b));
    setLines(toDrafts(b));
    setConflict(false);
  };

  useEffect(() => {
    if (loaded.data && loaded.data.id !== base?.id) reset(loaded.data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded.data]);

  useEffect(() => {
    if (!lineParam || !base) return;
    const i = lines.findIndex((l) => l.id === lineParam);
    if (i >= 0) setScrollTo({ index: i, seq: Date.now() });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lineParam, base?.id]);

  const serverErrors = useMemo(() => {
    const m = new Map<number, string[]>();
    for (const fe of fieldErrors(error)) {
      const [root, list, idx] = fe.loc;
      if (root === "body" && list === "lines" && typeof idx === "number") m.set(idx, [...(m.get(idx) ?? []), `${fe.field}: ${fe.message}`]);
    }
    return m;
  }, [error]);

  if (loaded.error && isNotFound(loaded.error))
    return <NotFoundPanel what="BOM" back={<Link className="btn" to={mfgPaths.itemBom(item.id)}>Back to BOM versions</Link>} />;
  if (loaded.error && !base) return <MfgError error={loaded.error} onRetry={loaded.reload} />;
  if (!base || !header) return <Spinner label="Loading BOM…" />;

  const readOnly = base.status !== "draft";
  const input = toInput(base, header, lines);
  const dirty = JSON.stringify(input) !== JSON.stringify(toInput(base, toHeader(base), toDrafts(base)));
  const problems = lines.map((l, i) => ({ i, p: lineProblems(l) })).filter((x) => x.p.length);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await updateBom(base.id, input, base.row_version);
      reset(next);
      setSaved(true);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const reload = async () => {
    try {
      reset(await getBom(base.id));
      setError(null);
    } catch (e) {
      setError(e);
    }
  };

  const copy = async () => {
    try {
      const c = await copyBom(base.id, { revision: null }, base.row_version);
      navigate(mfgPaths.bomEdit(item.id, c.id));
    } catch (e) {
      setError(e);
    }
  };

  const setH = (k: keyof Header, v: string) => {
    setHeader({ ...header, [k]: v });
    setSaved(false);
  };

  return (
    <div className="col gap-lg" data-testid="bom-edit">
      <div className="row wrap">
        <Link to={mfgPaths.itemBom(item.id, { bom: base.id })} className="btn sm ghost">
          <Icon name="chevron-right" style={{ transform: "rotate(180deg)" }} /> BOM versions
        </Link>
        <h2>
          BOM rev. {base.revision} v{base.version}
        </h2>
        <StatusChip status={base.status} />
        <span className="muted small">{lines.length} lines</span>
      </div>

      {readOnly ? (
        <Banner
          tone="info"
          icon="lock"
          testId="bom-readonly"
          title={base.status === "released" ? "Released - copy to a new version to edit" : "Obsolete - copy to a new version to edit"}
          actions={
            <button type="button" className="btn sm primary" onClick={() => void copy()} data-testid="bom-copy-banner">
              <Icon name="copy" /> Copy to a new version
            </button>
          }
        >
          Released and obsolete BOMs are read-only so that plans keep using exactly what was approved.
        </Banner>
      ) : null}
      {conflict ? <ConflictBanner onReload={() => void reload()} what="this BOM" /> : null}
      <MfgError error={error} title="Could not save the BOM" />

      <section className="card">
        <div className="card-header">
          <h3>Version</h3>
        </div>
        <div className="card-body form-grid">
          <TextField label="Revision" value={header.revision} onChange={(v) => setH("revision", v)} maxLength={16} disabled={readOnly} />
          <TextField label="Version" type="number" value={header.version} onChange={(v) => setH("version", v)} disabled={readOnly} />
          <TextField label="Effective from" type="date" value={header.effective_from} onChange={(v) => setH("effective_from", v)} disabled={readOnly} hint="Usually set when releasing." />
          <TextField label="Effective until" type="date" value={header.effective_to} onChange={(v) => setH("effective_to", v)} disabled={readOnly} hint="Exclusive; empty = open-ended." />
          {item.serialized ? (
            <>
              <TextField label="From unit serial" type="number" value={header.serial_from} onChange={(v) => setH("serial_from", v)} disabled={readOnly} />
              <TextField label="To unit serial" type="number" value={header.serial_to} onChange={(v) => setH("serial_to", v)} disabled={readOnly} />
            </>
          ) : null}
          <TextField label="Note" value={header.note} onChange={(v) => setH("note", v)} maxLength={500} disabled={readOnly} />
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h3>Lines</h3>
          <span className="muted small">Quantities are per 1 {item.uom} of {item.part_number}. Alternates share an alternate group; priority 1 is the primary part.</span>
        </div>
        <div className="card-body col">
          <BomLinesGrid
            lines={lines}
            onChange={(next) => {
              setLines(next);
              setSaved(false);
            }}
            readOnly={readOnly}
            parentId={item.id}
            uoms={uoms}
            selectedLineId={lineParam}
            serverErrors={serverErrors}
            scrollTo={scrollTo}
          />
          {!readOnly ? (
            <div>
              <button type="button" className="btn sm" onClick={() => setLines([...lines, blankLine(lines)])} data-testid="bom-line-add">
                <Icon name="plus" /> Add line
              </button>
            </div>
          ) : null}
          {problems.length && !readOnly ? (
            <ul className="small mfg-problem-list" role="status">
              {problems.slice(0, 8).map((x) => (
                <li key={x.i}>
                  <Icon name="alert" size={12} /> Line {x.i + 1}: {x.p.join("; ")}
                </li>
              ))}
              {problems.length > 8 ? <li>and {problems.length - 8} more lines</li> : null}
            </ul>
          ) : null}
        </div>
      </section>

      {!readOnly ? (
        <div className="row mfg-sticky-actions">
          <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || !dirty || problems.length > 0} data-testid="bom-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} Save BOM
          </button>
          <button type="button" className="btn" disabled={!dirty || busy} onClick={() => reset(base)}>
            Undo changes
          </button>
          <SaveState busy={false} saved={saved && !dirty} />
          <span className="grow" />
          <button type="button" className="btn" disabled={dirty || busy || lines.length === 0} onClick={() => setReleasing(true)} title={dirty ? "Save first" : undefined} data-testid="bom-release">
            <Icon name="check" /> Release…
          </button>
        </div>
      ) : null}

      {releasing ? (
        <ReleaseDialog
          what={`rev. ${base.revision} v${base.version}`}
          defaultFrom={todayInOffset(plant.data?.utc_offset)}
          hasReleased={(siblings.data?.items ?? []).some((b) => b.status === "released" && b.id !== base.id)}
          onClose={() => setReleasing(false)}
          onRelease={async (body) => {
            await releaseBom(base.id, body, base.row_version);
            navigate(mfgPaths.itemBom(item.id, { bom: base.id }));
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * `/mfg/items/:itemId/bom` (M 11.1): BOM versions (status, effectivity, release/obsolete/copy/delete), the
 * indented structure of the explosion at `?on=` (`BomTree`) or the total quantities (summarized), and the lines
 * of the version picked with `?bom=` (selecting `?line=`).
 */
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ApiError } from "../../api/client";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import {
  copyBom,
  createBom,
  deleteBom,
  getBom,
  getExplosion,
  listItemBoms,
  obsoleteBom,
  releaseBom,
} from "../api/client";
import type { BomLineRecord, BomSummary, ExplosionMode, SummarizedRow } from "../api/types";
import { BomTree } from "../components/BomTree";
import { ReleaseDialog } from "../components/DocumentActions";
import { EffectivityBadge } from "../components/EffectivityBadge";
import { MfgError, Spinner } from "../components/Feedback";
import { MakeBuyBadge, StatusChip } from "../components/StatusChip";
import { VirtualTable, type Column } from "../components/VirtualTable";
import { fmtDate, fmtQty } from "../lib/format";
import { mfgPaths } from "../lib/paths";
import { errorText, todayInOffset, useLoad, usePlant } from "../lib/useMfg";
import { useItem } from "./ItemShell";

type Pending = { kind: "release" | "obsolete" | "delete"; bom: BomSummary } | null;

export function BomTab() {
  const { item } = useItem();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const plant = usePlant();
  const bomParam = params.get("bom");
  const lineParam = params.get("line");
  const on = params.get("on") ?? "";
  const serial = params.get("serial") ?? "";
  const qty = params.get("qty") ?? "";
  const [mode, setMode] = useState<ExplosionMode>("indented");
  const [pending, setPending] = useState<Pending>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const versions = useLoad((signal) => listItemBoms(item.id, signal), [item.id]);
  const explosion = useLoad(
    (signal) =>
      item.make_buy === "buy"
        ? null
        : getExplosion(
            item.id,
            {
              on: on || undefined,
              serial: serial ? Number(serial) : undefined,
              qty: qty ? Number(qty) : undefined,
              mode,
            },
            signal,
          ),
    [item.id, on, serial, qty, mode, versions.data],
  );
  const selected = useLoad((signal) => (bomParam ? getBom(bomParam, signal) : null), [bomParam, versions.data]);

  const setParam = (k: string, v: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (v) next.set(k, v);
        else next.delete(k);
        return next;
      },
      { replace: true },
    );

  const list = versions.data?.items ?? [];
  const hasReleased = list.some((b) => b.status === "released");
  const today = todayInOffset(plant.data?.utc_offset);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      versions.reload();
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
      setPending(null);
    }
  };

  const newBom = () =>
    act(async () => {
      const b = await createBom({ item_id: item.id, lines: [] });
      navigate(mfgPaths.bomEdit(item.id, b.id));
    });

  const copy = (b: BomSummary) =>
    act(async () => {
      const c = await copyBom(b.id, { revision: null }, b.row_version);
      navigate(mfgPaths.bomEdit(item.id, c.id));
    });

  const tooLarge = explosion.error instanceof ApiError && explosion.error.code === "MFG_EXPLOSION_TOO_LARGE";

  if (item.make_buy === "buy")
    return (
      <Banner tone="info" title="Bought items have no BOM">
        {item.part_number} is bought from a supplier. To give it a bill of materials, change it to Make on the Details tab.
      </Banner>
    );

  return (
    <div className="col gap-lg">
      <section className="card" aria-labelledby="bom-versions-title">
        <div className="card-header">
          <h2 id="bom-versions-title">BOM versions</h2>
          <button type="button" className="btn sm primary" onClick={() => void newBom()} disabled={busy} data-testid="bom-new">
            <Icon name="plus" /> New BOM version
          </button>
        </div>
        <MfgError error={versions.error} onRetry={versions.reload} />
        <MfgError error={actionError} title="The action failed" />
        {list.length === 0 && !versions.loading ? (
          <div className="card-body muted">No BOM yet. Create one to list the parts this item is made of.</div>
        ) : null}
        <ul className="mfg-plain-list mfg-version-list">
          {list.map((b) => (
            <li
              key={b.id}
              className={`mfg-version${b.id === bomParam ? " mfg-selected" : ""}`}
              data-testid={`bom-version-${b.id}`}
              data-status={b.status}
              aria-current={b.id === bomParam ? "true" : undefined}
            >
              <button
                type="button"
                className="mfg-version-main"
                onClick={() => setParam("bom", b.id === bomParam ? "" : b.id)}
                aria-pressed={b.id === bomParam}
                title="Show this version's lines"
              >
                <strong>
                  Rev. {b.revision} v{b.version}
                </strong>
                <StatusChip status={b.status} />
                <EffectivityBadge from={b.effective_from} to={b.effective_to} serialFrom={b.serial_from} serialTo={b.serial_to} />
                <span className="muted small">{b.line_count} lines</span>
                {b.note ? <span className="muted small mfg-ellipsis">{b.note}</span> : null}
              </button>
              <span className="row">
                {b.status === "draft" ? (
                  <>
                    <Link className="btn sm" to={mfgPaths.bomEdit(item.id, b.id)} data-testid="bom-edit">
                      <Icon name="settings" /> Edit
                    </Link>
                    <button type="button" className="btn sm" onClick={() => setPending({ kind: "release", bom: b })} disabled={busy} data-testid="bom-release">
                      <Icon name="check" /> Release
                    </button>
                  </>
                ) : null}
                <button type="button" className="btn sm" onClick={() => void copy(b)} disabled={busy} data-testid="bom-copy" title="Copy to a new draft version">
                  <Icon name="copy" /> Copy
                </button>
                {b.status === "released" ? (
                  <button type="button" className="btn sm ghost" onClick={() => setPending({ kind: "obsolete", bom: b })} disabled={busy} data-testid="bom-obsolete">
                    <Icon name="ban" /> Make obsolete
                  </button>
                ) : (
                  <button type="button" className="btn sm ghost icon" onClick={() => setPending({ kind: "delete", bom: b })} disabled={busy} aria-label={`Delete version ${b.version}`} data-testid="bom-delete">
                    <Icon name="trash" />
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {bomParam ? <SelectedLines loading={selected.loading} error={selected.error} lines={selected.data?.lines ?? null} title={selected.data ? `Lines of rev. ${selected.data.revision} v${selected.data.version}` : "Lines"} line={lineParam} status={selected.data?.status} editTo={selected.data ? mfgPaths.bomEdit(item.id, selected.data.id) : null} onClose={() => setParam("bom", "")} /> : null}

      <section className="card" aria-labelledby="bom-structure-title">
        <div className="card-header">
          <h2 id="bom-structure-title">Structure</h2>
          <div className="btn-group" role="group" aria-label="View">
            <button type="button" className="btn sm" aria-pressed={mode === "indented"} onClick={() => setMode("indented")} data-testid="bom-mode-indented">
              All levels
            </button>
            <button type="button" className="btn sm" aria-pressed={mode === "summarized"} onClick={() => setMode("summarized")} data-testid="bom-mode-summarized">
              Total quantities
            </button>
          </div>
        </div>
        <div className="card-body col">
          <div className="toolbar" style={{ marginBottom: 0 }}>
            <div className="field">
              <label htmlFor="bom-on">Effective on</label>
              <input id="bom-on" type="date" className="input sm" value={on} onChange={(e) => setParam("on", e.target.value)} />
            </div>
            <div className="field" style={{ width: 120 }}>
              <label htmlFor="bom-qty">Quantity to build</label>
              <input id="bom-qty" type="number" min={0} step="any" className="input sm" value={qty} placeholder="1" onChange={(e) => setParam("qty", e.target.value)} />
            </div>
            {item.serialized ? (
              <div className="field" style={{ width: 120 }}>
                <label htmlFor="bom-serial">Unit serial</label>
                <input id="bom-serial" type="number" min={1} className="input sm" value={serial} onChange={(e) => setParam("serial", e.target.value)} />
              </div>
            ) : null}
            <span className="muted small" style={{ alignSelf: "flex-end" }}>
              {explosion.data ? `Released BOMs effective on ${fmtDate(explosion.data.on ?? (on || today))}; quantities include scrap and yield.` : null}
            </span>
          </div>
          {tooLarge ? (
            <Banner
              tone="warn"
              title="This structure is too large to show level by level"
              actions={
                <button type="button" className="btn sm" onClick={() => setMode("summarized")}>
                  Show total quantities
                </button>
              }
            >
              {errorText(explosion.error)}
            </Banner>
          ) : (
            <MfgError error={explosion.error} onRetry={explosion.reload} />
          )}
          {explosion.data?.warnings.length ? (
            <Banner tone="warn" title="Notes on this structure">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {explosion.data.warnings.map((w, i) => (
                  <li key={i}>{w.message}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
          {explosion.loading && !explosion.data ? <Spinner label="Loading structure…" /> : null}
          {explosion.data && explosion.data.mode === "indented" && mode === "indented" ? (
            explosion.data.rows.length <= 1 && !explosion.data.rows[0]?.has_children ? (
              <p className="muted" style={{ margin: 0 }}>
                No released BOM is effective on this date. Release a version above to see its structure.
              </p>
            ) : (
              <BomTree rows={explosion.data.rows} selectLineId={lineParam} />
            )
          ) : null}
          {explosion.data && explosion.data.mode === "summarized" && mode === "summarized" ? <SummaryTable rows={explosion.data.rows} /> : null}
          {explosion.data ? (
            <p className="small muted" style={{ margin: 0 }} data-testid="bom-totals">
              {explosion.data.totals.distinct_items.toLocaleString()} distinct items · {explosion.data.totals.make_items} make ·{" "}
              {explosion.data.totals.buy_items} buy · {explosion.data.totals.phantom_items} phantom · {explosion.data.totals.max_level + 1} levels
            </p>
          ) : null}
        </div>
      </section>

      {pending?.kind === "release" ? (
        <ReleaseDialog
          what={`rev. ${pending.bom.revision} v${pending.bom.version}`}
          defaultFrom={hasReleased ? today : ""}
          hasReleased={list.some((b) => b.status === "released" && b.id !== pending.bom.id)}
          onClose={() => setPending(null)}
          onRelease={async (body) => {
            await releaseBom(pending.bom.id, body, pending.bom.row_version);
            setPending(null);
            versions.reload();
          }}
        />
      ) : null}
      {pending?.kind === "obsolete" ? (
        <ConfirmDialog
          title={`Make rev. ${pending.bom.revision} v${pending.bom.version} obsolete?`}
          confirmLabel="Make obsolete"
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={() => void act(() => obsoleteBom(pending.bom.id, pending.bom.row_version))}
        >
          <p style={{ margin: 0 }}>It stops being used for planning and stays in the history (read-only).</p>
        </ConfirmDialog>
      ) : null}
      {pending?.kind === "delete" ? (
        <ConfirmDialog
          title={`Delete rev. ${pending.bom.revision} v${pending.bom.version}?`}
          confirmLabel="Delete"
          danger
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={() =>
            void act(async () => {
              await deleteBom(pending.bom.id, pending.bom.row_version);
              if (bomParam === pending.bom.id) setParam("bom", "");
            })
          }
        >
          <p style={{ margin: 0 }}>The version and its lines are deleted.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function SelectedLines({
  lines,
  title,
  line,
  status,
  editTo,
  loading,
  error,
  onClose,
}: {
  lines: BomLineRecord[] | null;
  title: string;
  line: string | null;
  status?: string;
  editTo: string | null;
  loading: boolean;
  error: unknown;
  onClose(): void;
}) {
  const index = useMemo(() => (lines && line ? lines.findIndex((l) => l.id === line) : -1), [lines, line]);
  const scrollTo = useMemo(() => (index >= 0 ? { index, seq: index + 1 } : null), [index]);
  const columns: Column<BomLineRecord>[] = [
    { key: "fn", header: "Find no.", width: "70px", render: (l) => <span className="mono">{l.find_number}</span> },
    {
      key: "pn",
      header: "Component",
      width: "minmax(160px, 1fr)",
      render: (l) => (
        <Link to={mfgPaths.item(l.child.id)} className="mono" tabIndex={-1}>
          {l.child.part_number}
        </Link>
      ),
    },
    { key: "desc", header: "Description", width: "minmax(160px, 1.4fr)", render: (l) => <span className="mfg-ellipsis">{l.child.description}</span> },
    { key: "mb", header: "Make / buy", width: "100px", render: (l) => <MakeBuyBadge value={l.child.make_buy} /> },
    { key: "qty", header: "Qty per", width: "80px", align: "right", render: (l) => fmtQty(l.qty_per) },
    { key: "uom", header: "Unit", width: "54px", render: (l) => l.uom },
    { key: "scrap", header: "Scrap %", width: "68px", align: "right", render: (l) => (l.scrap_pct ? fmtQty(l.scrap_pct) : "") },
    { key: "alt", header: "Alternate", width: "90px", render: (l) => (l.alt_group ? `${l.alt_group} / ${l.alt_priority}` : "") },
    { key: "op", header: "At operation", width: "90px", align: "right", render: (l) => l.operation_seq ?? "" },
    { key: "ref", header: "Ref. des.", width: "minmax(100px, 1fr)", render: (l) => <span className="mfg-ellipsis small">{l.ref_designators}</span> },
  ];
  return (
    <section className="card" aria-label={title} data-testid="bom-selected-lines">
      <div className="card-header">
        <h2>{title}</h2>
        <span className="row">
          {status && status !== "draft" ? <span className="muted small">Read-only ({status}); copy it to change it.</span> : null}
          {status === "draft" && editTo ? (
            <Link className="btn sm" to={editTo}>
              <Icon name="settings" /> Edit lines
            </Link>
          ) : null}
          <button type="button" className="btn sm ghost icon" aria-label="Close lines" onClick={onClose}>
            <Icon name="x" />
          </button>
        </span>
      </div>
      <div className="card-body">
        <MfgError error={error} />
        {loading && !lines ? <Spinner /> : null}
        {lines ? (
          <VirtualTable
            rows={lines}
            columns={columns}
            rowKey={(l) => l.id}
            label={title}
            height="min(40vh, 420px)"
            scrollTo={scrollTo}
            rowExtras={(l) => ({ testId: "bom-line-row", data: { "line-id": l.id }, className: l.id === line ? "mfg-selected" : undefined, ariaSelected: l.id === line })}
            empty="This version has no lines yet."
          />
        ) : null}
      </div>
    </section>
  );
}

function SummaryTable({ rows }: { rows: SummarizedRow[] }) {
  const columns: Column<SummarizedRow>[] = [
    {
      key: "pn",
      header: "Part number",
      width: "minmax(160px, 1fr)",
      render: (r) => (
        <Link to={mfgPaths.item(r.item_id)} className="mono" tabIndex={-1}>
          {r.part_number}
        </Link>
      ),
    },
    { key: "desc", header: "Description", width: "minmax(180px, 1.6fr)", render: (r) => <span className="mfg-ellipsis">{r.description}</span> },
    { key: "mb", header: "Make / buy", width: "100px", render: (r) => <MakeBuyBadge value={r.make_buy} /> },
    { key: "qty", header: "Total qty", width: "110px", align: "right", render: (r) => `${fmtQty(r.total_qty)} ${r.uom}` },
    { key: "lv", header: "Levels", width: "70px", align: "right", render: (r) => (r.min_level === r.max_level ? r.min_level : `${r.min_level}-${r.max_level}`) },
    { key: "occ", header: "Used", width: "70px", align: "right", render: (r) => `${r.occurrences}x` },
    { key: "lt", header: "Lead time", width: "80px", align: "right", render: (r) => (r.lead_time_days === null ? "" : `${r.lead_time_days} d`) },
  ];
  return <VirtualTable rows={rows} columns={columns} rowKey={(r) => r.item_id} label="Total quantities" testId="bom-summary" rowExtras={(r) => ({ testId: "bom-summary-row", data: { "part-number": r.part_number } })} />;
}

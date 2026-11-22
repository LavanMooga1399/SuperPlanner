/**
 * Transfers between plants (M5 3.5): `/mfg/transfers` (outgoing and incoming) and `/mfg/transfers/:id`.
 * A transfer order is made in the sending plant and appears, with the same number, as incoming in the receiving plant.
 * MRP sees it as demand here and supply there. Shipping (store keepers here) books `transfer_ship` per line with its
 * lots; receiving (store keepers in the other plant) books `transfer_receipt`, the lots carry over, and the trace
 * follows them across plants.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { listLocations, listWorkspaces, newIdempotencyKey } from "../../api/clientM2";
import { createTransfer, getTransfer, listTransfers, postTransferMovement, transferAction } from "../../api/clientM5";
import type { ItemRef } from "../../api/types";
import { isOutbound, type TransferInput, type TransferOrder, type TransferStatus } from "../../api/typesM5";
import { MfgError, Spinner } from "../../components/Feedback";
import { ItemPicker } from "../../components/ItemPicker";
import { addDays, fmtDate } from "../../lib/format";
import { loadItemInfo } from "../../lib/itemCache";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { needsText, useAccess, useCan } from "../../lib/permissions";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { PageHeader } from "../../../components/PageHeader";
import { FilterBar } from "../../../components/FilterBar";
import { DataTable } from "../../components/DataTable";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { DateInput } from "../../../components/DateInput";
import { t as tr, plural } from "../../../lib/i18n";

type TransferLine = TransferOrder["lines"][number];
const LINE_COLS: Column<TransferLine>[] = [
  { key: "line", header: "Line", width: "72px", sortValue: (l) => l.line_no, render: (l) => l.line_no },
  { key: "item", header: "Item", width: "minmax(160px, 1.5fr)", exportValue: (l) => l.item_id, render: (l) => <ItemCode id={l.item_id} /> },
  { key: "qty", header: "Qty", width: "100px", align: "right", sortValue: (l) => l.qty, render: (l) => fmtNum(l.qty) },
  { key: "shipped", header: "Shipped", width: "100px", align: "right", sortValue: (l) => l.shipped_qty, render: (l) => fmtNum(l.shipped_qty) },
  { key: "received", header: "Received", width: "100px", align: "right", sortValue: (l) => l.received_qty, render: (l) => fmtNum(l.received_qty) },
  { key: "dates", header: "Ship → arrives", width: "minmax(200px, 1fr)", sortValue: (l) => l.ship_date, render: (l) => `${fmtDate(l.ship_date)} → ${fmtDate(l.receive_date)}` },
];

/** part number of an item id (transfer lines carry ids only) */
function ItemCode({ id }: { id: string }) {
  const it = useLoad(() => loadItemInfo(id).catch(() => null), [id]);
  return <span className="mono">{it.data?.part_number ?? "…"}</span>;
}

const STATUS: Record<TransferStatus, { label: string; tone: string }> = {
  draft: { label: "Draft", tone: "info" },
  open: { label: "Open", tone: "accent" },
  partly_shipped: { label: "Partly shipped", tone: "warn" },
  shipped: { label: "Shipped", tone: "warn" },
  received: { label: "Received", tone: "ok" },
  closed: { label: "Closed", tone: "info" },
  cancelled: { label: "Cancelled", tone: "info" },
};

function TrfStatus({ s }: { s: TransferStatus }) {
  const m = STATUS[s] ?? { label: s, tone: "info" };
  return (
    <span className={`badge ${m.tone}`} data-status={s}>
      {m.label}
    </span>
  );
}

export function TransfersPage() {
  const navigate = useNavigate();
  const canEdit = useCan("transfer_edit");
  const [params, setParams] = useSearchParams();
  const dir = params.get("dir") ?? "outbound";
  const data = usePaged<TransferOrder>((offset, limit, signal) => listTransfers({ direction: dir === "inbound" ? "in" : "out", limit, offset }, signal), [dir]);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    document.title = "Transfers - SuperPlanner";
  }, []);
  const plantOf = (t: TransferOrder) => {
    const p = dir === "outbound" ? t.dest_plant : t.source_plant;
    return `${p.code}${p.name ? ` · ${p.name}` : ""}`;
  };
  const columns: Column<TransferOrder>[] = [
    {
      key: "number",
      header: "Transfer",
      width: "140px",
      exportValue: (t) => t.number,
      render: (t) => (
        <Link to={mfgPaths.transfer(t.id)} className="mono">
          {t.number}
        </Link>
      ),
    },
    { key: "plant", header: dir === "outbound" ? "To" : "From", label: "Plant", width: "minmax(200px, 1.5fr)", render: plantOf },
    { key: "status", header: "Status", width: "150px", exportValue: (t) => STATUS[t.status]?.label ?? t.status, render: (t) => <TrfStatus s={t.status} /> },
    { key: "lines", header: "Lines", width: "minmax(150px, 1fr)", render: (t) => `${plural(t.lines.length, "line")}, ${fmtNum(t.lines.reduce((a, l) => a + l.qty, 0))} units` },
    { key: "dates", header: "Ship → arrives", width: "200px", render: (t) => (t.lines[0] ? `${fmtDate(t.lines[0].ship_date)} → ${fmtDate(t.lines[0].receive_date)}` : "") },
  ];
  return (
    <div className="col gap-lg" data-testid="transfers-page">
      <PageHeader
        title={tr("mfg.transferPages.title.transfersBetweenPlants")}
        description={tr("mfg.transferPages.desc.sendStockToAnotherPlant")}
        actions={
          <>
            <button type="button" className="btn primary" disabled={!canEdit} title={canEdit ? undefined : needsText("transfer_edit")} onClick={() => setCreating(true)} data-testid="transfer-new">
            <Icon name="plus" /> {tr("mfg.transferPages.btn.newTransfer")}
            </button>
          </>
        }
      />
      <FilterBar>
        <div className="field">
          <span className="field-label" id="trf-dir-label">
            Direction
          </span>
          <div className="btn-group" role="group" aria-labelledby="trf-dir-label">
            <button type="button" className="btn" aria-pressed={dir === "outbound"} onClick={() => setSearchParam(setParams, "dir", "outbound")}>
              {tr("mfg.transferPages.btn.outgoing")}
            </button>
            <button type="button" className="btn" aria-pressed={dir === "inbound"} onClick={() => setSearchParam(setParams, "dir", "inbound")} data-testid="transfer-incoming">
              {tr("mfg.transferPages.btn.incoming")}
            </button>
          </div>
        </div>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(t) => t.id}
        label={dir === "outbound" ? "Outgoing transfers" : "Incoming transfers"}
        testId="transfer-table"
        tableId="transfer-table"
        totalCount={data.total}
        loading={data.loading}
        onEndReached={data.onEndReached}
        exportName={`transfers-${dir}`}
        rowExtras={(t) => ({ testId: "transfer-row", data: { status: t.status } })}
        empty={dir === "outbound" ? "No outgoing transfers. Create one to send stock to another plant of your organisation." : "No incoming transfers. Transfers other plants send here appear in this list."}
        card={{ title: "number", status: "status", fields: ["plant", "lines", "dates"] }}
      />
      {creating ? <NewTransferDialog onClose={() => setCreating(false)} onSaved={(t) => navigate(mfgPaths.transfer(t.id))} /> : null}
    </div>
  );
}

function NewTransferDialog({ onClose, onSaved }: { onClose(): void; onSaved(t: TransferOrder): void }) {
  const access = useAccess();
  const ws = useLoad((signal) => listWorkspaces(signal), []);
  const here = access.me?.workspace_owner_id;
  const myOrg = (ws.data?.items ?? []).find((w) => w.owner_id === here)?.org?.slug ?? null;
  const targets = (ws.data?.items ?? []).filter((w) => w.owner_id !== here && (!myOrg || w.org?.slug === myOrg));
  const today = new Date().toISOString().slice(0, 10);
  const [dest, setDest] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<{ item: ItemRef | null; qty: string; ship: string; recv: string }[]>([{ item: null, qty: "", ship: today, recv: addDays(today, 2) }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const ok = dest && lines.every((l) => l.item && Number(l.qty) > 0 && l.ship && l.recv && l.recv >= l.ship);
  return (
    <Dialog
      title={tr("mfg.transferPages.title.newTransfer")}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {tr("mfg.transferPages.btn.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !ok}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                const body: TransferInput = { dest_plant_owner_id: dest, note, lines: lines.map((l, i) => ({ line_no: (i + 1) * 10, item_id: l.item!.id, qty: Number(l.qty), ship_date: l.ship, receive_date: l.recv })) };
                onSaved(await createTransfer(body));
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
            data-testid="transfer-save"
          >
            Create
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="tf-dest">{tr("mfg.transferPages.label.toPlant")}</label>
          <select id="tf-dest" className="select" value={dest} onChange={(e) => setDest(e.target.value)} data-testid="transfer-dest">
            <option value="">{targets.length ? "Choose…" : "No other plant of your organisation is open to you"}</option>
            {targets.map((w) => (
              <option key={w.owner_id} value={w.owner_id}>
                {w.plant_code ? `${w.plant_code} · ` : ""}
                {w.plant_name}
              </option>
            ))}
          </select>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>{tr("mfg.transferPages.head.item")}</th>
              <th>{tr("mfg.transferPages.head.qty")}</th>
              <th>{tr("mfg.transferPages.head.ship")}</th>
              <th>{tr("mfg.transferPages.head.arrives")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i} data-testid="transfer-line">
                <td style={{ minWidth: 240 }}>
                  <ItemPicker value={l.item} onChange={(it) => setLines((x) => x.map((y, k) => (k === i ? { ...y, item: it } : y)))} label={tr("mfg.transferPages.label.item")} hideLabel />
                </td>
                <td>
                  <input className="input sm" inputMode="decimal" aria-label={tr("mfg.transferPages.aria.quantity")} value={l.qty} onChange={(e) => setLines((x) => x.map((y, k) => (k === i ? { ...y, qty: e.target.value } : y)))} data-testid="transfer-qty" />
                </td>
                <td>
                  <DateInput small ariaLabel="Ship date" value={l.ship} onChange={(v) => setLines((x) => x.map((y, k) => (k === i ? { ...y, ship: v } : y)))} />
                </td>
                <td>
                  <DateInput small ariaLabel="Arrival date" value={l.recv} onChange={(v) => setLines((x) => x.map((y, k) => (k === i ? { ...y, recv: v } : y)))} />
                </td>
                <td>
                  {lines.length > 1 ? (
                    <button type="button" className="btn sm ghost icon" aria-label={tr("mfg.transferPages.aria.removeLine")} onClick={() => setLines((x) => x.filter((_, k) => k !== i))}>
                      <Icon name="trash" />
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setLines((x) => [...x, { item: null, qty: "", ship: today, recv: addDays(today, 2) }])}>
          <Icon name="plus" /> {tr("mfg.transferPages.btn.line")}
        </button>
        <div className="field">
          <label htmlFor="tf-note">{tr("mfg.transferPages.label.note")}</label>
          <input id="tf-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <span className="faint small">The receiving plant needs the same items (same external reference or part number); publish master data first if not.</span>
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

export function TransferPage() {
  const { transferId = "" } = useParams();
  const canEdit = useCan("transfer_edit");
  const canStock = useCan("inventory");
  const t = useLoad((signal) => getTransfer(transferId, signal), [transferId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [moving, setMoving] = useState<null | "transfer_ship" | "transfer_receipt">(null);
  const d = t.data;
  if (t.loading && !d) return <Spinner />;
  if (!d) return <MfgError error={t.error} onRetry={t.reload} />;
  const out = isOutbound(d);
  const act = async (a: "open" | "close" | "cancel") => {
    setBusy(true);
    setError(null);
    try {
      t.setData(await transferAction(d.id, a, d.row_version));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const toShip = d.lines.some((l) => l.shipped_qty < l.qty);
  const toReceive = d.lines.some((l) => l.received_qty < l.shipped_qty);
  return (
    <div className="col gap-lg" data-testid="transfer-page" data-status={d.status} data-direction={d.direction}>
      <nav className="breadcrumb" aria-label={tr("mfg.transferPages.aria.breadcrumb")}>
        <Link to={`${mfgPaths.transfers()}?dir=${out ? "outbound" : "inbound"}`}>Transfers</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{d.number}</span>
      </nav>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <div className="col" style={{ gap: 4 }}>
          <h1 style={{ margin: 0 }}>
            <span className="mono">{d.number}</span> <TrfStatus s={d.status} />
          </h1>
          <span className="muted">
            {d.source_plant.code}
            {d.source_plant.name ? ` · ${d.source_plant.name}` : ""} <Icon name="arrow-right" size={12} /> {d.dest_plant.code}
            {d.dest_plant.name ? ` · ${d.dest_plant.name}` : ""}
            {out ? " (sent from this plant)" : " (coming to this plant)"}
          </span>
        </div>
        <div className="row wrap">
          {out && d.status === "draft" && canEdit ? (
            <button type="button" className="btn primary" disabled={busy} onClick={() => void act("open")} data-testid="transfer-open">
              {tr("mfg.transferPages.btn.confirmPlanningSeesIt")}
            </button>
          ) : null}
          {out && ["open", "partly_shipped"].includes(d.status) && toShip ? (
            <button type="button" className="btn primary" disabled={!canStock} title={canStock ? undefined : needsText("inventory")} onClick={() => setMoving("transfer_ship")} data-testid="transfer-ship">
              <Icon name="arrow-right" /> {tr("mfg.transferPages.btn.ship")}
            </button>
          ) : null}
          {!out && toReceive ? (
            <button type="button" className="btn primary" disabled={!canStock} title={canStock ? undefined : needsText("inventory")} onClick={() => setMoving("transfer_receipt")} data-testid="transfer-receive">
              <Icon name="download" /> {tr("mfg.transferPages.btn.receive")}
            </button>
          ) : null}
          {out && canEdit && ["draft", "open"].includes(d.status) ? (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act("cancel")}>
              {tr("mfg.transferPages.btn.cancelTransfer")}
            </button>
          ) : null}
          {out && canEdit && ["shipped", "partly_shipped", "received"].includes(d.status) ? (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act("close")}>
              {tr("mfg.transferPages.btn.close")}
            </button>
          ) : null}
        </div>
      </div>
      {!out && d.status === "open" ? <Banner tone="info" title={tr("mfg.transferPages.title.notShippedYet")}>The sending plant has not shipped; planning here already counts it as arriving on the dates below.</Banner> : null}
      <MfgError error={error} />
      <DataTable
        rows={d.lines}
        columns={LINE_COLS}
        rowKey={(l) => l.id}
        label={`Lines of ${d.number}`}
        testId="transfer-lines"
        exportName={`transfer-${d.number}`}
        rowExtras={() => ({ testId: "transfer-line-row" })}
        card={{ title: "item", fields: ["qty", "shipped", "received"] }}
      />
      {d.note ? <p className="muted">{d.note}</p> : null}
      {moving ? (
        <MoveDialog
          t={d}
          type={moving}
          onClose={() => setMoving(null)}
          onDone={() => {
            setMoving(null);
            t.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function MoveDialog({ t, type, onClose, onDone }: { t: TransferOrder; type: "transfer_ship" | "transfer_receipt"; onClose(): void; onDone(): void }) {
  const ship = type === "transfer_ship";
  const locs = useLoad((signal) => listLocations({ active: true }, signal), []);
  const open = t.lines.filter((l) => (ship ? l.shipped_qty < l.qty : l.received_qty < l.shipped_qty));
  const [rows, setRows] = useState(() => open.map((l) => ({ line: l, loc: "", lot: "", qty: String(ship ? l.qty - l.shipped_qty : l.shipped_qty - l.received_qty) })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [key] = useState(() => newIdempotencyKey());
  useEffect(() => {
    const def = (locs.data?.items ?? []).find((l) => (ship ? l.kind === "stores" : l.receipt_default)) ?? (locs.data?.items ?? [])[0];
    if (def) setRows((r) => r.map((x) => (x.loc ? x : { ...x, loc: def.id })));
  }, [locs.data, ship]);
  return (
    <Dialog
      title={`${ship ? "Ship" : "Receive"} ${t.number}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {tr("mfg.transferPages.btn.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !rows.some((r) => Number(r.qty) > 0) || rows.some((r) => Number(r.qty) > 0 && !r.loc)}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await postTransferMovement(
                  type,
                  rows.filter((r) => Number(r.qty) > 0).map((r) => ({ item_id: r.line.item_id, location_id: r.loc, qty: Number(r.qty), lot_code: r.lot.trim() || null, transfer_line_id: r.line.id })),
                  key,
                );
                onDone();
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
            data-testid="transfer-move-submit"
          >
            {ship ? "Post shipment" : "Post receipt"}
          </button>
        </>
      }
    >
      <table className="table">
        <thead>
          <tr>
            <th>{tr("mfg.transferPages.head.item")}</th>
            <th>{ship ? "From" : "Into"}</th>
            <th>{tr("mfg.transferPages.head.lot")}</th>
            <th>{tr("mfg.transferPages.head.qty")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.line.id}>
              <td>
                <ItemCode id={r.line.item_id} />
              </td>
              <td>
                <select className="select sm" aria-label={tr("mfg.transferPages.aria.location")} value={r.loc} onChange={(e) => setRows((x) => x.map((y, k) => (k === i ? { ...y, loc: e.target.value } : y)))}>
                  <option value="">Choose…</option>
                  {(locs.data?.items ?? []).map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.code}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input className="input sm mono" aria-label={tr("mfg.transferPages.aria.lot")} value={r.lot} placeholder={ship ? "FEFO if empty" : "as shipped"} onChange={(e) => setRows((x) => x.map((y, k) => (k === i ? { ...y, lot: e.target.value } : y)))} />
              </td>
              <td>
                <input className="input sm" inputMode="decimal" aria-label={tr("mfg.transferPages.aria.quantity")} value={r.qty} onChange={(e) => setRows((x) => x.map((y, k) => (k === i ? { ...y, qty: e.target.value } : y)))} data-testid="transfer-move-qty" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="faint small">{ship ? "Stock leaves this plant now and is in transit until the other plant receives it." : "Lots and serial numbers keep their identity from the sending plant."}</p>
      <MfgError error={error} />
    </Dialog>
  );
}

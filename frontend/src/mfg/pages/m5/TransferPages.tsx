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
  return (
    <div className="col gap-lg" data-testid="transfers-page">
      <div className="mfg-page-head">
        <div>
          <h1>Transfers between plants</h1>
          <p>Send stock to another plant of your organisation. Lots and serial numbers go with it.</p>
        </div>
        <button type="button" className="btn primary" disabled={!canEdit} title={canEdit ? undefined : needsText("transfer_edit")} onClick={() => setCreating(true)} data-testid="transfer-new">
          <Icon name="plus" /> New transfer
        </button>
      </div>
      <div className="row" role="group" aria-label="Direction">
        <button type="button" className={`btn sm${dir === "outbound" ? " primary" : ""}`} aria-pressed={dir === "outbound"} onClick={() => setSearchParam(setParams, "dir", "outbound")}>
          Outgoing
        </button>
        <button type="button" className={`btn sm${dir === "inbound" ? " primary" : ""}`} aria-pressed={dir === "inbound"} onClick={() => setSearchParam(setParams, "dir", "inbound")} data-testid="transfer-incoming">
          Incoming
        </button>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="transfer-table">
          <thead>
            <tr>
              <th>Transfer</th>
              <th>{dir === "outbound" ? "To" : "From"}</th>
              <th>Status</th>
              <th>Lines</th>
              <th>Ship / receive</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  {data.loading ? "Loading…" : "None."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((t) => (
              <tr key={t.id} data-testid="transfer-row" data-status={t.status}>
                <td>
                  <Link to={mfgPaths.transfer(t.id)} className="mono">
                    {t.number}
                  </Link>
                </td>
                <td>{dir === "outbound" ? `${t.dest_plant.code}${t.dest_plant.name ? ` · ${t.dest_plant.name}` : ""}` : `${t.source_plant.code}${t.source_plant.name ? ` · ${t.source_plant.name}` : ""}`}</td>
                <td>
                  <TrfStatus s={t.status} />
                </td>
                <td className="small">
                  {t.lines.length} line{t.lines.length === 1 ? "" : "s"}, {fmtNum(t.lines.reduce((a, l) => a + l.qty, 0))} units
                </td>
                <td className="small">
                  {t.lines[0] ? `${fmtDate(t.lines[0].ship_date)} → ${fmtDate(t.lines[0].receive_date)}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
      title="New transfer"
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
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
          <label htmlFor="tf-dest">To plant</label>
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
              <th>Item</th>
              <th>Qty</th>
              <th>Ship</th>
              <th>Arrives</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i} data-testid="transfer-line">
                <td style={{ minWidth: 240 }}>
                  <ItemPicker value={l.item} onChange={(it) => setLines((x) => x.map((y, k) => (k === i ? { ...y, item: it } : y)))} label="Item" hideLabel />
                </td>
                <td>
                  <input className="input sm" inputMode="decimal" aria-label="Quantity" value={l.qty} onChange={(e) => setLines((x) => x.map((y, k) => (k === i ? { ...y, qty: e.target.value } : y)))} data-testid="transfer-qty" />
                </td>
                <td>
                  <input className="input sm" type="date" aria-label="Ship date" value={l.ship} onChange={(e) => setLines((x) => x.map((y, k) => (k === i ? { ...y, ship: e.target.value } : y)))} />
                </td>
                <td>
                  <input className="input sm" type="date" aria-label="Arrival date" value={l.recv} onChange={(e) => setLines((x) => x.map((y, k) => (k === i ? { ...y, recv: e.target.value } : y)))} />
                </td>
                <td>
                  {lines.length > 1 ? (
                    <button type="button" className="btn sm ghost icon" aria-label="Remove line" onClick={() => setLines((x) => x.filter((_, k) => k !== i))}>
                      <Icon name="trash" />
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setLines((x) => [...x, { item: null, qty: "", ship: today, recv: addDays(today, 2) }])}>
          <Icon name="plus" /> Line
        </button>
        <div className="field">
          <label htmlFor="tf-note">Note</label>
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
      <nav className="breadcrumb" aria-label="Breadcrumb">
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
              Confirm (planning sees it)
            </button>
          ) : null}
          {out && ["open", "partly_shipped"].includes(d.status) && toShip ? (
            <button type="button" className="btn primary" disabled={!canStock} title={canStock ? undefined : needsText("inventory")} onClick={() => setMoving("transfer_ship")} data-testid="transfer-ship">
              <Icon name="arrow-right" /> Ship
            </button>
          ) : null}
          {!out && toReceive ? (
            <button type="button" className="btn primary" disabled={!canStock} title={canStock ? undefined : needsText("inventory")} onClick={() => setMoving("transfer_receipt")} data-testid="transfer-receive">
              <Icon name="download" /> Receive
            </button>
          ) : null}
          {out && canEdit && ["draft", "open"].includes(d.status) ? (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act("cancel")}>
              Cancel transfer
            </button>
          ) : null}
          {out && canEdit && ["shipped", "partly_shipped", "received"].includes(d.status) ? (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act("close")}>
              Close
            </button>
          ) : null}
        </div>
      </div>
      {!out && d.status === "open" ? <Banner tone="info" title="Not shipped yet">The sending plant has not shipped; planning here already counts it as arriving on the dates below.</Banner> : null}
      <MfgError error={error} />
      <div className="table-wrap card">
        <table className="table" data-testid="transfer-lines">
          <thead>
            <tr>
              <th>Line</th>
              <th>Item</th>
              <th className="right">Qty</th>
              <th className="right">Shipped</th>
              <th className="right">Received</th>
              <th>Ship → arrives</th>
            </tr>
          </thead>
          <tbody>
            {d.lines.map((l) => (
              <tr key={l.id} data-testid="transfer-line-row">
                <td>{l.line_no}</td>
                <td>
                  <ItemCode id={l.item_id} />
                </td>
                <td className="right">{fmtNum(l.qty)}</td>
                <td className="right">{fmtNum(l.shipped_qty)}</td>
                <td className="right">{fmtNum(l.received_qty)}</td>
                <td className="small">
                  {fmtDate(l.ship_date)} → {fmtDate(l.receive_date)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
            Cancel
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
            <th>Item</th>
            <th>{ship ? "From" : "Into"}</th>
            <th>Lot</th>
            <th>Qty</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.line.id}>
              <td>
                <ItemCode id={r.line.item_id} />
              </td>
              <td>
                <select className="select sm" aria-label="Location" value={r.loc} onChange={(e) => setRows((x) => x.map((y, k) => (k === i ? { ...y, loc: e.target.value } : y)))}>
                  <option value="">Choose…</option>
                  {(locs.data?.items ?? []).map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.code}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input className="input sm mono" aria-label="Lot" value={r.lot} placeholder={ship ? "FEFO if empty" : "as shipped"} onChange={(e) => setRows((x) => x.map((y, k) => (k === i ? { ...y, lot: e.target.value } : y)))} />
              </td>
              <td>
                <input className="input sm" inputMode="decimal" aria-label="Quantity" value={r.qty} onChange={(e) => setRows((x) => x.map((y, k) => (k === i ? { ...y, qty: e.target.value } : y)))} data-testid="transfer-move-qty" />
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

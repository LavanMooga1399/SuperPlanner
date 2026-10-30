/** `/mfg/items/:itemId/stock` (M2 14.2, #100): totals, balances, open supply and demand, latest-run shortage. */
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { getItemStock } from "../api/clientM2";
import type { StockFlow } from "../api/typesM2";
import { MfgError, Spinner } from "../components/Feedback";
import { PermissionGate } from "../components/PermissionGate";
import { HoldBadge, LocationKindBadge } from "../components/StatusM2";
import { fmtDate } from "../lib/format";
import { fmtMoney, fmtNum } from "../lib/formatM2";
import { mfgPaths } from "../lib/paths";
import { useLoad, usePlant } from "../lib/useMfg";
import { useItem } from "./ItemShell";

function flowLink(f: StockFlow): string | null {
  const r = f.ref;
  if (r.doc_id) return mfgPaths.purchaseDoc(f.type.startsWith("pr") ? "pr" : "po", r.doc_id, f.type.endsWith("schedule") ? { schedule: r.id } : undefined);
  if (r.wo_id) return mfgPaths.workOrder(r.wo_id, f.type === "wo_component" ? r.id : undefined);
  if (f.type === "wo") return mfgPaths.workOrder(r.id);
  if (r.order_id) return mfgPaths.demandOrder(r.order_id, r.id);
  return null;
}

function FlowTable({ title, rows, testId, uom }: { title: string; rows: StockFlow[]; testId: string; uom: string }) {
  return (
    <section className="card" data-testid={testId}>
      <div className="card-header">
        <h3>{title}</h3>
        <span className="muted small">{rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <div className="card-body muted small">None.</div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Document</th>
                <th className="right">Quantity</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f, i) => {
                const href = flowLink(f);
                return (
                  <tr key={i}>
                    <td>{fmtDate(f.date)}</td>
                    <td>{href ? <Link to={href}>{f.ref.label}</Link> : f.ref.label}</td>
                    <td className="right">
                      {fmtNum(f.qty)} {uom}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function ItemStockTab() {
  const { item } = useItem();
  const plant = usePlant();
  const stock = useLoad((signal) => getItemStock(item.id, signal), [item.id]);
  const s = stock.data;
  if (stock.error && !s) return <MfgError error={stock.error} onRetry={stock.reload} />;
  if (!s) return <Spinner label="Loading stock…" />;
  const t = s.totals;
  const tiles: [string, string, string][] = [
    ["Available", fmtNum(t.available), "Plannable on hand minus reserved"],
    ["Plannable on hand", fmtNum(t.nettable), "Stores and line side"],
    ["Reserved", fmtNum(t.reserved), "Held for work orders"],
    ["In inspection", fmtNum(t.inspection), "Goods-in, not yet in stores"],
    ["Quarantine", fmtNum(t.quarantine), "Never planned"],
    ["Value", fmtMoney(t.value, plant.data?.currency), "On hand x standard cost"],
  ];
  return (
    <div className="col gap-lg" data-testid="item-stock">
      <div className="row between wrap">
        <div className="kpis" style={{ flex: 1 }}>
          {tiles.map(([label, value, hint]) => (
            <div className="card kpi" key={label} title={hint}>
              <div className="kpi-label">{label}</div>
              <div className="kpi-value">
                {value} {label !== "Value" ? <span className="small muted">{item.uom}</span> : null}
              </div>
            </div>
          ))}
        </div>
      </div>
      {s.latest_run ? (
        s.latest_run.short_qty > 0 ? (
          <div className="banner warn" data-testid="item-stock-shortage">
            <Icon name="alert" />
            <div className="banner-body">
              <strong>
                Short {fmtNum(s.latest_run.short_qty)} {item.uom}
                {s.latest_run.first_short_date ? ` from ${fmtDate(s.latest_run.first_short_date)}` : ""}
              </strong>
              <div>In MRP run #{s.latest_run.run_no}, before planned orders.</div>
            </div>
            <div className="banner-actions">
              <Link className="btn sm" to={mfgPaths.runItem(s.latest_run.run_id, item.id)}>
                Open the item plan <Icon name="arrow-right" />
              </Link>
            </div>
          </div>
        ) : (
          <p className="muted small" style={{ margin: 0 }}>
            <Icon name="check" size={12} /> Not short in MRP run #{s.latest_run.run_no}.{" "}
            <Link to={mfgPaths.runItem(s.latest_run.run_id, item.id)}>Item plan</Link>
          </p>
        )
      ) : null}
      <section className="card">
        <div className="card-header">
          <h3>Stock by location</h3>
          <div className="mfg-actions">
            <Link className="btn sm" to={mfgPaths.transactions({ item: item.id })}>
              <Icon name="list" /> Ledger
            </Link>
            <PermissionGate perm="inventory">
              <Link className="btn sm primary" to={mfgPaths.post({ item: item.id })} data-testid="item-stock-post">
                <Icon name="plus" /> Post
              </Link>
            </PermissionGate>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Location</th>
                <th>Kind</th>
                <th>Lot</th>
                <th>Expires</th>
                <th className="right">On hand</th>
                <th className="right">Reserved</th>
                <th className="right">Available</th>
              </tr>
            </thead>
            <tbody>
              {s.balances.length === 0 ? (
                <tr>
                  <td colSpan={7} className="muted">
                    No stock.
                  </td>
                </tr>
              ) : null}
              {s.balances.map((b) => (
                <tr key={b.id} data-testid="balance-row" data-item={b.item.part_number} data-location={b.location.code} data-qty={b.qty_on_hand}>
                  <td className="mono">{b.location.code}</td>
                  <td>
                    <LocationKindBadge kind={b.location.kind} />
                  </td>
                  <td className="mono">
                    {b.lot?.lot_code ?? ""} {b.lot?.hold ? <HoldBadge /> : null}
                  </td>
                  <td>{fmtDate(b.lot?.expires_on)}</td>
                  <td className="right">{fmtNum(b.qty_on_hand)}</td>
                  <td className="right">{fmtNum(b.qty_reserved)}</td>
                  <td className="right">
                    <strong>{fmtNum(b.qty_available)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <div className="grid-2">
        <FlowTable title="Open supply" rows={s.open_supply} testId="item-open-supply" uom={item.uom} />
        <FlowTable title="Open demand" rows={s.open_demand} testId="item-open-demand" uom={item.uom} />
      </div>
    </div>
  );
}

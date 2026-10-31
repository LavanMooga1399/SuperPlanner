/**
 * Printable pages (M4 5, 15 Q3): travellers, lot / serial labels, operator badges and line cards, with Code 128
 * drawn in the browser (no printer drivers, no packages). The app chrome hides in print (`@media print`); labels
 * use a 3-column grid that fits common A4 label sheets.
 * - `/mfg/print/traveller/:woId`: WO header barcode + one barcode per operation (`WO-000143/30`) + components.
 * - `/mfg/print/labels?type=lot|serial|badge|line&ids=a,b` (badges/lines without ids: all active).
 */
import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listLines, listOperators } from "../../api/client";
import { getWorkOrder, listLots } from "../../api/clientM2";
import { getSerial, listWoOperationsM4 } from "../../api/clientM4";
import { Barcode } from "../../components/Barcode";
import { MfgError, Spinner } from "../../components/Feedback";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { useLoad } from "../../lib/useMfg";

function PrintBar({ title, back }: { title: string; back?: string }) {
  useEffect(() => {
    document.title = `${title} - SuperPlanner`;
  }, [title]);
  return (
    <div className="row wrap no-print" style={{ justifyContent: "space-between" }}>
      <h1 style={{ margin: 0 }}>{title}</h1>
      <span className="row">
        {back ? (
          <Link className="btn" to={back}>
            Back
          </Link>
        ) : null}
        <button type="button" className="btn primary" onClick={() => window.print()} data-testid="print-now">
          <Icon name="file" /> Print
        </button>
      </span>
    </div>
  );
}

export function TravellerPage() {
  const { woId = "" } = useParams();
  const wo = useLoad((signal) => getWorkOrder(woId, signal), [woId]);
  const ops = useLoad((signal) => listWoOperationsM4(woId, signal).catch(() => null), [woId]);
  const w = wo.data;
  if (wo.loading && !w) return <Spinner />;
  if (!w) return <MfgError error={wo.error} onRetry={wo.reload} />;
  const opRows = ops.data?.items ?? [];
  return (
    <div className="col gap-lg print-page" data-testid="traveller">
      <PrintBar title={`Traveller ${w.number}`} back={mfgPaths.workOrder(w.id)} />
      {(!opRows.length || opRows.every((o) => !o.id)) && !ops.loading ? (
        <div className="banner warn no-print">
          <Icon name="alert" /> This work order has no floor operations yet. Release it to the floor first; the traveller then lists every operation.
        </div>
      ) : null}
      <section className="traveller">
        <div className="traveller-head">
          <div className="col" style={{ gap: 4 }}>
            <span className="faint small">WORK ORDER TRAVELLER</span>
            <span style={{ fontSize: 26, fontWeight: 700 }} className="mono">
              {w.number}
            </span>
            <span>
              <span className="mono">{w.item.part_number}</span> {w.item.description ?? ""}
            </span>
            <span>
              Qty <strong>{fmtNum(w.qty)}</strong> · start {fmtDate(w.start_date)} · due {fmtDate(w.due_date)} · priority P{w.priority}
            </span>
            {w.demand_line ? (
              <span>
                For {w.demand_line.order_number}/{w.demand_line.line_no}
              </span>
            ) : null}
            {w.serial_from !== null && w.serial_to !== null ? (
              <span>
                Serials {w.serial_from} - {w.serial_to}
              </span>
            ) : null}
          </div>
          <Barcode value={w.number} height={56} module={1.8} testId="traveller-wo-barcode" />
        </div>
        <table className="traveller-table">
          <thead>
            <tr>
              <th>Op</th>
              <th>Operation</th>
              <th>Scan to open</th>
              <th>Good</th>
              <th>Scrap</th>
              <th>Operator / date</th>
            </tr>
          </thead>
          <tbody>
            {opRows.map((o) => (
              <tr key={o.id || `seq-${o.seq}`} data-testid="traveller-op">
                <td className="mono">{o.seq}</td>
                <td>
                  {o.name}
                  {o.group?.code ? <div className="faint small">{o.group.code}</div> : null}
                  {o.capture_serial ? <div className="small">Serial numbers captured here</div> : null}
                </td>
                <td>
                  <Barcode value={`${w.number}/${o.seq}`} height={36} module={1.3} />
                </td>
                <td className="traveller-blank" />
                <td className="traveller-blank" />
                <td className="traveller-blank" />
              </tr>
            ))}
          </tbody>
        </table>
        {w.components.length ? (
          <>
            <h2 style={{ fontSize: 16, margin: "12px 0 4px" }}>Components</h2>
            <table className="traveller-table">
              <thead>
                <tr>
                  <th>Part</th>
                  <th>Description</th>
                  <th>Qty</th>
                  <th>At op</th>
                </tr>
              </thead>
              <tbody>
                {w.components.map((c) => (
                  <tr key={c.id}>
                    <td className="mono">{c.item.part_number}</td>
                    <td className="small">{c.item.description ?? ""}</td>
                    <td>{fmtNum(c.required_qty)}</td>
                    <td>{c.operation_seq ?? "first"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </section>
    </div>
  );
}

interface Label {
  key: string;
  code: string;
  title: string;
  sub?: string;
}

export function LabelsPage() {
  const [params] = useSearchParams();
  const type = (params.get("type") ?? "badge") as "lot" | "serial" | "badge" | "line";
  const ids = (params.get("ids") ?? "").split(",").filter(Boolean);
  const copies = Math.min(20, Math.max(1, Number(params.get("copies") ?? 1) || 1));
  const data = useLoad(
    async (signal): Promise<Label[]> => {
      if (type === "badge") {
        const ops = await listOperators({ active: true }, signal);
        return ops.items.filter((o) => !ids.length || ids.includes(o.id)).map((o) => ({ key: o.id, code: `OP:${o.code}`, title: o.name, sub: o.code }));
      }
      if (type === "line") {
        const ls = await listLines({ active: true }, signal);
        return ls.items.filter((l) => !ids.length || ids.includes(l.id)).map((l) => ({ key: l.id, code: `LIN:${l.code}`, title: l.code, sub: l.name }));
      }
      if (type === "serial") {
        const us = await Promise.all(ids.map((id) => getSerial(id, signal)));
        return us.map((u) => ({ key: u.id, code: `S:${u.item?.part_number ?? ""}:${u.serial}`, title: u.serial, sub: u.item?.part_number }));
      }
      const item = params.get("item") ?? undefined;
      const lots = await listLots({ item_id: item, limit: 500, offset: 0 }, signal);
      return lots.items.filter((l) => !ids.length || ids.includes(l.id)).map((l) => ({ key: l.id, code: `L:${l.item.part_number}:${l.lot_code}`, title: l.lot_code, sub: `${l.item.part_number}${l.expires_on ? ` · exp ${fmtDate(l.expires_on)}` : ""}` }));
    },
    [type, ids.join(","), params.get("item")],
  );
  const title = type === "badge" ? "Operator badges" : type === "line" ? "Line cards" : type === "serial" ? "Serial labels" : "Lot labels";
  const labels = (data.data ?? []).flatMap((l) => Array.from({ length: copies }, (_, i) => ({ ...l, key: `${l.key}-${i}` })));
  return (
    <div className="col gap-lg print-page" data-testid="labels" data-type={type}>
      <PrintBar title={title} />
      {type === "badge" ? (
        <p className="muted no-print" style={{ margin: 0 }}>
          Operators scan their badge on a shared station tablet to sign their work. Personal logins linked to an operator do not need one.
        </p>
      ) : null}
      <MfgError error={data.error} onRetry={data.reload} />
      {data.loading && !data.data ? <Spinner /> : null}
      {data.data && !labels.length ? <p className="muted">Nothing to print.</p> : null}
      <div className="label-sheet">
        {labels.map((l) => (
          <div key={l.key} className={`label${type === "badge" ? " label-badge" : ""}`} data-testid="label">
            <strong className="label-title">{l.title}</strong>
            {l.sub ? <span className="label-sub">{l.sub}</span> : null}
            <Barcode value={l.code} height={type === "badge" ? 44 : 36} module={1.2} />
          </div>
        ))}
      </div>
    </div>
  );
}

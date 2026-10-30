/**
 * Work-order components with live kitting columns (M2 14.2 `KittingTable`, 7.4): required, issued, open,
 * reserved for this WO, free stock, shortage and next supply. Virtualized (up to 4,000 components per WO).
 */
import { useMemo } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import type { KittingComponent, WoComponentRecord } from "../api/typesM2";
import { fmtDate } from "../lib/format";
import { fmtNum } from "../lib/formatM2";
import { mfgPaths } from "../lib/paths";
import { VirtualTable, type Column } from "./VirtualTable";

export interface KitRow {
  c: WoComponentRecord;
  k: KittingComponent | null;
}

export function KittingTable({ components, kitting, highlight, showKitting }: { components: WoComponentRecord[]; kitting: KittingComponent[] | null; highlight?: string | null; showKitting: boolean }) {
  const rows: KitRow[] = useMemo(() => {
    const m = new Map((kitting ?? []).map((k) => [k.component_id, k]));
    return components.map((c) => ({ c, k: m.get(c.id) ?? null }));
  }, [components, kitting]);
  const hi = highlight ? rows.findIndex((r) => r.c.id === highlight) : -1;
  const scrollTo = useMemo(() => (hi >= 0 ? { index: hi, seq: 1 } : null), [hi]);

  const columns: Column<KitRow>[] = [
    { key: "fn", header: "Pos.", width: "64px", render: (r) => <span className="mono">{r.c.find_number ?? ""}</span> },
    {
      key: "pn",
      header: "Part number",
      width: "minmax(150px, 1.2fr)",
      render: (r) => (
        <Link to={mfgPaths.itemStock(r.c.item.id)} className="mono mfg-ellipsis" tabIndex={-1}>
          {r.c.item.part_number}
        </Link>
      ),
    },
    { key: "desc", header: "Description", width: "minmax(140px, 1.4fr)", render: (r) => <span className="mfg-ellipsis">{r.c.item.description}</span> },
    { key: "op", header: "Op.", width: "54px", align: "right", render: (r) => r.c.operation_seq ?? "" },
    { key: "req", header: "Required", width: "84px", align: "right", render: (r) => fmtNum(r.c.required_qty) },
    { key: "iss", header: "Issued", width: "74px", align: "right", render: (r) => fmtNum(r.c.issued_qty) },
    { key: "open", header: "Open", width: "70px", align: "right", render: (r) => fmtNum(r.c.open_qty) },
    { key: "res", header: "Reserved", width: "80px", align: "right", render: (r) => (r.c.reserved_qty ? fmtNum(r.c.reserved_qty) : <span className="faint">0</span>) },
    ...(showKitting
      ? ([
          { key: "free", header: "Free stock", width: "84px", align: "right", render: (r) => (r.k ? fmtNum(r.k.free) : "") },
          {
            key: "short",
            header: "Kit",
            width: "110px",
            render: (r) =>
              !r.k ? (
                ""
              ) : r.k.shortage > 0 ? (
                <span className="badge danger" title={`${fmtNum(r.k.shortage)} missing after reservations and free stock`}>
                  <Icon name="alert" /> Short {fmtNum(r.k.shortage)}
                </span>
              ) : r.c.open_qty > 0 ? (
                <span className="badge ok">
                  <Icon name="check" /> Covered
                </span>
              ) : (
                <span className="faint">Issued</span>
              ),
          },
          {
            key: "next",
            header: "Next supply",
            width: "minmax(150px, 1fr)",
            render: (r) =>
              r.k?.next_supply ? (
                <Link to={r.k.next_supply.link} className="mfg-ellipsis small" tabIndex={-1}>
                  {fmtNum(r.k.next_supply.qty)} on {fmtDate(r.k.next_supply.date)} · {r.k.next_supply.label}
                </Link>
              ) : r.k && r.k.shortage > 0 ? (
                <span className="faint small">No open supply</span>
              ) : (
                ""
              ),
          },
          {
            key: "where",
            header: "Where",
            width: "minmax(120px, 1fr)",
            render: (r) => <span className="mfg-ellipsis small faint">{(r.k?.locations ?? []).map((l) => `${l.location_code}${l.lot_code ? `/${l.lot_code}` : ""} ${fmtNum(l.available)}`).join(", ")}</span>,
          },
        ] as Column<KitRow>[])
      : []),
  ];

  return (
    <VirtualTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.c.id}
      label="Components and kitting"
      testId="kitting-table"
      height="min(56vh, 600px)"
      scrollTo={scrollTo}
      rowExtras={(r) => ({ testId: "kitting-row", data: { item: r.c.item.part_number, shortage: r.k ? r.k.shortage : undefined, component: r.c.id }, className: r.c.id === highlight ? "mfg-selected" : undefined })}
      empty="No components. Without an effective BOM nothing is generated; use Refresh from BOM after releasing one."
    />
  );
}

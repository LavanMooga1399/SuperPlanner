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
import { t } from "../../lib/i18n";

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
    { key: "fn", header: t("mfg.kittingTable.str.pos"), width: "64px", render: (r) => <span className="mono">{r.c.find_number ?? ""}</span> },
    {
      key: "pn",
      header: t("mfg.kittingTable.str.partNumber"),
      width: "minmax(150px, 1.2fr)",
      render: (r) => (
        <Link to={mfgPaths.itemStock(r.c.item.id)} className="mono mfg-ellipsis" tabIndex={-1}>
          {r.c.item.part_number}
        </Link>
      ),
    },
    { key: "desc", header: t("mfg.kittingTable.str.description"), width: "minmax(140px, 1.4fr)", render: (r) => <span className="mfg-ellipsis">{r.c.item.description}</span> },
    { key: "op", header: t("mfg.kittingTable.str.op"), width: "54px", align: "right", render: (r) => r.c.operation_seq ?? "" },
    { key: "req", header: t("mfg.kittingTable.str.required"), width: "96px", align: "right", render: (r) => fmtNum(r.c.required_qty) },
    { key: "iss", header: t("mfg.kittingTable.str.issued"), width: "96px", align: "right", render: (r) => fmtNum(r.c.issued_qty) },
    { key: "open", header: t("mfg.kittingTable.str.open"), width: "90px", align: "right", render: (r) => fmtNum(r.c.open_qty) },
    { key: "res", header: t("mfg.kittingTable.str.reserved"), width: "80px", align: "right", render: (r) => (r.c.reserved_qty ? fmtNum(r.c.reserved_qty) : <span className="faint">0</span>) },
    ...(showKitting
      ? ([
          { key: "free", header: t("mfg.kittingTable.str.freeStock"), width: "96px", align: "right", render: (r) => (r.k ? fmtNum(r.k.free) : "") },
          {
            key: "short",
            header: t("mfg.kittingTable.str.kit"),
            width: "110px",
            render: (r) =>
              !r.k ? (
                ""
              ) : r.k.shortage > 0 ? (
                <span className="badge danger" title={t("mfg.kittingTable.tpl.missingAfterReservationsAndFree", { shortage: fmtNum(r.k.shortage) })}>
                  <Icon name="alert" />{" "}{t("mfg.kittingTable.text.short", { shortage: fmtNum(r.k.shortage) })}
                </span>
              ) : r.c.open_qty > 0 ? (
                <span className="badge ok">
                  <Icon name="check" /> {t("mfg.kittingTable.btn.covered")}
                </span>
              ) : (
                <span className="faint">{t("mfg.kittingTable.text.issued")}</span>
              ),
          },
          {
            key: "next",
            header: t("mfg.kittingTable.str.nextSupply"),
            width: "minmax(150px, 1fr)",
            render: (r) =>
              r.k?.next_supply ? (
                <Link to={r.k.next_supply.link} className="mfg-ellipsis small" tabIndex={-1}>
                  {t("mfg.kittingTable.text.on", { qty: fmtNum(r.k.next_supply.qty), date: fmtDate(r.k.next_supply.date), label: r.k.next_supply.label })}
                </Link>
              ) : r.k && r.k.shortage > 0 ? (
                <span className="faint small">{t("mfg.kittingTable.text.noOpenSupply")}</span>
              ) : (
                ""
              ),
          },
          {
            key: "where",
            header: t("mfg.kittingTable.str.where"),
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
      label={t("mfg.kittingTable.label.componentsAndKitting")}
      testId="kitting-table"
      height="min(56vh, 600px)"
      scrollTo={scrollTo}
      rowExtras={(r) => ({ testId: "kitting-row", data: { item: r.c.item.part_number, shortage: r.k ? r.k.shortage : undefined, component: r.c.id }, className: r.c.id === highlight ? "mfg-selected" : undefined })}
      empty={t("mfg.kittingTable.empty.noComponentsWithoutAnEffective")}
    />
  );
}

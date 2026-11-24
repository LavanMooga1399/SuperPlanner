/** `/mfg/demand` (M2 14.2, #126): demand orders with open quantity, next due date and late lines (latest run). */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { FilterBar, type FilterChip } from "../../../components/FilterBar";
import { PageHeader } from "../../../components/PageHeader";
import { listDemandOrders } from "../../api/clientM2";
import { DEMAND_TYPES, type DemandOrderSummary, type DemandStatus, type DemandType } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { ImportShortcut } from "../../components/ImportShortcut";
import { PermissionGate } from "../../components/PermissionGate";
import { DemandStatusChip } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { DEMAND_TYPE_LABEL, fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";
import { BulkActions, bulkRows, useSelection, type BulkActionDef } from "../../components/BulkActions";
import { useCan } from "../../lib/permissions";
import { t, t as tr } from "../../../lib/i18n";
import { LOCALE } from "../../../lib/locale";

export function DemandList() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [program, setProgram] = useState(params.get("program") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const dProgram = useDebounced(program.trim(), 250);
  const status = (params.get("status") ?? "") as DemandStatus | "";
  const type = (params.get("type") ?? "") as DemandType | "";
  const lateOnly = params.get("late") === "1";
  const sort = params.get("sort") ?? "number";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => set("program", dProgram), [dProgram]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = usePaged<DemandOrderSummary>(
    (offset, limit, signal) =>
      listDemandOrders({ q: dq || undefined, status: status || undefined, demand_type: type || undefined, program: dProgram || undefined, late_only: lateOnly || undefined, sort: sort === "number" ? undefined : sort, limit, offset }, signal),
    [dq, status, type, dProgram, lateOnly, sort],
  );

  const columns: Column<DemandOrderSummary>[] = useMemo(
    () => [
      {
        key: "no",
        header: tr("mfg.demandList.str.order"),
        width: "130px",
        sortKey: "number",
        sortKeyDesc: "-number",
        exportValue: (o) => o.number,
        render: (o) => (
          <Link to={mfgPaths.demandOrder(o.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {o.number}
          </Link>
        ),
      },
      { key: "st", header: tr("mfg.demandList.str.status"), width: "158px", sortKey: "status", render: (o) => <DemandStatusChip status={o.status} /> },
      { key: "type", header: tr("mfg.demandList.str.type"), width: "140px", drop: 2, render: (o) => DEMAND_TYPE_LABEL[o.demand_type] ?? o.demand_type },
      { key: "cust", header: tr("mfg.demandList.str.customer"), width: "minmax(150px, 1.4fr)", sortKey: "customer", render: (o) => <span className="mfg-ellipsis">{o.customer}</span> },
      { key: "prog", header: tr("mfg.demandList.str.programme"), width: "110px", drop: 1, render: (o) => <span className="mono">{o.program ?? ""}</span> },
      { key: "prio", header: tr("mfg.demandList.str.priority"), width: "80px", drop: 4, sortKey: "priority", align: "right", render: (o) => `P${o.priority}` },
      { key: "lines", header: tr("mfg.demandList.str.lines"), width: "60px", drop: 3, align: "right", render: (o) => o.line_count },
      { key: "open", header: tr("mfg.demandList.str.openQty"), width: "90px", align: "right", render: (o) => fmtNum(o.open_qty) },
      { key: "due", header: tr("mfg.demandList.str.nextDue"), width: "106px", sortKey: "due_date", sortKeyDesc: "-due_date", render: (o) => fmtDate(o.next_due) },
      {
        key: "late",
        header: tr("mfg.demandList.str.lateLines"),
        width: "100px",
        render: (o) =>
          o.late_lines > 0 ? (
            <span className="badge danger">
              <Icon name="alert" /> {o.late_lines} late
            </span>
          ) : o.status === "open" ? (
            <span className="faint">
              <Icon name="check" size={12} /> {t("mfg.demandList.btn.none")}
            </span>
          ) : null,
      },
    ],
    [],
  );

  const canEdit = useCan("demand_edit");
  const [selected, setSelected] = useSelection(params.toString());
  const orders = (n: number) => (n === 1 ? tr("mfg.demandList.str.thisDemandOrder") : tr("mfg.demandList.tpl.theseDemandOrders", { n: n }));
  const bulkDefs: BulkActionDef[] = [
    { action: "demand-orders/close", label: tr("mfg.demandList.str.close"), icon: "check", testId: "bulk-demand-close", eligible: ["open"], what: (n) => tr("mfg.demandList.tpl.close", { n: orders(n) }), effect: tr("mfg.demandList.str.closedOrdersAreNoLonger") },
    { action: "demand-orders/cancel", label: tr("mfg.demandList.str.cancel"), icon: "ban", danger: true, testId: "bulk-demand-cancel", eligible: ["draft", "open"], what: (n) => tr("mfg.demandList.tpl.cancel", { n: orders(n) }), effect: tr("mfg.demandList.str.cancelledOrdersLeavePlanningThis") },
  ];
  const chips: FilterChip[] = [];
  if (q.trim()) chips.push({ key: "q", label: tr("mfg.demandList.str.search"), value: q.trim(), onClear: () => setQ("") });
  if (status) chips.push({ key: "st", label: tr("mfg.demandList.str.status"), value: status, onClear: () => set("status", "") });
  if (type) chips.push({ key: "type", label: tr("mfg.demandList.str.type"), value: DEMAND_TYPE_LABEL[type] ?? type, onClear: () => set("type", "") });
  if (program.trim()) chips.push({ key: "prog", label: tr("mfg.demandList.str.programme"), value: program.trim(), onClear: () => setProgram("") });
  if (lateOnly) chips.push({ key: "late", label: tr("mfg.demandList.str.lines"), value: "Late only", onClear: () => set("late", "") });

  return (
    <div className="col gap-lg">
      <PageHeader
        title={t("mfg.demandList.title.demand")}
        description={t("mfg.demandList.desc.customerOrdersSparesInternalAnd")}
        actions={
          <>
            <ImportShortcut what="demand" />
            <PermissionGate perm="demand_edit">
              <Link className="btn primary" to={mfgPaths.demandNew()} data-testid="demand-new">
                <Icon name="plus" /> {t("mfg.demandList.btn.newDemandOrder")}
              </Link>
            </PermissionGate>
          </>
        }
      />
      <FilterBar
        search={{ id: "dm-q", value: q, onChange: setQ, placeholder: "Order number or customer", testId: "demand-search" }}
        chips={chips}
        onClearAll={() => {
          setQ("");
          setProgram("");
          setParams({}, { replace: true });
        }}
        pageKey="demand"
      >
        <div className="field">
          <label htmlFor="dm-status">{t("mfg.demandList.label.status")}</label>
          <select id="dm-status" className="select" value={status} onChange={(e) => set("status", e.target.value)} data-testid="demand-status">
            <option value="">{tr("mfg.demandList.text.all")}</option>
            <option value="draft">{tr("mfg.demandList.text.draft")}</option>
            <option value="open">{tr("mfg.demandList.text.open")}</option>
            <option value="closed">{tr("mfg.demandList.text.closed")}</option>
            <option value="cancelled">{tr("mfg.demandList.text.cancelled")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="dm-type">{t("mfg.demandList.label.type")}</label>
          <select id="dm-type" className="select" value={type} onChange={(e) => set("type", e.target.value)}>
            <option value="">{tr("mfg.demandList.text.allTypes")}</option>
            {DEMAND_TYPES.map((t) => (
              <option key={t} value={t}>
                {DEMAND_TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ width: 140 }}>
          <label htmlFor="dm-prog">{t("mfg.demandList.label.programme")}</label>
          <input id="dm-prog" className="input" value={program} onChange={(e) => setProgram(e.target.value)} />
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", height: "var(--control-h)" }}>
          <input type="checkbox" checked={lateOnly} onChange={(e) => set("late", e.target.checked ? "1" : "")} data-testid="demand-late-only" />{" "}{tr("mfg.demandList.text.onlyLateLatestMrpRun")}
        </label>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      {canEdit ? <BulkActions rows={bulkRows(data.rows, selected)} noun={[tr("mfg.demandList.str.demandOrder"), tr("mfg.demandList.str.demandOrders")]} actions={bulkDefs} onDone={() => (setSelected(new Set()), data.reload())} onClear={() => setSelected(new Set())} /> : null}
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(o) => o.id}
        label={t("mfg.demandList.label.demandOrders")}
        testId="demand-table"
        card={{ title: "no", status: "st", fields: ["cust", "open", "due"] }}
        selection={canEdit ? { selected, onChange: setSelected, rowId: (o) => o.id, rowLabel: (o) => o.number } : undefined}
        totalCount={data.total}
        rowExtras={(o) => ({ testId: "demand-order-row", data: { number: o.number, status: o.status, late: o.late_lines } })}
        onRowClick={(o) => navigate(mfgPaths.demandOrder(o.id))}
        onActivate={(o) => navigate(mfgPaths.demandOrder(o.id))}
        onEndReached={data.onEndReached}
        loading={data.loading}
        sort={{ key: sort, dir: sort.startsWith("-") ? "desc" : "asc" }}
        onSortChange={(x) => set("sort", !x || x.key === "number" ? "" : x.key)}
        exportName="demand-orders"
        empty={data.loading ? tr("mfg.demandList.str.loading") : tr("mfg.demandList.str.noDemandOrdersMatchThese")}
        footer={<span>{tr("mfg.demandList.text.showingOrders", { tr: tr("common.nOfM", { n: data.rows.length.toLocaleString(LOCALE), m: data.total.toLocaleString(LOCALE) }) })}</span>}
      />
    </div>
  );
}

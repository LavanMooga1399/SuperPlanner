/** `/mfg/work-orders` (M2 14.2, #134): work orders by start date, status filter, link to the kitting check. */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { FilterBar, type FilterChip } from "../../../components/FilterBar";
import { PageHeader } from "../../../components/PageHeader";
import { listWorkOrders } from "../../api/clientM2";
import type { WoSort, WorkOrderSummary } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { ImportShortcut } from "../../components/ImportShortcut";
import { PermissionGate } from "../../components/PermissionGate";
import { SourceBadge, WoStatusChip } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtNum, serialText } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";
import { BulkActions, ReasonField, bulkRows, useSelection, type BulkActionDef } from "../../components/BulkActions";
import { useCan } from "../../lib/permissions";
import { t } from "../../../lib/i18n";

const STATUS_SETS: Record<string, string | undefined> = {
  active: "planned,released,in_progress",
  planned: "planned",
  released: "released,in_progress",
  done: "completed,closed",
  cancelled: "cancelled",
  all: undefined,
};

export function WorkOrderList() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const st = params.get("status") ?? "active";
  const sort = (params.get("sort") ?? "start_date") as WoSort;
  const source = params.get("source") ?? "";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = usePaged<WorkOrderSummary>(
    (offset, limit, signal) => listWorkOrders({ q: dq || undefined, status: STATUS_SETS[st], sort, source: (source || undefined) as WorkOrderSummary["source"] | undefined, limit, offset }, signal),
    [dq, st, sort, source],
  );

  const canEdit = useCan("wo_edit");
  const [selected, setSelected] = useSelection(params.toString());
  const bulkDefs: BulkActionDef[] = [
    {
      action: "work-orders/release",
      label: t("mfg.workOrderList.str.release"),
      icon: "play",
      testId: "bulk-wo-release",
      eligible: ["planned"],
      what: (n) => t("mfg.workOrderList.tpl.releaseToTheShopFloor", { v: n === 1 ? t("mfg.workOrderList.str.thisWorkOrder") : t("mfg.workOrderList.tpl.theseWorkOrders", { n: n }) }),
      effect: t("mfg.workOrderList.str.eachOneIsReleasedExactly"),
      form: (f, set) => (
        <>
          <label className="checkbox">
            <input type="checkbox" checked={f.reserve === "1"} onChange={(e) => set("reserve", e.target.checked ? "1" : "")} />{" "}{t("mfg.workOrderList.text.reserveAvailableStockForThe")}
          </label>
          <ReasonField id="bulk-override" label={t("mfg.workOrderList.label.reasonToReleaseWorkOrders")} value={f.override ?? ""} onChange={(v) => set("override", v)} testId="bulk-override" />
        </>
      ),
      params: (f) => ({ reserve: f.reserve === "1", ...(f.override?.trim() ? { override_reason: f.override.trim() } : {}) }),
    },
    { action: "work-orders/close", label: t("mfg.workOrderList.str.close"), icon: "check", testId: "bulk-wo-close", eligible: ["completed"], what: (n) => t("mfg.workOrderList.tpl.close", { v: n === 1 ? t("mfg.workOrderList.str.thisWorkOrder") : t("mfg.workOrderList.tpl.theseWorkOrders", { n: n }) }), effect: t("mfg.workOrderList.str.closedWorkOrdersTakeNo") },
    {
      action: "work-orders/cancel",
      label: t("mfg.workOrderList.str.cancel"),
      icon: "ban",
      danger: true,
      testId: "bulk-wo-cancel",
      eligible: ["planned", "released"],
      what: (n) => t("mfg.workOrderList.tpl.cancel", { v: n === 1 ? t("mfg.workOrderList.str.thisWorkOrder") : t("mfg.workOrderList.tpl.theseWorkOrders", { n: n }) }),
      effect: t("mfg.workOrderList.str.theirReservationsAreReleasedAnd"),
    },
  ];

  const columns: Column<WorkOrderSummary>[] = useMemo(
    () => [
      {
        key: "no",
        header: t("mfg.workOrderList.str.workOrder"),
        width: "116px",
        sortKey: "number",
        exportValue: (w) => w.number,
        render: (w) => (
          <Link to={mfgPaths.workOrder(w.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {w.number}
          </Link>
        ),
      },
      { key: "st", header: t("mfg.workOrderList.str.status"), width: "128px", render: (w) => <WoStatusChip status={w.status} /> },
      { key: "pn", header: t("mfg.workOrderList.str.item"), width: "minmax(110px, 1fr)", render: (w) => <span className="mono mfg-ellipsis">{w.item.part_number}</span> },
      { key: "desc", header: t("mfg.workOrderList.str.description"), width: "minmax(100px, 1.4fr)", render: (w) => <span className="mfg-ellipsis">{w.item.description}</span> },
      { key: "qty", header: t("mfg.workOrderList.str.qty"), width: "60px", align: "right", render: (w) => fmtNum(w.qty) },
      { key: "done", header: t("mfg.workOrderList.str.done"), width: "60px", drop: 3, align: "right", render: (w) => fmtNum(w.qty_completed) },
      { key: "start", header: t("mfg.workOrderList.str.start"), width: "96px", sortKey: "start_date", render: (w) => fmtDate(w.start_date) },
      { key: "due", header: t("mfg.workOrderList.str.due"), width: "96px", sortKey: "due_date", render: (w) => fmtDate(w.due_date) },
      { key: "prio", header: t("mfg.workOrderList.str.priority"), width: "80px", drop: 4, align: "right", sortKey: "priority", render: (w) => `P${w.priority}` },
      { key: "ser", header: t("mfg.workOrderList.str.units"), width: "64px", drop: 1, render: (w) => serialText(w.serial_from, w.serial_to) },
      { key: "dl", header: t("mfg.workOrderList.str.forDemand"), width: "104px", drop: 2, render: (w) => (w.demand_line ? <span className="mono small">{w.demand_line.order_number}/{w.demand_line.line_no}</span> : "") },
      { key: "src", header: t("mfg.workOrderList.str.source"), width: "96px", render: (w) => <SourceBadge source={w.source} runNo={w.source_run_no} /> },
    ],
    [],
  );

  const STATUS_LABEL: Record<string, string> = { planned: t("mfg.workOrderList.str.plannedFirm"), released: t("mfg.workOrderList.str.releasedInProgress"), done: t("mfg.workOrderList.str.completedClosed"), cancelled: t("mfg.workOrderList.str.cancelled"), all: t("mfg.workOrderList.str.all") };
  const SOURCE_LABEL: Record<string, string> = { manual: t("mfg.workOrderList.str.enteredByHand"), mrp: t("mfg.workOrderList.str.fromMrp"), import: t("mfg.workOrderList.str.imported") };
  const chips: FilterChip[] = [];
  if (dq) chips.push({ key: "q", label: t("mfg.workOrderList.str.search"), value: dq, onClear: () => setQ("") });
  if (st !== "active") chips.push({ key: "status", label: t("mfg.workOrderList.str.status"), value: STATUS_LABEL[st] ?? st, onClear: () => set("status", "") });
  if (source) chips.push({ key: "source", label: t("mfg.workOrderList.str.source"), value: SOURCE_LABEL[source] ?? source, onClear: () => set("source", "") });

  return (
    <div className="col gap-lg">
      <PageHeader
        title={t("mfg.workOrderList.title.workOrders")}
        description={t("mfg.workOrderList.desc.productionOrdersWithQuantitiesDates")}
        actions={
          <>
            <Link className="btn" to={mfgPaths.kitting()} data-testid="wo-kitting-check">
              <Icon name="check" /> {t("mfg.workOrderList.btn.kittingCheck")}
            </Link>
            <ImportShortcut what={t("mfg.workOrderList.attr.workOrders")} />
            <PermissionGate perm="wo_edit">
              <Link className="btn primary" to={mfgPaths.workOrderNew()} data-testid="wo-new">
                <Icon name="plus" /> {t("mfg.workOrderList.btn.newWorkOrder")}
              </Link>
            </PermissionGate>
          </>
        }
      />
      <FilterBar
        search={{ id: "wo-q", value: q, onChange: setQ, placeholder: "Number or part number", testId: "wo-search" }}
        chips={chips}
        onClearAll={() => {
          setQ("");
          setParams({}, { replace: true });
        }}
        pageKey="work-orders"
      >
        <div className="field">
          <label htmlFor="wo-status">{t("mfg.workOrderList.label.status")}</label>
          <select id="wo-status" className="select" value={st} onChange={(e) => set("status", e.target.value === "active" ? "" : e.target.value)} data-testid="wo-status">
            <option value="active">{t("mfg.workOrderList.text.notFinished")}</option>
            <option value="planned">{t("mfg.workOrderList.text.plannedFirm")}</option>
            <option value="released">{t("mfg.workOrderList.text.releasedInProgress")}</option>
            <option value="done">{t("mfg.workOrderList.text.completedClosed")}</option>
            <option value="cancelled">{t("mfg.workOrderList.text.cancelled")}</option>
            <option value="all">{t("mfg.workOrderList.text.all")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="wo-src">{t("mfg.workOrderList.label.source")}</label>
          <select id="wo-src" className="select" value={source} onChange={(e) => set("source", e.target.value)}>
            <option value="">{t("mfg.workOrderList.text.any")}</option>
            <option value="manual">{t("mfg.workOrderList.text.enteredByHand")}</option>
            <option value="mrp">{t("mfg.workOrderList.text.fromMrp")}</option>
            <option value="import">{t("mfg.workOrderList.text.imported")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="wo-sort">{t("mfg.workOrderList.label.sortBy")}</label>
          <select id="wo-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "start_date" ? "" : e.target.value)}>
            <option value="start_date">{t("mfg.workOrderList.text.startDate")}</option>
            <option value="due_date">{t("mfg.workOrderList.text.dueDate")}</option>
            <option value="priority">{t("mfg.workOrderList.text.priority")}</option>
            <option value="number">{t("mfg.workOrderList.text.number")}</option>
          </select>
        </div>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      {canEdit ? <BulkActions rows={bulkRows(data.rows, selected)} noun={[t("mfg.workOrderList.str.workOrder2"), t("mfg.workOrderList.str.workOrders")]} actions={bulkDefs} onDone={() => (setSelected(new Set()), data.reload())} onClear={() => setSelected(new Set())} /> : null}
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(w) => w.id}
        label={t("mfg.workOrderList.label.workOrders")}
        testId="wo-table"
        card={{ title: "no", status: "st", fields: ["pn", "qty", "due"] }}
        selection={canEdit ? { selected, onChange: setSelected, rowId: (w) => w.id, rowLabel: (w) => w.number } : undefined}
        totalCount={data.total}
        rowExtras={(w) => ({ testId: "wo-row", data: { number: w.number, status: w.status } })}
        onRowClick={(w) => navigate(mfgPaths.workOrder(w.id))}
        onActivate={(w) => navigate(mfgPaths.workOrder(w.id))}
        onEndReached={data.onEndReached}
        loading={data.loading}
        sort={{ key: sort, dir: "asc" }}
        onSortChange={(x) => set("sort", !x || x.key === "start_date" ? "" : x.key)}
        exportName="work-orders"
        empty={data.loading ? t("mfg.workOrderList.str.loading") : t("mfg.workOrderList.str.noWorkOrdersMatchThese")}
        footer={<span>{t("mfg.workOrderList.text.showingWorkOrders", { t: t("common.nOfM", { n: fmtNum(data.rows.length), m: fmtNum(data.total) }) })}</span>}
      />
    </div>
  );
}

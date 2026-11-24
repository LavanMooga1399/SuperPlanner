/**
 * Quality worklists (M7 10): one layout for inspection lots, holds, NCRs, CAPA, complaints, field actions,
 * equipment, plans and schemes - page header with the one primary action, filter bar with search, quick views
 * ("Due today", "Overdue", "Awaiting my signature"), status and list-specific filters, saved views, then the shared
 * virtual table (sorting, columns, CSV of loaded rows, phone cards). Filters live in the URL.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { FilterBar, type FilterChip } from "../../components/FilterBar";
import { PageHeader } from "../../components/PageHeader";
import type { QaPage } from "../api/typesM7";
import { MfgError } from "../components/Feedback";
import { VirtualTable, type CardSpec, type Column } from "../components/VirtualTable";
import { fmtNum } from "../lib/formatM2";
import { setSearchParam, usePaged } from "../lib/usePaged";
import { useDebounced } from "../lib/useMfg";
import { t } from "../../lib/i18n";
import "./qa.css";

export interface QuickView {
  key: string;
  label: string;
  query: Record<string, string>;
}

export interface Option {
  value: string;
  label: string;
}

export interface ExtraFilter {
  param: string;
  label: string;
  options: Option[];
}

export function QaWorklist<T>({
  title,
  description,
  actions,
  pageKey,
  testId,
  searchPlaceholder,
  views,
  statusOptions,
  defaultStatus = "",
  filters = [],
  fetch,
  columns,
  card,
  rowKey,
  rowExtras,
  rowPath,
  empty,
  noun,
  above,
  sortDefault,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  pageKey: string;
  testId: string;
  /** omit for lists without server search */
  searchPlaceholder?: string;
  views?: QuickView[];
  statusOptions?: Option[];
  /** value sent when the status select shows its first option */
  defaultStatus?: string;
  filters?: ExtraFilter[];
  fetch(query: Record<string, string | number | undefined>, signal: AbortSignal): Promise<QaPage<T>>;
  columns: Column<T>[];
  card: CardSpec;
  rowKey(row: T): string;
  rowExtras(row: T): { testId?: string; data?: Record<string, string | number | boolean | null | undefined> };
  rowPath?(row: T): string;
  empty: string;
  /** plural noun for the footer, e.g. "inspection lots" */
  noun: string;
  above?: ReactNode;
  sortDefault?: string;
}) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  const view = params.get("view") ?? "";
  const status = params.get("status") ?? "";
  const sort = params.get("sort") ?? sortDefault ?? "";
  const extra = filters.map((f) => [f.param, params.get(f.param) ?? ""] as const);
  const key = JSON.stringify([dq, view, status, sort, extra]);
  const viewDef = views?.find((v) => v.key === view);
  const data = usePaged<T, QaPage<T>>(
    (offset, limit, signal) =>
      fetch(
        {
          q: dq || undefined,
          status: status || defaultStatus || undefined,
          sort: sort || undefined,
          ...(viewDef?.query ?? {}),
          ...Object.fromEntries(extra.filter(([, v]) => v)),
          limit,
          offset,
        },
        signal,
      ),
    [key],
  );
  const chips: FilterChip[] = [];
  if (dq) chips.push({ key: "q", label: t("qa.list.label.search"), value: dq, onClear: () => setQ("") });
  if (status && statusOptions) chips.push({ key: "status", label: t("qa.list.label.status"), value: statusOptions.find((o) => o.value === status)?.label ?? status, onClear: () => set("status", "") });
  for (const f of filters) {
    const v = params.get(f.param);
    if (v) chips.push({ key: f.param, label: f.label, value: f.options.find((o) => o.value === v)?.label ?? v, onClear: () => set(f.param, "") });
  }
  const cols = useMemo(() => columns, [columns]);
  return (
    <div className="col gap-lg" data-testid={testId}>
      <PageHeader title={title} description={description} actions={actions} />
      {above}
      <FilterBar
        search={searchPlaceholder ? { id: `${pageKey}-q`, value: q, onChange: setQ, placeholder: searchPlaceholder, testId: `${pageKey}-search` } : undefined}
        chips={chips}
        onClearAll={() => {
          setQ("");
          setParams({}, { replace: true });
        }}
        pageKey={pageKey}
      >
        {views?.length ? (
          <div className="field">
            <span className="field-label" id={`${pageKey}-view-l`}>
              {t("qa.list.label.show")}
            </span>
            <div className="btn-group" role="group" aria-labelledby={`${pageKey}-view-l`}>
              <button type="button" className="btn" aria-pressed={view === ""} onClick={() => set("view", "")}>
                {t("qa.list.view.all")}
              </button>
              {views.map((v) => (
                <button key={v.key} type="button" className="btn" aria-pressed={view === v.key} onClick={() => set("view", v.key)} data-testid={`${pageKey}-view-${v.key}`}>
                  {v.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {statusOptions ? (
          <div className="field">
            <label htmlFor={`${pageKey}-status`}>{t("qa.list.label.status")}</label>
            <select id={`${pageKey}-status`} className="select" value={status} onChange={(e) => set("status", e.target.value)} data-testid={`${pageKey}-status`}>
              {statusOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        {filters.map((f) => (
          <div className="field" key={f.param}>
            <label htmlFor={`${pageKey}-${f.param}`}>{f.label}</label>
            <select id={`${pageKey}-${f.param}`} className="select" value={params.get(f.param) ?? ""} onChange={(e) => set(f.param, e.target.value)}>
              {f.options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        ))}
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={cols}
        rowKey={rowKey}
        label={title}
        testId={`${pageKey}-table`}
        card={card}
        totalCount={data.total}
        rowExtras={rowExtras}
        onRowClick={rowPath ? (r) => navigate(rowPath(r)) : undefined}
        onActivate={rowPath ? (r) => navigate(rowPath(r)) : undefined}
        onEndReached={data.onEndReached}
        loading={data.loading}
        sort={sort ? { key: sort, dir: sort.startsWith("-") ? "desc" : "asc" } : null}
        onSortChange={(x) => set("sort", x && x.key !== sortDefault ? x.key : "")}
        exportName={pageKey}
        empty={empty}
        footer={<span>{t("qa.list.tpl.showing", { n: t("common.nOfM", { n: fmtNum(data.rows.length), m: fmtNum(data.total) }), noun })}</span>}
      />
    </div>
  );
}

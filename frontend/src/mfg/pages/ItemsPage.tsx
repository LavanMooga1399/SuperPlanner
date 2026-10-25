/**
 * `/mfg/items` (M 11.1): virtual table over `GET /items`, debounced search (250 ms), filters, pages of 200
 * loaded as the user scrolls near the end (M 11.4). Search and filters live in the URL so reload keeps them.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../components/Icon";
import { listItems } from "../api/client";
import type { ItemQuery, ItemRecord, ItemSort, MakeBuy } from "../api/types";
import { MfgError } from "../components/Feedback";
import { NewItemDialog } from "../components/NewItemDialog";
import { ActiveBadge, MakeBuyBadge } from "../components/StatusChip";
import { VirtualTable, type Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { isAbortError, useDebounced } from "../lib/useMfg";

const PAGE = 200;

function yes(v: boolean, label: string) {
  return v ? (
    <span className="mfg-yes" title={label}>
      <Icon name="check" size={14} /> Yes
    </span>
  ) : (
    <span className="faint">No</span>
  );
}

function boolParam(v: string | null): boolean | undefined {
  return v === "true" ? true : v === "false" ? false : undefined;
}

export function ItemsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [family, setFamily] = useState(params.get("family") ?? "");
  const dq = useDebounced(q, 250);
  const dFamily = useDebounced(family, 250);
  const makeBuy = (params.get("make_buy") ?? "") as MakeBuy | "";
  const active = params.get("active") ?? "";
  const hasBom = params.get("has_bom") ?? "";
  const hasRouting = params.get("has_routing") ?? "";
  const sort = (params.get("sort") ?? "part_number") as ItemSort;
  const [items, setItems] = useState<ItemRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const gen = useRef(0);
  const inflight = useRef<AbortController | null>(null);

  const setParam = useCallback(
    (key: string, value: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  useEffect(() => setParam("q", dq.trim()), [dq, setParam]);
  useEffect(() => setParam("family", dFamily.trim()), [dFamily, setParam]);

  const query: ItemQuery = useMemo(
    () => ({
      q: dq.trim() || undefined,
      make_buy: makeBuy || undefined,
      family: dFamily.trim() || undefined,
      active: boolParam(active),
      has_bom: boolParam(hasBom),
      has_routing: boolParam(hasRouting),
      sort,
    }),
    [dq, makeBuy, dFamily, active, hasBom, hasRouting, sort],
  );

  const fetchPage = useCallback(
    async (offset: number, replace: boolean) => {
      const my = replace ? ++gen.current : gen.current;
      inflight.current?.abort();
      const ctl = new AbortController();
      inflight.current = ctl;
      setLoading(true);
      setError(null);
      try {
        const page = await listItems({ ...query, limit: PAGE, offset }, ctl.signal);
        if (my !== gen.current) return;
        setTotal(page.total);
        setItems((prev) => (replace ? page.items : [...prev, ...page.items]));
      } catch (e) {
        if (isAbortError(e) || my !== gen.current) return;
        setError(e);
      } finally {
        if (my === gen.current && inflight.current === ctl) setLoading(false);
      }
    },
    [query],
  );

  useEffect(() => {
    void fetchPage(0, true);
    return () => inflight.current?.abort();
  }, [fetchPage]);

  const onEndReached = useCallback(() => {
    if (!loading && !error && items.length < total) void fetchPage(items.length, false);
  }, [loading, error, items.length, total, fetchPage]);

  const columns: Column<ItemRecord>[] = useMemo(
    () => [
      {
        key: "pn",
        header: "Part number",
        width: "minmax(150px, 1.1fr)",
        render: (it) => (
          <Link to={mfgPaths.item(it.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {it.part_number}
          </Link>
        ),
      },
      { key: "rev", header: "Rev.", width: "52px", render: (it) => <span className="mono">{it.revision}</span> },
      { key: "desc", header: "Description", width: "minmax(200px, 2fr)", render: (it) => <span className="mfg-ellipsis">{it.description}</span> },
      { key: "mb", header: "Make / buy", width: "104px", render: (it) => <MakeBuyBadge value={it.make_buy} /> },
      { key: "uom", header: "Unit", width: "52px", render: (it) => it.uom },
      { key: "family", header: "Family", width: "110px", render: (it) => <span className="mfg-ellipsis">{it.family ?? ""}</span> },
      {
        key: "lead",
        header: "Lead time",
        width: "84px",
        align: "right",
        render: (it) => (it.lead_time_days === null ? <span className="faint">-</span> : `${it.lead_time_days} d`),
      },
      { key: "bom", header: "BOM", width: "64px", render: (it) => yes(it.has_bom, "Has a BOM") },
      { key: "rtg", header: "Routing", width: "72px", render: (it) => yes(it.has_routing, "Has a routing") },
      { key: "used", header: "Used in", width: "70px", align: "right", render: (it) => it.used_in_count },
      { key: "act", header: <span className="sr-only">Status</span>, label: "Status", width: "90px", render: (it) => <ActiveBadge active={it.active} /> },
    ],
    [],
  );

  const filtered = Boolean(query.q || query.make_buy || query.family || active || hasBom || hasRouting);

  return (
    <div className="col gap-lg">
      <div className="page-header mfg-header">
        <div>
          <h1>Items</h1>
          <p>Every part you make or buy: assemblies, boards, components, materials.</p>
        </div>
        <button type="button" className="btn primary" onClick={() => setCreating(true)} data-testid="item-new">
          <Icon name="plus" /> New item
        </button>
      </div>

      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 260px" }}>
          <label htmlFor="items-q">Search</label>
          <input
            id="items-q"
            className="input"
            type="search"
            placeholder="Part number or description"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            data-testid="items-search"
          />
        </div>
        <div className="field">
          <label htmlFor="items-mb">Make / buy</label>
          <select id="items-mb" className="select" value={makeBuy} onChange={(e) => setParam("make_buy", e.target.value)} data-testid="items-filter-make-buy">
            <option value="">All</option>
            <option value="make">Make</option>
            <option value="buy">Buy</option>
            <option value="phantom">Phantom</option>
          </select>
        </div>
        <div className="field" style={{ width: 140 }}>
          <label htmlFor="items-family">Family</label>
          <input id="items-family" className="input" value={family} onChange={(e) => setFamily(e.target.value)} data-testid="items-filter-family" />
        </div>
        <div className="field">
          <label htmlFor="items-active">Status</label>
          <select id="items-active" className="select" value={active} onChange={(e) => setParam("active", e.target.value)}>
            <option value="">All</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="items-bom">BOM</label>
          <select id="items-bom" className="select" value={hasBom} onChange={(e) => setParam("has_bom", e.target.value)}>
            <option value="">Any</option>
            <option value="true">Has a BOM</option>
            <option value="false">No BOM</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="items-rtg">Routing</label>
          <select id="items-rtg" className="select" value={hasRouting} onChange={(e) => setParam("has_routing", e.target.value)}>
            <option value="">Any</option>
            <option value="true">Has a routing</option>
            <option value="false">No routing</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="items-sort">Sort by</label>
          <select id="items-sort" className="select" value={sort} onChange={(e) => setParam("sort", e.target.value === "part_number" ? "" : e.target.value)}>
            <option value="part_number">Part number</option>
            <option value="description">Description</option>
            <option value="-updated_at">Recently changed</option>
          </select>
        </div>
      </div>

      <MfgError error={error} onRetry={() => void fetchPage(0, true)} />

      <VirtualTable
        rows={items}
        columns={columns}
        rowKey={(it) => it.id}
        label="Items"
        testId="items-table"
        totalCount={total}
        height="min(66vh, 720px)"
        rowExtras={(it) => ({ testId: "items-row", data: { "part-number": it.part_number }, className: it.active ? undefined : "mfg-inactive" })}
        onRowClick={(it) => navigate(mfgPaths.item(it.id))}
        onActivate={(it) => navigate(mfgPaths.item(it.id))}
        onEndReached={onEndReached}
        empty={
          loading ? (
            <span className="row" role="status">
              <span className="spinner" aria-hidden /> Loading items…
            </span>
          ) : filtered ? (
            "No items match these filters."
          ) : (
            <span>
              No items yet. Create one, <Link to={mfgPaths.importStart()}>import a file</Link> or{" "}
              <Link to={mfgPaths.home()}>load a sample</Link>.
            </span>
          )
        }
        footer={
          <span className="muted small" role="status" data-testid="items-count">
            {loading && items.length ? <span className="spinner" aria-hidden /> : null} Showing {items.length.toLocaleString()} of{" "}
            {total.toLocaleString()} items
          </span>
        }
      />

      {creating ? (
        <NewItemDialog onClose={() => setCreating(false)} onCreated={(it) => navigate(mfgPaths.item(it.id))} />
      ) : null}
    </div>
  );
}

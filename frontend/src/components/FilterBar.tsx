/**
 * Filter bar (UX-STANDARD 3/4): search, compact filter fields, active-filter chips with "Clear all", and saved
 * views (named URL query strings per page, kept in localStorage `sp.views.<pageKey>`). Pages keep their own
 * field ids and test ids; this component only lays them out the same way everywhere.
 */
import { Children, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { Icon } from "./Icon";
import { savePref, syncPref } from "../lib/serverPrefs";
import { t } from "../lib/i18n";

export interface FilterChip {
  key: string;
  label: string;
  value: string;
  onClear(): void;
}

export interface FilterSearchProps {
  id: string;
  value: string;
  onChange(v: string): void;
  placeholder: string;
  label?: string;
  testId?: string;
}

export function FilterBar({
  search,
  children,
  chips = [],
  onClearAll,
  pageKey,
  end,
}: {
  search?: FilterSearchProps;
  children?: ReactNode;
  chips?: FilterChip[];
  onClearAll?(): void;
  /** Enables saved views for this page. */
  pageKey?: string;
  end?: ReactNode;
}) {
  // phones: the filter fields fold behind one "Filters" button (search and chips stay visible)
  const [open, setOpen] = useState(false);
  const fieldCount = Children.count(children);
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className={`filter-bar toolbar mfg-filters${open ? " filters-open" : ""}`} role="search" style={{ marginBottom: 0 }}>
        {search ? (
          <div className="field filter-search">
            <label htmlFor={search.id}>{search.label ?? "Search"}</label>
            <div className="filter-search-wrap">
              <Icon name="search" size={14} />
              <input
                id={search.id}
                className="input"
                type="search"
                placeholder={search.placeholder}
                value={search.value}
                onChange={(e) => search.onChange(e.target.value)}
                data-testid={search.testId}
              />
            </div>
          </div>
        ) : null}
        {fieldCount ? (
          <button type="button" className="btn filter-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            <Icon name="filter" size={14} /> {t("filters.button")}
            {chips.length ? ` (${chips.length})` : ""}
          </button>
        ) : null}
        <div className="filter-fields">{children}</div>
        {end || pageKey ? (
          <div className="filter-bar-end">
            {end}
            {pageKey ? <SavedViews pageKey={pageKey} /> : null}
          </div>
        ) : null}
      </div>
      {chips.length ? (
        <div className="chips" aria-label={t("filters.active")}>
          {chips.map((c) => (
            <span key={c.key} className="filter-chip">
              <span>
                {c.label}: <b>{c.value}</b>
              </span>
              <button type="button" onClick={c.onClear} aria-label={t("filters.remove", { label: c.label, value: c.value })}>
                <Icon name="x" size={12} />
              </button>
            </span>
          ))}
          {onClearAll && chips.length > 1 ? (
            <button type="button" className="btn ghost sm" onClick={onClearAll}>
              {t("filters.clearAll")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

interface SavedView {
  name: string;
  search: string;
}

function loadViews(key: string): SavedView[] {
  try {
    return JSON.parse(window.localStorage.getItem(`sp.views.${key}`) ?? "[]") as SavedView[];
  } catch {
    return [];
  }
}

function SavedViews({ pageKey }: { pageKey: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [views, setViews] = useState<SavedView[]>(() => loadViews(pageKey));
  const [name, setName] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  useEffect(() => syncPref<SavedView[]>(`views.${pageKey}`, `sp.views.${pageKey}`, (v) => setViews(Array.isArray(v) ? v : [])), [pageKey]);
  const store = (v: SavedView[]) => {
    setViews(v);
    savePref(`views.${pageKey}`, `sp.views.${pageKey}`, v.length ? v : undefined);
  };
  const current = views.find((v) => v.search === location.search);
  const save = () => {
    const n = name.trim();
    if (!n) return;
    store([...views.filter((v) => v.name !== n), { name: n, search: location.search }]);
    setName("");
  };
  return (
    <div className="popover-anchor" ref={ref}>
      <button ref={btn} type="button" className="btn" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((v) => !v)} data-testid="saved-views" title="Saved views: named sets of filters">
        <Icon name="bookmark" size={14} />
        <span className="nowrap">{current ? current.name : t("views.button")}</span>
        <Icon name="chevron-down" size={12} />
      </button>
      {open ? (
        <div className="popover" role="dialog" aria-label="Saved views">
          <div className="popover-group">
            <span className="popover-legend">{t("views.title")}</span>
            {views.length === 0 ? <span className="small muted" style={{ padding: "2px 6px" }}>{t("views.none")}</span> : null}
            {views.map((v) => (
              <div key={v.name} className="col-row">
                <button type="button" className="menu-item" onClick={() => (navigate({ search: v.search }), setOpen(false))} aria-current={v === current ? "true" : undefined}>
                  {v === current ? <Icon name="check" size={14} /> : <span style={{ width: 14 }} />}
                  <span className="mfg-ellipsis">{v.name}</span>
                </button>
                <button type="button" className="btn ghost sm icon" onClick={() => store(views.filter((x) => x !== v))} aria-label={t("views.delete", { name: v.name })}>
                  <Icon name="trash" size={14} />
                </button>
              </div>
            ))}
          </div>
          <div className="menu-sep" />
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
          >
            <input className="input sm" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("views.namePlaceholder")} aria-label="Name for the current view" maxLength={60} />
            <button type="submit" className="btn sm primary" disabled={!name.trim()}>
              {t("views.save")}
            </button>
          </form>
          <button type="button" className="menu-item" onClick={() => (navigate({ search: "" }), setOpen(false))}>
            <Icon name="refresh" size={14} /> {t("views.reset")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

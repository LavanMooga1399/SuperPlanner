/**
 * Command palette (Ctrl/Cmd+K, UX-STANDARD 4): jump to any page, run a common action, or open a record (items,
 * work orders, purchase orders, demand orders, serials) through the existing list endpoints with `q`.
 * ARIA combobox + listbox; Up/Down move, Enter opens, Escape closes.
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Icon, type IconName } from "../Icon";
import { MFG_NAV } from "../../mfg/lib/nav";
import { mfgPaths } from "../../mfg/lib/paths";
import { listItems } from "../../mfg/api/client";
import { listDemandOrders, listPurchaseDocs, listWorkOrders } from "../../mfg/api/clientM2";
import { listSerials } from "../../mfg/api/clientM4";
import { setDensity, setTheme, usePrefs } from "../../lib/prefs";
import { closePalette, openShortcuts, useCommandState } from "./commands";
import { t } from "../../lib/i18n";

interface Entry {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: IconName;
  keywords?: string;
  mono?: boolean;
  run(): void;
}

const MAX_PER_KIND = 5;

/** Subsequence-free, word-start friendly match: every query word must appear in the haystack. */
function matches(q: string, hay: string): boolean {
  const h = hay.toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => h.includes(w));
}

function useRecordSearch(q: string, go: (to: string) => void): { entries: Entry[]; busy: boolean } {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setEntries([]);
      setBusy(false);
      return;
    }
    const ac = new AbortController();
    setBusy(true);
    const t = window.setTimeout(() => {
      const s = ac.signal;
      const safe = <T,>(p: Promise<T>) => p.catch(() => null);
      void Promise.all([
        safe(listItems({ q: term, limit: MAX_PER_KIND }, s)),
        safe(listWorkOrders({ q: term, limit: MAX_PER_KIND }, s)),
        safe(listPurchaseDocs("po", { q: term, limit: MAX_PER_KIND }, s)),
        safe(listDemandOrders({ q: term, limit: MAX_PER_KIND }, s)),
        safe(listSerials({ q: term, limit: MAX_PER_KIND }, s)),
      ]).then(([items, wos, pos, dos, serials]) => {
        if (s.aborted) return;
        const out: Entry[] = [];
        for (const i of items?.items ?? [])
          out.push({ id: `item-${i.id}`, group: "Items", label: i.part_number, hint: `Rev. ${i.revision} · ${i.description}`, icon: "list", mono: true, run: () => go(mfgPaths.item(i.id)) });
        for (const w of wos?.items ?? [])
          out.push({ id: `wo-${w.id}`, group: "Work orders", label: w.number, hint: `${w.item.part_number} · ${w.item.description}`, icon: "wrench", mono: true, run: () => go(mfgPaths.workOrder(w.id)) });
        for (const p of pos?.items ?? [])
          out.push({ id: `po-${p.id}`, group: "Purchase orders", label: p.number, hint: p.supplier?.name ?? "", icon: "briefcase", mono: true, run: () => go(mfgPaths.purchaseDoc("po", p.id)) });
        for (const d of dos?.items ?? [])
          out.push({ id: `do-${d.id}`, group: "Demand orders", label: d.number, hint: [d.customer, d.program].filter(Boolean).join(" · "), icon: "flag", mono: true, run: () => go(mfgPaths.demandOrder(d.id)) });
        for (const x of serials?.items ?? [])
          out.push({ id: `sn-${x.id}`, group: "Serials", label: x.serial, hint: `${x.item.part_number}${x.wo ? ` · ${x.wo.number}` : ""}`, icon: "barcode", mono: true, run: () => go(mfgPaths.serial(x.id)) });
        setEntries(out);
        setBusy(false);
      });
    }, 180);
    return () => {
      ac.abort();
      window.clearTimeout(t);
    };
  }, [q, go]);
  return { entries, busy };
}

export function CommandPalette() {
  const { palette } = useCommandState();
  return palette ? <PaletteDialog /> : null;
}

function PaletteDialog() {
  const navigate = useNavigate();
  const prefs = usePrefs();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();
  const prevFocus = useRef<HTMLElement | null>(null);

  const go = useMemo(
    () => (to: string) => {
      closePalette();
      navigate(to);
    },
    [navigate],
  );

  useEffect(() => {
    prevFocus.current = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => prevFocus.current?.focus?.();
  }, []);

  const staticEntries: Entry[] = useMemo(() => {
    const pages: Entry[] = [
      { id: "p-sched", group: "Pages", label: "Scheduling plans", hint: "Scheduling", icon: "calendar", run: () => go("/") },
      { id: "p-fin", group: "Pages", label: "Finance", hint: "Finance", icon: "briefcase", run: () => go("/finance") },
    ];
    for (const g of MFG_NAV)
      for (const s of g.sections)
        pages.push({ id: `p-${s.key}`, group: "Pages", label: s.label, hint: `Manufacturing · ${g.label}`, icon: s.icon, keywords: s.keywords, run: () => go(s.to) });
    pages.push({ id: "p-acct", group: "Pages", label: "Account", hint: "Your profile and tokens", icon: "user", run: () => go("/account") });
    const actions: Entry[] = [
      { id: "a-wo", group: "Actions", label: "New work order", icon: "plus", keywords: "create", run: () => go(mfgPaths.workOrderNew()) },
      { id: "a-po", group: "Actions", label: "New purchase order", icon: "plus", keywords: "create", run: () => go(mfgPaths.purchaseDocNew("po")) },
      { id: "a-do", group: "Actions", label: "New demand order", icon: "plus", keywords: "create sales", run: () => go(mfgPaths.demandNew()) },
      { id: "a-post", group: "Actions", label: "Post a stock movement", icon: "box", keywords: "receipt issue adjust", run: () => go(mfgPaths.post()) },
      { id: "a-imp", group: "Actions", label: "Import from Excel or CSV", icon: "upload", run: () => go(mfgPaths.importStart()) },
      {
        id: "a-theme",
        group: "Actions",
        label: prefs.resolved === "dark" ? "Switch to light theme" : "Switch to dark theme",
        icon: prefs.resolved === "dark" ? "sun" : "moon",
        keywords: "theme dark light appearance",
        run: () => {
          setTheme(prefs.resolved === "dark" ? "light" : "dark");
          closePalette();
        },
      },
      {
        id: "a-density",
        group: "Actions",
        label: prefs.density === "compact" ? "Use comfortable density" : "Use compact density",
        icon: "columns",
        keywords: "density rows spacing",
        run: () => {
          setDensity(prefs.density === "compact" ? "comfortable" : "compact");
          closePalette();
        },
      },
      { id: "a-keys", group: "Actions", label: "Keyboard shortcuts", icon: "keyboard", keywords: "help keys", run: () => openShortcuts() },
    ];
    return [...pages, ...actions];
  }, [go, prefs.resolved, prefs.density]);

  const records = useRecordSearch(q, go);
  const shown = useMemo(() => {
    const term = q.trim();
    const filtered = term ? staticEntries.filter((e) => matches(term, `${e.label} ${e.hint ?? ""} ${e.keywords ?? ""}`)) : staticEntries.filter((e) => e.group === "Actions" || ["p-overview", "p-work-orders", "p-schedule", "p-mrp", "p-items", "p-purchasing", "p-inventory"].includes(e.id));
    return [...filtered.slice(0, 12), ...records.entries];
  }, [q, staticEntries, records.entries]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(shown.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      shown[active]?.run();
    } else if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
    }
  };

  let lastGroup = "";
  return (
    <div className="overlay palette-overlay" onMouseDown={(e) => e.target === e.currentTarget && closePalette()}>
      <div className="palette" role="dialog" aria-modal="true" aria-label={t("studio.commandPalette.aria.searchAndCommands")} data-testid="command-palette">
        <div className="palette-input">
          <Icon name="search" />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={shown[active] ? `${listId}-${active}` : undefined}
            aria-autocomplete="list"
            aria-label={t("studio.commandPalette.aria.searchPagesActionsAndRecords")}
            placeholder={t("palette.placeholder")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            data-testid="command-input"
          />
          {records.busy ? <span className="spinner" aria-hidden /> : <kbd>Esc</kbd>}
        </div>
        <ul className="palette-list" role="listbox" id={listId} ref={listRef} aria-label={t("studio.commandPalette.aria.results")}>
          {shown.length === 0 ? (
            <li className="palette-empty" role="presentation">
              {records.busy ? t("palette.searching") : t("palette.none", { q: q.trim() })}
            </li>
          ) : null}
          {shown.map((e, i) => {
            const head = e.group !== lastGroup ? e.group : null;
            lastGroup = e.group;
            return (
              <li key={e.id} role="presentation">
                {head ? (
                  <div className="palette-group" role="presentation">
                    {head}
                  </div>
                ) : null}
                <div
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  data-index={i}
                  className={`palette-item${i === active ? " active" : ""}`}
                  onMouseMove={() => i !== active && setActive(i)}
                  onClick={() => e.run()}
                >
                  <Icon name={e.icon} size={14} />
                  <span className={`palette-label${e.mono ? " mono" : ""}`}>{e.label}</span>
                  {e.hint ? <span className="palette-hint">{e.hint}</span> : null}
                  {i === active ? <Icon name="arrow-right" size={14} className="palette-enter" /> : null}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="palette-foot">
          <span><kbd>↑</kbd> <kbd>↓</kbd> move</span>
          <span><kbd>Enter</kbd> open</span>
          <span><kbd>Esc</kbd> close</span>
          <span className="grow" />
          <span>{t("palette.hint")}</span>
        </div>
      </div>
    </div>
  );
}

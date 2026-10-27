/**
 * Location select (cached `GET /locations`, at most 1,000 per plant) and supplier combobox (server search, first
 * 20 shown; ARIA 1.2 combobox as `ItemPicker`).
 */
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { listLocations, listSuppliers } from "../api/clientM2";
import type { Ref } from "../api/types";
import type { LocationKind, LocationRecord } from "../api/typesM2";
import { isAbortError, useDebounced } from "../lib/useMfg";
import { LOCATION_KIND_LABEL } from "./StatusM2";

let locCache: Promise<LocationRecord[]> | null = null;

export function invalidateLocations(): void {
  locCache = null;
}

export function useLocations(): LocationRecord[] | null {
  const [locs, setLocs] = useState<LocationRecord[] | null>(null);
  useEffect(() => {
    let alive = true;
    if (!locCache) {
      locCache = listLocations({}).then(
        (r) => r.items,
        (e: unknown) => {
          locCache = null;
          throw e;
        },
      );
    }
    locCache.then(
      (l) => alive && setLocs(l),
      () => alive && setLocs([]),
    );
    return () => {
      alive = false;
    };
  }, []);
  return locs;
}

export function LocationSelect({
  value,
  onChange,
  label,
  hideLabel,
  kinds,
  allowEmpty,
  emptyLabel = "Choose a location",
  testId,
  disabled,
  includeInactive,
}: {
  value: string;
  onChange(id: string): void;
  label: string;
  hideLabel?: boolean;
  kinds?: LocationKind[];
  allowEmpty?: boolean;
  emptyLabel?: string;
  testId?: string;
  disabled?: boolean;
  includeInactive?: boolean;
}) {
  const locs = useLocations();
  const id = useId().replace(/:/g, "");
  const shown = (locs ?? []).filter((l) => (includeInactive || l.active || l.id === value) && (!kinds || kinds.includes(l.kind)));
  const control = (
    <select
      id={`loc-${id}`}
      className="select sm"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={hideLabel ? label : undefined}
      data-testid={testId}
      disabled={disabled}
    >
      {allowEmpty || !value ? <option value="">{locs === null ? "Loading…" : emptyLabel}</option> : null}
      {shown.map((l) => (
        <option key={l.id} value={l.id} data-code={l.code}>
          {l.code} · {l.name} ({LOCATION_KIND_LABEL[l.kind]}){l.receipt_default ? " · receiving" : ""}
        </option>
      ))}
    </select>
  );
  if (hideLabel) return control;
  return (
    <div className="field">
      <label htmlFor={`loc-${id}`}>{label}</label>
      {control}
    </div>
  );
}

export function SupplierPicker({
  value,
  onChange,
  label,
  hideLabel,
  testId,
  disabled,
  allowClear,
}: {
  value: Ref | null;
  onChange(s: Ref | null): void;
  label: string;
  hideLabel?: boolean;
  testId?: string;
  disabled?: boolean;
  allowClear?: boolean;
}) {
  const text0 = value ? `${value.code} · ${value.name}` : "";
  const [text, setText] = useState(text0);
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<Ref[]>([]);
  const [hi, setHi] = useState(0);
  const dq = useDebounced(text, 200);
  const id = useId().replace(/:/g, "");
  const wrap = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [rect, setRect] = useState<{ top: number; left: number; width: number } | null>(null);

  useEffect(() => setText(text0), [text0]);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = inputRef.current?.getBoundingClientRect();
      if (r) setRect({ top: r.bottom + 2, left: r.left, width: Math.max(r.width, 300) });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const ctl = new AbortController();
    const q = dq.trim() === text0 ? "" : dq.trim();
    listSuppliers({ q: q || undefined, active: true }, ctl.signal)
      .then((r) => {
        setOptions(r.items.slice(0, 20).map((s) => ({ id: s.id, code: s.code, name: s.name })));
        setHi(0);
      })
      .catch((e: unknown) => {
        if (!isAbortError(e)) setOptions([]);
      });
    return () => ctl.abort();
  }, [dq, open, text0]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) {
        setOpen(false);
        setText(text0);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, text0]);

  const pick = (s: Ref | null) => {
    onChange(s);
    setOpen(false);
  };
  const listId = `sp-list-${id}`;
  const inputId = `sp-input-${id}`;
  return (
    <div className={hideLabel ? "mfg-picker" : "field mfg-picker"} ref={wrap}>
      {hideLabel ? null : <label htmlFor={inputId}>{label}</label>}
      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
        <input
          ref={inputRef}
          id={inputId}
          className="input sm grow"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label={hideLabel ? label : undefined}
          aria-activedescendant={open && options[hi] ? `${listId}-${hi}` : undefined}
          value={text}
          placeholder="Search supplier code or name"
          disabled={disabled}
          data-testid={testId}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              setHi((h) => Math.min(options.length - 1, h + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setHi((h) => Math.max(0, h - 1));
            } else if (e.key === "Enter") {
              if (open && options[hi]) {
                e.preventDefault();
                pick(options[hi]);
              }
            } else if (e.key === "Escape" && open) {
              e.stopPropagation();
              setOpen(false);
              setText(text0);
            } else if (e.key === "Tab") {
              setOpen(false);
              setText(text0);
            }
          }}
        />
        {allowClear && value && !disabled ? (
          <button type="button" className="btn sm ghost icon" aria-label={`Clear ${label}`} onClick={() => pick(null)}>
            ×
          </button>
        ) : null}
      </div>
      {open ? (
        <ul className="mfg-picker-list" role="listbox" id={listId} aria-label={`${label} options`} style={rect ? { top: rect.top, left: rect.left, width: rect.width } : undefined}>
          {options.length === 0 ? <li className="mfg-picker-empty">No matching suppliers</li> : null}
          {options.map((s, i) => (
            <li
              key={s.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === hi}
              className={i === hi ? "hi" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(s);
              }}
              onMouseEnter={() => setHi(i)}
            >
              <span className="mono">{s.code}</span>
              <span className="muted small mfg-ellipsis">{s.name}</span>
              <span />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

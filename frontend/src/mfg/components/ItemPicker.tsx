/**
 * Item combobox over `GET /items?q=` (limit 20, M 11.2). ARIA 1.2 combobox pattern: the input owns a listbox,
 * Up/Down move the highlighted option, Enter picks it, Escape closes.
 */
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { listItems } from "../api/client";
import type { ItemRef, MakeBuy } from "../api/types";
import { isAbortError, useDebounced } from "../lib/useMfg";

export interface ItemPickerProps {
  value: ItemRef | null;
  onChange(item: ItemRef): void;
  label: string;
  /** Hide the visible label (grids); the input keeps `aria-label`. */
  hideLabel?: boolean;
  makeBuy?: MakeBuy;
  excludeId?: string;
  disabled?: boolean;
  testId?: string;
  placeholder?: string;
  autoFocus?: boolean;
}

export function ItemPicker({
  value,
  onChange,
  label,
  hideLabel,
  makeBuy,
  excludeId,
  disabled,
  testId,
  placeholder = "Search part number",
  autoFocus,
}: ItemPickerProps) {
  const [text, setText] = useState(value?.part_number ?? "");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ItemRef[]>([]);
  const [hi, setHi] = useState(0);
  const [loading, setLoading] = useState(false);
  const dq = useDebounced(text, 200);
  const id = useId().replace(/:/g, "");
  const wrap = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [rect, setRect] = useState<{ top: number; left: number; width: number } | null>(null);

  // The list is position: fixed so grids with overflow do not clip it; it follows scroll/resize.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = inputRef.current?.getBoundingClientRect();
      if (r) setRect({ top: r.bottom + 2, left: r.left, width: Math.max(r.width, 320) });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  useEffect(() => setText(value?.part_number ?? ""), [value?.id, value?.part_number]);

  useEffect(() => {
    if (!open) return;
    const ctl = new AbortController();
    setLoading(true);
    listItems({ q: dq.trim() || undefined, make_buy: makeBuy, limit: 20, offset: 0 }, ctl.signal)
      .then((page) => {
        setOptions(page.items.filter((it) => it.id !== excludeId));
        setHi(0);
      })
      .catch((e: unknown) => {
        if (!isAbortError(e)) setOptions([]);
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    return () => ctl.abort();
  }, [dq, open, makeBuy, excludeId]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) {
        setOpen(false);
        setText(value?.part_number ?? "");
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, value?.part_number]);

  const pick = (it: ItemRef) => {
    onChange({
      id: it.id,
      part_number: it.part_number,
      revision: it.revision,
      description: it.description,
      uom: it.uom,
      make_buy: it.make_buy,
      active: it.active,
    });
    setText(it.part_number);
    setOpen(false);
  };

  const listId = `ip-list-${id}`;
  const inputId = `ip-input-${id}`;
  return (
    <div className="mfg-picker" ref={wrap}>
      {hideLabel ? null : (
        <label htmlFor={inputId} className="field-label">
          {label}
        </label>
      )}
      <input
        ref={inputRef}
        id={inputId}
        className="input sm"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-label={hideLabel ? label : undefined}
        aria-activedescendant={open && options[hi] ? `${listId}-${hi}` : undefined}
        value={text}
        placeholder={placeholder}
        disabled={disabled}
        autoFocus={autoFocus}
        data-testid={testId}
        title={value ? `${value.part_number} ${value.description}` : undefined}
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
          } else if (e.key === "Escape") {
            if (open) {
              e.stopPropagation();
              setOpen(false);
              setText(value?.part_number ?? "");
            }
          } else if (e.key === "Tab") {
            setOpen(false);
            setText(value?.part_number ?? "");
          }
        }}
      />
      {open ? (
        <ul
          className="mfg-picker-list"
          role="listbox"
          id={listId}
          aria-label={`${label} options`}
          style={rect ? { top: rect.top, left: rect.left, width: rect.width } : undefined}
        >
          {loading && options.length === 0 ? <li className="mfg-picker-empty">Searching…</li> : null}
          {!loading && options.length === 0 ? <li className="mfg-picker-empty">No matching items</li> : null}
          {options.map((it, i) => (
            <li
              key={it.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === hi}
              className={i === hi ? "hi" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(it);
              }}
              onMouseEnter={() => setHi(i)}
            >
              <span className="mono">{it.part_number}</span>
              <span className="muted small mfg-ellipsis">{it.description}</span>
              <span className="faint small">{it.uom}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

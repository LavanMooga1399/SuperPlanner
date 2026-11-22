/** Header "Display" menu: theme (system / light / dark) and density (compact / comfortable). */
import { useEffect, useRef, useState } from "react";
import { Icon } from "../Icon";
import { setDensity, setTheme, usePrefs, type Density, type ThemePref } from "../../lib/prefs";
import { t } from "../../lib/i18n";

const THEMES: { v: ThemePref; label: string }[] = [
  { v: "system", label: "Match system" },
  { v: "light", label: "Light" },
  { v: "dark", label: "Dark" },
];
const DENSITIES: { v: Density; label: string; hint: string }[] = [
  { v: "compact", label: "Compact", hint: "More rows on screen" },
  { v: "comfortable", label: "Comfortable", hint: "Larger rows and controls" },
];

export function DisplayMenu() {
  const prefs = usePrefs();
  const [open, setOpen] = useState(false);
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
  return (
    <div className="popover-anchor" ref={ref}>
      <button
        ref={btn}
        type="button"
        className="btn ghost icon"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t("studio.displayMenu.aria.displaySettings")}
        title="Display settings"
        onClick={() => setOpen((v) => !v)}
        data-testid="display-menu"
      >
        <Icon name="eye" />
      </button>
      {open ? (
        <div className="popover" role="dialog" aria-label={t("studio.displayMenu.aria.displaySettings")}>
          <fieldset className="popover-group">
            <legend>{t("studio.displayMenu.head.theme")}</legend>
            {THEMES.map((t) => (
              <label key={t.v} className="popover-option">
                <input type="radio" name="sp-theme" checked={prefs.theme === t.v} onChange={() => setTheme(t.v)} />
                {t.label}
              </label>
            ))}
          </fieldset>
          <fieldset className="popover-group">
            <legend>{t("studio.displayMenu.head.density")}</legend>
            {DENSITIES.map((d) => (
              <label key={d.v} className="popover-option">
                <input type="radio" name="sp-density" checked={prefs.density === d.v} onChange={() => setDensity(d.v)} data-testid={`density-${d.v}`} />
                <span>
                  {d.label} <span className="faint small">{d.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>
        </div>
      ) : null}
    </div>
  );
}

/** One-click light/dark switch (kept for muscle memory and the existing `theme-toggle` test id). */
export function ThemeToggle() {
  const { resolved } = usePrefs();
  const next = resolved === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="btn ghost icon"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      data-testid="theme-toggle"
    >
      <Icon name={resolved === "dark" ? "sun" : "moon"} />
    </button>
  );
}

/** Global keyboard shortcuts and their help dialog (`?`). */
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import { Dialog } from "../Dialog";
import { GO_KEYS, MOD, closeShortcuts, isTyping, openShortcuts, togglePalette, useCommandState } from "./commands";
import { t } from "../../lib/i18n";

export function GlobalShortcuts() {
  const navigate = useNavigate();
  const pendingG = useRef<number | null>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        togglePalette();
        return;
      }
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || isTyping(e)) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      if (pendingG.current !== null) {
        const hit = GO_KEYS.find((g) => g.key === e.key.toLowerCase());
        window.clearTimeout(pendingG.current);
        pendingG.current = null;
        if (hit) {
          e.preventDefault();
          navigate(hit.to);
        }
        return;
      }
      if (e.key === "?") {
        e.preventDefault();
        openShortcuts();
      } else if (e.key === "/") {
        const search = document.querySelector<HTMLInputElement>('#main input[type="search"], #main [role="search"] input');
        e.preventDefault();
        if (search) search.focus();
        else togglePalette();
      } else if (e.key === "g") {
        pendingG.current = window.setTimeout(() => (pendingG.current = null), 1200);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate]);
  return null;
}

const GENERAL: [string[], string][] = [
  [[MOD, "K"], t("shell.shortcuts.str.searchPagesActionsAndRecords")],
  [["/"], t("shell.shortcuts.str.focusTheSearchBoxOf")],
  [["?"], t("shell.shortcuts.str.showThisHelp")],
  [[t("shell.shortcuts.str.esc")], t("shell.shortcuts.str.closeADialogDrawerOr")],
];
const TABLES: [string[], string][] = [
  [["↑", "↓"], t("shell.shortcuts.str.moveBetweenRows")],
  [["PgUp", "PgDn"], t("shell.shortcuts.str.moveAPageOfRows")],
  [["Home", "End"], t("shell.shortcuts.str.firstOrLastRow")],
  [["Enter"], t("shell.shortcuts.str.openTheFocusedRow")],
  [["←", "→"], t("shell.shortcuts.str.collapseOrExpandTreesScroll")],
  [["[", "]"], t("shell.shortcuts.str.previousOrNextOperationGantt")],
  [["+", "−"], t("shell.shortcuts.str.zoomInOrOutGantt")],
  [["Alt", "←", "→"], t("shell.shortcuts.str.moveTheSelectedOperationBy")],
  [["Shift", "Alt", "↑", "↓"], t("shell.shortcuts.str.moveItToThePrevious")],
];

function Keys({ keys }: { keys: string[] }) {
  return (
    <span className="row" style={{ gap: 4 }}>
      {keys.map((k) => (
        <kbd key={k}>{k}</kbd>
      ))}
    </span>
  );
}

export function ShortcutsDialog() {
  const { shortcuts } = useCommandState();
  if (!shortcuts) return null;
  return (
    <Dialog title={t("studio.shortcuts.title.keyboardShortcuts")} onClose={closeShortcuts} wide>
      <div className="shortcut-cols">
        <section>
          <h3>{t("studio.shortcuts.head.general")}</h3>
          <dl className="shortcut-list">
            {GENERAL.map(([k, d]) => (
              <div key={d}>
                <dt><Keys keys={k} /></dt>
                <dd>{d}</dd>
              </div>
            ))}
          </dl>
          <h3 className="mt">{t("studio.shortcuts.head.tablesAndGantt")}</h3>
          <dl className="shortcut-list">
            {TABLES.map(([k, d]) => (
              <div key={d}>
                <dt><Keys keys={k} /></dt>
                <dd>{d}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section>
          <h3>{t("studio.shortcuts.head.goToPressGThen")}</h3>
          <dl className="shortcut-list">
            {GO_KEYS.map((g) => (
              <div key={g.key}>
                <dt><Keys keys={["G", g.key.toUpperCase()]} /></dt>
                <dd>{g.label}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </Dialog>
  );
}

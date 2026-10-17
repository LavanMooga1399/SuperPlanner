import { useId, useState, type ReactNode } from "react";
import { GLOSSARY, type GlossaryKey } from "../lib/glossary";
import { Icon } from "./Icon";

/**
 * A term with a plain-language explanation on hover and on keyboard focus (PHASE2.md 3.6).
 * The visible text stays as it is; a small info button next to it carries `aria-describedby` to the tooltip.
 * The tooltip is rendered only while shown, so it does not change the text of the surrounding element.
 * `bare` shows only the info button (to follow a sentence or a heading-like label).
 * Do not place inside a `<label>` (the button would become part of the field's name).
 */
export function Term({ k, children, bare = false }: { k: GlossaryKey; children?: ReactNode; bare?: boolean }) {
  const entry = GLOSSARY[k];
  const id = useId();
  const tipId = `term-tip-${id}`;
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const open = (hover || focus) && !dismissed;
  return (
    <span
      className="term"
      onMouseEnter={() => (setHover(true), setDismissed(false))}
      onMouseLeave={() => setHover(false)}
      data-testid={`term-${k}`}
    >
      {bare ? null : children ?? entry.term}
      <button
        type="button"
        className="term-btn"
        aria-label={`What is "${entry.term}"?`}
        aria-describedby={open ? tipId : undefined}
        aria-expanded={open}
        onFocus={() => (setFocus(true), setDismissed(false))}
        onBlur={() => setFocus(false)}
        onClick={() => setDismissed(open)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.stopPropagation();
            setDismissed(true);
          }
        }}
      >
        <Icon name="help" size={13} />
      </button>
      {open ? (
        <span role="tooltip" id={tipId} className="term-tip">
          <strong>{entry.term}.</strong> {entry.text}
        </span>
      ) : null}
    </span>
  );
}

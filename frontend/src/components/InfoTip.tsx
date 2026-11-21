/** Small "i" button with a tooltip on hover or keyboard focus (for secondary guidance that should not take space). */
import { useId, type ReactNode } from "react";
import { Icon } from "./Icon";

export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <span className="info-tip">
      <button type="button" className="btn ghost sm icon" aria-label={label} aria-describedby={id}>
        <Icon name="info" size={14} />
      </button>
      <span role="tooltip" id={id} className="info-tip-body">
        {children}
      </span>
    </span>
  );
}

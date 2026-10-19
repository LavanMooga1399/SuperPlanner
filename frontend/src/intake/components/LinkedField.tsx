import type { CSSProperties, ReactNode } from "react";
import { Icon } from "../../components/Icon";
import { useIntake } from "../state/IntakeContext";
import { ConfidenceBadge } from "./ConfidenceBadge";

/**
 * Wraps one draft field: test id `intake-field-<path>`, the confidence badge, the inline error and the
 * two-way highlight with the source text (hover or focus here highlights the matching `mark`).
 */
export function LinkedField({
  path,
  children,
  error,
  errorId,
  className = "",
  style,
  badge = true,
}: {
  path: string;
  children: ReactNode;
  error?: string | null;
  errorId?: string;
  className?: string;
  style?: CSSProperties;
  badge?: boolean;
}) {
  const { state, activePath, setActivePath } = useIntake();
  const prov = state.response?.draft.provenance[path];
  const active = activePath === path;
  return (
    <div
      className={`linked-field${active ? " active" : ""}${className ? ` ${className}` : ""}`}
      style={style}
      data-testid={`intake-field-${path}`}
      data-intake-path={path}
      onMouseEnter={() => setActivePath(path)}
      onMouseLeave={() => activePath === path && setActivePath(null)}
      onFocus={() => setActivePath(path)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null) && activePath === path) setActivePath(null);
      }}
    >
      <div className="linked-field-row">
        {children}
        {badge ? <ConfidenceBadge path={path} provenance={prov} /> : null}
      </div>
      {error ? (
        <span className="field-error" id={errorId} role="alert">
          <Icon name="alert" size={12} /> {error}
        </span>
      ) : null}
    </div>
  );
}

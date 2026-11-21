/** Page header (UX-STANDARD 3): title, optional status/meta, one-line description or key facts, actions right. */
import type { ReactNode } from "react";

export function PageHeader({
  title,
  meta,
  description,
  facts,
  actions,
  testId,
}: {
  title: ReactNode;
  /** Badges next to the title (status, version). */
  meta?: ReactNode;
  description?: ReactNode;
  /** Key facts under the title: [label, value] pairs. */
  facts?: [string, ReactNode][];
  actions?: ReactNode;
  testId?: string;
}) {
  return (
    <div className="page-header mfg-header" data-testid={testId}>
      <div>
        <div className="row wrap" style={{ gap: 8 }}>
          <h1>{title}</h1>
          {meta}
        </div>
        {description ? <p>{description}</p> : null}
        {facts?.length ? (
          <div className="page-facts">
            {facts.map(([k, v]) => (
              <span key={k}>
                {k} <b>{v}</b>
              </span>
            ))}
          </div>
        ) : null}
      </div>
      {actions ? <div className="row page-actions">{actions}</div> : null}
    </div>
  );
}

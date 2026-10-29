/**
 * MRP exception messages (M2 14.2 `ExceptionList`, 8.12): severity icon + text, plain-language message, what to
 * do, and the server-built link to the object to act on (never derived in the UI, 14.3).
 */
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import type { MrpExceptionRow } from "../api/typesM2";
import { fmtDate } from "../lib/format";
import { fmtNum } from "../lib/formatM2";
import { exceptionLabel } from "../lib/mrpText";
import { MrpSeverityBadge, mrpSeverityIcon } from "./StatusM2";

export function ExceptionDetail({ ex, compact }: { ex: MrpExceptionRow; compact?: boolean }) {
  return (
    <div className="issue" data-testid="exception-row" data-code={ex.code} data-severity={ex.severity} data-subject={ex.subject.label}>
      <span className="issue-icon" aria-hidden>
        <Icon name={mrpSeverityIcon(ex.severity)} />
      </span>
      <div className="grow col" style={{ gap: 2, minWidth: 0 }}>
        <div className="row wrap" style={{ gap: 6 }}>
          <MrpSeverityBadge severity={ex.severity} />
          <strong>{exceptionLabel(ex.code)}</strong>
          <span className="mono small">{ex.subject.label}</span>
          {!compact ? <code className="faint small">{ex.code}</code> : null}
        </div>
        <div>{ex.message}</div>
        {ex.action ? (
          <div className="muted small">
            <strong>What to do:</strong> {ex.action}
            {ex.suggested?.date ? ` Suggested date ${fmtDate(ex.suggested.date)}.` : ""}
            {ex.suggested?.qty !== undefined ? ` Suggested quantity ${fmtNum(ex.suggested.qty)}.` : ""}
          </div>
        ) : null}
        {!compact && ex.related.length ? <div className="faint small">Related: {ex.related.map((r) => r.label).join(", ")}</div> : null}
      </div>
      {ex.link ? (
        <Link className="btn sm" to={ex.link} data-testid="exception-link">
          Open <Icon name="arrow-right" />
        </Link>
      ) : null}
    </div>
  );
}

export function ExceptionList({ items, compact, testId = "exception-list" }: { items: MrpExceptionRow[]; compact?: boolean; testId?: string }) {
  if (!items.length) return null;
  return (
    <ul className="mfg-plain-list" data-testid={testId}>
      {items.map((ex) => (
        <li key={ex.id}>
          <ExceptionDetail ex={ex} compact={compact} />
        </li>
      ))}
    </ul>
  );
}

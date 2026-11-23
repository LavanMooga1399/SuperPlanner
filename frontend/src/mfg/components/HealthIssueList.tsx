/**
 * Health issues grouped by code (M 11.2) with severity icon + text and a "Fix" link. The link is always the
 * server's `issue.link` (M 7.1, 11.3); the UI never builds a route for a health entity itself.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import type { HealthIssue } from "../api/types";
import { SeverityBadge } from "./StatusChip";
import { t } from "../../lib/i18n";

const GROUP_PREVIEW = 50;

export function HealthIssueList({ issues }: { issues: HealthIssue[] }) {
  const groups = useMemo(() => {
    const m = new Map<string, HealthIssue[]>();
    for (const i of issues) m.set(i.code, [...(m.get(i.code) ?? []), i]);
    return [...m.entries()];
  }, [issues]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (issues.length === 0) return null;
  return (
    <div className="col" data-testid="health-issue-list">
      {groups.map(([code, list]) => {
        const all = expanded.has(code);
        const shown = all ? list : list.slice(0, GROUP_PREVIEW);
        return (
          <section key={code} className="card" aria-labelledby={`hc-${code}`} data-testid="health-code-group" data-code={code}>
            <div className="card-header">
              <h3 id={`hc-${code}`} className="row">
                <SeverityBadge severity={list[0].severity} />
                <code>{code}</code>
                <span className="muted small">{list.length === 1 ? "1 issue" : `${list.length} issues`}</span>
              </h3>
            </div>
            <ul className="mfg-plain-list">
              {shown.map((i, n) => (
                <li key={`${i.entity?.id ?? ""}-${n}`} className="issue" data-testid="health-issue" data-code={i.code} data-severity={i.severity} data-entity-type={i.entity?.type} data-entity-id={i.entity?.id ?? undefined}>
                  <span className="issue-icon" aria-hidden>
                    <Icon name={i.severity === "error" ? "x" : i.severity === "warning" ? "alert" : "info"} />
                  </span>
                  <div className="grow col" style={{ gap: 2 }}>
                    <div>{i.message}</div>
                    {i.fix ? (
                      <div className="muted small">
                        <strong>{t("mfg.healthIssueList.text.howToFix")}</strong> {i.fix}
                      </div>
                    ) : null}
                    <div className="faint small">
                      {String(i.entity?.type ?? "record").replace(/_/g, " ")}: <span className="mono">{i.entity?.label ?? ""}</span>
                      {i.related?.length ? t("mfg.healthIssueList.tpl.related", { join: i.related.map((r) => r.label).join(", ") }) : ""}
                      {i.field ? t("mfg.healthIssueList.tpl.field", { field: i.field }) : ""}
                    </div>
                  </div>
                  {i.link ? (
                    <Link className="btn sm" to={i.link} data-testid="health-fix-link">
                      {t("mfg.healthIssueList.text.fix")}{" "}<Icon name="arrow-right" />
                    </Link>
                  ) : null}
                </li>
              ))}
            </ul>
            {list.length > GROUP_PREVIEW ? (
              <div className="card-footer">
                <button
                  type="button"
                  className="btn sm ghost"
                  onClick={() =>
                    setExpanded((s) => {
                      const nx = new Set(s);
                      if (nx.has(code)) nx.delete(code);
                      else nx.add(code);
                      return nx;
                    })
                  }
                >
                  {all ? t("mfg.healthIssueList.str.showFewer") : t("mfg.healthIssueList.tpl.showAll", { length: list.length })}
                </button>
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}

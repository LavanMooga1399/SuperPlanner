import { Link } from "react-router-dom";
import type { Issue, Problem } from "../api/types";
import type { Terms } from "../lib/terms";
import { Icon } from "./Icon";

function issueLink(issue: Issue): { to: string; label: string } | null {
  if (issue.task_ids.length && (issue.field?.startsWith("dependencies") || issue.code.includes("DEPENDENCY"))) {
    return { to: "../dependencies", label: "Open dependencies" };
  }
  if (issue.task_ids.length) return { to: `../tasks?focus=${encodeURIComponent(issue.task_ids[0])}`, label: "Go to row" };
  if (issue.resource_ids.length) return { to: `../resources?focus=${encodeURIComponent(issue.resource_ids[0])}`, label: "Go to row" };
  if (issue.field?.startsWith("dependencies")) return { to: "../dependencies", label: "Open dependencies" };
  if (issue.field?.startsWith("tasks")) return { to: "../tasks", label: "Open list" };
  if (issue.field?.startsWith("resources")) return { to: "../resources", label: "Open list" };
  return null;
}

export function IssueList({ issues, draft, terms }: { issues: Issue[]; draft: Problem; terms: Terms }) {
  const taskNames = new Map(draft.tasks.map((t) => [t.id, t.name]));
  const resNames = new Map(draft.resources.map((r) => [r.id, r.name]));
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");
  const group = (title: string, list: Issue[], kind: "error" | "warning") =>
    list.length ? (
      <section aria-label={title}>
        <div className="card-header" style={{ borderTop: kind === "warning" && errors.length ? "1px solid var(--border)" : undefined }}>
          <h3 className="row">
            <Icon name={kind === "error" ? "x" : "alert"} style={{ color: kind === "error" ? "var(--danger)" : "var(--warn)" }} />
            {title} ({list.length})
          </h3>
          <span className="small muted">{kind === "error" ? "Must be fixed before optimizing" : "Worth a look, does not block"}</span>
        </div>
        {list.map((iss, i) => {
          const link = issueLink(iss);
          const related = [
            ...iss.task_ids.map((id) => taskNames.get(id) ?? id),
            ...iss.resource_ids.map((id) => resNames.get(id) ?? id),
          ];
          return (
            <div className="issue" key={`${iss.code}-${i}`} data-testid={`issue-${iss.code}`} data-severity={iss.severity}>
              <span className="issue-icon">
                <span className={`badge ${kind === "error" ? "danger" : "warn"}`}>
                  <Icon name={kind === "error" ? "x" : "alert"} />
                  {kind === "error" ? "Error" : "Warning"}
                </span>
              </span>
              <div className="grow">
                <div>{iss.message}</div>
                <div className="small faint row wrap" style={{ gap: 8 }}>
                  <code>{iss.code}</code>
                  {related.length ? <span>{related.slice(0, 6).join(", ")}{related.length > 6 ? "…" : ""}</span> : null}
                </div>
              </div>
              {link ? (
                <Link className="btn sm" to={link.to}>
                  {link.label} <Icon name="arrow-right" />
                </Link>
              ) : null}
            </div>
          );
        })}
      </section>
    ) : null;
  return (
    <div className="card" data-testid="issue-list">
      {issues.length === 0 ? (
        <div className="empty">
          <Icon name="check" size={28} style={{ color: "var(--ok)" }} />
          <strong>No problems found</strong>
          <span>The plan is ready to optimize. All {terms.tasksL}, {terms.resourcesL} and dependencies fit together.</span>
        </div>
      ) : (
        <>
          {group("Errors", errors, "error")}
          {group("Warnings", warnings, "warning")}
        </>
      )}
    </div>
  );
}

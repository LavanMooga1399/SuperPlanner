import { useState } from "react";
import { Link } from "react-router";
import { deleteProblem, downloadJson, errorMessage, exportProblem } from "../api/client";
import type { ProblemSummary } from "../api/types";
import { fmtRelative } from "../lib/time";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

const DOMAIN_LABEL: Record<string, string> = {
  manufacturing: "Manufacturing",
  exam_prep: "Exam preparation",
  project: "Project",
  generic: "General",
};

export function PlanList({ items, onChanged }: { items: ProblemSummary[]; onChanged(): void }) {
  const [toDelete, setToDelete] = useState<ProblemSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doExport = async (p: ProblemSummary) => {
    setError(null);
    try {
      const file = await exportProblem(p.id);
      const slug = p.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || p.id;
      downloadJson(file, `${slug}.superplanner.json`);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const doDelete = async () => {
    if (!toDelete) return;
    setBusy(true);
    setError(null);
    try {
      await deleteProblem(toDelete.id);
      setToDelete(null);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
      setToDelete(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" data-testid="plan-list">
      {error ? (
        <div className="banner danger" role="alert" style={{ margin: 12 }}>
          <Icon name="alert" />
          <div className="banner-body">{error}</div>
        </div>
      ) : null}
      {items.length === 0 ? (
        <div className="empty">
          <Icon name="calendar" size={32} />
          <strong>No plans yet</strong>
          <span>Create one from a template below, or import a JSON file.</span>
        </div>
      ) : (
        items.map((p) => (
          <div className="plan-item" key={p.id} data-testid={`plan-item-${p.id}`}>
            <div className="grow">
              <Link to={`/plans/${p.id}/tasks`} className="plan-name">
                {p.name}
              </Link>
              <div className="small muted row wrap" style={{ gap: 10, marginTop: 2 }}>
                <span>{DOMAIN_LABEL[p.domain] ?? p.domain}</span>
                <span>·</span>
                <span>
                  {p.task_count} tasks, {p.resource_count} resources
                </span>
                <span>·</span>
                <span>version {p.version}</span>
                <span>·</span>
                <span>updated {fmtRelative(p.updated_at)}</span>
              </div>
            </div>
            <div className="row wrap hide-sm">
              {p.approved_schedule_id ? <StatusBadge kind="approved" label="Has approved schedule" /> : null}
              {p.latest_run ? <StatusBadge kind={p.latest_run.status} label={`Last run: ${p.latest_run.status}`} /> : null}
            </div>
            <div className="row">
              <button className="btn ghost sm icon" onClick={() => doExport(p)} aria-label={`Export ${p.name}`} title="Export JSON">
                <Icon name="download" />
              </button>
              <button className="btn ghost sm icon" onClick={() => setToDelete(p)} aria-label={`Delete ${p.name}`} title="Delete">
                <Icon name="trash" />
              </button>
            </div>
          </div>
        ))
      )}
      {toDelete ? (
        <ConfirmDialog
          title="Delete plan?"
          confirmLabel="Delete plan"
          danger
          busy={busy}
          onConfirm={doDelete}
          onCancel={() => setToDelete(null)}
        >
          <p style={{ margin: 0 }}>
            “{toDelete.name}” and all its runs and schedules will be removed permanently.
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

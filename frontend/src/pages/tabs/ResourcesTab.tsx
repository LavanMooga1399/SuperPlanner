import { useState } from "react";
import { useSearchParams } from "react-router";
import type { Resource } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { ResourceTable } from "../../components/ResourceTable";
import { makeResource, removeResource } from "../../lib/planEdit";
import { useTerms } from "../../lib/terms";
import { useLoadedPlan } from "../../state/PlanContext";

export function ResourcesTab() {
  const { draft, update } = useLoadedPlan();
  const terms = useTerms();
  const [params] = useSearchParams();
  const [toDelete, setToDelete] = useState<Resource | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const add = () =>
    update((p) => {
      const r = makeResource(p, terms.newResource);
      setCreated(r.id);
      return { ...p, resources: [...p.resources, r] };
    });

  const refs = toDelete ? draft.tasks.filter((t) => t.requirements.some((r) => r.alternatives.includes(toDelete.id))).length : 0;

  return (
    <div>
      <div className="toolbar">
        <span className="small muted">{terms.countResources(draft.resources.length)}</span>
        <div className="grow" />
        <button className="btn primary" onClick={add}>
          <Icon name="plus" /> Add {terms.resourceL}
        </button>
      </div>
      {draft.resources.length === 0 ? (
        <div className="card empty">
          <Icon name="layers" size={32} />
          <strong>No {terms.resourcesL} yet</strong>
          <span>{terms.resources} are what {terms.tasksL} need: people, machines, rooms or time slots, each with a capacity and opening hours.</span>
          <button className="btn primary" onClick={add}>
            <Icon name="plus" /> Add {terms.resourceL}
          </button>
        </div>
      ) : (
        <ResourceTable draft={draft} terms={terms} update={update} onDelete={setToDelete} focusId={params.get("focus") ?? created} />
      )}
      {toDelete ? (
        <ConfirmDialog
          title={`Delete ${terms.resourceL}?`}
          confirmLabel="Delete"
          danger
          onCancel={() => setToDelete(null)}
          onConfirm={() => {
            update((p) => removeResource(p, toDelete.id));
            setToDelete(null);
          }}
        >
          <p style={{ margin: 0 }}>
            “{toDelete.name}” will be removed.
            {refs ? ` It is an option for ${terms.countTasks(refs)}; it will be removed from their requirements.` : ""}
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

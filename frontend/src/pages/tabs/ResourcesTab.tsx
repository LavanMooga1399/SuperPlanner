import { useState } from "react";
import { useSearchParams } from "react-router";
import type { Resource } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { Term } from "../../components/Term";
import { ResourceTable } from "../../components/ResourceTable";
import { makeResource, removeResource } from "../../lib/planEdit";
import { useTerms } from "../../lib/terms";
import { useLoadedPlan } from "../../state/PlanContext";
import { t, t as tr } from "../../lib/i18n";

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
        <Term k="resource" bare />
        <div className="grow" />
        <button className="btn primary" onClick={add}>
          <Icon name="plus" />{" "}{tr("studio.resourcesTab.text.add", { resourceL: terms.resourceL })}
        </button>
      </div>
      {draft.resources.length === 0 ? (
        <div className="card empty">
          <Icon name="layers" size={32} />
          <strong>{tr("studio.resourcesTab.text.noYet", { resourcesL: terms.resourcesL })}</strong>
          <span>{tr("studio.resourcesTab.text.areWhatNeedPeopleMachines", { resources: terms.resources, tasksL: terms.tasksL })}</span>
          <button className="btn primary" onClick={add}>
            <Icon name="plus" />{" "}{tr("studio.resourcesTab.text.add", { resourceL: terms.resourceL })}
          </button>
        </div>
      ) : (
        <ResourceTable draft={draft} terms={terms} update={update} onDelete={setToDelete} focusId={params.get("focus") ?? created} />
      )}
      {toDelete ? (
        <ConfirmDialog
          title={tr("studio.resourcesTab.tpl.delete", { resourceL: terms.resourceL })}
          confirmLabel={t("studio.resourcesTab.btn.delete")}
          danger
          onCancel={() => setToDelete(null)}
          onConfirm={() => {
            update((p) => removeResource(p, toDelete.id));
            setToDelete(null);
          }}
        >
          <p style={{ margin: 0 }}>
            {tr("studio.resourcesTab.text.willBeRemoved", { name: toDelete.name, v: refs ? tr("studio.resourcesTab.tpl.itIsAnOptionFor", { refs: terms.countTasks(refs) }) : "" })}
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

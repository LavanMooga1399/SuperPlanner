import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import type { Task } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { TaskTable } from "../../components/TaskTable";
import { makeTask, removeTask } from "../../lib/planEdit";
import { useTerms } from "../../lib/terms";
import { fmtDuration } from "../../lib/time";
import { useLoadedPlan } from "../../state/PlanContext";
import { t, t as tr } from "../../lib/i18n";

export function TasksTab() {
  const { draft, update } = useLoadedPlan();
  const terms = useTerms();
  const [params] = useSearchParams();
  const focus = params.get("focus");
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("");
  const [toDelete, setToDelete] = useState<Task | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const groups = useMemo(
    () => Array.from(new Set(draft.tasks.map((t) => t.group).filter((g): g is string => !!g))).sort(),
    [draft.tasks],
  );
  const q = query.trim().toLowerCase();
  const visible = draft.tasks.filter(
    (t) =>
      (!group || (group === "__none" ? !t.group : t.group === group)) &&
      (!q || t.name.toLowerCase().includes(q) || t.id.toLowerCase().includes(q)),
  );
  const totalWork = draft.tasks.reduce((s, t) => s + t.duration_minutes, 0);

  const add = () => {
    update((p) => {
      const t = makeTask(p, terms.newTask, group && group !== "__none" ? group : null);
      setCreated(t.id);
      return { ...p, tasks: [...p.tasks, t] };
    });
  };

  const deps = toDelete ? draft.dependencies.filter((d) => d.predecessor === toDelete.id || d.successor === toDelete.id).length : 0;

  return (
    <div>
      <div className="toolbar">
        <div className="field" style={{ width: 240 }}>
          <label htmlFor="task-search" className="sr-only">
            {tr("studio.tasksTab.text.search", { tasksL: terms.tasksL })}
          </label>
          <input id="task-search" className="input" placeholder={tr("studio.tasksTab.tpl.search", { tasksL: terms.tasksL })} value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {groups.length ? (
          <div className="field" style={{ width: 180 }}>
            <label htmlFor="task-group" className="sr-only">
              {tr("studio.tasksTab.text.filterBy", { groupL: terms.groupL })}
            </label>
            <select id="task-group" className="select" value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="">{tr("studio.tasksTab.text.allS", { group: terms.group.toLowerCase() })}</option>
              {groups.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
              <option value="__none">{tr("studio.tasksTab.text.no", { groupL: terms.groupL })}</option>
            </select>
          </div>
        ) : null}
        <span className="small muted">
          {tr("studio.tasksTab.text.ofWork", { length: terms.countTasks(draft.tasks.length), totalWork: fmtDuration(totalWork) })}
        </span>
        <div className="grow" />
        <button className="btn primary" onClick={add}>
          <Icon name="plus" />{" "}{tr("studio.tasksTab.text.add", { taskL: terms.taskL })}
        </button>
      </div>
      {draft.tasks.length === 0 ? (
        <div className="card empty">
          <Icon name="list" size={32} />
          <strong>{tr("studio.tasksTab.text.noYet", { tasksL: terms.tasksL })}</strong>
          <span>{tr("studio.tasksTab.text.addTheThatNeedTo", { tasksL: terms.tasksL })}</span>
          <button className="btn primary" onClick={add}>
            <Icon name="plus" />{" "}{tr("studio.tasksTab.text.add", { taskL: terms.taskL })}
          </button>
        </div>
      ) : (
        <TaskTable
          draft={draft}
          tasks={visible}
          terms={terms}
          update={update}
          onDelete={(t) => setToDelete(t)}
          focusId={focus ?? created}
          expandedInit={focus}
        />
      )}
      {toDelete ? (
        <ConfirmDialog
          title={tr("studio.tasksTab.tpl.delete", { taskL: terms.taskL })}
          confirmLabel={t("studio.tasksTab.btn.delete")}
          danger
          onCancel={() => setToDelete(null)}
          onConfirm={() => {
            update((p) => removeTask(p, toDelete.id));
            setToDelete(null);
          }}
        >
          <p style={{ margin: 0 }}>
            {tr("studio.tasksTab.text.willBeRemoved", { name: toDelete.name, v: deps ? tr("studio.tasksTab.tpl.togetherWithDependenc", { deps: deps, v: deps === 1 ? "y" : "ies" }) : "" })}
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

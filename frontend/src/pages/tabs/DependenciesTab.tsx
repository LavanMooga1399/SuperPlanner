import { useMemo, useState } from "react";
import { Link } from "react-router";
import type { DependencyType } from "../../api/types";
import { Banner } from "../../components/Banner";
import { DependencyGraph } from "../../components/DependencyGraph";
import { Icon } from "../../components/Icon";
import { Term } from "../../components/Term";
import { NumberInput } from "../../components/Inputs";
import { DEP_TYPE_HELP, DEP_TYPE_LABEL } from "../../components/TaskTable";
import { cycleEdges, edgeKey, quickCriticalPath } from "../../lib/graphLayout";
import { removeDependency, setDependency } from "../../lib/planEdit";
import { useTerms } from "../../lib/terms";
import { fmtDuration } from "../../lib/time";
import { useStoredState } from "../../lib/useAsync";
import { useLoadedPlan } from "../../state/PlanContext";

export function DependenciesTab() {
  const { draft, update } = useLoadedPlan();
  const terms = useTerms();
  const [view, setView] = useStoredState<"graph" | "list">("sp.deps.view", "graph");
  const [showCritical, setShowCritical] = useStoredState("sp.deps.critical", true);
  const [selected, setSelected] = useState<string | null>(null);
  const [pred, setPred] = useState("");
  const [succ, setSucc] = useState("");
  const [type, setType] = useState<DependencyType>("FS");
  const [lag, setLag] = useState(0);

  const names = useMemo(() => new Map(draft.tasks.map((t) => [t.id, t.name])), [draft.tasks]);
  const cpm = useMemo(
    () =>
      quickCriticalPath(
        draft.tasks.map((t) => ({ id: t.id, duration: t.duration_minutes })),
        draft.dependencies,
      ),
    [draft.tasks, draft.dependencies],
  );
  const cyc = useMemo(
    () => cycleEdges(draft.tasks.map((t) => t.id), draft.dependencies.map((d) => ({ from: d.predecessor, to: d.successor }))),
    [draft.tasks, draft.dependencies],
  );
  const dangling = draft.dependencies.filter((d) => !names.has(d.predecessor) || !names.has(d.successor));
  const exists = draft.dependencies.some((d) => d.predecessor === pred && d.successor === succ);
  const canAdd = !!pred && !!succ && !exists;

  const add = () => {
    if (!canAdd) return;
    update((p) => setDependency(p, { predecessor: pred, successor: succ, type, lag_minutes: lag }));
    setSucc("");
  };

  const sel = selected ? draft.tasks.find((t) => t.id === selected) : null;

  return (
    <div className="col gap-lg">
      <div className="card card-body">
        <h3 className="mb">Add a dependency</h3>
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ width: 220 }}>
            <label htmlFor="dep-succ">{terms.task}</label>
            <select id="dep-succ" className="select" value={succ} onChange={(e) => setSucc(e.target.value)}>
              <option value="">Choose…</option>
              {draft.tasks.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.id})</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 230 }}>
            <label htmlFor="dep-type">Rule</label>
            <select id="dep-type" className="select" value={type} onChange={(e) => setType(e.target.value as DependencyType)}>
              {(Object.keys(DEP_TYPE_LABEL) as DependencyType[]).map((t) => (
                <option key={t} value={t}>{DEP_TYPE_HELP[t]}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 220 }}>
            <label htmlFor="dep-pred">Other {terms.taskL}</label>
            <select id="dep-pred" className="select" value={pred} onChange={(e) => setPred(e.target.value)}>
              <option value="">Choose…</option>
              {draft.tasks.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.id})</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="dep-lag">Lag (min)</label>
            <NumberInput id="dep-lag" className="input" value={lag} width={90} label="Lag in minutes" onChange={setLag} />
          </div>
          <button className="btn primary" onClick={add} disabled={!canAdd} data-testid="add-dependency">
            <Icon name="plus" /> Add dependency
          </button>
        </div>
        {exists ? <div className="small mt" style={{ color: "var(--warn)" }}>This dependency already exists; edit it below.</div> : null}
        {pred && pred === succ ? <div className="small mt" style={{ color: "var(--warn)" }}>A {terms.taskL} that waits for itself can never start; Validate will report it.</div> : null}
      </div>

      {cyc.size ? (
        <Banner tone="danger" role="alert" title="These dependencies form a loop.">
          {terms.tasks} on a loop wait for each other and can never start. Remove at least one of the red dashed dependencies.
        </Banner>
      ) : null}
      {dangling.length ? (
        <Banner tone="warn" title={`${dangling.length} dependenc${dangling.length === 1 ? "y refers" : "ies refer"} to a missing ${terms.taskL}.`} />
      ) : null}

      <div className="toolbar" style={{ marginBottom: 0 }}>
        <div className="btn-group" role="group" aria-label="View">
          <button className="btn sm" aria-pressed={view === "graph"} onClick={() => setView("graph")}><Icon name="graph" /> Graph</button>
          <button className="btn sm" aria-pressed={view === "list"} onClick={() => setView("list")}><Icon name="list" /> List</button>
        </div>
        <label className="switch small">
          <input type="checkbox" checked={showCritical} onChange={(e) => setShowCritical(e.target.checked)} />
          <span>Highlight critical path</span>
        </label>
        <Term k="critical_chain" bare />
        {cpm && showCritical ? (
          <span className="small muted">
            Shortest possible duration: <strong>{fmtDuration(cpm.makespan)}</strong> (ignores {terms.resourcesL} and calendars)
          </span>
        ) : null}
      </div>

      {view === "graph" ? (
        draft.tasks.length === 0 ? (
          <div className="card empty">
            <Icon name="graph" size={32} />
            <strong>Nothing to connect yet</strong>
            <span>Dependencies say which {terms.taskL} waits for which. Add {terms.tasksL} first.</span>
            <Link className="btn primary" to="../tasks">
              <Icon name="plus" /> Add {terms.tasksL}
            </Link>
          </div>
        ) : (
          <div className="split">
            <div className="graph-wrap" data-testid="dependency-graph">
              <DependencyGraph
                tasks={draft.tasks}
                dependencies={draft.dependencies}
                criticalPath={cpm?.path ?? []}
                critical={cpm?.critical ?? new Set()}
                showCritical={showCritical}
                selected={selected}
                onSelect={setSelected}
                milestoneLabel={terms.milestone}
              />
            </div>
            <div className="card card-body col">
              {sel ? (
                <>
                  <h3>{sel.name}</h3>
                  <div className="small muted">{sel.type === "milestone" ? terms.milestone : fmtDuration(sel.duration_minutes)}{sel.group ? ` · ${terms.group} ${sel.group}` : ""}</div>
                  <div className="small"><strong>Waits for:</strong> {draft.dependencies.filter((d) => d.successor === sel.id).map((d) => names.get(d.predecessor) ?? d.predecessor).join(", ") || "nothing"}</div>
                  <div className="small"><strong>Needed by:</strong> {draft.dependencies.filter((d) => d.predecessor === sel.id).map((d) => names.get(d.successor) ?? d.successor).join(", ") || "nothing"}</div>
                  <Link className="btn sm" to={`../tasks?focus=${encodeURIComponent(sel.id)}`} style={{ alignSelf: "flex-start" }}>Edit {terms.taskL} <Icon name="arrow-right" /></Link>
                </>
              ) : (
                <>
                  <h3>Reading the graph</h3>
                  <div className="small muted">Arrows point from a {terms.taskL} to the ones that wait for it. Click a box to see its neighbours.</div>
                  <div className="legend col" style={{ alignItems: "flex-start" }}>
                    <span className="legend-item"><span className="swatch" style={{ background: "var(--accent)" }} /> Critical path: any delay here delays the end</span>
                    <span className="legend-item"><span className="swatch" style={{ background: "var(--danger)" }} /> Loop (dashed): must be fixed</span>
                    <span className="legend-item"><span className="swatch" style={{ background: "var(--border-strong)" }} /> Other dependencies</span>
                  </div>
                  {cpm && cpm.path.length ? (
                    <div className="small">
                      <strong>Critical path:</strong> {cpm.path.map((id) => names.get(id) ?? id).join(" → ")}
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>
        )
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>{terms.task}</th>
                <th>Rule</th>
                <th>Waits for</th>
                <th>Lag (min)</th>
                <th><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {draft.dependencies.length === 0 ? (
                <tr>
                  <td colSpan={5} className="muted" data-testid="deps-empty">
                    No dependencies yet: every {terms.taskL} can start independently. Add one in the &ldquo;After&rdquo; column on the{" "}
                    <Link to="../tasks">{terms.tasks} tab</Link>.
                  </td>
                </tr>
              ) : null}
              {draft.dependencies.map((d) => {
                const k = edgeKey(d.predecessor, d.successor);
                return (
                  <tr key={k} data-testid={`dep-row-${d.predecessor}-${d.successor}`}>
                    <td>{names.get(d.successor) ?? <span style={{ color: "var(--danger)" }}>{d.successor} (missing)</span>}</td>
                    <td>
                      <select className="select sm" style={{ width: 210 }} value={d.type} aria-label={`Rule for ${names.get(d.successor) ?? d.successor}`} onChange={(e) => update((p) => setDependency(p, { ...d, type: e.target.value as DependencyType }))}>
                        {(Object.keys(DEP_TYPE_LABEL) as DependencyType[]).map((t) => <option key={t} value={t}>{DEP_TYPE_HELP[t]}</option>)}
                      </select>
                    </td>
                    <td>
                      {names.get(d.predecessor) ?? <span style={{ color: "var(--danger)" }}>{d.predecessor} (missing)</span>}
                      {cyc.has(k) ? <span className="badge danger" style={{ marginLeft: 6 }}><Icon name="refresh" /> Loop</span> : null}
                    </td>
                    <td>
                      <NumberInput value={d.lag_minutes} width={90} label="Lag in minutes" onChange={(v) => update((p) => setDependency(p, { ...d, lag_minutes: v }))} />
                    </td>
                    <td>
                      <button className="btn ghost sm icon" aria-label={`Remove dependency ${d.predecessor} to ${d.successor}`} onClick={() => update((p) => removeDependency(p, d.predecessor, d.successor))}>
                        <Icon name="trash" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

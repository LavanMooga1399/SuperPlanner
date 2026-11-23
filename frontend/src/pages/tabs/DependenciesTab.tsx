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
import { t, t as tr } from "../../lib/i18n";

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
        <h3 className="mb">{t("studio.dependenciesTab.head.addADependency")}</h3>
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ width: 220 }}>
            <label htmlFor="dep-succ">{terms.task}</label>
            <select id="dep-succ" className="select" value={succ} onChange={(e) => setSucc(e.target.value)}>
              <option value="">{tr("studio.dependenciesTab.text.choose")}</option>
              {draft.tasks.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.id})</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 230 }}>
            <label htmlFor="dep-type">{t("studio.dependenciesTab.label.rule")}</label>
            <select id="dep-type" className="select" value={type} onChange={(e) => setType(e.target.value as DependencyType)}>
              {(Object.keys(DEP_TYPE_LABEL) as DependencyType[]).map((t) => (
                <option key={t} value={t}>{DEP_TYPE_HELP[t]}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 220 }}>
            <label htmlFor="dep-pred">{tr("studio.dependenciesTab.text.other", { taskL: terms.taskL })}</label>
            <select id="dep-pred" className="select" value={pred} onChange={(e) => setPred(e.target.value)}>
              <option value="">{tr("studio.dependenciesTab.text.choose")}</option>
              {draft.tasks.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.id})</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="dep-lag">{t("studio.dependenciesTab.label.lagMin")}</label>
            <NumberInput id="dep-lag" className="input" value={lag} width={90} label={t("studio.dependenciesTab.label.lagInMinutes")} onChange={setLag} />
          </div>
          <button className="btn primary" onClick={add} disabled={!canAdd} data-testid="add-dependency">
            <Icon name="plus" /> {t("studio.dependenciesTab.btn.addDependency")}
          </button>
        </div>
        {exists ? <div className="small mt" style={{ color: "var(--warn)" }}>{tr("studio.dependenciesTab.text.thisDependencyAlreadyExistsEdit")}</div> : null}
        {pred && pred === succ ? <div className="small mt" style={{ color: "var(--warn)" }}>{tr("studio.dependenciesTab.text.aThatWaitsForItself", { taskL: terms.taskL })}</div> : null}
      </div>

      {cyc.size ? (
        <Banner tone="danger" role="alert" title={t("studio.dependenciesTab.title.theseDependenciesFormALoop")}>
          {tr("studio.dependenciesTab.text.onALoopWaitFor", { tasks: terms.tasks })}
        </Banner>
      ) : null}
      {dangling.length ? (
        <Banner tone="warn" title={tr("studio.dependenciesTab.tpl.dependencToAMissing", { length: dangling.length, v: dangling.length === 1 ? "y refers" : "ies refer", taskL: terms.taskL })} />
      ) : null}

      <div className="toolbar" style={{ marginBottom: 0 }}>
        <div className="btn-group" role="group" aria-label={t("studio.dependenciesTab.aria.view")}>
          <button className="btn sm" aria-pressed={view === "graph"} onClick={() => setView("graph")}><Icon name="graph" />{" "}{tr("studio.dependenciesTab.text.graph")}</button>
          <button className="btn sm" aria-pressed={view === "list"} onClick={() => setView("list")}><Icon name="list" />{" "}{tr("studio.dependenciesTab.text.list")}</button>
        </div>
        <label className="switch small">
          <input type="checkbox" checked={showCritical} onChange={(e) => setShowCritical(e.target.checked)} />
          <span>{tr("studio.dependenciesTab.text.highlightCriticalPath")}</span>
        </label>
        <Term k="critical_chain" bare />
        {cpm && showCritical ? (
          <span className="small muted">
            {tr("studio.dependenciesTab.text.shortestPossibleDuration")}{" "}<strong>{fmtDuration(cpm.makespan)}</strong>{" "}{tr("studio.dependenciesTab.text.ignoresAndCalendars", { resourcesL: terms.resourcesL })}
          </span>
        ) : null}
      </div>

      {view === "graph" ? (
        draft.tasks.length === 0 ? (
          <div className="card empty">
            <Icon name="graph" size={32} />
            <strong>{t("studio.dependenciesTab.head.nothingToConnectYet")}</strong>
            <span>{tr("studio.dependenciesTab.text.dependenciesSayWhichWaitsFor", { taskL: terms.taskL, tasksL: terms.tasksL })}</span>
            <Link className="btn primary" to="../tasks">
              <Icon name="plus" />{" "}{tr("studio.dependenciesTab.text.add", { tasksL: terms.tasksL })}
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
                  <div className="small"><strong>{tr("studio.dependenciesTab.text.waitsFor")}</strong> {draft.dependencies.filter((d) => d.successor === sel.id).map((d) => names.get(d.predecessor) ?? d.predecessor).join(", ") || "nothing"}</div>
                  <div className="small"><strong>{tr("studio.dependenciesTab.text.neededBy")}</strong> {draft.dependencies.filter((d) => d.predecessor === sel.id).map((d) => names.get(d.successor) ?? d.successor).join(", ") || "nothing"}</div>
                  <Link className="btn sm" to={`../tasks?focus=${encodeURIComponent(sel.id)}`} style={{ alignSelf: "flex-start" }}>{tr("studio.dependenciesTab.text.edit", { taskL: terms.taskL })}{" "}<Icon name="arrow-right" /></Link>
                </>
              ) : (
                <>
                  <h3>{t("studio.dependenciesTab.head.readingTheGraph")}</h3>
                  <div className="small muted">{tr("studio.dependenciesTab.text.arrowsPointFromATo", { taskL: terms.taskL })}</div>
                  <div className="legend col" style={{ alignItems: "flex-start" }}>
                    <span className="legend-item"><span className="swatch" style={{ background: "var(--accent)" }} />{" "}{tr("studio.dependenciesTab.text.criticalPathAnyDelayHere")}</span>
                    <span className="legend-item"><span className="swatch" style={{ background: "var(--danger)" }} />{" "}{tr("studio.dependenciesTab.text.loopDashedMustBeFixed")}</span>
                    <span className="legend-item"><span className="swatch" style={{ background: "var(--border-strong)" }} />{" "}{tr("studio.dependenciesTab.text.otherDependencies")}</span>
                  </div>
                  {cpm && cpm.path.length ? (
                    <div className="small">
                      <strong>{tr("studio.dependenciesTab.text.criticalPath")}</strong> {cpm.path.map((id) => names.get(id) ?? id).join(" → ")}
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
                <th>{t("studio.dependenciesTab.head.rule")}</th>
                <th>{t("studio.dependenciesTab.head.waitsFor")}</th>
                <th>{t("studio.dependenciesTab.head.lagMin")}</th>
                <th><span className="sr-only">{tr("studio.dependenciesTab.text.actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {draft.dependencies.length === 0 ? (
                <tr>
                  <td colSpan={5} className="muted" data-testid="deps-empty">
                    {tr("studio.dependenciesTab.text.noDependenciesYetEveryCan", { taskL: terms.taskL, v: " " })}
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
                      <select className="select sm" style={{ width: 210 }} value={d.type} aria-label={tr("studio.dependenciesTab.tpl.ruleFor", { v: names.get(d.successor) ?? d.successor })} onChange={(e) => update((p) => setDependency(p, { ...d, type: e.target.value as DependencyType }))}>
                        {(Object.keys(DEP_TYPE_LABEL) as DependencyType[]).map((t) => <option key={t} value={t}>{DEP_TYPE_HELP[t]}</option>)}
                      </select>
                    </td>
                    <td>
                      {names.get(d.predecessor) ?? <span style={{ color: "var(--danger)" }}>{d.predecessor} (missing)</span>}
                      {cyc.has(k) ? <span className="badge danger" style={{ marginLeft: 6 }}><Icon name="refresh" />{" "}{tr("studio.dependenciesTab.text.loop")}</span> : null}
                    </td>
                    <td>
                      <NumberInput value={d.lag_minutes} width={90} label={t("studio.dependenciesTab.label.lagInMinutes")} onChange={(v) => update((p) => setDependency(p, { ...d, lag_minutes: v }))} />
                    </td>
                    <td>
                      <button className="btn ghost sm icon" aria-label={tr("studio.dependenciesTab.tpl.removeDependencyTo", { predecessor: d.predecessor, successor: d.successor })} onClick={() => update((p) => removeDependency(p, d.predecessor, d.successor))}>
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

import { useEffect, useState } from "react";
import { NavLink, Outlet, useParams } from "react-router-dom";
import { downloadJson, errorMessage, exportProblem } from "../api/client";
import type { Problem } from "../api/types";
import { Banner, ErrorBanner, Loading } from "../components/Banner";
import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import { makeTerms } from "../lib/terms";
import { inputToIso, isoToInput, offsetLabel, offsetMinutesOf, offsetText } from "../lib/time";
import { PlanProvider, usePlan, type SaveState } from "../state/PlanContext";

export function PlanWorkspace() {
  const { planId } = useParams();
  if (!planId) return null;
  return (
    <PlanProvider planId={planId} key={planId}>
      <WorkspaceInner />
    </PlanProvider>
  );
}

function SaveIndicator({ state, dirty, error }: { state: SaveState; dirty: boolean; error: string | null }) {
  let content;
  if (state === "saving") content = (<><span className="spinner" aria-hidden /> Saving…</>);
  else if (state === "conflict") content = (<><Icon name="alert" /> Conflict</>);
  else if (state === "error") content = (<><Icon name="x" /> Not saved{error ? `: ${error}` : ""}</>);
  else if (dirty) content = (<><Icon name="clock" /> Edited</>);
  else content = (<><Icon name="check" /> Saved</>);
  const stateAttr = state === "saved" && dirty ? "dirty" : state;
  return (
    <span className="save-state" data-testid="save-state" data-state={stateAttr} role="status" aria-live="polite"
      style={state === "error" || state === "conflict" ? { color: "var(--danger)" } : undefined}>
      {content}
    </span>
  );
}

function PlanSettingsDialog({ draft, onClose, onApply }: { draft: Problem; onClose(): void; onApply(p: Problem): void }) {
  const [offset, setOffset] = useState(offsetText(offsetMinutesOf(draft.horizon_start)));
  const offMin = (() => {
    const m = offset.match(/^([+-])(\d{2}):(\d{2})$/);
    return m ? (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])) : null;
  })();
  const [start, setStart] = useState(isoToInput(draft.horizon_start, offsetMinutesOf(draft.horizon_start)));
  const [days, setDays] = useState(draft.horizon_days);
  const [description, setDescription] = useState(draft.description);
  const [currency, setCurrency] = useState(draft.currency);
  const valid = offMin !== null && !!start && days >= 1 && days <= 366;
  return (
    <Dialog
      title="Plan settings"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button
            className="btn primary"
            disabled={!valid}
            onClick={() => {
              const hs = inputToIso(start, offMin ?? 0);
              if (!hs) return;
              onApply({ ...draft, horizon_start: hs, horizon_days: days, description, currency: currency.slice(0, 8) });
              onClose();
            }}
          >
            Apply
          </button>
        </>
      }
    >
      <div className="form-grid">
        <div className="field">
          <label htmlFor="ps-start">Plan starts</label>
          <input id="ps-start" className="input" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ps-offset">UTC offset</label>
          <input id="ps-offset" className="input" value={offset} onChange={(e) => setOffset(e.target.value)} aria-invalid={offMin === null} placeholder="+05:30" />
          <span className="hint">All plan times use this offset.</span>
        </div>
        <div className="field">
          <label htmlFor="ps-days">Planning horizon (days)</label>
          <input id="ps-days" className="input" type="number" min={1} max={366} value={days} onChange={(e) => setDays(Number(e.target.value))} />
        </div>
        <div className="field">
          <label htmlFor="ps-currency">Currency</label>
          <input id="ps-currency" className="input" value={currency} maxLength={8} onChange={(e) => setCurrency(e.target.value)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="ps-desc">Description</label>
        <textarea id="ps-desc" className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
    </Dialog>
  );
}

function WorkspaceInner() {
  const plan = usePlan();
  const { record, draft, loading, loadError, saveState, saveError, dirty, conflictDismissed } = plan;
  const [name, setName] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    if (draft) setName(draft.name);
  }, [draft?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (draft) document.title = `${draft.name} - SuperPlanner`;
    return () => {
      document.title = "SuperPlanner Studio";
    };
  }, [draft?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading && !draft) return <Loading label="Loading plan…" />;
  if (loadError && !draft) return <ErrorBanner error={loadError} onRetry={() => void plan.reload()} />;
  if (!draft || !record) return null;

  const terms = makeTerms(draft.terminology);
  const commitName = () => {
    const v = name.trim();
    if (v && v !== draft.name) plan.update((p) => ({ ...p, name: v.slice(0, 200) }));
    else setName(draft.name);
  };

  const tabs = [
    { to: "tasks", label: terms.tasks, count: draft.tasks.length, icon: "list" as const },
    { to: "resources", label: terms.resources, count: draft.resources.length, icon: "layers" as const },
    { to: "dependencies", label: "Dependencies", count: draft.dependencies.length, icon: "graph" as const },
    { to: "validate", label: "Validate", icon: "check" as const },
    { to: "optimize", label: "Optimize", icon: "play" as const },
    { to: "schedule", label: terms.schedule, icon: "calendar" as const },
    { to: "compare", label: "Compare", icon: "compare" as const },
  ];

  const doExport = async () => {
    setExportError(null);
    try {
      if (dirty) await plan.save();
      const file = await exportProblem(record.id);
      const slug = draft.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || record.id;
      downloadJson(file, `${slug}.superplanner.json`);
    } catch (err) {
      setExportError(errorMessage(err));
    }
  };

  return (
    <div>
      <div className="ws-header">
        <div className="ws-title">
          <label htmlFor="plan-name" className="sr-only">Plan name</label>
          <input
            id="plan-name"
            className="ws-title-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={commitName}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                setName(draft.name);
                (e.target as HTMLInputElement).blur();
              }
            }}
            size={Math.min(40, Math.max(8, name.length + 1))}
          />
          <span className="chip" title="Server version of this plan">v{record.version}</span>
          <SaveIndicator state={saveState} dirty={dirty} error={saveError} />
        </div>
        <span className="small muted hide-sm">Times in {offsetLabel(offsetMinutesOf(draft.horizon_start))}</span>
        <button className="btn sm" onClick={() => setSettingsOpen(true)}>
          <Icon name="settings" /> Plan settings
        </button>
        <button className="btn sm" onClick={doExport}>
          <Icon name="download" /> Export
        </button>
        <button className="btn sm primary" onClick={() => void plan.save()} disabled={!dirty || saveState === "saving" || saveState === "conflict"}>
          <Icon name="save" /> Save
        </button>
      </div>

      {saveState === "conflict" && !conflictDismissed ? (
        <Banner
          tone="danger"
          role="alert"
          testId="conflict-banner"
          title="This plan was changed elsewhere."
          actions={
            <>
              <button className="btn sm" onClick={() => void plan.reload()}>
                Reload (discard your edits)
              </button>
              <button className="btn sm" onClick={() => void plan.keepEditing()}>
                Keep editing
              </button>
            </>
          }
        >
          Your latest edits were not saved, so nothing was overwritten. Reload to see the other changes, or keep editing to
          replace them with your version on the next save.
        </Banner>
      ) : null}
      <ErrorBanner error={exportError} />

      <nav className="tabs" aria-label="Plan sections">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => `tab${isActive ? " active" : ""}`}>
            <Icon name={t.icon} />
            {t.label}
            {t.count !== undefined ? <span className="tab-count">{t.count}</span> : null}
          </NavLink>
        ))}
      </nav>
      <div className="tab-panel">
        <Outlet />
      </div>
      {settingsOpen ? (
        <PlanSettingsDialog draft={draft} onClose={() => setSettingsOpen(false)} onApply={(p) => plan.update(() => p)} />
      ) : null}
    </div>
  );
}

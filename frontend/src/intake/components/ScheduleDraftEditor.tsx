import { useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { MultiSelect, TextInput } from "../../components/Inputs";
import { Term } from "../../components/Term";
import { KINDS } from "../../landing/kinds";
import type { DraftResource, DraftResourceKind, DraftTask, DurationUnit, ScheduleDraft, WorkingTime } from "../api/types";
import { draftProblems, dropProvenance, nextKey, resourceKey } from "../lib/draft";
import { useIntake } from "../state/IntakeContext";
import { LinkedField } from "./LinkedField";
import { DurationRangeInput } from "./fields";
import { windowsText, WorkingTimeFields } from "./QuestionInput";
import { DateInput } from "../../components/DateInput";
import { t, t as tr } from "../../lib/i18n";

const DEFAULT_UNIT: Record<string, DurationUnit> = { project: "days", study: "hours", production: "hours", generic: "days" };
const DEFAULT_WT: Record<string, WorkingTime> = {
  project: { days: ["mon", "tue", "wed", "thu", "fri"], windows: [{ start: "09:00", end: "17:00" }], weekend_windows: null },
  generic: { days: ["mon", "tue", "wed", "thu", "fri"], windows: [{ start: "09:00", end: "17:00" }], weekend_windows: null },
  study: {
    days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    windows: [{ start: "18:00", end: "21:00" }],
    weekend_windows: [
      { start: "09:00", end: "13:00" },
      { start: "14:00", end: "18:00" },
    ],
  },
  production: {
    days: ["mon", "tue", "wed", "thu", "fri", "sat"],
    windows: [
      { start: "06:00", end: "14:00" },
      { start: "14:00", end: "22:00" },
    ],
    weekend_windows: null,
  },
};

const RES_KINDS: { v: DraftResourceKind; label: string }[] = [
  { v: "person", label: tr("studio.scheduleDraftEditor.str.person") },
  { v: "machine", label: tr("studio.scheduleDraftEditor.str.machine") },
  { v: "room", label: tr("studio.scheduleDraftEditor.str.room") },
  { v: "equipment", label: tr("studio.scheduleDraftEditor.str.equipment") },
  { v: "generic", label: tr("studio.scheduleDraftEditor.str.other") },
];

export function workingTimeText(wt: WorkingTime): string {
  const days = wt.days.map((d) => d[0].toUpperCase() + d.slice(1)).join(", ");
  const wk = wt.weekend_windows ? `; Sat-Sun ${windowsText(wt.weekend_windows)}` : "";
  return `${days} ${windowsText(wt.windows)}${wk}`;
}

/** Tasks, resources and working time of a scheduling draft (PHASE2.md 3.3). */
export function ScheduleDraftEditor({ draft }: { draft: ScheduleDraft }) {
  const { state, editDraft } = useIntake();
  const terms = KINDS[state.kind].terminology ?? KINDS.project.terminology!;
  const [wtOpen, setWtOpen] = useState(false);
  const [pending, setPending] = useState<{ name: string; run(): void } | null>(null);
  const problems = draftProblems(draft);
  const errOf = (path: string) => problems.find((p) => p.path === path)?.message ?? null;
  const unit = DEFAULT_UNIT[draft.kind] ?? "days";

  const setTask = (key: string, patch: Partial<DraftTask>, fields: string[]) =>
    editDraft(
      { ...draft, tasks: draft.tasks.map((t) => (t.key === key ? { ...t, ...patch } : t)) },
      fields.map((f) => `/tasks/${key}/${f}`),
    );
  const setRes = (key: string, patch: Partial<DraftResource>, fields: string[]) =>
    editDraft(
      { ...draft, resources: draft.resources.map((r) => (r.key === key ? { ...r, ...patch } : r)) },
      fields.map((f) => `/resources/${key}/${f}`),
    );

  const removeTask = (key: string) => {
    const next = dropProvenance(
      { ...draft, tasks: draft.tasks.filter((t) => t.key !== key).map((t) => ({ ...t, after: t.after.filter((a) => a !== key) })) },
      `/tasks/${key}/`,
    );
    editDraft(next, []);
  };
  const addTask = () => {
    const key = nextKey(
      "t",
      draft.tasks.map((t) => t.key),
    );
    const t: DraftTask = {
      key,
      name: tr("studio.scheduleDraftEditor.tpl.new", { task: terms.task.toLowerCase() }),
      milestone: false,
      duration: { optimistic: 1, likely: 1, pessimistic: 1, unit },
      after: [],
      resources: [],
      resource_mode: "any",
      deadline: null,
      deadline_hard: false,
      earliest_start: null,
      priority: null,
      group: null,
      notes: "",
    };
    editDraft({ ...draft, tasks: [...draft.tasks, t] }, [`/tasks/${key}/name`, `/tasks/${key}/duration`]);
  };
  const removeRes = (key: string) => {
    const next = dropProvenance(
      {
        ...draft,
        resources: draft.resources.filter((r) => r.key !== key),
        tasks: draft.tasks.map((t) => ({ ...t, resources: t.resources.filter((r) => r !== key) })),
      },
      `/resources/${key}/`,
    );
    editDraft(next, []);
  };
  const addRes = () => {
    const name = tr("studio.scheduleDraftEditor.tpl.new2", { resource: terms.resource.toLowerCase() });
    const key = resourceKey(
      `${name} ${draft.resources.length + 1}`,
      draft.resources.map((r) => r.key),
    );
    const kind: DraftResourceKind = draft.kind === "production" ? "machine" : draft.kind === "study" ? "generic" : "person";
    editDraft({ ...draft, resources: [...draft.resources, { key, name, kind, count: 1 }] }, [`/resources/${key}/name`]);
  };

  const wt = draft.working_time ?? DEFAULT_WT[draft.kind] ?? DEFAULT_WT.generic;
  const taskOptions = (self: string) => draft.tasks.filter((t) => t.key !== self).map((t) => ({ value: t.key, label: t.name }));
  const resOptions = draft.resources.map((r) => ({ value: r.key, label: r.count > 1 ? `${r.name} (${r.count})` : r.name }));

  return (
    <div className="col" style={{ gap: 16 }}>
      <section aria-labelledby="draft-plan-title" className="col" style={{ gap: 8 }}>
        <h3 id="draft-plan-title" className="section-title">
          {tr("studio.scheduleDraftEditor.text.thePlan")}
        </h3>
        <div className="form-grid">
          <LinkedField path="/name" error={errOf("/name")}>
            <div className="field grow">
              <label htmlFor="draft-name">{t("studio.scheduleDraftEditor.label.planName")}</label>
              <TextInput
                id="draft-name"
                className="input"
                label={t("studio.scheduleDraftEditor.label.planName")}
                value={draft.name}
                required
                onChange={(v) => editDraft({ ...draft, name: v }, ["/name"])}
              />
            </div>
          </LinkedField>
          <LinkedField path="/start_date">
            <div className="field grow">
              <label htmlFor="draft-start">{t("studio.scheduleDraftEditor.label.startDate")}</label>
              <DateInput id="draft-start" value={draft.start_date ?? ""} onChange={(v) => editDraft({ ...draft, start_date: v || null }, ["/start_date"])} />
              {!draft.start_date ? <span className="hint">{tr("studio.scheduleDraftEditor.text.emptyTheNextWorkingDay")}</span> : null}
            </div>
          </LinkedField>
        </div>
        <LinkedField path="/working_time">
          <div className="col grow" style={{ gap: 4 }}>
            <span className="field-label">
              {tr("studio.scheduleDraftEditor.text.workingTime")}{" "}<Term k="calendar_window" bare />
            </span>
            <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <span data-testid="draft-working-time">
                {workingTimeText(wt)}
                {!draft.working_time ? <span className="muted">{" "}{tr("studio.scheduleDraftEditor.text.usualForThisKindOf")}</span> : null}
              </span>
              <button type="button" className="btn sm" aria-expanded={wtOpen} onClick={() => setWtOpen(!wtOpen)}>
                {wtOpen ? tr("studio.scheduleDraftEditor.str.done") : tr("studio.scheduleDraftEditor.str.change")}
              </button>
            </span>
            {wtOpen ? (
              <WorkingTimeFields
                value={wt}
                idPrefix="draft-wt"
                onChange={(v) => editDraft({ ...draft, working_time: v }, ["/working_time"])}
              />
            ) : null}
          </div>
        </LinkedField>
      </section>

      <section aria-labelledby="draft-res-title" className="col" style={{ gap: 8 }}>
        <div className="row">
          <h3 id="draft-res-title" className="section-title grow">
            {terms.resources} <Term k="resource" bare />
          </h3>
          <button type="button" className="btn sm" onClick={addRes} data-testid="draft-add-resource">
            <Icon name="plus" />{" "}{tr("studio.scheduleDraftEditor.text.add", { resource: terms.resource.toLowerCase() })}
          </button>
        </div>
        {draft.resources.length === 0 ? (
          <p className="small muted" style={{ margin: 0 }}>
            {tr("studio.scheduleDraftEditor.text.noneNamedYetThePlan", { resource: terms.resource.toLowerCase() })}
          </p>
        ) : (
          <ul className="plain-list col" style={{ gap: 6 }}>
            {draft.resources.map((r) => (
              <li key={r.key} className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                <LinkedField path={`/resources/${r.key}/name`} error={errOf(`/resources/${r.key}/name`)}>
                  <TextInput
                    label={`${terms.resource} name`}
                    value={r.name}
                    required
                    onChange={(v) => setRes(r.key, { name: v }, ["name"])}
                  />
                </LinkedField>
                <select
                  className="select sm"
                  aria-label={`${r.name}: kind`}
                  value={r.kind}
                  onChange={(e) => setRes(r.key, { kind: e.target.value as DraftResourceKind }, ["kind"])}
                >
                  {RES_KINDS.map((k) => (
                    <option key={k.v} value={k.v}>
                      {k.label}
                    </option>
                  ))}
                </select>
                <LinkedField path={`/resources/${r.key}/count`}>
                  <label className="small muted row" style={{ gap: 4 }}>
                    {tr("studio.scheduleDraftEditor.text.howMany")}
                    <input
                      type="number"
                      className="input sm"
                      style={{ width: 60 }}
                      min={1}
                      max={50}
                      value={r.count}
                      onChange={(e) => {
                        const n = Math.max(1, Math.min(50, Math.round(Number(e.target.value) || 1)));
                        if (n !== r.count) setRes(r.key, { count: n }, ["count"]);
                      }}
                    />
                  </label>
                </LinkedField>
                <button
                  type="button"
                  className="btn sm icon ghost"
                  aria-label={tr("studio.scheduleDraftEditor.tpl.remove", { name: r.name })}
                  onClick={() => setPending({ name: r.name, run: () => removeRes(r.key) })}
                >
                  <Icon name="trash" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="draft-tasks-title" className="col" style={{ gap: 8 }}>
        <div className="row">
          <h3 id="draft-tasks-title" className="section-title grow">
            {terms.tasks}
          </h3>
          <button type="button" className="btn sm" onClick={addTask} data-testid="draft-add-task">
            <Icon name="plus" />{" "}{tr("studio.scheduleDraftEditor.text.add2", { task: terms.task.toLowerCase() })}
          </button>
        </div>
        {draft.tasks.length === 0 ? (
          <div className="empty small">
            <p style={{ margin: 0 }}>{tr("studio.scheduleDraftEditor.text.noYetAddThemHere", { tasks: terms.tasks.toLowerCase() })}</p>
            <button type="button" className="btn primary sm" onClick={addTask}>
              <Icon name="plus" />{" "}{tr("studio.scheduleDraftEditor.text.add2", { task: terms.task.toLowerCase() })}
            </button>
          </div>
        ) : (
          <ul className="draft-items">
            {draft.tasks.map((t) => {
              const durErrId = `err-dur-${t.key}`;
              const durErr = errOf(`/tasks/${t.key}/duration`);
              return (
                <li key={t.key} className="draft-item" data-task-key={t.key}>
                  <div className="draft-item-head">
                    <LinkedField path={`/tasks/${t.key}/name`} error={errOf(`/tasks/${t.key}/name`)}>
                      <TextInput
                        label={`${terms.task} name`}
                        value={t.name}
                        required
                        style={{ minWidth: 150 }}
                        onChange={(v) => setTask(t.key, { name: v }, ["name"])}
                      />
                    </LinkedField>
                    <LinkedField path={`/tasks/${t.key}/milestone`}>
                      <label className="checkbox small">
                        <input
                          type="checkbox"
                          checked={t.milestone}
                          onChange={(e) =>
                            setTask(
                              t.key,
                              e.target.checked
                                ? { milestone: true, duration: null, resources: [] }
                                : { milestone: false, duration: { optimistic: 1, likely: 1, pessimistic: 1, unit } },
                              ["milestone", "duration"],
                            )
                          }
                        />
                        {tr("studio.scheduleDraftEditor.text.aMomentNoWork", { milestone: terms.milestone })}
                      </label>
                    </LinkedField>
                    <div className="grow" />
                    <button
                      type="button"
                      className="btn sm icon ghost"
                      aria-label={tr("studio.scheduleDraftEditor.tpl.remove", { name: t.name })}
                      onClick={() => setPending({ name: t.name, run: () => removeTask(t.key) })}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                  <div className="draft-item-body">
                    <div className="draft-cell">
                      <span className="field-label">
                        {tr("studio.scheduleDraftEditor.text.duration")}{" "}<Term k="duration_range" bare />
                      </span>
                      {t.milestone ? (
                        <span className="muted small">{tr("studio.scheduleDraftEditor.text.noDuration")}</span>
                      ) : (
                        <LinkedField path={`/tasks/${t.key}/duration`} error={durErr} errorId={durErrId}>
                          <DurationRangeInput
                            value={t.duration}
                            defaultUnit={unit}
                            label={`${t.name}: duration`}
                            describedBy={durErr ? durErrId : undefined}
                            invalid={!!durErr}
                            onChange={(d) => setTask(t.key, { duration: d }, ["duration"])}
                          />
                        </LinkedField>
                      )}
                    </div>
                    <div className="draft-cell">
                      <span className="field-label">
                        {tr("studio.scheduleDraftEditor.text.comesAfter")}{" "}<Term k="dependency" bare />
                      </span>
                      <LinkedField path={`/tasks/${t.key}/after`}>
                        <MultiSelect
                          label={tr("studio.scheduleDraftEditor.tpl.comesAfter", { name: t.name })}
                          options={taskOptions(t.key)}
                          value={t.after}
                          onChange={(v) => setTask(t.key, { after: v }, ["after"])}
                        />
                      </LinkedField>
                    </div>
                    <div className="draft-cell">
                      <span className="field-label">{tr("studio.scheduleDraftEditor.text.who")}</span>
                      {t.milestone ? (
                        <span className="muted small">-</span>
                      ) : (
                        <LinkedField path={`/tasks/${t.key}/resources`}>
                          <span className="col" style={{ gap: 4 }}>
                            <MultiSelect
                              label={`${t.name}: who`}
                              options={resOptions}
                              value={t.resources}
                              placeholder={draft.resources.length > 1 ? tr("studio.scheduleDraftEditor.str.anyone") : tr("studio.scheduleDraftEditor.str.default")}
                              onChange={(v) => setTask(t.key, { resources: v }, ["resources"])}
                            />
                            {t.resources.length > 1 ? (
                              <select
                                className="select sm"
                                aria-label={tr("studio.scheduleDraftEditor.tpl.howTheyWorkOnIt", { name: t.name })}
                                value={t.resource_mode}
                                onChange={(e) => setTask(t.key, { resource_mode: e.target.value as "any" | "all" }, ["resource_mode"])}
                              >
                                <option value="any">{tr("studio.scheduleDraftEditor.text.anyOneOfThem")}</option>
                                <option value="all">{tr("studio.scheduleDraftEditor.text.allOfThemTogether")}</option>
                              </select>
                            ) : null}
                          </span>
                        </LinkedField>
                      )}
                    </div>
                    <div className="draft-cell">
                      <span className="field-label">{terms.deadline}</span>
                      <LinkedField path={`/tasks/${t.key}/deadline`}>
                        <span className="col" style={{ gap: 4 }}>
                          <DateInput small ariaLabel={`${t.name}: ${terms.deadline.toLowerCase()}`} value={t.deadline ?? ""} onChange={(v) => setTask(
                                t.key,
                                { deadline: v || null, deadline_hard: v ? t.deadline_hard : false },
                                ["deadline"],
                              )
                            } />
                          {t.deadline ? (
                            <label className="checkbox small">
                              <input
                                type="checkbox"
                                checked={t.deadline_hard}
                                onChange={(e) => setTask(t.key, { deadline_hard: e.target.checked }, ["deadline_hard"])}
                              />
                              {tr("studio.scheduleDraftEditor.text.mustBeMet")}
                            </label>
                          ) : null}
                        </span>
                      </LinkedField>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      {pending ? (
        <ConfirmDialog
          title={tr("studio.scheduleDraftEditor.tpl.remove2", { name: pending.name })}
          confirmLabel={t("studio.scheduleDraftEditor.btn.remove")}
          danger
          onCancel={() => setPending(null)}
          onConfirm={() => {
            pending.run();
            setPending(null);
          }}
        >
          {tr("studio.scheduleDraftEditor.text.itIsRemovedFromThe")}
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

/** `/mfg/resources/operators` (`?operator=`, M 11.1): operators with skills, shift template + shift names, home stage. */
import { useEffect, useMemo, useState } from "react";
import { OperatorAbsences } from "../components/OperatorAbsences";
import { Link, useSearchParams } from "react-router";
import { mfgPaths } from "../lib/paths";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { MultiSelect } from "../../components/Inputs";
import {
  createOperator,
  deleteOperator,
  getOperator,
  listGroups,
  listOperators,
  listShiftTemplates,
  listSkills,
  updateOperator,
} from "../api/client";
import type { GroupRecord, OperatorInput, OperatorRecord, ShiftTemplateRecord, SkillRecord } from "../api/types";
import { listMembers } from "../api/clientM2";
import type { OperatorM4Fields } from "../api/typesM4";
import { ConflictBanner, MfgError, SaveState, Spinner } from "../components/Feedback";
import { CheckField, SelectField, TextField } from "../components/Field";
import { RecordList, withParam } from "../components/RecordList";
import { ActiveBadge } from "../components/StatusChip";
import { isConflict, useDebounced, useLoad } from "../lib/useMfg";

export function OperatorsPage() {
  const [params, setParams] = useSearchParams();
  const opParam = params.get("operator");
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 250);
  const operators = useLoad((signal) => listOperators({ q: dq.trim() || undefined }, signal), [dq]);
  const skills = useLoad((signal) => listSkills(signal), []);
  const templates = useLoad((signal) => listShiftTemplates(signal), []);
  const groups = useLoad((signal) => listGroups({}, signal), []);
  const [creating, setCreating] = useState(false);
  const list = operators.data?.items ?? [];

  return (
    <div className="split mfg-split">
      <section className="card" aria-labelledby="ops-title">
        <div className="card-header">
          <h2 id="ops-title">Operators</h2>
          <Link className="btn sm" to={mfgPaths.printLabels({ type: "badge" })} data-testid="print-badges">
            <Icon name="file" /> Print badges
          </Link>
          <button
            type="button"
            className="btn sm primary"
            onClick={() => {
              setCreating(true);
              setParams((p) => withParam(p, "operator", null));
            }}
            data-testid="operator-new"
          >
            <Icon name="plus" /> New operator
          </button>
        </div>
        <div style={{ padding: "8px 16px 0" }}>
          <input className="input sm" type="search" placeholder="Search code or name" aria-label="Search operators" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <MfgError error={operators.error} onRetry={operators.reload} />
        {operators.loading && !operators.data ? <Spinner /> : null}
        {operators.data ? (
          <RecordList
            items={list}
            selectedId={creating ? null : opParam}
            onSelect={(id) => {
              setCreating(false);
              setParams((p) => withParam(p, "operator", id));
            }}
            testId="operator-row"
            empty="No operators yet."
            render={(o) => (
              <>
                <strong className="mono">{o.code}</strong>
                <span className="grow mfg-ellipsis">{o.name}</span>
                <span className="muted small mfg-ellipsis" style={{ maxWidth: 160 }}>
                  {o.skills.map((s) => s.code).join(", ")}
                </span>
                <span className="chip">{o.shift_template?.code ?? "no shift"}</span>
                <ActiveBadge active={o.active} />
              </>
            )}
          />
        ) : null}
      </section>
      <aside aria-label="Operator details">
        {creating ? (
          <OperatorForm
            key="new"
            operatorId={null}
            skills={skills.data?.items ?? []}
            templates={templates.data?.items ?? []}
            groups={groups.data?.items ?? []}
            onSaved={(o) => {
              setCreating(false);
              operators.reload();
              setParams((p) => withParam(p, "operator", o.id));
            }}
            onCancel={() => setCreating(false)}
          />
        ) : opParam ? (
          <OperatorForm
            key={opParam}
            operatorId={opParam}
            skills={skills.data?.items ?? []}
            templates={templates.data?.items ?? []}
            groups={groups.data?.items ?? []}
            onSaved={() => operators.reload()}
            onDeleted={() => {
              operators.reload();
              setParams((p) => withParam(p, "operator", null));
            }}
          />
        ) : (
          <div className="card card-body muted">Select an operator, or add a new one.</div>
        )}
        {!creating && opParam ? <OperatorAbsences key={`abs-${opParam}`} operatorId={opParam} /> : null}
      </aside>
    </div>
  );
}

function OperatorForm({
  operatorId,
  skills,
  templates,
  groups,
  onSaved,
  onCancel,
  onDeleted,
}: {
  operatorId: string | null;
  skills: SkillRecord[];
  templates: ShiftTemplateRecord[];
  groups: GroupRecord[];
  onSaved(o: OperatorRecord): void;
  onCancel?(): void;
  onDeleted?(): void;
}) {
  const loaded = useLoad((signal) => (operatorId ? getOperator(operatorId, signal) : null), [operatorId]);
  const [base, setBase] = useState<OperatorRecord | null>(null);
  const [f, setF] = useState({ code: "", name: "", skill_ids: [] as string[], template: "", shift_names: [] as string[], home: "", active: true, user: "", m4: true });
  const members = useLoad((signal) => listMembers(signal).catch(() => null), []);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const reset = (o: OperatorRecord) => {
    setBase(o);
    setF({ code: o.code, name: o.name, skill_ids: o.skill_ids, template: o.shift_template_id ?? "", shift_names: o.shift_names, home: o.home_group_id ?? "", active: o.active, user: (o as OperatorRecord & OperatorM4Fields).user_id ?? "", m4: "user_id" in o });
    setConflict(false);
  };
  useEffect(() => {
    if (loaded.data) reset(loaded.data);
  }, [loaded.data]);

  const template = templates.find((t) => t.id === f.template);
  const skillOptions = useMemo(() => skills.map((s) => ({ value: s.id, label: `${s.code} - ${s.name}` })), [skills]);

  if (operatorId && loaded.error && !base) return <MfgError error={loaded.error} onRetry={loaded.reload} />;
  if (operatorId && !base) return <Spinner />;

  const body = (): OperatorInput & OperatorM4Fields => ({
    ...(f.m4 ? { user_id: f.user || null } : {}),
    code: f.code.trim(),
    name: f.name.trim(),
    skill_ids: f.skill_ids,
    shift_template_id: f.template || null,
    shift_names: f.template ? f.shift_names.filter((n) => template?.shifts.some((s) => s.name === n)) : [],
    home_group_id: f.home || null,
    active: f.active,
  });

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const o = base ? await updateOperator(base.id, body(), base.row_version) : await createOperator(body());
      reset(o);
      setSaved(true);
      onSaved(o);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="operator-form"
      data-operator-id={base?.id}
    >
      <div className="card-header">
        <h2>{base ? `Operator ${base.code}` : "New operator"}</h2>
        <SaveState busy={false} saved={saved} />
      </div>
      <div className="card-body col">
        {conflict && base ? <ConflictBanner onReload={() => void getOperator(base.id).then(reset, setError)} what="this operator" /> : null}
        <MfgError error={error} title="Could not save" />
        <div className="form-grid">
          <TextField label="Code" value={f.code} onChange={(v) => setF({ ...f, code: v })} required maxLength={32} hint="e.g. badge number" testId="operator-code" />
          <TextField label="Name" value={f.name} onChange={(v) => setF({ ...f, name: v })} required testId="operator-name" />
        </div>
        <div className="field">
          <span className="field-label">Skills</span>
          <MultiSelect options={skillOptions} value={f.skill_ids} onChange={(v) => setF({ ...f, skill_ids: v })} label="Skills" placeholder="No skills" />
        </div>
        <div className="form-grid">
          <SelectField
            label="Works shift template"
            value={f.template}
            onChange={(v) => setF({ ...f, template: v, shift_names: [] })}
            options={[{ value: "", label: "None" }, ...templates.map((t) => ({ value: t.id, label: `${t.code} - ${t.name}` }))]}
            testId="operator-template"
          />
          <SelectField label="Home stage" value={f.home} onChange={(v) => setF({ ...f, home: v })} options={[{ value: "", label: "None" }, ...groups.map((g) => ({ value: g.id, label: `${g.code} - ${g.name}` }))]} />
          {f.m4 ? (
            <SelectField
              label="Personal login"
              value={f.user}
              onChange={(v) => setF({ ...f, user: v })}
              options={[
                { value: "", label: "None (badge scan on a shared tablet)" },
                ...(members.data?.items ?? []).filter((m) => m.active).map((m) => ({ value: m.user.id, label: `${m.user.display_name || m.user.email}${m.user.email ? ` (${m.user.email})` : ""}` })),
                ...(f.user && !(members.data?.items ?? []).some((m) => m.user.id === f.user) ? [{ value: f.user, label: "Linked account" }] : []),
              ]}
              hint="An operator signed in with their own account needs no badge scan. Members are managed under Members."
            />
          ) : null}
        </div>
        {template ? (
          <fieldset className="mfg-fieldset">
            <legend>Shifts of {template.code}</legend>
            <div className="row wrap">
              {template.shifts.map((s) => (
                <label key={s.name} className="checkbox">
                  <input type="checkbox" checked={f.shift_names.includes(s.name)} onChange={(e) => setF({ ...f, shift_names: e.target.checked ? [...f.shift_names, s.name] : f.shift_names.filter((n) => n !== s.name) })} />
                  {s.name} ({s.start}-{s.end})
                </label>
              ))}
            </div>
            <span className="hint">None ticked = all shifts of the template.</span>
          </fieldset>
        ) : null}
        <CheckField label="Active" checked={f.active} onChange={(v) => setF({ ...f, active: v })} />
        <div className="row">
          <button type="submit" className="btn primary sm" disabled={busy || !f.code.trim() || !f.name.trim()} data-testid="operator-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {base ? "Save operator" : "Create operator"}
          </button>
          {onCancel ? (
            <button type="button" className="btn sm" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
          <span className="grow" />
          {base && onDeleted ? (
            <button type="button" className="btn sm danger" onClick={() => setConfirm(true)} data-testid="operator-delete">
              <Icon name="trash" /> Delete
            </button>
          ) : null}
        </div>
      </div>
      {confirm && base && onDeleted ? (
        <ConfirmDialog
          title={`Delete operator ${base.code}?`}
          confirmLabel="Delete"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            deleteOperator(base.id, base.row_version).then(onDeleted, setError);
          }}
        >
          <p style={{ margin: 0 }}>Consider marking the operator inactive instead.</p>
        </ConfirmDialog>
      ) : null}
    </form>
  );
}

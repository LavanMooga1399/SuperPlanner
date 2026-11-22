/**
 * `/mfg/resources/skills` (`?skill=`, M 11.1): skills; the selected skill lists the operators who hold it and
 * the shifts they work (target of `MFG_SKILL_NOT_ON_SHIFT` links).
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { createSkill, deleteSkill, listOperators, listSkills, updateSkill } from "../api/client";
import type { SkillRecord } from "../api/types";
import { EntityFormDialog } from "../components/EntityFormDialog";
import { MfgError, Spinner } from "../components/Feedback";
import { TextField } from "../components/Field";
import { RecordList, withParam } from "../components/RecordList";
import { ActiveBadge } from "../components/StatusChip";
import { DataTable } from "../components/DataTable";
import { mfgPaths } from "../lib/paths";
import { useLoad } from "../lib/useMfg";
import { t } from "../../lib/i18n";

export function SkillsPage() {
  const [params, setParams] = useSearchParams();
  const skillParam = params.get("skill");
  const skills = useLoad((signal) => listSkills(signal), []);
  const [editing, setEditing] = useState<SkillRecord | "new" | null>(null);
  const [del, setDel] = useState<SkillRecord | null>(null);
  const [error, setError] = useState<unknown>(null);
  const list = skills.data?.items ?? [];
  const selected = list.find((s) => s.id === skillParam) ?? null;

  return (
    <div className="split mfg-split">
      <section className="card" aria-labelledby="skills-title">
        <div className="card-header">
          <h2 id="skills-title">Skills</h2>
          <button type="button" className="btn sm primary" onClick={() => setEditing("new")} data-testid="skill-new">
            <Icon name="plus" /> {t("mfg.skillsPage.btn.newSkill")}
          </button>
        </div>
        <MfgError error={skills.error} onRetry={skills.reload} />
        <MfgError error={error} title="The action failed" />
        {skills.loading && !skills.data ? <Spinner /> : null}
        {skills.data ? (
          <RecordList
            items={list}
            selectedId={skillParam}
            onSelect={(id) => setParams((p) => withParam(p, "skill", id))}
            testId="skill-row"
            empty={t("mfg.skillsPage.empty.noSkillsYetSkillsSay")}
            render={(s) => (
              <>
                <strong className="mono">{s.code}</strong>
                <span className="grow mfg-ellipsis">{s.name}</span>
                <span className="muted small">
                  {s.operator_count} people · {s.operation_count} operations
                </span>
              </>
            )}
          />
        ) : null}
      </section>
      <aside className="col" aria-label="Skill details">
        {selected ? (
          <SkillHolders
            skill={selected}
            onEdit={() => setEditing(selected)}
            onDelete={() => setDel(selected)}
          />
        ) : (
          <div className="card card-body muted">Select a skill to see who holds it and when they work.</div>
        )}
      </aside>
      {editing ? (
        <SkillDialog
          skill={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(s) => {
            setEditing(null);
            skills.reload();
            setParams((p) => withParam(p, "skill", s.id));
          }}
        />
      ) : null}
      {del ? (
        <ConfirmDialog
          title={`Delete skill ${del.code}?`}
          confirmLabel={t("mfg.skillsPage.btn.delete")}
          danger
          onCancel={() => setDel(null)}
          onConfirm={() => {
            const s = del;
            setDel(null);
            setError(null);
            deleteSkill(s.id, s.row_version).then(() => {
              skills.reload();
              setParams((p) => withParam(p, "skill", null));
            }, setError);
          }}
        >
          <p style={{ margin: 0 }}>A skill required by operations cannot be deleted. Operators lose it.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function SkillHolders({ skill, onEdit, onDelete }: { skill: SkillRecord; onEdit(): void; onDelete(): void }) {
  const ops = useLoad((signal) => listOperators({ skill_id: skill.id }, signal), [skill.id, skill.row_version]);
  return (
    <section className="card" data-testid="skill-panel" data-skill-id={skill.id}>
      <div className="card-header">
        <h2>
          <span className="mono">{skill.code}</span> {skill.name}
        </h2>
        <span className="row">
          <button type="button" className="btn sm" onClick={onEdit} data-testid="skill-edit">
            {t("mfg.skillsPage.btn.edit")}
          </button>
          <button type="button" className="btn sm ghost icon" onClick={onDelete} aria-label={`Delete skill ${skill.code}`}>
            <Icon name="trash" />
          </button>
        </span>
      </div>
      <div className="card-body col">
        {skill.description ? <p style={{ margin: 0 }}>{skill.description}</p> : null}
        <h3>Who holds this skill</h3>
        <MfgError error={ops.error} onRetry={ops.reload} />
        {ops.loading && !ops.data ? <Spinner /> : null}
        {ops.data && ops.data.items.length === 0 ? (
          <p className="muted small" style={{ margin: 0 }}>
            Nobody yet. Operations needing {skill.code} cannot be staffed. <Link to={mfgPaths.operators()}>Add the skill to an operator</Link>.
          </p>
        ) : null}
        {ops.data && ops.data.items.length ? (
          <DataTable
            rows={ops.data.items}
            columns={[
              {
                key: "operator",
                header: "Operator",
                width: "minmax(200px, 1.5fr)",
                sortValue: (o) => o.code,
                exportValue: (o) => `${o.code} ${o.name}`,
                render: (o) => (
                  <span className="mfg-ellipsis">
                    <Link to={mfgPaths.operators(o.id)} className="mono">
                      {o.code}
                    </Link>{" "}
                    {o.name}
                  </span>
                ),
              },
              { key: "template", header: "Shift template", width: "minmax(130px, 1fr)", sortValue: (o) => o.shift_template?.code ?? "", exportValue: (o) => o.shift_template?.code ?? "", render: (o) => (o.shift_template ? <Link to={mfgPaths.shifts({ template: o.shift_template.id })}>{o.shift_template.code}</Link> : <span className="faint">None</span>) },
              { key: "shifts", header: "Shifts", width: "minmax(130px, 1fr)", render: (o) => (o.shift_template ? (o.shift_names.length ? o.shift_names.join(", ") : "All") : "") },
              { key: "status", header: "Status", width: "100px", sortValue: (o) => (o.active ? 0 : 1), exportValue: (o) => (o.active ? "Active" : "Inactive"), render: (o) => <ActiveBadge active={o.active} /> },
            ]}
            rowKey={(o) => o.id}
            label={`Holders of ${skill.code}`}
            testId="skill-holders"
            exportName={`skill-${skill.code}-holders`}
            rowExtras={() => ({ testId: "skill-holder" })}
          />
        ) : null}
        <p className="faint small" style={{ margin: 0 }}>
          The data-health check warns when a line with an operation needing this skill works at a time when nobody
          holding it is on shift (e.g. overtime).
        </p>
      </div>
    </section>
  );
}

function SkillDialog({ skill, onClose, onSaved }: { skill: SkillRecord | null; onClose(): void; onSaved(s: SkillRecord): void }) {
  const [code, setCode] = useState(skill?.code ?? "");
  const [name, setName] = useState(skill?.name ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  return (
    <EntityFormDialog
      title={skill ? `Edit skill ${skill.code}` : "New skill"}
      submitLabel={t("mfg.skillsPage.btn.save")}
      onClose={onClose}
      testId="skill-form"
      disabled={!code.trim() || !name.trim()}
      onSubmit={async () => {
        const body = { code: code.trim(), name: name.trim(), description };
        onSaved(skill ? await updateSkill(skill.id, body, skill.row_version) : await createSkill(body));
      }}
    >
      <div className="form-grid">
        <TextField label="Code" value={code} onChange={setCode} required maxLength={32} testId="skill-code" />
        <TextField label="Name" value={name} onChange={setName} required testId="skill-name" />
      </div>
      <TextField label="Description" value={description} onChange={setDescription} maxLength={500} />
    </EntityFormDialog>
  );
}

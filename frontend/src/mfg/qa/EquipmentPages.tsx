/**
 * Equipment and calibration (M7 8, 10): list with due states and a due calendar, the equipment record (calibration
 * history, calibration entry signed per policy with certificate upload, out of service / return to service, impact
 * list after a failed calibration with "Create NCR"), and the overdue banner. Calibration blocks use: results with
 * an invalid gauge are refused, lines with invalid equipment cannot start operations.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { DateInput } from "../../components/DateInput";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { listLines } from "../api/client";
import { createEquipment, getEquipment, getEquipmentImpact, listCalibrations, listEquipment, recordCalibration, setEquipmentStatus, updateEquipment, uploadAttachment } from "../api/clientM7";
import type { Calibration, CalibrationInput, Equipment, EquipmentInput, EquipmentKind } from "../api/typesM7";
import { ConflictBanner, MfgError, Spinner } from "../components/Feedback";
import { FormErrors, TextField } from "../components/Field";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { isConflict, useLoad } from "../lib/useMfg";
import { fmtDate } from "../lib/format";
import { formatNumber } from "../../lib/locale";
import { plural, t, type StringKey } from "../../lib/i18n";
import { usePersonName } from "./common";
import { CalChip, CAL_STATE, EQ_STATUS, EqStatusChip, labelOf, LotStatusChip } from "./labels";
import { AttachmentsTab, HistoryTab, LinksTab, RecordHeader, RecordTabs, Section, SignatureList, SignaturesTab, standardTabs, TabPanel, useChangeReason } from "./RecordShell";
import { QaWorklist } from "./Worklist";
import "./qa.css";

const KIND_KEY: Record<EquipmentKind, StringKey> = { gauge: "qa.eq.kind.gauge", instrument: "qa.eq.kind.instrument", fixture: "qa.eq.kind.fixture", tool: "qa.eq.kind.tool", line_equipment: "qa.eq.kind.lineEquipment", chamber: "qa.eq.kind.chamber" };
const RESULT_KEY: Record<string, StringKey> = { pass: "qa.eq.result.pass", adjusted_pass: "qa.eq.result.adjusted", fail: "qa.eq.result.fail" };
const todayIso = () => new Date().toISOString().slice(0, 10);

// ---------------------------------------------------------------- list
export function EquipmentListPage() {
  const canEdit = useCan("equipment_edit");
  const [params, setParams] = useSearchParams();
  const mode = params.get("mode") === "calendar" ? "calendar" : "list";
  const due = useLoad((s) => listEquipment({ due_within_days: 0, limit: 200 }, s).catch(() => null), []);
  useEffect(() => {
    document.title = t("qa.eq.str.docTitle");
  }, []);
  const overdue = (due.data?.items ?? []).filter((e) => e.due_state === "overdue" || e.due_state === "in_grace");
  const columns = useMemo<Column<Equipment>[]>(
    () => [
      {
        key: "code",
        header: t("qa.eq.head.code"),
        width: "120px",
        sortKey: "code",
        exportValue: (e) => e.code,
        render: (e) => (
          <Link to={mfgPaths.qaEquipment(e.id)} className="mono" tabIndex={-1} onClick={(ev) => ev.stopPropagation()}>
            {e.code}
          </Link>
        ),
      },
      { key: "name", header: t("qa.plans.head.name"), width: "minmax(180px, 2fr)", render: (e) => <span className="mfg-ellipsis">{e.name}</span> },
      { key: "kind", header: t("qa.capa.head.kind"), width: "130px", render: (e) => t(KIND_KEY[e.kind]) },
      { key: "class", header: t("qa.eq.head.class"), width: "110px", render: (e) => <span className="mono small">{e.equipment_class}</span> },
      { key: "status", header: t("qa.ncr.head.status"), width: "130px", exportValue: (e) => labelOf(EQ_STATUS, e.status), render: (e) => <EqStatusChip s={e.status} /> },
      { key: "cal", header: t("qa.eq.head.calibration"), width: "150px", exportValue: (e) => labelOf(CAL_STATE, e.due_state), render: (e) => <CalChip state={e.due_state} valid={e.valid} due={e.due_on} /> },
      { key: "due", header: t("qa.eq.head.due"), width: "120px", sortKey: "due_on", render: (e) => fmtDate(e.due_on) },
      { key: "loc", header: t("qa.eq.head.location"), width: "minmax(120px, 1fr)", drop: 1, render: (e) => <span className="mfg-ellipsis">{e.location}</span> },
    ],
    [],
  );
  const above = (
    <>
      {overdue.length ? (
        <Banner tone="danger" icon="alert" title={t("qa.eq.title.overdue", { n: plural(overdue.length, t("qa.eq.str.item"), t("qa.eq.str.items")) })} testId="eq-overdue-banner">
          {overdue.slice(0, 6).map((e, i) => (
            <span key={e.id}>
              {i ? ", " : ""}
              <Link to={mfgPaths.qaEquipment(e.id)} className="mono">
                {e.code}
              </Link>{" "}
              <span className="muted">{t("qa.eq.tpl.dueSince", { d: fmtDate(e.due_on) })}</span>
            </span>
          ))}
          <div className="small">{t("qa.eq.text.overdueEffect")}</div>
        </Banner>
      ) : null}
      <div className="btn-group" role="group" aria-label={t("qa.eq.aria.view")}>
        <button type="button" className="btn" aria-pressed={mode === "list"} onClick={() => setParams((p) => (p.delete("mode"), p), { replace: true })}>
          <Icon name="list" /> {t("qa.eq.btn.list")}
        </button>
        <button type="button" className="btn" aria-pressed={mode === "calendar"} onClick={() => setParams((p) => (p.set("mode", "calendar"), p), { replace: true })} data-testid="eq-calendar-toggle">
          <Icon name="calendar" /> {t("qa.eq.btn.calendar")}
        </button>
      </div>
      {mode === "calendar" ? <DueCalendar /> : null}
    </>
  );
  return (
    <QaWorklist<Equipment>
      title={t("qa.eq.title")}
      description={t("qa.eq.desc")}
      actions={
        canEdit ? (
          <Link className="btn primary" to={mfgPaths.qaEquipment("new")} data-testid="eq-new">
            <Icon name="plus" /> {t("qa.eq.btn.new")}
          </Link>
        ) : null
      }
      above={above}
      pageKey="qa-equipment"
      testId="qa-eq-page"
      searchPlaceholder={t("qa.eq.ph.search")}
      views={[
        { key: "due", label: t("qa.eq.view.due"), query: { due_within_days: "14" } },
        { key: "overdue", label: t("qa.lots.view.overdue"), query: { due_within_days: "0" } },
      ]}
      statusOptions={[{ value: "", label: t("qa.list.status.all") }, ...Object.keys(EQ_STATUS).map((s) => ({ value: s, label: labelOf(EQ_STATUS, s) }))]}
      fetch={(q, signal) => listEquipment(q, signal)}
      columns={columns}
      card={{ title: "code", status: "cal", fields: ["name", "status", "due"] }}
      rowKey={(e) => e.id}
      rowExtras={(e) => ({ testId: "eq-row", data: { valid: e.valid, state: e.due_state } })}
      rowPath={(e) => mfgPaths.qaEquipment(e.id)}
      empty={t("qa.eq.empty")}
      noun={t("qa.eq.str.noun")}
      sortDefault="due_on"
    />
  );
}

/** Month calendar of calibration due dates (current and next month). */
function DueCalendar() {
  const [offset, setOffset] = useState(0);
  const base = new Date();
  const first = new Date(base.getFullYear(), base.getMonth() + offset, 1);
  const data = useLoad((s) => listEquipment({ due_within_days: 400, limit: 1000 }, s), []);
  const byDay = new Map<string, Equipment[]>();
  for (const e of data.data?.items ?? []) if (e.due_on) byDay.set(e.due_on, [...(byDay.get(e.due_on) ?? []), e]);
  const startDow = (first.getDay() + 6) % 7;
  const days: Date[] = [];
  for (let i = -startDow; i < 42 - startDow; i++) days.push(new Date(first.getFullYear(), first.getMonth(), 1 + i));
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const todayKey = iso(new Date());
  const monthLabel = fmtDate(iso(first)).replace(/^\d+\s/, "");
  const DOW: StringKey[] = ["mfg.format.str.mon", "mfg.format.str.tue", "mfg.format.str.wed", "mfg.format.str.thu", "mfg.format.str.fri", "mfg.format.str.sat", "mfg.format.str.sun"];
  return (
    <section className="card" data-testid="eq-calendar">
      <div className="card-header">
        <h2>{t("qa.eq.tpl.calendar", { m: monthLabel })}</h2>
        <div className="row" style={{ gap: 4 }}>
          <button type="button" className="btn sm" onClick={() => setOffset(offset - 1)} aria-label={t("qa.eq.aria.prev")}>
            <Icon name="chevron-right" size={14} className="flip-x" />
          </button>
          <button type="button" className="btn sm" onClick={() => setOffset(0)}>
            {t("qa.eq.btn.today")}
          </button>
          <button type="button" className="btn sm" onClick={() => setOffset(offset + 1)} aria-label={t("qa.eq.aria.next")}>
            <Icon name="chevron-right" size={14} />
          </button>
        </div>
      </div>
      <div className="card-body">
        <div className="qa-cal-grid" role="grid" aria-label={t("qa.eq.tpl.calendar", { m: monthLabel })}>
          {DOW.map((k) => (
            <div key={k} className="qa-cal-head" role="columnheader">
              {t(k)}
            </div>
          ))}
          {days.map((d) => {
            const k = iso(d);
            const list = byDay.get(k) ?? [];
            return (
              <div key={k} className={`qa-cal-day${d.getMonth() !== first.getMonth() ? " other" : ""}${k === todayKey ? " today" : ""}`} role="gridcell">
                <span className="qa-cal-n">{d.getDate()}</span>
                {list.slice(0, 3).map((e) => (
                  <Link key={e.id} to={mfgPaths.qaEquipment(e.id)} title={`${e.code} ${e.name}`}>
                    <span className={`badge ${e.due_state === "overdue" ? "danger" : e.due_state === "ok" ? "info" : "warn"}`} style={{ maxWidth: "100%" }}>
                      <span className="mono mfg-ellipsis">{e.code}</span>
                    </span>
                  </Link>
                ))}
                {list.length > 3 ? <span className="small muted">{t("qa.eq.tpl.more", { n: list.length - 3 })}</span> : null}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- record
const blankEq = (): EquipmentInput => ({ code: "", name: "", kind: "gauge", equipment_class: "", line_id: null, tool_pool_id: null, serial_no: "", manufacturer: "", location: "", calibration_required: true, interval_days: 365, grace_days: 0, due_on: null, procedure_ref: "", provider: "internal", note: "" });
const eqInput = (e: Equipment): EquipmentInput => ({ code: e.code, name: e.name, kind: e.kind, equipment_class: e.equipment_class, line_id: e.line_id, tool_pool_id: e.tool_pool_id, serial_no: e.serial_no, manufacturer: e.manufacturer, location: e.location, calibration_required: e.calibration_required, interval_days: e.interval_days, grace_days: e.grace_days, due_on: e.due_on, procedure_ref: e.procedure_ref, provider: e.provider === "external" ? "external" : "internal", note: e.note });

export function EquipmentPage() {
  const { equipmentId = "" } = useParams();
  const isNew = equipmentId === "new";
  const navigate = useNavigate();
  const canEdit = useCan("equipment_edit");
  const reason = useChangeReason();
  const rec = useLoad((s) => (isNew ? null : getEquipment(equipmentId, s)), [equipmentId]);
  const lines = useLoad((s) => listLines({ active: true }, s).catch(() => null), []);
  const e = rec.data;
  const [form, setForm] = useState<EquipmentInput>(blankEq());
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("calibrations");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [calibrating, setCalibrating] = useState(false);
  const [statusTo, setStatusTo] = useState<null | "active" | "out_of_service" | "retired">(null);
  const [calTick, setCalTick] = useState(0);
  useEffect(() => {
    if (e) {
      setForm(eqInput(e));
      setDirty(false);
      document.title = `${e.code} - ${t("qa.eq.title")}`;
    } else if (isNew) {
      setTab("details");
      document.title = t("qa.eq.str.newDocTitle");
    }
  }, [e, isNew]);
  if (!isNew && rec.loading && !e) return <Spinner />;
  if (!isNew && !e) return <MfgError error={rec.error} onRetry={rec.reload} />;
  // review M6: while the item is not valid its calibration settings, line and tool pool are fixed (409
  // QA_EQUIPMENT_BLOCKING) - the way out is a calibration (or retiring it); the due date moves only by calibrations
  const blocked = Boolean(e && !e.valid && e.status !== "retired");
  const set = (p: Partial<EquipmentInput>) => {
    setForm((f) => ({ ...f, ...p }));
    setDirty(true);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const c = await createEquipment(form);
        toast(t("qa.eq.toast.created", { c: c.code }));
        setDirty(false);
        navigate(mfgPaths.qaEquipment(c.id), { replace: true });
      } else if (e) {
        const r = await reason.ask(e.code);
        if (r === null) return;
        rec.setData(await updateEquipment(e.id, form, e.row_version, r));
        setDirty(false);
        toast(t("qa.eq.toast.saved"));
      }
    } catch (x) {
      setError(x);
    } finally {
      setBusy(false);
    }
  };
  const formView = (
    <FormErrors error={error}>
      <Section title={t("qa.fa.head.details")}>
        {blocked && canEdit ? (
          <div style={{ padding: "12px 16px 0" }}>
            <Banner tone="warn" icon="lock" title={t("qa.eq.title.blocked")} testId="eq-blocked">
              {t("qa.eq.text.blocked")}
            </Banner>
          </div>
        ) : null}
        <div className="qa-form-grid">
          <TextField label={t("qa.eq.head.code")} name="code" value={form.code} onChange={(v) => set({ code: v.toUpperCase() })} disabled={!canEdit || !isNew} required maxLength={32} testId="eq-code" hint={t("qa.eq.hint.code")} />
          <div className="span-2">
            <TextField label={t("qa.plans.head.name")} name="name" value={form.name} onChange={(v) => set({ name: v })} disabled={!canEdit} required />
          </div>
          <div className="field">
            <label htmlFor="eq-kind">{t("qa.capa.head.kind")}</label>
            <select id="eq-kind" className="select" value={form.kind} disabled={!canEdit} onChange={(x) => set({ kind: x.target.value as EquipmentKind })}>
              {(Object.keys(KIND_KEY) as EquipmentKind[]).map((k) => (
                <option key={k} value={k}>
                  {t(KIND_KEY[k])}
                </option>
              ))}
            </select>
          </div>
          <TextField label={t("qa.eq.head.class")} name="equipment_class" value={form.equipment_class} onChange={(v) => set({ equipment_class: v.toUpperCase() })} disabled={!canEdit} required hint={t("qa.eq.hint.class")} />
          <div className="field">
            <label htmlFor="eq-line">{t("qa.eq.label.line")}</label>
            <select id="eq-line" className="select" value={form.line_id ?? ""} disabled={!canEdit || blocked} onChange={(x) => set({ line_id: x.target.value || null })}>
              <option value="">{t("qa.settings.str.none")}</option>
              {(lines.data?.items ?? []).map((l) => (
                <option key={l.id} value={l.id}>
                  {l.code} {l.name}
                </option>
              ))}
            </select>
            <span className="hint">{t("qa.eq.hint.line")}</span>
          </div>
          <TextField label={t("qa.eq.label.serial")} name="serial_no" value={form.serial_no} onChange={(v) => set({ serial_no: v })} disabled={!canEdit} />
          <TextField label={t("qa.eq.label.manufacturer")} name="manufacturer" value={form.manufacturer} onChange={(v) => set({ manufacturer: v })} disabled={!canEdit} />
          <TextField label={t("qa.eq.head.location")} name="location" value={form.location} onChange={(v) => set({ location: v })} disabled={!canEdit} />
          <label className="checkbox" style={{ alignSelf: "end" }}>
            <input type="checkbox" checked={form.calibration_required} disabled={!canEdit || blocked} onChange={(x) => set({ calibration_required: x.target.checked })} /> {t("qa.eq.label.required")}
          </label>
          {form.calibration_required ? (
            <>
              <TextField label={t("qa.eq.label.interval")} name="interval_days" type="number" value={form.interval_days === null ? "" : String(form.interval_days)} onChange={(v) => set({ interval_days: v ? Number(v) : null })} disabled={!canEdit || blocked} required />
              <TextField label={t("qa.eq.label.grace")} name="grace_days" type="number" value={String(form.grace_days)} onChange={(v) => set({ grace_days: Number(v) || 0 })} disabled={!canEdit || blocked} hint={t("qa.eq.hint.grace")} />
              {isNew ? (
                <div className="field">
                  <label htmlFor="eq-due">{t("qa.eq.head.due")}</label>
                  <DateInput id="eq-due" value={form.due_on ?? ""} onChange={(v) => set({ due_on: v || null })} />
                </div>
              ) : (
                <div className="field">
                  <span className="field-label">{t("qa.eq.head.due")}</span>
                  <span data-testid="eq-due-readonly">{fmtDate(form.due_on)}</span>
                  <span className="hint">{t("qa.eq.hint.dueViaCalibration")}</span>
                </div>
              )}
              <TextField label={t("qa.eq.label.procedure")} name="procedure_ref" value={form.procedure_ref} onChange={(v) => set({ procedure_ref: v })} disabled={!canEdit} />
              <div className="field">
                <label htmlFor="eq-prov">{t("qa.eq.label.provider")}</label>
                <select id="eq-prov" className="select" value={form.provider} disabled={!canEdit} onChange={(x) => set({ provider: x.target.value as "internal" })}>
                  <option value="internal">{t("qa.eq.str.internal")}</option>
                  <option value="external">{t("qa.eq.str.external")}</option>
                </select>
              </div>
            </>
          ) : null}
          <div className="field span-all">
            <label htmlFor="eq-note">{t("qa.plans.label.note")}</label>
            <input id="eq-note" className="input" value={form.note} maxLength={500} disabled={!canEdit} onChange={(x) => set({ note: x.target.value })} />
          </div>
        </div>
      </Section>
    </FormErrors>
  );
  if (isNew)
    return (
      <div className="col gap-lg" data-testid="eq-new-page">
        <UnsavedChangesGuard when={dirty} what={t("qa.eq.str.thisEq")} />
        <PageHeader
          title={t("qa.eq.str.newTitle")}
          description={t("qa.eq.desc")}
          actions={
            <button type="button" className="btn primary" disabled={busy || !form.code.trim() || !form.name.trim() || !form.equipment_class.trim()} onClick={() => void save()} data-testid="eq-save">
              <Icon name="save" /> {t("qa.ncr.btn.create")}
            </button>
          }
        />
        <MfgError error={error} />
        {formView}
      </div>
    );
  const x = e!;
  return (
    <div className="col gap-lg" data-testid="eq-page" data-status={x.status}>
      <UnsavedChangesGuard when={dirty} what={t("qa.eq.str.thisEq")} />
      <RecordHeader
        crumbs={[[t("nav.mfg.section.qa-equipment"), mfgPaths.qaEquipmentList()]]}
        number={x.code}
        title={x.name}
        status={<EqStatusChip s={x.status} />}
        chips={<CalChip state={x.due_state} valid={x.valid} due={x.due_on} />}
        facts={[
          [t("qa.capa.head.kind"), t(KIND_KEY[x.kind])],
          [t("qa.eq.head.class"), <span key="c" className="mono">{x.equipment_class}</span>],
          [t("qa.eq.label.last"), fmtDate(x.last_calibrated_on)],
          [t("qa.eq.head.due"), x.calibration_required ? fmtDate(x.due_on) : t("qa.status.cal.notRequired")],
          [t("qa.eq.label.interval"), x.interval_days ? t("qa.eq.tpl.days", { n: x.interval_days }) : null],
          [t("qa.eq.head.location"), x.location],
          [t("qa.eq.label.serial"), x.serial_no],
        ]}
        actions={
          canEdit ? (
            <>
              {x.status === "active" ? (
                <button type="button" className="btn ghost" onClick={() => setStatusTo("out_of_service")} data-testid="eq-oos">
                  <Icon name="ban" /> {t("qa.eq.btn.oos")}
                </button>
              ) : x.status === "out_of_service" ? (
                <button type="button" className="btn" onClick={() => setStatusTo("active")} data-testid="eq-return">
                  <Icon name="check" /> {t("qa.eq.btn.return")}
                </button>
              ) : null}
              <button type="button" className="btn" disabled={busy || !dirty} onClick={() => void save()}>
                <Icon name="save" /> {t("qa.plans.btn.save")}
              </button>
              {x.calibration_required && x.status !== "retired" ? (
                <button type="button" className="btn primary" onClick={() => setCalibrating(true)} data-testid="eq-calibrate">
                  <Icon name="check" /> {t("qa.eq.btn.calibrate")}
                </button>
              ) : null}
            </>
          ) : null
        }
      />
      {!x.valid && x.status !== "retired" ? (
        <Banner tone="danger" icon="ban" title={x.status === "out_of_service" ? t("qa.eq.title.oos") : t("qa.eq.title.invalid")} testId="eq-invalid">
          {x.line_id ? t("qa.eq.text.invalidLine") : t("qa.eq.text.invalid")}
        </Banner>
      ) : null}
      {isConflict(error) ? <ConflictBanner onReload={() => (setError(null), rec.reload())} /> : <MfgError error={error} />}
      <RecordTabs
        label={t("qa.eq.aria.tabs")}
        value={tab}
        onChange={setTab}
        tabs={[{ key: "calibrations", label: t("qa.eq.tab.calibrations") }, ...(x.failed_on ? [{ key: "impact", label: t("qa.eq.tab.impact"), testId: "eq-tab-impact" }] : []), { key: "details", label: t("qa.shell.tab.details") }, ...standardTabs(x)]}
      />
      {tab === "calibrations" ? (
        <TabPanel id="calibrations">
          <Calibrations key={calTick} eq={x} />
        </TabPanel>
      ) : null}
      {tab === "impact" ? (
        <TabPanel id="impact">
          <Impact eq={x} />
        </TabPanel>
      ) : null}
      {tab === "details" ? <TabPanel id="details">{formView}</TabPanel> : null}
      {tab === "links" ? (
        <TabPanel id="links">
          <LinksTab links={x.links} fromType="equipment" fromId={x.id} canEdit={canEdit} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "attachments" ? (
        <TabPanel id="attachments">
          <AttachmentsTab attachments={x.attachments} entityType="equipment" entityId={x.id} canEdit={canEdit} locked={false} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "history" ? (
        <TabPanel id="history">
          <HistoryTab entityType="equipment" entityId={x.id} />
        </TabPanel>
      ) : null}
      {tab === "signatures" ? (
        <TabPanel id="signatures">
          <SignaturesTab signatures={x.signatures} recordType="equipment" recordId={x.id} />
        </TabPanel>
      ) : null}
      {reason.dialog}
      {calibrating ? <CalibrationDialog eq={x} onClose={() => setCalibrating(false)} onDone={() => (setCalibrating(false), rec.reload(), setCalTick((n) => n + 1))} /> : null}
      {statusTo ? (
        <SignatureDialog<Equipment>
          title={statusTo === "active" ? t("qa.eq.tpl.returnTitle", { c: x.code }) : t("qa.eq.tpl.oosTitle", { c: x.code })}
          recordType="equipment"
          recordId={x.id}
          recordLabel={x.code}
          action={statusTo === "active" ? "return_to_service" : "status"}
          signable={statusTo === "active"}
          meaning="approved"
          danger={statusTo !== "active"}
          commentRequired
          commentLabel={t("qa.eq.label.statusReason")}
          submitLabel={statusTo === "active" ? t("qa.eq.btn.signReturn") : t("qa.eq.btn.oos")}
          plainLabel={statusTo === "active" ? t("qa.eq.btn.return") : t("qa.eq.btn.oos")}
          effect={statusTo === "active" ? t("qa.eq.text.returnEffect") : t("qa.eq.text.oosEffect")}
          perform={(sig, comment) => setEquipmentStatus(x.id, statusTo, comment, x.row_version, sig)}
          onDone={(res) => {
            toast(signedToast(res, t("qa.eq.toast.status")));
            setStatusTo(null);
            if (res.status === 200) rec.setData(res.record);
            else rec.reload();
          }}
          onClose={() => setStatusTo(null)}
        />
      ) : null}
    </div>
  );
}

function Calibrations({ eq }: { eq: Equipment }) {
  const person = usePersonName();
  const data = useLoad((s) => listCalibrations(eq.id, s), [eq.id]);
  const cols: Column<Calibration>[] = [
    { key: "on", header: t("qa.eq.head.performed"), width: "120px", sortValue: (c) => c.performed_on, render: (c) => fmtDate(c.performed_on) },
    { key: "result", header: t("qa.capa.label.result"), width: "150px", sortValue: (c) => c.result, render: (c) => <span className={`badge ${c.result === "fail" ? "danger" : "ok"}`}><Icon name={c.result === "fail" ? "x" : "check"} /> {t(RESULT_KEY[c.result])}</span> },
    { key: "by", header: t("qa.eq.head.by"), width: "minmax(140px, 1fr)", render: (c) => c.provider_name || person(c.performed_by) },
    { key: "cert", header: t("qa.eq.head.certificate"), width: "minmax(130px, 1fr)", render: (c) => <span className="mono small">{c.certificate_ref}</span> },
    { key: "next", header: t("qa.eq.head.nextDue"), width: "120px", render: (c) => fmtDate(c.next_due_on) },
    { key: "found", header: t("qa.eq.head.asFound"), width: "minmax(160px, 1.5fr)", drop: 1, wrap: true, render: (c) => [c.as_found, c.as_left].filter(Boolean).join(" → ") },
    { key: "sig", header: t("qa.shell.tab.signatures"), width: "minmax(200px, 2fr)", wrap: true, exportValue: (c) => c.signatures.map((s) => s.signer_legal_name).join("; "), render: (c) => (c.signatures.length ? <SignatureList signatures={c.signatures} compact /> : <span className="faint">—</span>) },
  ];
  return (
    <section className="card card-table">
      <div className="card-header">
        <h2>{t("qa.eq.tab.calibrations")}</h2>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <DataTable rows={data.data?.items ?? []} columns={cols} rowKey={(c) => c.id} label={t("qa.eq.tab.calibrations")} tableId="eq-calibrations" loading={data.loading && !data.data} empty={t("qa.eq.empty.cal")} exportName={`${eq.code}-calibrations`} />
    </section>
  );
}

function CalibrationDialog({ eq, onClose, onDone }: { eq: Equipment; onClose(): void; onDone(): void }) {
  const [f, setF] = useState<CalibrationInput>({ performed_on: todayIso(), performed_by: null, provider_name: "", result: "pass", as_found: "", as_left: "", certificate_ref: "", next_due_on: null });
  const [file, setFile] = useState<File | null>(null);
  const nextDue = f.next_due_on ?? (eq.interval_days ? new Date(new Date(`${f.performed_on}T00:00:00Z`).getTime() + eq.interval_days * 864e5).toISOString().slice(0, 10) : null);
  return (
    <SignatureDialog<Calibration>
      title={t("qa.eq.tpl.calTitle", { c: eq.code })}
      recordType="calibration"
      recordId={eq.id}
      recordLabel={eq.code}
      action="record"
      meaning="performed"
      danger={f.result === "fail"}
      submitLabel={t("qa.eq.btn.signCal")}
      plainLabel={t("qa.eq.btn.saveCal")}
      canSubmit={Boolean(f.performed_on)}
      effect={f.result === "fail" ? t("qa.eq.text.failEffect") : t("qa.eq.tpl.passEffect", { d: fmtDate(nextDue) })}
      perform={async (sig) => {
        const res = await recordCalibration(eq.id, f, sig);
        if (res.status === 200 && file) {
          try {
            await uploadAttachment("calibration", res.record.id, file);
          } catch {
            toast(t("qa.eq.toast.certFailed"), "warn");
          }
        }
        return res;
      }}
      onDone={(res) => {
        toast(signedToast(res, t("qa.eq.toast.cal")));
        onDone();
      }}
      onClose={onClose}
    >
      <div className="qa-form-grid">
        <div className="field">
          <label htmlFor="cal-on">{t("qa.eq.head.performed")}</label>
          <DateInput id="cal-on" value={f.performed_on} max={todayIso()} onChange={(v) => setF({ ...f, performed_on: v })} />
        </div>
        <div className="field">
          <label htmlFor="cal-res">{t("qa.capa.label.result")}</label>
          <select id="cal-res" className="select" value={f.result} onChange={(e) => setF({ ...f, result: e.target.value as CalibrationInput["result"] })} data-testid="cal-result">
            {Object.keys(RESULT_KEY).map((k) => (
              <option key={k} value={k}>
                {t(RESULT_KEY[k])}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="cal-prov">{t("qa.eq.label.providerName")}</label>
          <input id="cal-prov" className="input" value={f.provider_name} onChange={(e) => setF({ ...f, provider_name: e.target.value })} maxLength={200} />
        </div>
        <div className="field">
          <label htmlFor="cal-cert">{t("qa.eq.head.certificate")}</label>
          <input id="cal-cert" className="input" value={f.certificate_ref} onChange={(e) => setF({ ...f, certificate_ref: e.target.value })} maxLength={200} />
        </div>
        <div className="field">
          <label htmlFor="cal-next">{t("qa.eq.head.nextDue")}</label>
          <DateInput id="cal-next" value={f.next_due_on ?? ""} min={f.performed_on} onChange={(v) => setF({ ...f, next_due_on: v || null })} />
          <span className="hint">{t("qa.eq.hint.next", { d: fmtDate(nextDue) })}</span>
        </div>
        <div className="field">
          <label htmlFor="cal-file">{t("qa.eq.label.file")}</label>
          <input id="cal-file" type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        <div className="field span-2">
          <label htmlFor="cal-found">{t("qa.eq.head.asFound")}</label>
          <input id="cal-found" className="input" value={f.as_found} onChange={(e) => setF({ ...f, as_found: e.target.value })} maxLength={2000} />
        </div>
        <div className="field span-2">
          <label htmlFor="cal-left">{t("qa.eq.label.asLeft")}</label>
          <input id="cal-left" className="input" value={f.as_left} onChange={(e) => setF({ ...f, as_left: e.target.value })} maxLength={2000} />
        </div>
      </div>
    </SignatureDialog>
  );
}

function Impact({ eq }: { eq: Equipment }) {
  const data = useLoad((s) => getEquipmentImpact(eq.id, s), [eq.id]);
  const canNcr = useCan("ncr_edit");
  type Row = NonNullable<typeof data.data>["inspection_lots"][number];
  const cols: Column<Row>[] = [
    { key: "lot", header: t("qa.lots.head.lot"), width: "130px", render: (r) => <Link to={mfgPaths.qaLot(r.id)} className="mono">{r.number}</Link> },
    { key: "status", header: t("qa.ncr.head.status"), width: "160px", render: (r) => <LotStatusChip s={r.status} /> },
    { key: "stock", header: t("qa.lots.head.stockLot"), width: "minmax(120px, 1fr)", render: (r) => <span className="mono">{r.lot_code ?? ""}</span> },
    { key: "results", header: t("qa.eq.head.results"), width: "120px", align: "right", render: (r) => formatNumber(r.results) },
    {
      key: "ncr",
      header: "",
      label: t("qa.cmp.btn.ncr"),
      width: "140px",
      hideable: false,
      render: (r) =>
        canNcr && r.decision === "accept" ? (
          <Link className="btn sm" to={mfgPaths.qaNcr("new")}>
            <Icon name="alert" /> {t("qa.cmp.btn.ncr")}
          </Link>
        ) : null,
    },
  ];
  return (
    <section className="card card-table" data-testid="eq-impact">
      <div className="card-header">
        <h2>{t("qa.eq.tab.impact")}</h2>
      </div>
      <p className="small" style={{ margin: "8px 16px" }}>
        {data.data ? t("qa.eq.tpl.impact", { n: formatNumber(data.data.results), d: fmtDate(data.data.since) || "—" }) : null}
      </p>
      <MfgError error={data.error} onRetry={data.reload} />
      <DataTable rows={data.data?.inspection_lots ?? []} columns={cols} rowKey={(r) => r.id} label={t("qa.eq.tab.impact")} tableId="eq-impact" loading={data.loading && !data.data} empty={t("qa.eq.empty.impact")} />
    </section>
  );
}

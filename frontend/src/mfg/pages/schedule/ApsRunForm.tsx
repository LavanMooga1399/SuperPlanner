/**
 * New schedule run (M3 12, 6.1 `ApsParams`). Guided: one click schedules the whole plant with the plant's overtime
 * default. The overtime policy is shown up front (M3 16 Q1: `suggest` default, `allow` on demand, `off` as a
 * baseline). Planning options (horizon, MRP run, split, improvement time) and the what-if section (start time,
 * capacity changes, ignore material) are behind toggles. `initial` prefills the form (e.g. "Re-run with these
 * opened" from the overtime tab).
 */
import { useEffect, useState } from "react";
import { Icon } from "../../../components/Icon";
import { listMrpRuns } from "../../api/clientM2";
import { createApsRun } from "../../api/clientM3";
import type { MrpRunRecord } from "../../api/typesM2";
import type { ApsParams, ApsRunRecord, CapacityOverride, OvertimePolicy, PlantM3Fields } from "../../api/typesM3";
import { MfgError } from "../../components/Feedback";
import { numOrNull } from "../../components/Field";
import { listLines } from "../../api/client";
import type { LineRecord, PlantRecord } from "../../api/types";
import { usePlantClock } from "../../lib/plantTime";
import { useLoad, usePlant } from "../../lib/useMfg";
import { toast } from "../../../components/Toast";
import { t } from "../../../lib/i18n";

export const POLICY_TEXT: Record<OvertimePolicy, { label: string; help: string }> = {
  off: { label: t("mfg.apsRunForm.str.regularShiftsOnly"), help: t("mfg.apsRunForm.str.baselineNoOvertimeIsUsed") },
  suggest: { label: t("mfg.apsRunForm.str.suggestOvertime"), help: t("mfg.apsRunForm.str.plansOnRegularShiftsAnd") },
  allow: { label: t("mfg.apsRunForm.str.useOvertimeAutomatically"), help: t("mfg.apsRunForm.str.opensExtraShiftsWithinWeekly") },
};

export function PolicyPicker({ value, onChange, name = "aps-policy" }: { value: OvertimePolicy; onChange(v: OvertimePolicy): void; name?: string }) {
  return (
    <fieldset className="mfg-fieldset" data-testid="aps-policy">
      <legend>{t("mfg.apsRunForm.head.overtime")}</legend>
      <div className="row wrap" role="radiogroup" aria-label={t("mfg.apsRunForm.aria.overtimePolicy")}>
        {(["suggest", "allow", "off"] as OvertimePolicy[]).map((p) => (
          <label key={p} className={`card card-body col${value === p ? " mfg-inline-form" : ""}`} style={{ flex: "1 1 220px", gap: 4, cursor: "pointer" }}>
            <span className="row">
              <input type="radio" name={name} checked={value === p} onChange={() => onChange(p)} data-testid={`aps-policy-${p}`} />
              <strong>{POLICY_TEXT[p].label}</strong>
            </span>
            <span className="small muted">{POLICY_TEXT[p].help}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

interface OvDraft {
  key: number;
  target_id: string;
  start: string;
  end: string;
  mode: CapacityOverride["mode"];
}
let k = 0;

export function ApsRunForm({ onClose, onDone, initial }: { onClose(): void; onDone(r: ApsRunRecord): void; initial?: ApsParams | null }) {
  const plant = usePlant();
  const clock = usePlantClock();
  const p3 = plant.data as (PlantRecord & PlantM3Fields) | null;
  const [label, setLabel] = useState(initial?.label ?? "");
  const [policy, setPolicy] = useState<OvertimePolicy>(initial?.overtime ?? "suggest");
  const [policyTouched, setPolicyTouched] = useState(Boolean(initial?.overtime));
  const [expert, setExpert] = useState(false);
  const [whatIf, setWhatIf] = useState(Boolean(initial?.capacity_overrides?.length || initial?.as_of || initial?.material === "ignore"));
  const [horizon, setHorizon] = useState(initial?.horizon_days ? String(initial.horizon_days) : "");
  const [mrpRun, setMrpRun] = useState(initial?.mrp_run_id ?? "");
  const [split, setSplit] = useState(initial?.split ?? true);
  const [includePlanned, setIncludePlanned] = useState(initial?.include_planned ?? true);
  const [improve, setImprove] = useState(String(initial?.improve_seconds ?? 30));
  const [asOf, setAsOf] = useState(initial?.as_of ? clock.toLocal(initial.as_of) : "");
  const [ignoreMaterial, setIgnoreMaterial] = useState(initial?.material === "ignore");
  const [ovs, setOvs] = useState<OvDraft[]>(() =>
    (initial?.capacity_overrides ?? []).map((o) => ({ key: ++k, target_id: o.target_id, start: clock.toLocal(o.start), end: clock.toLocal(o.end), mode: o.mode })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const mrpRuns = useLoad((signal) => listMrpRuns({ kind: "live", limit: 20, offset: 0 }, signal), []);
  const lines = useLoad((signal) => listLines({ active: true }, signal), []);

  // plant default policy (3.1), unless prefilled or chosen
  useEffect(() => {
    if (!policyTouched && p3?.aps_overtime_policy) setPolicy(p3.aps_overtime_policy);
  }, [p3?.aps_overtime_policy, policyTouched]);

  const h = numOrNull(horizon);
  const imp = numOrNull(improve);
  const hBad = h !== null && !(Number.isInteger(h) && h >= 7 && h <= 120);
  const impBad = imp === null || !(Number.isInteger(imp) && imp >= 0 && imp <= 300);
  const ovBad = ovs.some((o) => !o.target_id || !o.start || !o.end || o.start >= o.end);

  const params: ApsParams = {
    label: label.trim(),
    overtime: policy,
    ...(initial?.copy_of ? { copy_of: initial.copy_of } : {}),
    ...(expert || initial
      ? { horizon_days: h, mrp_run_id: mrpRun || null, split, include_planned: includePlanned, improve_seconds: imp ?? 30 }
      : {}),
    ...(whatIf
      ? {
          as_of: asOf ? clock.fromLocal(asOf) : null,
          material: ignoreMaterial ? "ignore" : "strict",
          capacity_overrides: ovs.map((o) => ({ target_type: "line", target_id: o.target_id, start: clock.fromLocal(o.start), end: clock.fromLocal(o.end), mode: o.mode })),
        }
      : {}),
  };
  const isWhatIf = whatIf && (Boolean(asOf) || ignoreMaterial || ovs.length > 0);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await createApsRun(params));
      toast(t("mfg.apsRunForm.toast.scheduleRunStarted"));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <section className="card mfg-inline-form" data-testid="aps-run-form" aria-labelledby="aps-form-title">
      <div className="card-header">
        <h2 id="aps-form-title">{t("mfg.apsRunForm.head.scheduleTheWholePlant")}</h2>
        <button type="button" className="btn sm ghost" onClick={onClose}>
          <Icon name="x" /> {t("mfg.apsRunForm.btn.close")}
        </button>
      </div>
      <div className="card-body col">
        <p className="muted small" style={{ margin: 0 }}>
          {t("mfg.apsRunForm.text.placesEveryOperationOfThe")}
        </p>
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="aps-label">{t("mfg.apsRunForm.label.nameOptional")}</label>
          <input id="aps-label" className="input" maxLength={100} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("mfg.apsRunForm.ph.egWeek45")} data-testid="aps-label" />
        </div>
        <PolicyPicker
          value={policy}
          onChange={(v) => {
            setPolicy(v);
            setPolicyTouched(true);
          }}
        />
        <div className="row wrap">
          <button type="button" className="btn sm ghost" aria-expanded={expert} onClick={() => setExpert((x) => !x)} data-testid="aps-expert-toggle">
            <Icon name={expert ? "chevron-down" : "chevron-right"} /> {t("mfg.apsRunForm.btn.planningOptions")}
          </button>
          <button type="button" className="btn sm ghost" aria-expanded={whatIf} onClick={() => setWhatIf((x) => !x)} data-testid="aps-whatif-toggle">
            <Icon name={whatIf ? "chevron-down" : "chevron-right"} /> {t("mfg.apsRunForm.btn.whatifScenario")}
          </button>
        </div>
        {expert ? (
          <fieldset className="mfg-fieldset" data-testid="aps-expert">
            <legend>{t("mfg.apsRunForm.head.planningOptions")}</legend>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="aps-h">{t("mfg.apsRunForm.label.horizonDays")}</label>
                <input id="aps-h" className="input" type="number" min={7} max={120} value={horizon} placeholder={String(p3?.aps_horizon_days ?? 42)} onChange={(e) => setHorizon(e.target.value)} aria-invalid={hBad} />
                <span className="hint">{hBad ? t("mfg.apsRunForm.str.7To120Days") : t("mfg.apsRunForm.str.operationsThatCannotStartBefore")}</span>
              </div>
              <div className="field">
                <label htmlFor="aps-mrp">{t("mfg.apsRunForm.label.materialPlanMrpRun")}</label>
                <select id="aps-mrp" className="select" value={mrpRun} onChange={(e) => setMrpRun(e.target.value)}>
                  <option value="">{t("mfg.apsRunForm.text.latestLiveRun")}</option>
                  {(mrpRuns.data?.items ?? [])
                    .filter((r: MrpRunRecord) => r.status === "completed")
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        {t("common.runNo", { n: r.run_no })}
                        {r.label ? ` · ${r.label}` : ""}
                      </option>
                    ))}
                </select>
                <span className="hint">{t("mfg.apsRunForm.text.givesThePlannedOrdersAnd")}</span>
              </div>
              <div className="field">
                <label htmlFor="aps-imp">{t("mfg.apsRunForm.label.improvementTimeSeconds")}</label>
                <input id="aps-imp" className="input" type="number" min={0} max={300} value={improve} onChange={(e) => setImprove(e.target.value)} aria-invalid={impBad} />
                <span className="hint">{impBad ? "0 to 300." : t("mfg.apsRunForm.str.0FirstPlanOnlyMore")}</span>
              </div>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={split} onChange={(e) => setSplit(e.target.checked)} />{" "}{t("mfg.apsRunForm.text.splitUrgentOperationsAcrossLines")}
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={includePlanned} onChange={(e) => setIncludePlanned(e.target.checked)} />{" "}{t("mfg.apsRunForm.text.includeMrpPlannedOrdersNot")}
            </label>
          </fieldset>
        ) : null}
        {whatIf ? (
          <fieldset className="mfg-fieldset" data-testid="aps-whatif">
            <legend>{t("mfg.apsRunForm.head.whatifScenario")}</legend>
            <p className="hint" style={{ margin: 0 }}>
              {t("mfg.apsRunForm.text.onlyForThisRunFor")}
            </p>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="aps-asof">{t("mfg.apsRunForm.text.scheduleFrom", { zoneLabel: clock.zoneLabel })}</label>
                <input id="aps-asof" className="input" type="datetime-local" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
                <span className="hint">{t("mfg.apsRunForm.text.emptyNow")}</span>
              </div>
              <label className="checkbox" style={{ alignSelf: "flex-end" }}>
                <input type="checkbox" checked={ignoreMaterial} onChange={(e) => setIgnoreMaterial(e.target.checked)} data-testid="aps-ignore-material" />{" "}{t("mfg.apsRunForm.text.ignoreMaterialAsIfEvery")}
              </label>
            </div>
            <div className="col" style={{ gap: 6 }} data-testid="aps-overrides">
              <span className="field-label">{t("mfg.apsRunForm.text.capacityChanges")}</span>
              {ovs.map((o, i) => (
                <div key={o.key} className="row wrap" style={{ gap: 6 }} data-testid="aps-override-row">
                  <select className="select sm" aria-label={t("mfg.apsRunForm.aria.line")} value={o.target_id} onChange={(e) => setOvs((x) => x.map((y, j) => (j === i ? { ...y, target_id: e.target.value } : y)))}>
                    <option value="">{t("mfg.apsRunForm.text.chooseALine")}</option>
                    {(lines.data?.items ?? []).map((l: LineRecord) => (
                      <option key={l.id} value={l.id}>
                        {l.code} · {l.name}
                      </option>
                    ))}
                  </select>
                  <select className="select sm" aria-label={t("mfg.apsRunForm.aria.change")} value={o.mode} onChange={(e) => setOvs((x) => x.map((y, j) => (j === i ? { ...y, mode: e.target.value as CapacityOverride["mode"] } : y)))}>
                    <option value="open_optional">{t("mfg.apsRunForm.text.openExtraShiftTime")}</option>
                    <option value="close">{t("mfg.apsRunForm.text.closeBreakdownMaintenance")}</option>
                  </select>
                  <input className="input sm" type="datetime-local" aria-label={t("mfg.apsRunForm.aria.from")} value={o.start} onChange={(e) => setOvs((x) => x.map((y, j) => (j === i ? { ...y, start: e.target.value } : y)))} />
                  <input className="input sm" type="datetime-local" aria-label={t("mfg.apsRunForm.aria.until")} value={o.end} onChange={(e) => setOvs((x) => x.map((y, j) => (j === i ? { ...y, end: e.target.value } : y)))} />
                  <button type="button" className="btn sm ghost icon" aria-label={t("mfg.apsRunForm.aria.remove")} onClick={() => setOvs((x) => x.filter((_, j) => j !== i))}>
                    <Icon name="trash" />
                  </button>
                </div>
              ))}
              <div>
                <button type="button" className="btn sm" onClick={() => setOvs((x) => [...x, { key: ++k, target_id: "", start: "", end: "", mode: "open_optional" }])}>
                  <Icon name="plus" /> {t("mfg.apsRunForm.btn.addACapacityChange")}
                </button>
              </div>
            </div>
          </fieldset>
        ) : null}
        {isWhatIf ? (
          <p className="small" role="status" style={{ margin: 0 }}>
            <Icon name="help" size={12} />{" "}{t("mfg.apsRunForm.text.thisWillBeA")}{" "}<strong>what-if</strong>{" "}{t("mfg.apsRunForm.text.runForComparisonCannotBe")}
          </p>
        ) : null}
        <MfgError error={error} title={t("mfg.apsRunForm.attr.theScheduleCouldNotBe")} />
        <div className="row">
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || hBad || impBad || ovBad} data-testid="aps-run-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />} {isWhatIf ? t("mfg.apsRunForm.str.runWhatIfSchedule") : t("mfg.apsRunForm.str.scheduleNow")}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            {t("mfg.apsRunForm.btn.cancel")}
          </button>
        </div>
      </div>
    </section>
  );
}

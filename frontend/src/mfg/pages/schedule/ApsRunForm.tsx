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

export const POLICY_TEXT: Record<OvertimePolicy, { label: string; help: string }> = {
  off: { label: "Regular shifts only", help: "Baseline: no overtime is used or suggested." },
  suggest: { label: "Suggest overtime", help: "Plans on regular shifts and lists which extra shifts would reduce lateness, and by how much." },
  allow: { label: "Use overtime automatically", help: "Opens extra shifts (within weekly limits) when work would otherwise be late; their cost is counted." },
};

export function PolicyPicker({ value, onChange, name = "aps-policy" }: { value: OvertimePolicy; onChange(v: OvertimePolicy): void; name?: string }) {
  return (
    <fieldset className="mfg-fieldset" data-testid="aps-policy">
      <legend>Overtime</legend>
      <div className="row wrap" role="radiogroup" aria-label="Overtime policy">
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
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <section className="card mfg-inline-form" data-testid="aps-run-form" aria-labelledby="aps-form-title">
      <div className="card-header">
        <h2 id="aps-form-title">Schedule the whole plant</h2>
        <button type="button" className="btn sm ghost" onClick={onClose}>
          <Icon name="x" /> Close
        </button>
      </div>
      <div className="card-body col">
        <p className="muted small" style={{ margin: 0 }}>
          Places every operation of the released and firm work orders and of the MRP planned orders on the lines, in the shifts, with crews, tools and
          material availability, most urgent first. Runs in the background; you can keep working.
        </p>
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="aps-label">Name (optional)</label>
          <input id="aps-label" className="input" maxLength={100} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Week 45" data-testid="aps-label" />
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
            <Icon name={expert ? "chevron-down" : "chevron-right"} /> Planning options
          </button>
          <button type="button" className="btn sm ghost" aria-expanded={whatIf} onClick={() => setWhatIf((x) => !x)} data-testid="aps-whatif-toggle">
            <Icon name={whatIf ? "chevron-down" : "chevron-right"} /> What-if scenario
          </button>
        </div>
        {expert ? (
          <fieldset className="mfg-fieldset" data-testid="aps-expert">
            <legend>Planning options</legend>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="aps-h">Horizon (days)</label>
                <input id="aps-h" className="input" type="number" min={7} max={120} value={horizon} placeholder={String(p3?.aps_horizon_days ?? 42)} onChange={(e) => setHorizon(e.target.value)} aria-invalid={hBad} />
                <span className="hint">{hBad ? "7 to 120 days." : "Operations that cannot start before the end are listed, not scheduled."}</span>
              </div>
              <div className="field">
                <label htmlFor="aps-mrp">Material plan (MRP run)</label>
                <select id="aps-mrp" className="select" value={mrpRun} onChange={(e) => setMrpRun(e.target.value)}>
                  <option value="">Latest live run</option>
                  {(mrpRuns.data?.items ?? [])
                    .filter((r: MrpRunRecord) => r.status === "completed")
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        Run #{r.run_no}
                        {r.label ? ` · ${r.label}` : ""}
                      </option>
                    ))}
                </select>
                <span className="hint">Gives the planned orders and when each part arrives.</span>
              </div>
              <div className="field">
                <label htmlFor="aps-imp">Improvement time (seconds)</label>
                <input id="aps-imp" className="input" type="number" min={0} max={300} value={improve} onChange={(e) => setImprove(e.target.value)} aria-invalid={impBad} />
                <span className="hint">{impBad ? "0 to 300." : "0 = first plan only; more time can reduce lateness and setups."}</span>
              </div>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={split} onChange={(e) => setSplit(e.target.checked)} /> Split urgent operations across lines
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={includePlanned} onChange={(e) => setIncludePlanned(e.target.checked)} /> Include MRP planned orders (not only work orders)
            </label>
          </fieldset>
        ) : null}
        {whatIf ? (
          <fieldset className="mfg-fieldset" data-testid="aps-whatif">
            <legend>What-if scenario</legend>
            <p className="hint" style={{ margin: 0 }}>
              Only for this run, for comparison; a what-if run cannot be published.
            </p>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="aps-asof">Schedule from ({clock.zoneLabel})</label>
                <input id="aps-asof" className="input" type="datetime-local" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
                <span className="hint">Empty = now</span>
              </div>
              <label className="checkbox" style={{ alignSelf: "flex-end" }}>
                <input type="checkbox" checked={ignoreMaterial} onChange={(e) => setIgnoreMaterial(e.target.checked)} data-testid="aps-ignore-material" /> Ignore material (as if every part were in stock)
              </label>
            </div>
            <div className="col" style={{ gap: 6 }} data-testid="aps-overrides">
              <span className="field-label">Capacity changes</span>
              {ovs.map((o, i) => (
                <div key={o.key} className="row wrap" style={{ gap: 6 }} data-testid="aps-override-row">
                  <select className="select sm" aria-label="Line" value={o.target_id} onChange={(e) => setOvs((x) => x.map((y, j) => (j === i ? { ...y, target_id: e.target.value } : y)))}>
                    <option value="">Choose a line</option>
                    {(lines.data?.items ?? []).map((l: LineRecord) => (
                      <option key={l.id} value={l.id}>
                        {l.code} · {l.name}
                      </option>
                    ))}
                  </select>
                  <select className="select sm" aria-label="Change" value={o.mode} onChange={(e) => setOvs((x) => x.map((y, j) => (j === i ? { ...y, mode: e.target.value as CapacityOverride["mode"] } : y)))}>
                    <option value="open_optional">Open extra shift time</option>
                    <option value="close">Close (breakdown, maintenance)</option>
                  </select>
                  <input className="input sm" type="datetime-local" aria-label="From" value={o.start} onChange={(e) => setOvs((x) => x.map((y, j) => (j === i ? { ...y, start: e.target.value } : y)))} />
                  <input className="input sm" type="datetime-local" aria-label="Until" value={o.end} onChange={(e) => setOvs((x) => x.map((y, j) => (j === i ? { ...y, end: e.target.value } : y)))} />
                  <button type="button" className="btn sm ghost icon" aria-label="Remove" onClick={() => setOvs((x) => x.filter((_, j) => j !== i))}>
                    <Icon name="trash" />
                  </button>
                </div>
              ))}
              <div>
                <button type="button" className="btn sm" onClick={() => setOvs((x) => [...x, { key: ++k, target_id: "", start: "", end: "", mode: "open_optional" }])}>
                  <Icon name="plus" /> Add a capacity change
                </button>
              </div>
            </div>
          </fieldset>
        ) : null}
        {isWhatIf ? (
          <p className="small" role="status" style={{ margin: 0 }}>
            <Icon name="help" size={12} /> This will be a <strong>what-if</strong> run (for comparison; cannot be published).
          </p>
        ) : null}
        <MfgError error={error} title="The schedule could not be started" />
        <div className="row">
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || hBad || impBad || ovBad} data-testid="aps-run-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />} {isWhatIf ? "Run what-if schedule" : "Schedule now"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </section>
  );
}
